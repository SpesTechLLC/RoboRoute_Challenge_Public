# 100×100・多数問い合わせの追加比較

2026-10-25（日本時間）。100×100でも問い合わせ数を増やして長い処理時間を作れるか、公開条件で実測しました。基本4セットはそのまま残し、追加練習用として以下の2セットを用意しました。

| データセット | サイズ | 問い合わせ | seed | 基準中央値 | 基準最大メモリ | 参照BFS中央値 |
|---|---|---:|---:|---:|---:|---:|
| stress_open_unique_100x100_q2000 | 100×100 | 2,000 | 2026102511 | 21.503537秒 | 8.88MiB | 11.061264秒 |
| stress_detour_100x100_q2000 | 100×100 | 2,000 | 2026102512 | 17.678035秒 | 8.90MiB | 9.444091秒 |

まず同じseed・地図の24件pilotを基準・参照BFS各5回で測り、その後、問題仕様の上限2,000件まで増やして各5回測定しました。全測定は既存の128MiB・swapなしの隔離を使用し、COMPLETEかつ全10回OKを確認しました。学生チームA〜E・最速チームのコードは測定していません。60秒の運営停止は競技の時間制限ではありません。

| データセット | pilot基準中央値 | 基準1〜5回（秒） |
|---|---:|---|
| stress_open_unique_100x100_q2000 | 0.322362秒 | 21.036185 / 20.792287 / 21.503537 / 21.951501 / 21.862027 |
| stress_detour_100x100_q2000 | 0.289539秒 | 17.563580 / 18.819795 / 18.043756 / 17.168825 / 17.678035 |

メモリ値はcgroup memory.peakの5回最大値で、RSSではありません。測定環境は既存4セットと同じWSL、Python 3.14.4、kernel 6.6.87.2-microsoft-standard-WSL2です。公開ファイルは測定用候補とSHA-256が一致しています。

## 難しさと使い分け

| データセット | 到達可能 / 不可 | 始点重複率 | 終点重複率 | 正解距離中央値（到達可能） |
|---|---:|---:|---:|---:|
| stress_open_unique_100x100_q2000 | 2000 / 0 | 0.00% | 0.00% | 106 |
| stress_detour_100x100_q2000 | 1700 / 300 | 62.30% | 62.20% | 174 |

開放地図は始点・終点がそれぞれ全2,000件で異なり、Manhattan距離は90以上です。Manhattanより長い問い合わせは0件です。このseedでは全件の正解がManhattanと一致しますが、他の地図でも一致するとは限りません。基準中央値は21.50秒で、既存の181×181・359件の13.64秒より長くなりました。地図サイズだけで負荷は決まりません。

迂回地図は障害物率1.150%ですが、大きな迂回が必要な問い合わせが1700件、到達不能が300件あります。到達可能の正解−Manhattanの中央値は150です。壁の近くへ多数の問い合わせを置くため端点の重複が多く、キャッシュの効果も確認できます。

100×100・2,000件の方式は、問い合わせ処理を何度も行う負荷や、端点重複への対応を比較する追加セットとして有効です。一方、100×100は探索対象が最大10,000セルなので、251×251の迷路などより探索時のメモリ・空間的な広がりは小さくなります。未知の大規模地図への対応も確認するため、基本4セットと組み合わせる構成を推奨します。

基準・参照BFSの実測であり、最速チームでも固定コストを十分上回ることは未確認です。問い合わせ数は現行上限の2,000件を維持し、ルール・baseline・評価器・work/は変更していません。

既存のwork/を変更せず、両セットの `./rr check` でも正解を確認しました（[CLI確認記録](cli_checks.json)）。

## 実行・再生成

```bash
./rr check --dataset stress_open_unique_100x100_q2000
./rr bench --dataset stress_open_unique_100x100_q2000
./rr check --dataset stress_detour_100x100_q2000
./rr bench --dataset stress_detour_100x100_q2000
```

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_open_unique_100x100_q2000 \
  --kind stress_open_unique --width 100 --height 100 --queries 2000 --seed 2026102511
```

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_detour_100x100_q2000 \
  --kind stress_detour --width 100 --height 100 --queries 2000 --seed 2026102512
```

全件検証はload_dataset、既存参照BFS、独立した配列BFS、到達可否・構造の閾値、metadata・ファイル容量、同一seedからのバイト再生成を含みます。設定・SHA-256は[manifest](manifest.json)、各セットの全件検査・全run・pilotは以下にあります。

- stress_open_unique_100x100_q2000: [validation](stress_open_unique_100x100_q2000.validation.json) / [benchmark](stress_open_unique_100x100_q2000.benchmark.json) / [pilot](stress_open_unique_100x100_q2000.pilot.json)

- stress_detour_100x100_q2000: [validation](stress_detour_100x100_q2000.validation.json) / [benchmark](stress_detour_100x100_q2000.benchmark.json) / [pilot](stress_detour_100x100_q2000.pilot.json)

[基本4セットの結果](../REPORT.md) / [生成・検証・180秒案](../../STRESS_DAY2.md)
