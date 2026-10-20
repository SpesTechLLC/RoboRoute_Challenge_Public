"""Opt in on normal Linux/WSL: ROBOROUTE_INTEGRATION_TESTS=1.

All probes run in limited cgroups. Only fixed, trusted lifecycle fixtures call
_execute directly so a child can deliberately outlive its parent without the
PID namespace killing it. Submission checks use the full bubblewrap runner.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from tools import isolated_runner as runner


@unittest.skipUnless(os.environ.get('ROBOROUTE_INTEGRATION_TESTS') == '1',
                     'requires normal WSL/Linux cgroup delegation; opt in explicitly')
class LifecycleIntegrationTests(unittest.TestCase):
    def execute_descendant(self, persistent=False, safety_stop=None):
        with tempfile.TemporaryFile() as info, tempfile.TemporaryFile() as stdout, \
             tempfile.TemporaryFile() as stderr:
            with runner.limited_group(128) as group:
                for name, expected in [('memory.max', 128 * runner.MIB), ('pids.max', 64)]:
                    self.assertEqual(int((group / name).read_text()), expected)
                ready_read, ready_write = os.pipe()
                try:
                    # Handshake ensures the descendant is alive before parent exit.
                    code = f'''
import os, time
os.write({ready_write}, b'R')
os.close({ready_write})
r, w = os.pipe()
if os.fork() == 0:
    os.close(r)
    os.write(w, b'R')
    os.close(w)
    if {persistent!r}:
        time.sleep(60)
    else:
        until = time.monotonic() + .08
        while time.monotonic() < until:
            pass
        os.write(1, b'descendant finished\\n')
    os._exit(0)
os.close(w)
os.read(r, 1)
os._exit(0)
'''
                    result = runner._execute([sys.executable, '-I', '-S', '-c', code],
                                             group, info, stdout, stderr, ready_read, ready_write,
                                             safety_stop=safety_stop, output_limit=runner.MIB)
                finally:
                    os.close(ready_read)
                    os.close(ready_write)
                status, _, elapsed, ready, stopped, startup_failed, populated, diagnostics = result
                self.assertTrue(diagnostics['initial_populated'])
                self.assertGreater(diagnostics['parent_pid'], 0)
                memory_events = dict(line.split() for line in (group / 'memory.events').read_text().splitlines())
                state = runner._classify(ready=ready, stopped=stopped, startup_failed=startup_failed,
                                         populated=populated, events={k: int(v) for k, v in memory_events.items()},
                                         returncode=os.waitstatus_to_exitcode(status),
                                         output_size=os.fstat(stdout.fileno()).st_size, output_limit=runner.MIB)
                output = os.pread(stdout.fileno(), runner.MIB, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                self.assertEqual(os.pread(stderr.fileno(), runner.MIB, 0), b'')
            self.assertFalse(group.exists(), 'cleanup must kill leftovers and remove the cgroup')
        return state, elapsed, diagnostics, output

    def test_transient_descendant_time_and_output_are_included(self):
        state, elapsed, diagnostics, output = self.execute_descendant()
        self.assertEqual(state, 'OK')
        self.assertEqual(output, b'descendant finished\n')
        self.assertEqual(diagnostics['outcome'], 'drained')
        self.assertGreater(diagnostics['drain_seconds'], .02)
        self.assertGreaterEqual(elapsed, diagnostics['decision_elapsed_seconds'])
        self.assertGreaterEqual(elapsed, diagnostics['parent_elapsed_seconds'] + diagnostics['drain_seconds'])

    def test_persistent_descendant_is_rejected_and_killed(self):
        state, _, diagnostics, _ = self.execute_descendant(persistent=True)
        self.assertEqual(state, 'LEFTOVER_PROCESSES')
        self.assertEqual(diagnostics['outcome'], 'deadline')
        self.assertGreaterEqual(diagnostics['drain_seconds'], runner.EXIT_GRACE_SECONDS)
        self.assertTrue(diagnostics['snapshots'][-1]['processes'])
        json.dumps(diagnostics)  # usable in benchmark result JSON

    def test_operator_stop_during_drain(self):
        state, _, diagnostics, _ = self.execute_descendant(persistent=True, safety_stop=.1)
        self.assertEqual(state, 'OPERATOR_STOP')
        self.assertEqual(diagnostics['outcome'], 'operator_stop')

    def isolated(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'main.py').write_text(code)
            return runner.run_isolated(directory, 'main.py', Path(__file__).resolve().parents[1] / 'datasets/sample',
                                       memory_mib=128, **kwargs)

    def test_full_bubblewrap_bootstrap_and_pid_namespace_cleanup(self):
        result = self.isolated('import os, time\nif os.fork() == 0:\n    time.sleep(60)\nelse:\n    print("parent finished")\n')
        self.assertEqual(result.status, 'OK')
        self.assertEqual(result.stdout, 'parent finished\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.mechanism, 'cgroup-v2+namespace')

    def test_memory_limit_and_oom_detection(self):
        result = self.isolated('x = bytearray(256 * 1024 * 1024)\n')
        self.assertEqual(result.status, 'MEMORY_EXCEEDED')
        self.assertGreater(result.memory_events.get('oom_kill', 0), 0)

    def test_output_limit(self):
        result = self.isolated('import os\nwhile True:\n    os.write(1, b"x" * 4096)\n', output_limit=4096)
        self.assertEqual(result.status, 'OUTPUT_LIMIT')
        self.assertEqual(len(result.stdout), 4096)


if __name__ == '__main__':
    unittest.main()
