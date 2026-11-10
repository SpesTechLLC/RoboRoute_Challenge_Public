# 生徒向け：3日目のデータで試す

**本番と同じ515枚を、講師の許可により公開しました。** 開放型・迂回型・迷路/部屋型・分断型・混合型が **各103枚** あります。
これまでの `work/main.py` と `work/roboroute/` をそのまま使えます。workの中身は変更・上書きしません。

## 1. リポジトリを更新

Ubuntu / WSLのターミナルで、自分のリポジトリへ移動します。

```bash
cd ~/RoboRoute_Challenge_Public
git pull --ff-only
```

workがまだない人だけ `./rr init` を実行してください。すでに作業している人は初期化不要です。

## 2. 180秒で何枚解けるかを測る

5種類を混ぜて測る場合：

```bash
./rr mock-final
```

1種類だけで測る場合（それぞれ、その種類の103枚が対象）：

```bash
./rr mock-final --family open
./rr mock-final --family detour
./rr mock-final --family maze
./rr mock-final --family disconnected
./rr mock-final --family mixed
```

| 指定 | 地図の種類 |
|---|---|
| `open` | 開放型：広い場所が多い |
| `detour` | 迂回型：壁を回り込む必要がある |
| `maze` | 迷路・部屋型：通路や部屋がある |
| `disconnected` | 分断型：到達できない組合せを含む |
| `mixed` | 混合型：複数の特徴が混在 |

正解した地図は **+1**、誤答・形式違反・異常終了・メモリ超過などは **-1** です。
180秒で判定が終わっていない地図は0点です。メモリ上限は子プロセスを含む128MiBです。
失敗後も次の地図へ進みます。

**180秒で全103枚を終える保証はありません。** 時間内に確定した枚数・得点を表示します。
103枚を一巡しても時間が余れば、同じ103枚を繰り返します。全種類の場合は515枚が対象です。

まず短く動作確認する場合：

```bash
./rr mock-final --family open --seconds 3
```

## 3. 103枚すべての正誤を確認する

「180秒で何枚解くか」と別に、指定した種類の **全103枚を1回ずつ** 試せます。

```bash
./rr check-final --family open
./rr check-final --family detour
./rr check-final --family maze
./rr check-final --family disconnected
./rr check-final --family mixed
```

全515枚を1回ずつ確認する場合：

```bash
./rr check-final
```

全件確認は180秒方式ではなく、枚数を基準に終了します。時間がかかることがあります。
止まらないコードへの対策として、1地図の実行を既定10秒で安全停止します。その地図は未確定として記録し、次へ進みます。
10秒では足りない場合は、例えば次のように30秒へ変更できます。これは全件確認専用の設定で、本番形式の制限を変更するものではありません。

```bash
./rr check-final --family maze --safety-stop 30
```

## 4. 地図1枚を見て調べる

各種類の最初の地図：

```bash
./rr show --dataset final_practice/open --query 0
./rr show --dataset final_practice/detour --query 0 --animate
./rr check --dataset final_practice/maze
```

2枚目以降は `open-001` から `open-102` のような名前です。

```bash
./rr show --dataset final_practice/open-001 --query 0
./rr check --dataset final_practice/mixed-050
```

## 5. 結果を保存して改善前後を比べる

結果は自動的に `results/` 内の別名JSONへ保存されます。最後に表示されるパスを確認してください。
正解数・失敗数・得点・処理数・終了理由・実時間・最大メモリと、地図ごとの判定が記録されます。

自分で名前を付ける例：

```bash
./rr mock-final --family open --result results/open-before.json
# workのコードを改善してから別名で測る
./rr mock-final --family open --result results/open-after.json
```

同じ結果名は上書きしません。別の名前を付けてください。実験レポートに、変更内容・正解数・失敗数・得点を残しましょう。

注意：

- このコマンドの結果は練習結果です。公式順位は講師が集計します。
- 探索対象の地図とseedは今回公開されました。答えの埋め込みはせず、任意の入力で正しく動くコードにしてください。
- 測定中は他の測定や重い処理を止めてください。
- 隔離環境のエラーが出たら、制限を外さず講師に相談してください。
- `./rr mock-stress --full` は以前の性能比較です。180秒の地図単位採点は `mock-final` を使います。

詳しい制限・検証・再生成は [FINAL_PRACTICE.md](FINAL_PRACTICE.md) を参照してください。
