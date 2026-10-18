#!/usr/bin/env python3
"""Read-only host diagnosis plus a trusted, bounded bubblewrap probe.

Does not create cgroups, change configuration, use network, or run submissions.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.isolated_runner import EnvironmentUnavailable, _bubblewrap, _started, delegated_parent


def command_probe(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                stdin=subprocess.DEVNULL, close_fds=True)
        return {'returncode': result.returncode, 'stdout': result.stdout.strip()[:4096],
                'stderr': result.stderr.strip()[:4096]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'error': str(error)}


def read_optional(path):
    try:
        return Path(path).read_text().strip()
    except OSError as error:
        return {'error': str(error)}


def diagnose():
    root = Path('/sys/fs/cgroup')
    report = {'python': sys.version, 'executable': sys.executable,
              'kernel': platform.release(), 'cgroup_membership': read_optional('/proc/self/cgroup'),
              'cgroup_controllers': read_optional(root / 'cgroup.controllers'),
              'cgroup_mount': command_probe(['findmnt', '-n', '-o', 'TARGET,FSTYPE,OPTIONS', '/sys/fs/cgroup']),
              'systemd_user': command_probe(['systemctl', '--user', 'show', '-p', 'ControlGroup', '--value']),
              'bwrap_version': command_probe(['bwrap', '--version'])}
    try:
        report['delegated_parent'] = {'path': str(delegated_parent()), 'inspection': 'OK'}
    except EnvironmentUnavailable as error:
        report['delegated_parent'] = {'inspection': 'UNAVAILABLE', 'error': str(error)}
    # Only this fixed, trusted probe is run without a memory cgroup. No submissions.
    if shutil.which('bwrap'):
        try:
            with tempfile.TemporaryDirectory(prefix='roboroute-diagnostic-') as temporary, tempfile.TemporaryFile() as info:
                directory = Path(temporary)
                (directory / 'main.py').write_text(
                    'import json, os\nfrom pathlib import Path\n'
                    'print(json.dumps({"pid": os.getpid(), "net_namespace": os.readlink("/proc/self/ns/net"), '
                    '"home_visible": Path("/home").exists(), "cgroup_visible": Path("/sys/fs/cgroup").exists()}))\n')
                ready_read, ready_write = os.pipe()
                try:
                    command = _bubblewrap(directory, directory, Path('main.py'), info.fileno(), ready_write)
                    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                            text=True, timeout=10, pass_fds=(info.fileno(), ready_write))
                    os.set_blocking(ready_read, False)
                    try:
                        bootstrap_ready = os.read(ready_read, 2) == b'R'
                    except BlockingIOError:
                        bootstrap_ready = False
                    report['bubblewrap_probe'] = {'returncode': result.returncode,
                        'pid_metadata_present': _started(info), 'bootstrap_ready': bootstrap_ready,
                        'stdout': result.stdout.strip()[:4096], 'stderr': result.stderr.strip()[:4096],
                        'host_net_namespace': os.readlink('/proc/self/ns/net')}
                finally:
                    os.close(ready_read)
                    os.close(ready_write)
        except (OSError, EnvironmentUnavailable, subprocess.TimeoutExpired) as error:
            report['bubblewrap_probe'] = {'error': str(error)}
    else:
        report['bubblewrap_probe'] = {'error': 'bubblewrap is missing'}
    report['note'] = 'Diagnosis only; cgroup enforcement has NOT been exercised.'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    report = diagnose()
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
