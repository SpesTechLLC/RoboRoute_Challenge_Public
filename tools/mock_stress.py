"""Day-two public practice: aggregate the existing isolated five-run benchmark."""
from __future__ import annotations

import math
import time

from tools.benchmark import ROOT, evaluate

FULL_DATASETS = (
    'stress_open_unique', 'stress_detour', 'stress_maze_long',
    'stress_islands_mixed', 'stress_open_unique_100x100_q2000',
    'stress_detour_100x100_q2000',
)
MODES = {'full': FULL_DATASETS, 'lite': tuple(name + '_lite' for name in FULL_DATASETS)}


def summarize(result, mode):
    """Keep execution completeness separate from a participant's invalid result."""
    names = MODES[mode]
    result.update(kind='stress-mock-measurement', mode=mode,
                  aggregate_method='geometric-mean-of-six-baseline-speedups-v1',
                  official_score=False)
    records = result['datasets']
    reasons = []
    correct = 0
    for record in records:
        team = record.get('team', {})
        runs = team.get('runs', [])
        ok = (team.get('status') == 'OK' and len(runs) == 5
              and all(run['status'] == 'OK' for run in runs))
        record['correct'] = ok
        correct += ok
        if not ok:
            failures = [f'{index}回目: {run["status"]}' for index, run in enumerate(runs, 1)
                        if run['status'] != 'OK']
            reason = ', '.join(failures) or team.get('status', '未測定')
            reasons.append(f'{record["dataset_id"]}: {reason}')
    if result['status'] != 'COMPLETE':
        reasons.insert(0, result.get('error', '隔離測定が完了していません。'))
    elif tuple(record['dataset_id'] for record in records) != names or any(
            record.get(side, {}).get('status') != 'OK'
            or len(record.get(side, {}).get('runs', [])) != 5
            or any(run['status'] != 'OK' for run in record[side]['runs'])
            for record in records for side in ('baseline',)):
        result['status'] = 'INCOMPLETE'
        reasons.insert(0, '6種類の基準測定が揃っていません。')
    valid = result['status'] == 'COMPLETE' and correct == len(names)
    geometric = ratio = None
    if valid:
        baseline = [record['baseline']['median_seconds'] for record in records]
        team = [record['team']['median_seconds'] for record in records]
        if any(value is None or not math.isfinite(value) or value <= 0 for value in baseline + team):
            result['status'] = 'INCOMPLETE'
            valid = False
            reasons.append('測定中央値が正の有限値ではありません。')
        else:
            geometric = math.exp(math.fsum(math.log(b) - math.log(t) for b, t in zip(baseline, team)) / len(names))
            ratio = math.fsum(baseline) / math.fsum(team)
    result['summary'] = {
        'status': 'INCOMPLETE' if result['status'] != 'COMPLETE' else 'VALID' if valid else 'INVALID',
        'valid': valid, 'correct_datasets': correct, 'total_datasets': len(names),
        'geometric_mean_speedup': geometric, 'total_time_ratio': ratio,
        'team_memory_peak_mib': max((run['memory_peak_mib'] for record in records
                                     for run in record.get('team', {}).get('runs', [])), default=None),
        'reasons': reasons,
    }
    return result


def evaluate_stress(program, mode, safety_stop=None, *, team_id=None):
    started = time.perf_counter()
    result = evaluate(program, 'main.py', [ROOT / 'datasets' / name for name in MODES[mode]],
                      128, safety_stop, team_id=team_id)
    result['wall_seconds'] = time.perf_counter() - started
    return summarize(result, mode)


def display_stress(result):
    summary = result['summary']
    print(f'模擬本番 {result["mode"].title()}')
    print('基準比の練習用評価（各5回中央値・128 MiB）。正式な180秒スループットの点数とは別です。')
    print(f'正解: {summary["correct_datasets"]}/{summary["total_datasets"]}')
    if summary['valid']:
        print(f'総合高速化率（幾何平均）: {summary["geometric_mean_speedup"]:.2f} 倍')
        print(f'合計時間比（参考）: {summary["total_time_ratio"]:.2f} 倍')
    else:
        print(f'総合結果: {summary["status"]}（総合高速化率・合計時間比は無効）')
        for reason in summary['reasons']:
            print(f'  原因: {reason}')
    peak = summary['team_memory_peak_mib']
    print('最大メモリ（改善版）: ' + (f'{peak:.2f} MiB' if peak is not None else '未測定'))
    print('メモリは全測定の最大cgroup memory.peak（RSSではありません）。')
    for record in result['datasets']:
        print(f'\nDataset: {record["dataset_id"]} / 正解判定: {record.get("team", {}).get("status", "未完了")}')
        for side, label in [('baseline', '基準'), ('team', '改善版')]:
            measurement = record.get(side, {})
            seconds = measurement.get('median_seconds')
            peak = measurement.get('memory_peak_mib')
            if peak is None:
                peak = max((run['memory_peak_mib'] for run in measurement.get('runs', [])), default=None)
            timing = f'{seconds:.6f} 秒' if seconds is not None else '無効/未完了'
            memory = f'{peak:.2f} MiB' if peak is not None else '未測定'
            print(f'  {label}中央値: {timing} / 最大メモリ: {memory}')
        speedup = record.get('speedup')
        print('  高速化率: ' + (f'{speedup:.2f} 倍' if speedup is not None else '無効/未完了'))
    if 'wall_seconds' in result:
        print(f'\n所要時間: {result["wall_seconds"]:.2f} 秒（正解生成・測定・集計を含む）')
    return 0 if summary['valid'] else 2 if summary['status'] == 'INCOMPLETE' else 1
