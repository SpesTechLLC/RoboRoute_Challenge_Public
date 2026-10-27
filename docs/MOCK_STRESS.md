# 2日目のストレス模擬本番

従来のbenchと同じ「基準プログラムから何倍高速化したか」を、公開ストレス6種類で確認します。正式な180秒スループットの点数とは別の練習用評価で、180秒の打ち切りや処理枚数の集計はありません。baseline・公式採点式・128MiB制限・既存の `./rr mock` は変更しません。

## 実行方法

通常のWSLターミナルで、既存のwork/をそのまま評価します。work/を初期化し直す必要はありません。

```bash
# 開発中の繰り返し確認
./rr mock-stress --lite

# 2日目の最終確認
./rr mock-stress --full

# 別の作業ディレクトリ・チーム名・JSON保存先も指定可能
./rr mock-stress --lite --work /path/to/existing/work \
  --team team01 --result results/team01-stress-lite.json
```

`--lite` または `--full` のどちらか一方が必須です。省略すると引数エラーで停止します。`--result` の省略時も、毎回 `results/mock-stress-lite-日時.json` / `results/mock-stress-full-日時.json` に保存します。

他のベンチマークや重い処理と同時に実行しないでください。改善版が遅い場合、全体も長くなります。`--safety-stop 秒数` は1実行に対する運営上の安全停止で、競技上の制限ではありません。停止した結果はINCOMPLETEとして再測定します。

## LiteとFullの入力

| Fullの公開データ | 地図 | Full問い合わせ | Lite問い合わせ |
|---|---|---:|---:|
| stress_open_unique | 181×181 | 359 | 16 |
| stress_detour | 181×181 | 455 | 20 |
| stress_maze_long | 251×251 | 563 | 24 |
| stress_islands_mixed | 241×221 | 947 | 40 |
| stress_open_unique_100x100_q2000 | 100×100 | 2,000 | 128 |
| stress_detour_100x100_q2000 | 100×100 | 2,000 | 128 |

Liteは各名に `_lite` を付けた独立した公開データです。地図の3ファイルのうちmap.csvは元の地図とバイト一致し、queries.csvは元の問い合わせから抽出します。元データ・抽出行番号（ヘッダーを除く0始まり）・元ファイルのSHA-256をmetadata.jsonに記録します。

抽出は到達不能・同一セル・直接距離で到達・迂回を区別し、距離の四分位と端点の重複も考慮します。全種類で参照BFSと独立した配列BFSを照合しました。開放地図の端点の一意性と少数の迂回例、迂回地図の約15%の到達不能、迷路の長い経路、島地図の約40%の到達不能・同一セル・約20%の端点重複を保ちます。100×100版は小件数版より問い合わせを多くし、迂回版では端点重複も約半数残します。

少数標本なのでFullと比率が完全に同じにはなりません。まれな迂回も少なくとも1件含め、誤実装を見逃しにくくしています。Liteの高速化率はFullと直接比較せず、最後はFullで確認してください。

## 測定と集計

既存の `tools.benchmark.evaluate()` と `tools.isolated_runner.run_isolated()` を再利用します。地図ごとに基準と改善版を交互に各5回実行し、全回の出力を参照解と照合します。各実行は従来と同じcgroup v2・bubblewrapの隔離、128MiB・swapなしです。メモリ値は子プロセス・cache・tmpfs等を含むcgroup memory.peakで、RSSではありません。

各地図について正解判定、基準中央値、改善版中央値、高速化率、基準と改善版それぞれの最大メモリを表示・保存します。地図iの基準中央値をBᵢ、改善版中央値をTᵢとすると、集計は次のとおりです。

- 地図別高速化率：Bᵢ / Tᵢ
- 総合高速化率（主指標）：6種類の高速化率の幾何平均 `exp(Σ(log Bᵢ − log Tᵢ) / 6)`
- 合計時間比（参考）：`ΣBᵢ / ΣTᵢ`
- 全体の最大メモリ：改善版の6種類×5回、計30回の最大値

| 状態 | 画面・JSON | 終了コード |
|---|---|---:|
| 6種類すべて全5回正解・正常終了 | VALID、両総合指標が有効 | 0 |
| 1回でも誤答・メモリ超過・実行失敗等 | INVALID、原因の地図・回数・状態を表示。両総合指標はnull | 1 |
| 隔離起動失敗・基準異常・安全停止・ワーカー中断等 | INCOMPLETE、原因を表示。競技上の不正解として扱わず再測定 | 2 |

競技側の失敗が出ても、隔離環境が正常なら残りの地図も測定します。1種類の全5回が正解・正常終了して初めて正解数に加算します。総合結果が無効でも、成功した地図の個別結果と失敗runの標準出力・標準エラー・メモリイベントはJSONで確認できます。

JSONの最上位 `status=COMPLETE` は測定が完了したことを表します。有効性は `summary.status`（VALID / INVALID / INCOMPLETE）と `summary.valid` を参照してください。`summary.geometric_mean_speedup`、`summary.total_time_ratio` は有効時のみ数値です。`official_score=false` であり、公式点数は計算しません。入力・基準・改善版のハッシュ、全run、環境情報も既存benchと同様に保存します。

## 実測と再現

2026-10-27の所要時間・各地図の結果・テスト結果は[検証レポート](mock_stress/REPORT.md)を参照してください。Liteは基準30回の合計を30秒以内にする開発用の目安で調整し、実測で23.85秒を確認しました。これは制限時間ではなく、実行環境によって変わります。

入力の再生成はPython標準ライブラリだけで実行できます。生成先は新しいディレクトリを指定してください。既存入力は上書きしません。Fullの公開入力と参照BFSを使うため、生成にも時間がかかります。非公開地図・非公開seedは使用しません。

```bash
python3 tools/stress_lite.py --output results/reproduce-stress-lite
python3 -m unittest discover -s tests -v

# 実機の隔離テストも有効にする場合
systemd-run --user --wait --pipe --collect --working-directory="$PWD" \
  /usr/bin/env ROBOROUTE_INTEGRATION_TESTS=1 \
  /usr/bin/python3 -m unittest discover -s tests -v
```

[抽出条件・構造統計・SHA-256](mock_stress/lite-manifest.json)も公開しています。Fullは既存の公開6種類を使用し、sample・practice・performance・mock_*および元のstress入力は変更していません。
