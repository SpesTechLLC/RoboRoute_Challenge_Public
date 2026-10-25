# 公開ストレスデータの検証・測定結果

2026-10-25（日本時間）。master `a9c034a` を起点とする追加データです。全seed・条件を公開し、非公開評価用データは作成していません。既存6セット、baseline、work/、評価器、採点式は変更しません。

[利用・再生成・実行器・180秒案](../STRESS_DAY2.md) / [設定・SHA一覧](manifest.json)

100×100・2,000問い合わせの追加2セットは[別の比較レポート](100x100/REPORT.md)にあります。以下は基本4セットの結果です。

## データ一覧

| 名前 | サイズ | 問い合わせ | seed | 障害物 | 成分 | 到達可 / 不可 |
|---|---|---:|---:|---:|---:|---:|
| stress_open_unique | 181×181 | 359 | 2026102501 | 0.995% | 1 | 359 / 0 |
| stress_detour | 181×181 | 455 | 2026102502 | 0.641% | 2 | 387 / 68 |
| stress_maze_long | 251×251 | 563 | 2026102503 | 50.399% | 1 | 563 / 0 |
| stress_islands_mixed | 241×221 | 947 | 2026102504 | 1.849% | 4 | 567 / 380 |

| 名前 | 最短距離（到達可能の最小 / 中央値 / 最大） | 始点重複率 | 終点重複率 | 分岐セル |
|---|---|---:|---:|---:|
| stress_open_unique | 163 / 192 / 323 | 0.00% | 0.00% | 32405 |
| stress_detour | 249 / 307 / 364 | 14.29% | 13.41% | 32540 |
| stress_maze_long | 558 / 5028 / 11393 | 0.53% | 1.24% | 1504 |
| stress_islands_mixed | 0 / 68 / 191 | 19.43% | 19.43% | 52182 |

重複率は各役割の `1 − distinct/Q`。到達不能の距離−1は距離統計から除外しています。分岐セルは通行可能な隣接セルが3つ以上あるセルです。

- open_unique：始点359個・終点359個はそれぞれ全件異なり、同一問い合わせもありません。Manhattan距離は163〜323。1件は正解がManhattanより2長く、残りは一致します。
- detour：455件中387件（85.05%）が大きな迂回を必要とし、残り68件は到達不能です。到達可能全件で正解−Manhattanが240〜354（中央値268）、正解/Manhattanが4.29〜70.60（中央値9.97）。障害物率0.641%でも直接距離は通用しません。
- maze_long：全件到達可能ですが、最短距離中央値5,028、最大11,393です。Manhattan中央値225、最短距離−Manhattan中央値4,816、分岐セル1,504で、長距離・分岐・壁の影響があります。
- islands_mixed：4成分の大きさは15,943 / 13,046 / 12,808 / 10,479セル。到達不能380件（40.13%）、始終点それぞれ約19.43%の重複、同一セルの始終点23件を含みます。

## 基準5回の実測

既存の隔離評価器によるCOMPLETEのみ採用。すべてbaselineと検証用参照BFSが各5回OK、128MiB・swapなしです。メモリは5回の最大cgroup memory.peakで、RSSではありません。秒数は実行順です。

| 名前 | 基準1〜5回（秒） | 基準中央値（秒） | 基準最大MiB | 参照BFS中央値（秒） | 参照BFS最大MiB |
|---|---|---:|---:|---:|---:|
| stress_open_unique | 13.499977 / 13.747701 / 13.642337 / 13.428658 / 13.920775 | 13.642337 | 12.28 | 7.703230 | 12.06 |
| stress_detour | 15.207557 / 14.586214 / 15.053650 / 15.642656 / 14.867280 | 15.053650 | 12.59 | 8.459385 | 12.23 |
| stress_maze_long | 12.633698 / 12.573391 / 12.805156 / 12.332287 / 12.219930 | 12.573391 | 13.52 | 7.748155 | 12.38 |
| stress_islands_mixed | 11.189351 / 10.775129 / 10.748057 / 10.997204 / 11.059227 | 10.997204 | 10.31 | 5.717512 | 10.25 |

環境：Python `3.14.4 (main, Jun 18 2026, 14:25:02) [GCC 15.2.0]`、kernel `6.6.87.2-microsoft-standard-WSL2`。基準と参照BFSを交互に測定しています。各JSONにはPython・kernel・入力ハッシュ・プログラムハッシュ・全run・残存プロセス診断を残しました。

`team` フィールドは `TRUSTED_REFERENCE_BFS_CALIBRATION_ONLY` という検証用プログラムです。チームA〜Eの改善版・最速版を測定した結果ではありません。参照BFSでは固定コストに対して十分な負荷ですが、数十倍高速な最速チームでも同じことが成り立つかは未測定です。

