"""Public final-practice adapter using the existing cgroup/bubblewrap machinery."""
from pathlib import Path
import os
import sys
import tempfile
import time

from tools import isolated_runner as legacy


def run(program, dataset, *, deadline=None):
    """All setup is inside the caller's absolute monotonic competition deadline.

    The legacy safety-stop semantics are unchanged. Only this adapter maps a
    competition deadline to TIME_LIMIT, which earns zero for the in-flight map.
    """
    program, dataset = Path(program).resolve(), Path(dataset).resolve()
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in program.rglob('*')):
        raise ValueError('Submission must contain regular files/directories only.')
    if not (program / 'main.py').is_file():
        raise ValueError('main.py missing')
    if deadline is not None and time.perf_counter() >= deadline:
        return legacy.RunResult('TIME_LIMIT', 0, 0, 0, 128, 0, '', '', {})
    with tempfile.TemporaryFile() as info, tempfile.TemporaryFile() as stdout, \
         tempfile.TemporaryFile() as stderr, tempfile.TemporaryDirectory(prefix='rr-final-input-') as temporary, \
         legacy.limited_group(128) as group:
        import shutil
        for name in ('map.csv', 'queries.csv', 'metadata.json'):
            shutil.copyfile(dataset / name, Path(temporary) / name)
        ready_read, ready_write = os.pipe()
        try:
            command = legacy._bubblewrap(program, Path(temporary), Path('main.py'), info.fileno(), ready_write)
            # Hide system executables and installed third-party Python packages.
            # The interpreter and stdlib remain available; Python is not a code
            # policy verifier (ctypes/native-code misuse still requires review).
            interpreter = str(Path(sys.executable).resolve())
            restrictions = ['--setenv', 'PYTHONHASHSEED', '0', '--tmpfs', '/bin', '--tmpfs', '/usr/bin',
                            '--ro-bind', interpreter, interpreter]
            for hidden in ('/usr/local', '/usr/lib/python3/dist-packages', '/usr/sbin', '/sbin'):
                if Path(hidden).is_dir():
                    restrictions += ['--tmpfs', hidden]
            pos = command.index('--')
            command[pos:pos] = restrictions
            bootstrap = command.index('-c') + 1
            command[bootstrap] = command[bootstrap].replace(
                "os.write(fd, b'R')",
                "import resource\nresource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))\nos.write(fd, b'R')")
            if deadline is not None and time.perf_counter() >= deadline:
                return legacy.RunResult('TIME_LIMIT', 0, 0, 0, 128, 0, '', '', {})
            remaining = None if deadline is None else max(.000001, deadline - time.perf_counter())
            status, usage, elapsed, ready, stopped, startup_failed, populated, diagnostics = legacy._execute(
                command, group, info, stdout, stderr, ready_read, ready_write,
                safety_stop=remaining, output_limit=legacy.MIB)
        finally:
            os.close(ready_read)
            os.close(ready_write)
        events = {k: int(v) for k, v in (line.split() for line in (group / 'memory.events').read_text().splitlines())}
        peak = int((group / 'memory.peak').read_text()) / legacy.MIB
        returncode = os.waitstatus_to_exitcode(status)
        state = 'TIME_LIMIT' if stopped else legacy._classify(
            ready=ready, stopped=False, startup_failed=startup_failed, events=events,
            populated=populated, returncode=returncode,
            output_size=max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size),
            output_limit=legacy.MIB)
        return legacy.RunResult(state, elapsed, peak, usage.ru_maxrss / 1024, 128, returncode,
                                os.pread(stdout.fileno(), legacy.MIB, 0).decode('utf-8', errors='replace'),
                                os.pread(stderr.fileno(), legacy.MIB, 0).decode('utf-8', errors='replace'),
                                events, cgroup_diagnostics=diagnostics)
