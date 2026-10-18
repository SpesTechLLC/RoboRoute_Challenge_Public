"""Student CLI. Every execution of work/ code uses the existing isolation runner."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from roboroute.dataset import load_dataset
from tools.benchmark import ROOT, evaluate, fingerprint
from tools.isolated_runner import EnvironmentUnavailable, delegated_parent, run_isolated
from tools.reference_solver import solve_dataset
from tools.submission import extract_submission, MAX_BYTES, MAX_FILES

MOCK_DATASETS = ('mock_rooms', 'mock_maze', 'mock_islands')


def dataset_path(name):
    candidate = Path(name)
    if not candidate.is_dir():
        candidate = ROOT / 'datasets' / name
    if not candidate.is_dir():
        raise ValueError(f'Datasetが見つかりません: {name}')
    return candidate.resolve()


def init_work(work):
    work = Path(work)
    if work.exists() or work.is_symlink():
        raise ValueError(f'{work} は既に存在します。既存の作業は変更していません。')
    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rr-init-', dir=work.parent) as temporary:
        staged = Path(temporary) / 'work'
        staged.mkdir()
        shutil.copyfile(ROOT / 'solution/main.py', staged / 'main.py')
        shutil.copytree(ROOT / 'roboroute', staged / 'roboroute', ignore=shutil.ignore_patterns('__pycache__'))
        (staged / 'report').mkdir()
        shutil.copyfile(ROOT / 'templates/experiment_log.md', staged / 'report/experiment_log.md')
        # rename won't replace an existing nonempty work directory.
        if work.exists() or work.is_symlink():
            raise ValueError('作業ディレクトリが作成されました。上書きせず停止します。')
        staged.rename(work)
    return work


def _regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'通常ファイルが必要です（リンク不可）: {path}')
    return path


def pack_submission(work, team, slides, output=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', team):
        raise ValueError('チーム名は英数字で始まる英数字・_・-の1～64文字です。')
    work, slides = Path(work), _regular(Path(slides))
    if work.is_symlink() or not work.is_dir():
        raise ValueError('workディレクトリが必要です。先に ./rr init を実行してください。')
    _regular(work / 'main.py')
    report = next((work / 'report' / ('experiment_log' + ext) for ext in ('.md', '.txt')
                   if (work / 'report' / ('experiment_log' + ext)).exists()), None)
    if report is None:
        raise ValueError('report/experiment_log.md または .txt が必要です。')
    _regular(report)
    if report.parent.is_symlink():
        raise ValueError('reportディレクトリのリンクは使用できません。')
    files = []
    for path in sorted(work.rglob('*')):
        relative = path.relative_to(work)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f'リンクを含む作業はZIP化できません: {relative}')
        if path.suffix == '.py' and 'report' not in relative.parts:
            files.append((_regular(path), relative.as_posix()))
    files += [(report, 'report/' + report.name), (slides, 'slides.pdf')]
    if (work / 'README.md').exists():
        files.append((_regular(work / 'README.md'), 'README.md'))
    if len(files) > MAX_FILES or sum(path.stat().st_size for path, _ in files) > MAX_BYTES:
        raise ValueError('提出物は1024ファイル・展開後32MiB以内にしてください。')
    output = Path(output) if output else ROOT / 'submissions' / (team + '.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise ValueError(f'{output} は既に存在します。--outputで別名を指定してください。')
    with tempfile.TemporaryDirectory(prefix='.rr-pack-', dir=output.parent) as temporary:
        archive = Path(temporary) / 'submission.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for path, name in files:
                zipped.write(path, name)
        extract_submission(archive, Path(temporary) / 'validated')
        # Exclusive creation protects an already-produced archive, including races.
        with output.open('xb') as target, archive.open('rb') as source:
            try:
                shutil.copyfileobj(source, target)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    return output


def _inside_delegation():
    try:
        parent = delegated_parent()
        member = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        current = (Path('/sys/fs/cgroup') / member.lstrip('/')).resolve()
        return current == parent or parent in current.parents
    except (EnvironmentUnavailable, OSError, StopIteration):
        return False


def run_service(arguments):
    if not shutil.which('systemd-run'):
        raise EnvironmentUnavailable('systemd-runがありません。Linux/WSLの評価環境を確認してください。')
    command = ['systemd-run', '--user', '--wait', '--pipe', '--collect',
               '--working-directory=' + str(ROOT), sys.executable, str(ROOT / 'rr'), '--_worker', *arguments]
    return subprocess.run(command, stdin=subprocess.DEVNULL).returncode


def _check(work, dataset, safety_stop=None):
    expected = solve_dataset(load_dataset(dataset))
    run = run_isolated(work, 'main.py', dataset, memory_mib=128, safety_stop=safety_stop)
    if run.status == 'OK':
        lines = run.stdout.splitlines()
        try:
            actual = [int(line) for line in lines] if all(re.fullmatch(r'-?[0-9]+', line) for line in lines) else None
        except ValueError:
            actual = None
        if actual != expected:
            run.status = 'WRONG_ANSWER'
    return {'schema_version': 2, 'kind': 'correctness-check', 'status': run.status,
            'dataset_id': dataset.name, 'sha256': fingerprint(dataset, ('map.csv', 'queries.csv', 'metadata.json')),
            'run': asdict(run)}


def display_measurement(result):
    if result['status'] != 'COMPLETE':
        print('未完了: ' + result.get('error', '評価環境を確認してください。'), file=sys.stderr)
        return 2
    failed = False
    for record in result['datasets']:
        team, base = record['team'], record['baseline']
        print(f'Dataset: {record["dataset_id"]} / 正解判定: {team["status"]}')
        print(f'  基準中央値: {base["median_seconds"]:.6f} 秒')
        if team['median_seconds'] is not None:
            print(f'  改善版中央値: {team["median_seconds"]:.6f} 秒 / 高速化率: {record["speedup"]:.2f} 倍')
        print(f'  最大メモリ: {team["memory_peak_mib"]:.2f} MiB / 上限: 128 MiB（cgroup、RSSではありません）')
        failed |= team['status'] != 'OK'
    print('正式な処理性能点は、全チームの結果を集めてから相対評価で計算します。')
    return 1 if failed else 0


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='./rr', description='RoboRoute 実習用コマンド')
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='基準とレポートをwork/に準備（上書きしません）')
    init.add_argument('--work', type=Path, default=ROOT / 'work')
    show = commands.add_parser('show', help='地図・経路・探索アニメーション')
    show.add_argument('--dataset', default='sample')
    show.add_argument('--query', type=int)
    show.add_argument('--animate', action='store_true')
    show.add_argument('--delay', type=float, default=.04)
    show.add_argument('--steps-per-frame', type=int, default=8)
    for name, default in [('check', 'sample'), ('bench', 'practice'), ('mock', None)]:
        command = commands.add_parser(name, help={'check':'1回実行して正解判定', 'bench':'基準・改善版を各5回測定', 'mock':'模擬本番3種類を各5回測定'}[name])
        command.add_argument('--work', type=Path, default=ROOT / 'work')
        if default:
            command.add_argument('--dataset', default=default)
        command.add_argument('--result', type=Path)
        command.add_argument('--safety-stop', type=float)
        command.add_argument('--team')
    pack = commands.add_parser('pack', help='新しい提出形式のZIPを作成・検査')
    pack.add_argument('--work', type=Path, default=ROOT / 'work')
    pack.add_argument('--team', required=True)
    pack.add_argument('--slides', type=Path, required=True)
    pack.add_argument('--output', type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.command == 'init':
            work = init_work(args.work)
            print(f'準備完了: {work}\n編集するファイル: {work / "main.py"}、{work / "roboroute"}\n次: ./rr show --query 10 → ./rr check → ./rr bench\nレポート: {work / "report/experiment_log.md"}')
            return 0
        if args.command == 'show':
            command = [sys.executable, str(ROOT / 'tools/visualize.py'), str(dataset_path(args.dataset))]
            if args.query is not None:
                command += ['--query', str(args.query)]
            if args.animate:
                command += ['--animate', '--delay', str(args.delay), '--steps-per-frame', str(args.steps_per_frame)]
            return subprocess.run(command).returncode
        if args.command == 'pack':
            output = pack_submission(args.work, args.team, args.slides, args.output)
            print(f'ZIP作成・安全検査: OK\n提出ファイル: {output}')
            return 0
        # Resolve user paths before the worker changes working directory.
        args.work = args.work.resolve()
        if not args.work.is_dir() or not (args.work / 'main.py').is_file():
            raise ValueError('work/main.pyがありません。先に ./rr init を実行してください。')
        if args.command != 'mock':
            args.dataset = str(dataset_path(args.dataset))
        if args.result is None:
            args.result = ROOT / 'results' / (args.command + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1000000:06d}.json')
        args.result = args.result.resolve()
        if not args._worker and not _inside_delegation():
            forwarded = [args.command, '--work', str(args.work), '--result', str(args.result)]
            if args.command != 'mock':
                forwarded += ['--dataset', args.dataset]
            if args.safety_stop is not None:
                forwarded += ['--safety-stop', str(args.safety_stop)]
            if args.team:
                forwarded += ['--team', args.team]
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(json.dumps({'schema_version': 2, 'kind': 'benchmark-measurement', 'status': 'INCOMPLETE', 'error': '隔離ワーカーが完了していません。'}) + '\n')
            code = run_service(forwarded)
            if code == 2 or code not in (0, 1) or json.loads(args.result.read_text()).get('status') == 'INCOMPLETE':
                print('隔離実行を完了できませんでした。通常WSLで ./rr を実行し、ユーザーsystemd・cgroup・bubblewrapを確認してください。無制限実行には切り替えません。', file=sys.stderr)
            return code
        if args.command == 'check':
            result = _check(args.work, Path(args.dataset), args.safety_stop)
            print(f'正解判定: {result["status"]} / 上限: 128 MiB')
            code = 0 if result['status'] == 'OK' else (2 if result['status'] == 'OPERATOR_STOP' else 1)
        else:
            datasets = [ROOT / 'datasets' / n for n in MOCK_DATASETS] if args.command == 'mock' else [Path(args.dataset)]
            result = evaluate(args.work, 'main.py', datasets, 128, args.safety_stop, team_id=args.team)
            code = display_measurement(result)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(f'結果JSON: {args.result}')
        return code
    except (EnvironmentUnavailable, OSError, ValueError, zipfile.BadZipFile) as error:
        if getattr(args, 'result', None) is not None:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(json.dumps({'schema_version': 2, 'kind': 'benchmark-measurement', 'status': 'INCOMPLETE', 'error': str(error)}, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'ERROR: {error}', file=sys.stderr)
        if isinstance(error, EnvironmentUnavailable):
            print('通常WSLのユーザーsystemd・cgroup・bubblewrapを確認してください。隔離なしでは実行しません。', file=sys.stderr)
        return 2
