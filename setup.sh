#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
/usr/bin/python3 - <<'PY'
import json
from pathlib import Path
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10以降が必要です。担当講師へ相談してください。')
from tools.diagnose_environment import diagnose
report = diagnose()
output = Path('results/environment-check.json')
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
probe = report['bubblewrap_probe']
ready = report['delegated_parent'].get('inspection') == 'OK' and probe.get('returncode') == 0 and probe.get('bootstrap_ready') is True
print('環境診断:', 'OK' if ready else '利用できない機能があります')
print('詳細:', output)
if not ready:
    print('通常のUbuntu/WSLターミナルで実行し、docs/ENVIRONMENT.mdを確認して担当講師へ相談してください。')
    raise SystemExit(2)
print('次: ./rr init → ./rr show --query 10 → ./rr check')
print('メモリ上限の実際の適用は ./rr check で確認します。')
PY
