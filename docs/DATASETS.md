# 公開データセット

| 名前 | 地図 | 問い合わせ数 | 用途 |
|---|---|---:|---|
| sample | 40×20 | 100 | 正解判定と表示の確認 |
| practice | 70×70 | 180 | 日々の改善実験。benchの既定値 |
| performance | 150×150 | 400 | 大きめの入力での性能測定 |
| mock_rooms | 100×100 | 180 | 部屋のある地図での模擬本番 |
| mock_maze | 101×101 | 120 | 長い迷路での模擬本番 |
| mock_islands | 100×100 | 180 | 到達不能を含む模擬本番 |

```bash
./rr show --dataset practice --query 10
./rr check --dataset practice
./rr bench --dataset performance
./rr mock
```

どのデータにもmap.csv、queries.csv、metadata.jsonがあります。生成seed等は各metadataを参照できます。最終評価用のデータはこのリポジトリに含まれません。

## 自分で練習データを作る

既存の配布データを上書きせず、results内の新しいフォルダーを使います。幅・高さは各300以下、問い合わせ数は2,000以下です。生成ツールの幅・高さは3以上です。

```bash
python3 tools/generate_dataset.py --output results/my-map --width 100 --height 100 --queries 200 --map-type rooms --query-type mixed --seed 12345
./rr show --dataset results/my-map --query 10
./rr bench --dataset results/my-map
```

地図はopen/random/rooms/maze/islands、問い合わせはrandom/repeated_goal/repeated_start/local/long_distance/mixedを選べます。条件を変えて、改善の得意・不得意を確かめてください。
