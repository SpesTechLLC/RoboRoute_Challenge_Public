# RoboRoute Challenge

2次元グリッドの最短経路探索を高速化する、3日間のプログラミング実習です。Python 3標準ライブラリを使い、アルゴリズム・データ構造・前処理を改善します。

このリポジトリは生徒向けの配布版です。配布コード、公開データ、操作説明、レポートテンプレートを収録しています。

## はじめに

通常のUbuntu / WSLターミナルで、次を実行します。公開リポジトリなので、cloneにGitHubアカウントやSSH鍵は不要です。

```bash
git clone --branch master https://github.com/SpesTechLLC/RoboRoute_Challenge_Public.git
cd RoboRoute_Challenge_Public
./setup.sh
./rr init
./rr show --query 10
./rr check
./rr bench
```

`setup.sh`はPythonや隔離環境を確認するだけです。パッケージのインストールやシステム設定の変更は行いません。利用できない機能がある場合は[環境の確認](docs/ENVIRONMENT.md)を読み、担当講師へ相談してください。

## 実習で使うコマンド

リポジトリ直下で実行します。

| コマンド | 操作 |
|---|---|
| `./rr init` | 基準コードとレポートをwork/へコピー。既存の作業は上書きしません |
| `./rr show --query 10` | sampleの問い合わせ10の経路を表示 |
| `./rr show --query 10 --animate` | 探索の進み方をアニメーション表示 |
| `./rr check` | 自分のプログラムをsampleで実行し、正解判定 |
| `./rr bench` | practiceで基準と自分のプログラムを各5回測定 |
| `./rr bench --dataset performance` | 公開の大規模データで測定 |
| `./rr mock` | 公開の模擬本番3種類で測定 |
| `./rr mock-stress --lite` | 2日目の公開ストレス6種類を短縮版で測定 |
| `./rr mock-stress --full` | 2日目の公開ストレス6種類をすべて測定 |
| `./rr submit --check` | 提出前の構文・依存・構成・容量・収録一覧を検査（ZIPは作りません） |
| `./rr submit` | 現在のworkから提出ZIPを作成・検査 |
| `./rr pack --team team01 --slides slides.pdf` | 従来の提出ZIP作成コマンド |

check・bench・showは`--dataset`で[公開データ](docs/DATASETS.md)を変更できます。

```bash
./rr check --dataset practice
./rr show --dataset practice --query 10 --animate
./rr mock --team team01 --result results/team01.json
```

## 編集するファイル

```text
work/
├── main.py                  # プログラムの入口
├── roboroute/               # 改善するPythonソース
└── report/
    └── experiment_log.md    # 実験を追記
```

`work/main.py`と`work/roboroute/`を編集します。リポジトリ直下の`solution/`と`roboroute/`は比較用の基準なので編集しません。必要な補助Pythonファイルはwork内に追加できます。

`work/`、`results/`、`submissions/`はGitの対象外です。初期化をもう一度実行しても、既存workは上書きされません。作業は自分でもバックアップしてください。

## 実験の進め方

1. 遅い処理について仮説を立てる。
2. workのコードを変更する。AIへの相談内容と採用理由も記録する。
3. `./rr check`で正しさを確かめる。
4. `./rr bench`で実行時間・高速化率・メモリを比較する。
5. 結果と考察をレポートへ追記し、次の仮説を試す。
6. `./rr mock`で複数の条件を確認する。

benchは各5回の中央値と、基準中央値÷自分の中央値の「高速化率」を表示します。各回の測定値はresults内のJSONへ保存されます。`--result`を省略すると毎回別名になります。同じコードでも時間は少し変動します。

2日目は `./rr mock-stress --lite` で繰り返し確認し、最後に `./rr mock-stress --full` で6種類を確認できます。全種類が正解の場合だけ、高速化率の幾何平均を総合値として表示します。正式な180秒スループットの点数とは別の練習用評価です。[入力・集計方法・所要時間](docs/MOCK_STRESS.md)を参照してください。

実行は128MiBのメモリ上限付きで隔離します。長いsystemd-runの入力は不要です。隔離が使えない場合は理由を表示して停止し、無制限の実行へ切り替えません。

