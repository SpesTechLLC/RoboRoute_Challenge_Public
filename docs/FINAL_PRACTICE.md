# 3日目：180秒の公開練習

講師の明示的な許可により、**本番と同じ515枚・seedを公開**しました。5種類が103枚ずつです。
元の本番出題順・提出物・採点結果・セッションは含みません。学生は [すぐ試す手順](FINAL_STUDENT_GUIDE.md) から始めてください。
本番と同じ地図単位の得点・持ち時間・メモリ制限を体験できます。得点や速度を本番順位として使いません。

## 180秒を測る

いつもの `work/main.py` と `work/roboroute/` を使います。既存のwork、提出ZIP、以前の結果を上書きしません。
測定直前にPythonソースと公開入力をコピーし、そのコピーを測定します。測定途中の編集は次回の実行から反映されます。

```bash
./rr mock-final
```

開放・迂回・迷路/部屋・分断・混合から1枚ずつ出し、この並びを103回繰り返す公開練習用の順序です。
515マップを終えたら同じ順に巡回し、180秒になるまで続けます。毎回、新しいプロセスで地図1枚を実行します。
同じ地図が後の巡回で再び出題され、その回に解いた地図として得点に数えられます。

| 判定 | 地図1枚の得点 |
|---|---:|
| 全問い合わせの距離が正しい | +1 |
| 誤答・出力形式違反 | -1 |
| 異常終了・128MiB超過・出力超過・残存プロセス | -1 |
| 180秒時点で未確定・処理途中 | 0 |

失敗した地図の後はプロセスを後始末して次へ進みます。同じ失敗で二重に減点しません。
180秒にはプロセス起動、入力コピー・読込み、前処理、計算、出力、正解照合、地図ごとの結果保存を含みます。
事前のソース検査・入力ハッシュ検証・コピー準備は測定前です。終了後の後始末で実時間が少し超える場合は、超過秒もJSONへ記録します。

128MiBは子プロセス・cache・tmpfsを含むcgroup memory.peakです。swapは0、プロセス数は64、ファイル記述子は256に制限します。
bubblewrapでネットワークやホストのhomeを隔離し、プログラムには入力3ファイルだけを渡します。正解ファイルは渡しません。
隔離が使えなければ停止し、無制限実行へ切り替えません。Python標準ライブラリだけを使用してください。

## 5種類を別々に測る

各コマンドは、その種類の103枚だけを順に出して180秒測ります。103枚を一巡したら繰り返します。
180秒で全103枚を解き切る保証はありません。全103枚を1回ずつ確認するには `check-final` を使います。

```bash
./rr mock-final --family open
./rr mock-final --family detour
./rr mock-final --family maze
./rr mock-final --family disconnected
./rr mock-final --family mixed
```

短い起動確認では秒数を指定できます（0より大きく180以下）。短時間の得点を180秒の得点へ換算しません。

```bash
./rr mock-final --seconds 3
./rr mock-final --family detour --seconds 10
```

## 全103枚を1回ずつ正誤確認

```bash
./rr check-final --family open
./rr check-final --family detour
./rr check-final --family maze
./rr check-final --family disconnected
./rr check-final --family mixed
```

`./rr check-final` は全515枚を1回ずつ確認します。180秒測定とは別のモードで、全件が終わるまで実行します。
1地図の実行は既定10秒で安全停止し、未確定として記録して次へ進みます。`--safety-stop 30` 等で変更できます。
全件確認は `kind: public-final-correctness-check` として保存し、180秒の結果とは分離します。

## 地図を見たり、1枚だけ確認したりする

| 種類 | 最初の1枚 | 残り102枚 |
|---|---|---|
| 開放型 | `final_practice/open` | `open-001`〜`open-102` |
| 迂回型 | `final_practice/detour` | `detour-001`〜`detour-102` |
| 迷路・部屋型 | `final_practice/maze` | `maze-001`〜`maze-102` |
| 分断型 | `final_practice/disconnected` | `disconnected-001`〜`disconnected-102` |
| 混合型 | `final_practice/mixed` | `mixed-001`〜`mixed-102` |

すべて `datasets/final_practice/` 内です。サイズ・障害物率・問い合わせ数は地図ごとに異なり、300×300・2,000問い合わせ以内です。
既存の入力形式を変えず、次のコマンドで使えます。

```bash
./rr show --dataset final_practice/open --query 10
./rr show --dataset final_practice/detour --query 10 --animate
./rr check --dataset final_practice/maze
./rr check --dataset final_practice/disconnected
./rr bench --dataset final_practice/mixed-001
```

`bench`は従来どおり基準と改善版を各5回測り、中央値と高速化率を表示します。180秒の±1方式は `mock-final` を使います。
`mock-stress --full` は2日目の公開6種類による性能回帰確認です。目的・結果の形式を混ぜません。

## 結果を見る

画面に正解数、不正解/失敗数、得点、処理数、未確定数、終了理由、実時間、最大メモリと種類別集計を表示します。
JSONは `results/mock-final-種類-日時-識別子.json` に毎地図後と終了時に保存します。既存ファイルは上書きしません。

```bash
./rr mock-final --result results/final-first.json
python3 -m json.tool results/final-first.json
```

JSONには `kind: public-final-practice`、`official_score: false`、持ち時間、公開入力・ソースのハッシュ、
地図ごとの確定時刻・判定・累積点、種類別集計、最大メモリ、時間超過を記録します。
結果先にwork内や既存ファイルを指定すると、上書きせず停止します。

終了コードは、正常完了かつ失敗なしが0、正常完了だが失敗した地図ありが1、環境・設定エラーが2、中断が130です。
1でも測定結果は保存されています。環境障害と競技上の失敗を区別してください。
Ctrl-Cではワーカーサービスを停止し、未完了の記録を残します。同じ試行の途中再開はせず、新しい結果名で測り直します。

## 公開データの検証・再生成

原本515枚は既存の参照BFSと独立した配列BFSで照合済みです。公開時には全入力・正解のbyte一致と全515枚の公開seedによる再生成を確認しています。
講師が公開を許可したseed、各地図の生成条件、入力・正解ハッシュは `datasets/final_practice/manifest.json` にあります。
この515枚とseedは公開済みです。元の本番出題順・セッション・生徒提出物・採点結果は含みません。

```bash
# 入力上限・端点・ハッシュ・公開構成を検査
python3 tools/final_practice_data.py verify

# 全515枚の独立正解計算と、一時領域でのbyte一致再生成も検査（時間がかかります）
python3 tools/final_practice_data.py verify --full

# 未使用のフォルダへ同じ公開データを再生成
python3 tools/final_practice_data.py generate --output results/final-practice-rebuilt
```

通常のUbuntu/WSLターミナルで実行し、他の重い処理と同時に測らないでください。
コードの最適化による効果はこの公開データで比較し、本番の正式な採点・集計は講師に任せます。
