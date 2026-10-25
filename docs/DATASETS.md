# 公開データセット

| 名前 | 地図 | 問い合わせ数 | 用途 |
|---|---|---:|---|
| sample | 40×20 | 100 | 正解判定と表示の確認 |
| practice | 70×70 | 180 | 日々の改善実験。benchの既定値 |
| performance | 150×150 | 400 | 大きめの入力での性能測定 |
| mock_rooms | 100×100 | 180 | 部屋のある地図での模擬本番 |
| mock_maze | 101×101 | 120 | 長い迷路での模擬本番 |
| mock_islands | 100×100 | 180 | 到達不能を含む模擬本番 |
| stress_open_unique | 181×181 | 359 | 低重複・長距離の開放地図 |
| stress_detour | 181×181 | 455 | 低障害物率でも大幅な迂回・到達不能 |
| stress_maze_long | 251×251 | 563 | 長い通路・分岐のある大規模迷路 |
| stress_islands_mixed | 241×221 | 947 | 4連結成分・到達不能・繰返し端点 |

```bash
./rr show --dataset practice --query 10
./rr check --dataset practice
./rr bench --dataset performance
./rr mock
```

どのデータにもmap.csv、queries.csv、metadata.jsonがあります。生成seed等は各metadataを参照できます。最終評価用のデータはこのリポジトリに含まれません。

追加のstress_*は2日目以降の公開練習用です。基準中央値が約10〜20秒になるよう実測で負荷を調整しました。4種類とも基準・検証用参照BFSの各5回が正解し、128MiB制限を遵守しています。最速チームのコードでの負荷は未測定です。既存の `work/` をそのまま使用できます。

```bash
./rr check --dataset stress_detour
./rr bench --dataset stress_maze_long
```

[構造・全seed・5回の測定値・メモリ・SHA-256・検証結果](stress_day2/REPORT.md)と、[再生成・利用方法・180秒追加チャレンジの検討](STRESS_DAY2.md)を参照してください。既存データ・公式採点・入力形式は変更していません。

## 自分で練習データを作る

既存の配布データを上書きせず、results内の新しいフォルダーを使います。幅・高さは各300以下、問い合わせ数は2,000以下です。生成ツールの幅・高さは3以上です。

```bash
python3 tools/generate_dataset.py --output results/my-map --width 100 --height 100 --queries 200 --map-type rooms --query-type mixed --seed 12345
./rr show --dataset results/my-map --query 10
./rr bench --dataset results/my-map
```

地図はopen/random/rooms/maze/islands、問い合わせはrandom/repeated_goal/repeated_start/local/long_distance/mixedを選べます。条件を変えて、改善の得意・不得意を確かめてください。