## レポートと提出

レポートは`work/report/experiment_log.md`へ実験02、03…と追記します。[テンプレート](templates/experiment_log.md)を参照してください。TXTでも提出できます。レポートのPDF化は不要です。発表資料はPDFにします。

発表資料をリポジトリ直下の`slides.pdf`に保存し、次を実行します。

```bash
./rr submit
```

`submissions/submission-日時-識別番号.zip`が作成され、出力先の絶対パスが表示されます。毎回別名になるので、その回に表示されたZIPを提出してください。生成後に既存の提出検証器で展開・形式検査を行い、合格したZIPだけを出力します。元のソースと資料は変更しません。

事前検査だけ行う場合は、次を実行します。ZIPや一時ファイルは作らず、提出元や既存ZIPも変更しません。

```bash
./rr submit --check
```

結果は`PASS`（合格）、`WARN`（要確認）、`FAIL`（修正が必要）と収録ファイル一覧で表示します。必須ファイル、パス・構成、全Pythonソースの構文、静的importの依存先、ファイル数、展開後容量、圧縮後容量を検査します。圧縮後容量はZIPを作らず、圧縮データとZIPヘッダーの容量から計算します。FAILがあればZIPは作成しません。終了コードは合格・WARNのみなら0、事前検査のFAILは1、出力・引数・生成後の検査エラーは2です。

Pythonソースは読み取るだけで、import・実行はしません。静的importは標準ライブラリか提出内のモジュールに限定します。動的importや`exec`等はWARNとなり、依存を完全には保証できません。正解判定や実行時の動作確認は、従来の`./rr check`・`./rr mock`等で行ってください。

ZIPの内部構造は従来の`pack`と同じです。外側に`work/`やチーム名のフォルダは付けません。

```text
submission-日時-識別番号.zip
├── main.py
├── roboroute/                 # 使用する補助Pythonソース
├── report/
│   └── experiment_log.md      # experiment_log.txtでも可
├── slides.pdf
└── README.md                 # 任意
```

別の作業場所・発表資料・出力先を使う場合は指定できます。`--team`は任意で、指定すると日時付きファイル名の先頭にチーム名が付きます。チーム名は英数字で始まる英数字・_・-の1～64文字です。既存ファイルやリンクは上書きしません。`--output`で作ったZIPを再作成する場合は別名を指定します。

```bash
./rr submit --team team01
./rr submit --work work --slides presentation.pdf --output submissions/team01-v2.zip
```

圧縮・展開後とも32MiB以下、1024ファイル以下です。ZIPのディレクトリ情報は256KiB以下です。これ以外の個別ファイル容量制限はありません。必要な補助Pythonソースはwork内へ置いてください。READMEは任意です。

収録するのは`work/`内のPythonソース、`work/report/experiment_log.md`（なければ`.txt`）、発表資料（ZIP内は常に`slides.pdf`）、任意の`work/README.md`です。隠しファイル・隠しディレクトリ、キャッシュ、仮想環境、`site-packages/`、`node_modules/`、`results/`、`logs/`・`log/`、`data/`・`datasets/`、`tests/`・`test/`、`build/`・`dist/`・`htmlcov/`、`submissions/`、テスト用ソース（`test_*.py`・`*_test.py`・`tests.py`・`conftest.py`）は除外します。レポートディレクトリの他のファイルや、CSV・ログ・測定JSON等も収録しません。補助モジュールは除外対象以外の場所へ置いてください。収録対象のシンボリックリンクはエラーになります。

従来の`./rr pack --team team01 --slides slides.pdf`も引き続き使えます。ZIPを提出するので、GitHubへのpushは提出条件ではありません。

## ルールと評価

[問題仕様](problem.md)と[競技ルール・採点](docs/RULES.md)を確認してください。メモリ上限は128MiB、入力上限は幅・高さが各300、問い合わせ2,000です。

開発中は高速化率を確認します。正式な処理性能点は、全チームの有効な実行時間中央値を基準として、提出後に講師が計算します。高速化率とは別の指標です。