| 名前 | pilotサイズ | pilot問い合わせ | pilot基準中央値（秒） | 確定問い合わせ |
|---|---|---:|---:|---:|
| stress_open_unique | 181×181 | 24 | 1.002292 | 359 |
| stress_detour | 181×181 | 24 | 0.791500 | 455 |
| stress_maze_long | 251×251 | 24 | 0.639235 | 563 |
| stress_islands_mixed | 241×221 | 24 | 0.380032 | 947 |

今回は各pilotの実測に基づく問い合わせ数の調整1回で全4種が10〜20秒へ入り、初期の幅・高さを拡大する必要はありませんでした。公開版の入力は測定した作業用候補と3ファイルのSHA-256が完全一致します。公開版へのコピー後にも全件参照検証・再生成照合を実施しました。

## 探索量の比較（参考）

到達可能距離の16分位相当サンプルと、先頭の到達不能最大4件で、各アルゴリズムの正解を検証してから展開セル数を集計しました。下表は平均です。時間計測ではなく、優劣の順位付けにも使いません。連結成分判定・キャッシュは使用していません。

| 名前 | サンプル数 | BFS | 双方向BFS | A* |
|---|---:|---:|---:|---:|
| stress_open_unique | 16 | 27523.3 | 21819.6 | 9439.4 |
| stress_detour | 20 | 24021.8 | 18615.6 | 13747.8 |
| stress_maze_long | 16 | 18428.1 | 18064.4 | 18079.6 |
| stress_islands_mixed | 20 | 8143.2 | 7110.7 | 4281.6 |

このA*はManhattanヒューリスティック、同順位では `(f,g,セル番号)` を使います。双方向BFSは合流層を全展開します。タイブレーク・隣接順・前処理で結果は変わります。このサンプルでは開放地図でA*の探索削減が見られ、迷路では3方式の探索セル数が近く、Manhattanだけでは壁の先の長い通路を絞りにくいことが確認できます。

## 検証記録

| 名前 | 全件検査 | 正式形式の5回測定JSON | pilot | 探索量 |
|---|---|---|---|---|
| stress_open_unique | [validation](stress_open_unique.validation.json) | [benchmark](stress_open_unique.benchmark.json) | [pilot](stress_open_unique.pilot.json) | [search](stress_open_unique.search.json) |
| stress_detour | [validation](stress_detour.validation.json) | [benchmark](stress_detour.benchmark.json) | [pilot](stress_detour.pilot.json) | [search](stress_detour.search.json) |
| stress_maze_long | [validation](stress_maze_long.validation.json) | [benchmark](stress_maze_long.benchmark.json) | [pilot](stress_maze_long.pilot.json) | [search](stress_maze_long.search.json) |
| stress_islands_mixed | [validation](stress_islands_mixed.validation.json) | [benchmark](stress_islands_mixed.benchmark.json) | [pilot](stress_islands_mixed.pilot.json) | [search](stress_islands_mixed.search.json) |

全件検査は既存load_dataset、参照BFS、独立した一次元配列BFS、連結成分判定、距離の下界・偶奇、構造ごとの難しさの閾値、同一seedからの3入力ファイルのバイト再現を含みます。問い合わせ順に答えを照合し、答えのSHA-256も保存しています。全データの各CSVは4MiB以下、metadataは64KiB以下、各辺300以下、問い合わせ2,000以下です。

既存のwork/を変更せず、4セットとも `./rr check --dataset 名前` がOKになりました（[CLI確認](cli_checks.json)、[元ファイル・work/の保存確認](preservation.json)）。

20件の回帰テストは通常WSLのcgroup・bubblewrap実機テストも有効化して全件成功しました（skipなし）。既存の終了後待機・残存・OOM・出力制限・namespaceのテストを含みます。

## 確定条件から再生成

同名フォルダーを上書きしないため、以下は未使用のresults配下へ生成します。

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_open_unique \
  --kind stress_open_unique --width 181 --height 181 \
  --queries 359 --seed 2026102501
```

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_detour \
  --kind stress_detour --width 181 --height 181 \
  --queries 455 --seed 2026102502
```

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_maze_long \
  --kind stress_maze_long --width 251 --height 251 \
  --queries 563 --seed 2026102503
```

```bash
python3 tools/stress_dataset.py generate --output results/reproduce-stress_islands_mixed \
  --kind stress_islands_mixed --width 241 --height 221 \
  --queries 947 --seed 2026102504
```

## 公開練習用としての推奨

4種類すべてを追加公開する構成を推奨します。detourで迂回と到達不能の正しさ、open_uniqueで低重複・長距離、maze_longで壁と長い通路、islands_mixedで連結成分・繰返し端点への対応を確認できます。既存mock_roomsが部屋構造を補うため、今回の追加rooms候補は作っていません。

公開版の結果だけでは未知入力への対応は証明できません。最終評価用セットの作成は別途講師判断とし、この4地図を正式評価用に転用したり公式の重み・採点を変更したりしていません。masterへは確認後にマージします。
