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
| `./rr pack --team team01 --slides slides.pdf` | 提出ZIPを作成して検査 |

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

実行は128MiBのメモリ上限付きで隔離します。長いsystemd-runの入力は不要です。隔離が使えない場合は理由を表示して停止し、無制限の実行へ切り替えません。

## レポートと提出

レポートは`work/report/experiment_log.md`へ実験02、03…と追記します。[テンプレート](templates/experiment_log.md)を参照してください。TXTでも提出できます。レポートのPDF化は不要です。発表資料はPDFにします。

```bash
./rr pack --team team01 --slides slides.pdf
```

`submissions/team01.zip`が作成され、ZIPの安全検査も行われます。

```text
team01.zip
├── main.py
├── roboroute/                 # 使用する補助Pythonソース
├── report/
│   └── experiment_log.md      # experiment_log.txtでも可
├── slides.pdf
└── README.md                 # 任意
```

チーム名は英数字で始まる英数字・_・-の1～64文字です。既存ZIPは上書きしません。再提出用に作り直す場合は別名を指定します。

```bash
./rr pack --team team01 --slides slides.pdf --output submissions/team01-v2.zip
```

圧縮・展開後とも32MiB以下、1024ファイル以下です。必要な補助Pythonソースはwork内へ置いてください。READMEは任意です。ZIPを提出するので、GitHubへのpushは提出条件ではありません。

## ルールと評価

[問題仕様](problem.md)と[競技ルール・採点](docs/RULES.md)を確認してください。メモリ上限は128MiB、入力上限は幅・高さが各300、問い合わせ2,000です。

開発中は高速化率を確認します。正式な処理性能点は、全チームの有効な実行時間中央値を基準として、提出後に講師が計算します。高速化率とは別の指標です。
