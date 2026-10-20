"""Fail-closed Linux runner: cgroup v2 limits and bubblewrap namespaces.

memory.peak is a cgroup charge (descendants/cache/tmpfs), not peak RSS.
An isolated trusted bootstrap must signal readiness BEFORE loading submissions.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import resource
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

MIB = 1024 * 1024
STARTUP_SECONDS = 10
# A teardown grace period, not a submission runtime limit. All of it is timed.
EXIT_GRACE_SECONDS = .2

# -I -S prevents importing submission/site modules before the readiness signal.
# The readiness FD is closed before student code is loaded, so it cannot forge it.
BOOTSTRAP = '''import os, runpy, sys, json
fd = int(sys.argv[1])
entry = sys.argv[2]
expected = json.loads(sys.argv[3])
for kind, host in expected.items():
    if os.readlink('/proc/self/ns/' + kind) == host:
        raise RuntimeError('Namespace was not isolated: ' + kind)
os.write(fd, b'R')
os.close(fd)
sys.argv = [entry, '/input']
sys.path.insert(0, os.path.dirname(entry))
runpy.run_path(entry, run_name='__main__')
'''


class EnvironmentUnavailable(RuntimeError):
    """Required limiting or isolation facility is unavailable."""


@dataclass
class RunResult:
    status: str
    elapsed_seconds: float
    memory_peak_mib: float
    peak_rss_mib: float
    memory_limit_mib: int
    returncode: int
    stdout: str
    stderr: str
    memory_events: dict[str, int]
    mechanism: str = 'cgroup-v2+namespace'
    cgroup_diagnostics: dict | None = None

    def as_dict(self):
        return asdict(self)


def delegated_parent():
    try:
        return _delegated_parent()
    except OSError as error:
        raise EnvironmentUnavailable(f'Cannot inspect cgroup delegation: {error}') from error


def _delegated_parent():
    if sys.platform != 'linux':
        raise EnvironmentUnavailable('Linux/WSL2 cgroup v2 and bubblewrap are required.')
    override = os.environ.get('ROBOROUTE_CGROUP_PARENT')
    if override:
        parent = Path(override).resolve()
    else:
        try:
            name = subprocess.check_output(
                ['systemctl', '--user', 'show', '-p', 'ControlGroup', '--value'],
                text=True, stderr=subprocess.PIPE, timeout=5).strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise EnvironmentUnavailable('User systemd delegation unavailable; see docs/ENVIRONMENT.md.') from error
        if not name.startswith('/') or name == '/':
            raise EnvironmentUnavailable('No delegated user service cgroup.')
        parent = Path('/sys/fs/cgroup') / name.lstrip('/')
    if Path('/sys/fs/cgroup').resolve() not in parent.parents:
        raise EnvironmentUnavailable('A delegated cgroup v2 parent is required.')
    if not {'memory', 'pids'} <= set((parent / 'cgroup.subtree_control').read_text().split()):
        raise EnvironmentUnavailable('memory and pids controllers must be delegated/enabled.')
    if not shutil.which('bwrap'):
        raise EnvironmentUnavailable('bubblewrap is missing.')
    return parent


def _populated(group):
    return dict(line.split() for line in (group / 'cgroup.events').read_text().splitlines())['populated'] == '1'


def _cgroup_snapshot(group, parent_reaped):
    """Best-effort host diagnostics: processes may disappear during any read."""
    snapshot = {'seconds_after_parent_reap': time.perf_counter() - parent_reaped}
    for name in ('cgroup.events', 'cgroup.procs'):
        try:
            snapshot[name] = (group / name).read_text()
        except OSError as error:
            snapshot[name] = {'error': str(error)}
    processes = []
    procs = snapshot['cgroup.procs']
    for value in procs.split() if isinstance(procs, str) else ():
        pid = int(value)
        record = {'pid': pid}
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
            # comm can contain spaces and parentheses; fields after its last ')'
            # start at field 3 (state). Keep CPU counters to diagnose live work.
            fields = stat[stat.rfind(')') + 2:].split()
            record.update(comm=stat[stat.find('(') + 1:stat.rfind(')')],
                          state=fields[0], ppid=int(fields[1]),
                          utime_ticks=int(fields[11]), stime_ticks=int(fields[12]),
                          starttime_ticks=int(fields[19]))
            record['wchan'] = Path(f'/proc/{pid}/wchan').read_text().strip()
        except OSError as error:
            record['error'] = str(error)
        processes.append(record)
    snapshot['processes'] = processes
    return snapshot


def _wait_for_empty(group, *, started, parent_reaped, safety_stop):
    """Wait for cgroup teardown, waking on populated changes or the deadline.

    bubblewrap's monitor can return the payload status via eventfd before its
    namespace init finishes exiting (bubblewrap.c: monitor_child/do_init).
    wait4 only reaps that monitor. Never accept a populated group
    at the deadline, even when cgroup.procs happens to be empty.
    """
    deadline = parent_reaped + EXIT_GRACE_SECONDS
    stopped = False
    with (group / 'cgroup.events').open() as events:
        poller = select.poll()
        poller.register(events, select.POLLPRI | select.POLLERR)

        def populated():
            # Reading this same FD also acknowledges cgroup notifications.
            events.seek(0)
            return dict(line.split() for line in events)['populated'] == '1'

        if not populated():
            return False, False, None
        diagnostics = {'cgroup': str(group), 'grace_seconds': EXIT_GRACE_SECONDS,
                       'initial_populated': True,
                       'parent_elapsed_seconds': parent_reaped - started,
                       'snapshots': [_cgroup_snapshot(group, parent_reaped)]}
        while True:
            remaining = deadline - time.perf_counter()
            if safety_stop is not None:
                remaining = min(remaining, started + safety_stop - time.perf_counter())
            if remaining > 0:
                poller.poll(math.ceil(remaining * 1000))
            occupied = populated()
            now = time.perf_counter()
            # A running descendant also remains subject to the operator stop.
            if safety_stop is not None and now - started >= safety_stop:
                stopped = True
                (group / 'cgroup.kill').write_text('1')
            if not occupied or stopped or now >= deadline:
                break
        diagnostics.update(drain_seconds=now - parent_reaped,
                           decision_elapsed_seconds=now - started,
                           outcome='operator_stop' if stopped else 'deadline' if occupied else 'drained')
        diagnostics['snapshots'].append(_cgroup_snapshot(group, parent_reaped))
        return occupied, stopped, diagnostics


def _cleanup_group(group):
    if not group.exists():
        return
    try:
        if _populated(group):
            (group / 'cgroup.kill').write_text('1')
        deadline = time.monotonic() + 2
        while _populated(group):
            if time.monotonic() >= deadline:
                raise EnvironmentUnavailable(f'Execution cgroup still populated: {group}')
            time.sleep(.01)
        group.rmdir()
    except OSError as error:
        raise EnvironmentUnavailable(f'Execution cgroup cleanup failed: {group}: {error}') from error


@contextmanager
def limited_group(memory_mib):
    if type(memory_mib) is not int or memory_mib < 16:
        raise ValueError('memory_mib must be an integer >=16 MiB.')
    group = delegated_parent() / ('roboroute-' + uuid.uuid4().hex)
    try:
        group.mkdir()
        settings = [('memory.max', memory_mib * MIB), ('memory.swap.max', 0),
                    ('memory.oom.group', 1), ('pids.max', 64)]
        for name, value in settings:
            (group / name).write_text(str(value))
        for name in ('memory.peak', 'memory.events', 'cgroup.kill', 'cgroup.events', 'cgroup.procs'):
            if not (group / name).exists():
                raise EnvironmentUnavailable('Required kernel interface missing: ' + name)
        for name, expected in settings:
            if int((group / name).read_text()) != expected:
                raise EnvironmentUnavailable(f'Limit readback failed: {name}')
        yield group
    except OSError as error:
        raise EnvironmentUnavailable(f'Cannot use delegated cgroup: {error}') from error
    finally:
        _cleanup_group(group)


def _host_namespaces():
    return {kind: os.readlink('/proc/self/ns/' + kind) for kind in ('mnt', 'pid', 'net', 'user')}


def _bubblewrap(program, dataset, entry, info_fd, ready_fd=None):
    interpreter = Path(sys.executable).resolve()
    if Path('/usr') not in interpreter.parents or not interpreter.is_file():
        raise EnvironmentUnavailable('Use a Python interpreter installed under /usr for this runtime profile.')
    command = [shutil.which('bwrap'), '--unshare-all', '--unshare-user',
               '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
               '--disable-userns', '--info-fd', str(info_fd), '--clearenv',
               '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
               '--setenv', 'HOME', '/tmp', '--ro-bind', '/usr', '/usr']
    for path in ('/bin', '/lib', '/lib64'):
        if Path(path).exists():
            command += ['--ro-bind', path, path]
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--ro-bind', str(program), '/submission', '--ro-bind', str(dataset), '/input',
                '--chdir', '/submission', '--', str(interpreter), '-B', '-I', '-S']
    if ready_fd is None:
        # Only fixed, trusted diagnosis code may use this mode.
        return command + ['/submission/' + entry.as_posix(), '/input']
    return command + ['-c', BOOTSTRAP, str(ready_fd), '/submission/' + entry.as_posix(),
                      json.dumps(_host_namespaces())]


def _started(info):
    """Diagnostic PID metadata only: not proof that sandbox setup completed."""
    try:
        return type(json.loads(os.pread(info.fileno(), 65536, 0)).get('child-pid')) is int
    except (ValueError, AttributeError):
        return False


def _close_other_fds(keep):
    # A caller may have deliberately inheritable FDs; never expose them to bwrap.
    for value in os.listdir('/proc/self/fd'):
        fd = int(value)
        if fd > 2 and fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass  # includes the now-closed descriptor used by listdir


def _terminate_and_reap(pid, group):
    """Always reap even if cgroup attachment or kill failed."""
    errors = []
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as error:
        errors.append(str(error))
    try:
        (group / 'cgroup.kill').write_text('1')
    except OSError as error:
        errors.append(str(error))
    finally:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    if errors:
        raise EnvironmentUnavailable('Child termination failed: ' + '; '.join(errors))


def _execute(command, group, info, stdout, stderr, ready_read, ready_write, *, safety_stop, output_limit):
    gate_read, gate_write = os.pipe()
    started = time.perf_counter()
    pid = None
    try:
        pid = os.fork()
        if pid == 0:
            try:
                os.close(gate_write)
                os.setsid()
                os.set_inheritable(info.fileno(), True)
                os.set_inheritable(ready_write, True)
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                null = os.open(os.devnull, os.O_RDONLY)
                os.dup2(null, 0)
                resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                if os.read(gate_read, 1) != b'1':
                    os._exit(125)
                _close_other_fds({info.fileno(), ready_write})
                os.execv(command[0], command)
            except BaseException as error:
                os.write(2, ('RUNNER ERROR: ' + str(error)).encode())
                os._exit(125)
        os.close(gate_read)
        gate_read = -1
        # The caller owns readiness FDs and closes both exactly once.
        (group / 'cgroup.procs').write_text(str(pid))
        if pid not in map(int, (group / 'cgroup.procs').read_text().split()):
            raise EnvironmentUnavailable('Child cgroup attachment readback failed.')
        os.write(gate_write, b'1')
        os.close(gate_write)
        gate_write = -1
        ready = False
        stopped = False
        startup_failed = False
        os.set_blocking(ready_read, False)
        while True:
            try:
                token = os.read(ready_read, 2)
                ready = ready or token == b'R'
            except BlockingIOError:
                pass
            waited, status, usage = os.wait4(pid, os.WNOHANG)
            if waited:
                pid = None  # already reaped
                parent_reaped = time.perf_counter()
                break
            elapsed = time.perf_counter() - started
            if not ready and elapsed > STARTUP_SECONDS:
                startup_failed = True
                (group / 'cgroup.kill').write_text('1')
            elif safety_stop is not None and elapsed > safety_stop:
                stopped = True
                (group / 'cgroup.kill').write_text('1')
            time.sleep(.002)
        # A very short-lived process may signal between the read and wait4 above.
        if not ready:
            try:
                ready = os.read(ready_read, 2) == b'R'
            except BlockingIOError:
                pass
        populated, drain_stopped, diagnostics = _wait_for_empty(
            group, started=started, parent_reaped=parent_reaped, safety_stop=safety_stop)
        if diagnostics is not None:
            diagnostics['parent_pid'] = waited
        return (status, usage, time.perf_counter() - started, ready,
                stopped or drain_stopped, startup_failed, populated, diagnostics)
    except BaseException:
        if pid is not None:
            _terminate_and_reap(pid, group)
        raise
    finally:
        for fd in (gate_read, gate_write):
            if fd >= 0:
                os.close(fd)


def _classify(*, ready, stopped, startup_failed, events, populated, returncode, output_size, output_limit):
    if stopped:
        return 'OPERATOR_STOP'
    if startup_failed or not ready:
        raise EnvironmentUnavailable('Isolation bootstrap did not complete before submission execution.')
    if any(events.get(name, 0) for name in ('max', 'oom', 'oom_kill', 'oom_group_kill')):
        return 'MEMORY_EXCEEDED'
    if populated:
        return 'LEFTOVER_PROCESSES'
    if output_size > output_limit or (output_size == output_limit and returncode):
        return 'OUTPUT_LIMIT'
    if returncode:
        return 'RUNTIME_ERROR'
    return 'OK'


def run_isolated(program, entry, dataset, *, memory_mib, safety_stop=None, output_limit=MIB):
    """Measure through cgroup drain; safety_stop is NOT a competition limit."""
    program, dataset, entry = Path(program).resolve(), Path(dataset).resolve(), Path(entry)
    resolved_entry = (program / entry).resolve()
    if not program.is_dir() or not dataset.is_dir():
        raise ValueError('Missing program/dataset directory.')
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in program.rglob('*')):
        raise ValueError('Program trees must contain only regular files/directories, no symbolic links.')
    if entry.is_absolute() or program not in resolved_entry.parents or not resolved_entry.is_file():
        raise ValueError('Entry must be an existing file inside the program directory.')
    if safety_stop is not None and (not math.isfinite(safety_stop) or safety_stop <= 0):
        raise ValueError('safety_stop must be finite and positive.')
    if type(output_limit) is not int or output_limit <= 0:
        raise ValueError('output_limit must be positive.')
    with tempfile.TemporaryFile() as info, tempfile.TemporaryDirectory(prefix='roboroute-input-') as input_dir, \
         tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr, limited_group(memory_mib) as group:
        for name in ('map.csv', 'queries.csv', 'metadata.json'):
            shutil.copyfile(dataset / name, Path(input_dir) / name)
        ready_read, ready_write = os.pipe()
        try:
            command = _bubblewrap(program, Path(input_dir), entry, info.fileno(), ready_write)
            status, usage, elapsed, ready, stopped, startup_failed, populated, diagnostics = _execute(
                command, group, info, stdout, stderr, ready_read, ready_write,
                safety_stop=safety_stop, output_limit=output_limit)
        finally:
            for fd in (ready_read, ready_write):
                try:
                    os.close(fd)
                except OSError:
                    pass
        events = {key: int(value) for key, value in
                  (line.split() for line in (group / 'memory.events').read_text().splitlines())}
        peak = int((group / 'memory.peak').read_text()) / MIB
        returncode = os.waitstatus_to_exitcode(status)
        output_size = max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size)
        out = os.pread(stdout.fileno(), output_limit, 0).decode('utf-8', errors='replace')
        err = os.pread(stderr.fileno(), output_limit, 0).decode('utf-8', errors='replace')
        try:
            state = _classify(ready=ready, stopped=stopped, startup_failed=startup_failed,
                              events=events, populated=populated, returncode=returncode,
                              output_size=output_size, output_limit=output_limit)
        except EnvironmentUnavailable as error:
            raise EnvironmentUnavailable(f'{error} {err[:1000]}') from error
        return RunResult(state, elapsed, peak, usage.ru_maxrss / 1024, memory_mib, returncode, out, err, events,
                         cgroup_diagnostics=diagnostics)
