# 実行環境の確認

Ubuntu / WSLの通常ターミナルで操作します。Python 3.10以降とbubblewrap、ユーザーsystemd、memory/pidsが委譲されたcgroup v2が必要です。Pythonの外部ライブラリやpipのインストールは実習プログラムには不要です。

```bash
./setup.sh
```

このコマンドは固定の診断コードで起動条件を確認し、results/environment-check.jsonへ保存します。学生のプログラムは実行せず、インストールやシステム設定の変更もしません。実際のプログラム実行・メモリ制限は、続く`./rr check`で確認します。

## 隔離実行が使えないとき

1. 通常のUbuntuターミナルで実行しているか確かめる。AIツール内の実行環境では権限が制限されている場合があります。
2. `./setup.sh`の結果とエラー表示を担当講師へ伝える。
3. 設定が準備された環境で、改めて`./rr check`を実行する。

bubblewrapがない、ユーザーsystemdへ接続できない、cgroupが読み取り専用等の場合は、講師へ相談してください。自分で権限拡張・再マウント・システム設定変更をして回避しないでください。

`./rr`は必要に応じて一時ユーザーサービス内で実行します。長いsystemd-runを自分で入力する必要はありません。隔離が利用できないとき、無制限実行へは切り替えません。

## メモリと時間

メモリ上限は128MiBです。画面の値はcgroup memory.peakで、子プロセス・cache・一時領域等を含み、RSSとは異なります。大量の探索結果を保持すると、速くなる一方で上限に達することがあります。

基準と自分のプログラムを各5回測定し、すべて正解の場合に中央値を比較します。他の処理を同時に動かすと時間が変動するため、同じ環境・条件で比較してください。競技の処理時間上限は設けません。

## 終了時の残存プロセス診断

bubblewrapの監視プロセスは、実行プログラムの終了を通知されると、namespace内のinitの終了処理が完了する前に終了することがあります（[bubblewrap 0.11.1のmonitor_child / do_init](https://github.com/containers/bubblewrap/blob/v0.11.1/bubblewrap.c#L465-L634)）。監視プロセスを回収した直後の`cgroup.events`が`populated=1`であることだけでは、子プロセスが終了しないとは判断できません。

ランナーは監視プロセス回収後、cgroupが空になるまで最大200msの猶予を設けます。空なら待たず、残存時は`cgroup.events`の変更通知で待機を解除します。待機と診断にかかった時間は測定時間に含め、OOM・最大メモリ・出力量は待機後に確認します。猶予後も`populated=1`なら`LEFTOVER_PROCESSES`として失敗し、残存プロセスを強制終了してcgroupを削除します。`--safety-stop`はこの待機中にも適用します。

終了直後に残存を観測した回は、結果JSONの各runの`cgroup_diagnostics`に次を保存します（即座に空だった回は`null`）。診断はプログラムの標準出力・標準エラーには混ぜません。

- cgroupのパス、回収した監視プロセスのホストPID、猶予時間
- 親回収までの時間、回収後の待機時間、判定までの合計時間、結果（`drained` / `deadline` / `operator_stop`）
- 待機前後の`cgroup.events`・`cgroup.procs`と、取得できた各ホストPIDの名前・状態・PPID・CPU時間カウンタ・開始時刻カウンタ・`wchan`

各ファイルの読み取りは同時ではありません。途中でPIDが消えた場合は読み取りエラーを記録します。`initial_populated=true`でも最初のスナップショット取得時には空になっている場合があります。`cgroup.procs`が空でも`populated=1`なら成功扱いにはしません。`deadline`が続く場合はスナップショットのPID・状態・CPU時間を調べ、猶予の延長だけで対処しないでください。

回帰テストは標準ライブラリのunittestで実行します。

```bash
python3 -m unittest discover -s tests -v
```

実際のcgroup・bubblewrapを使うテストは通常WSLで明示的に有効化します。短時間で終了する子と終了しない子、子の実行時間と出力、後始末、OOM、出力制限、namespace内の子の終了を検証します。インストールやシステム設定の変更は行いません。

```bash
systemd-run --user --wait --pipe --collect --working-directory="$PWD" \
  /usr/bin/env ROBOROUTE_INTEGRATION_TESTS=1 \
  /usr/bin/python3 -m unittest discover -s tests -v
```

Ubuntu 26.04 / WSL2・Python 3.14.4・bubblewrap 0.11.1で動作確認した教材を基にしています。別のUbuntuやPythonで使う場合は、講師の案内に従って動作を確認してください。
