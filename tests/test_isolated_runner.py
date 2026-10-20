"""Deterministic cgroup lifecycle tests; no delegation or privileges needed."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import isolated_runner as runner


class DrainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.group = Path(self.temporary.name)
        self.now = 10.
        self.parent_reaped = self.now
        self.started = 9.
        self.write_events(True)
        (self.group / 'cgroup.procs').write_text('')
        self.changes = []
        self.timeouts = []
        self.poller = self

    def write_events(self, populated):
        (self.group / 'cgroup.events').write_text(f'populated {int(populated)}\nfrozen 0\n')

    def register(self, fd, events):
        self.assertEqual(events, runner.select.POLLPRI | runner.select.POLLERR)

    def poll(self, milliseconds):
        self.timeouts.append(milliseconds)
        if self.changes:
            delay, populated = self.changes.pop(0)
            self.assertLessEqual(delay, milliseconds / 1000)
            self.now += delay
            self.write_events(populated)
        else:
            self.now += milliseconds / 1000
        return []

    def wait(self, safety_stop=None):
        with patch.object(runner.time, 'perf_counter', side_effect=lambda: self.now), \
             patch.object(runner.select, 'poll', return_value=self.poller):
            return runner._wait_for_empty(self.group, started=self.started,
                                          parent_reaped=self.parent_reaped, safety_stop=safety_stop)

    def test_already_empty_does_not_wait(self):
        self.write_events(False)
        self.assertEqual(self.wait(), (False, False, None))
        self.assertEqual(self.timeouts, [])
        self.assertEqual(self.now, self.parent_reaped)

    def test_transient_empty_procs_but_populated_events_drains(self):
        self.changes = [(.012, False)]
        populated, stopped, diagnostics = self.wait()
        self.assertFalse(populated)
        self.assertFalse(stopped)
        self.assertAlmostEqual(diagnostics['drain_seconds'], .012)
        self.assertAlmostEqual(diagnostics['decision_elapsed_seconds'], 1.012)
        self.assertEqual(diagnostics['outcome'], 'drained')
        first, last = diagnostics['snapshots']
        self.assertIn('populated 1', first['cgroup.events'])
        self.assertEqual(first['cgroup.procs'], '')
        self.assertIn('populated 0', last['cgroup.events'])

    def test_persistent_population_reaches_deadline_and_fails(self):
        # Empty cgroup.procs alone is NOT evidence of cgroup emptiness.
        populated, stopped, diagnostics = self.wait()
        self.assertTrue(populated)
        self.assertFalse(stopped)
        self.assertEqual(diagnostics['outcome'], 'deadline')
        self.assertAlmostEqual(diagnostics['drain_seconds'], runner.EXIT_GRACE_SECONDS)
        self.assertEqual(self.classify(populated=populated), 'LEFTOVER_PROCESSES')

    def test_spurious_notification_does_not_end_wait(self):
        self.changes = [(.005, True), (.004, False)]
        populated, _, diagnostics = self.wait()
        self.assertFalse(populated)
        self.assertEqual(len(self.timeouts), 2)
        self.assertLess(self.timeouts[1], self.timeouts[0])
        self.assertAlmostEqual(diagnostics['drain_seconds'], .009)

    def test_operator_stop_also_limits_descendant_wait(self):
        _, stopped, diagnostics = self.wait(safety_stop=1.05)
        self.assertTrue(stopped)
        self.assertEqual((self.group / 'cgroup.kill').read_text(), '1')
        self.assertEqual(diagnostics['outcome'], 'operator_stop')
        self.assertLess(diagnostics['drain_seconds'], .052)
        self.assertEqual(self.classify(stopped=stopped, populated=True), 'OPERATOR_STOP')

    def test_cgroup_read_failure_is_not_success(self):
        (self.group / 'cgroup.events').unlink()
        with self.assertRaises(OSError):
            self.wait()

    @staticmethod
    def classify(**overrides):
        arguments = dict(ready=True, stopped=False, startup_failed=False,
                         events={}, populated=False, returncode=0, output_size=0, output_limit=100)
        arguments.update(overrides)
        return runner._classify(**arguments)

    def test_existing_failures_remain_enforced(self):
        for event in ('max', 'oom', 'oom_kill', 'oom_group_kill'):
            with self.subTest(event=event):
                self.assertEqual(self.classify(events={event: 1}, populated=True), 'MEMORY_EXCEEDED')
        self.assertEqual(self.classify(output_size=101), 'OUTPUT_LIMIT')
        self.assertEqual(self.classify(returncode=1), 'RUNTIME_ERROR')
        with self.assertRaises(runner.EnvironmentUnavailable):
            self.classify(ready=False)

    def test_snapshot_records_host_pid_state_and_cpu(self):
        (self.group / 'cgroup.procs').write_text(f'{os.getpid()}\n2147483647\n')
        snapshot = runner._cgroup_snapshot(self.group, self.parent_reaped)
        current, vanished = snapshot['processes']
        self.assertEqual(current['pid'], os.getpid())
        self.assertIn(current['state'], ('R', 'S'))
        self.assertEqual(current['ppid'], os.getppid())
        self.assertGreater(current['starttime_ticks'], 0)
        self.assertGreaterEqual(current['utime_ticks'], 0)
        self.assertIn('error', vanished)


if __name__ == '__main__':
    unittest.main()
