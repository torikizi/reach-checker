# セットアップと実機接続

[ドキュメント一覧](README.md)

コマンドはアプリのルートフォルダ（`setup.sh` がある場所）で実行します。

## Macの準備

確認対象はApple Silicon Mac、Python 3.12です。初回セットアップにはインターネット接続と、uvまたはPython 3.12が必要です。公式SDKと本体Daemonの確認対象は **1.12.0**。別バージョンのDaemonでは互換性を再確認してください。

```bash
./setup.sh
./run.sh
```

アプリのルートフォルダ（`setup.sh` がある場所）で実行します。親の作業フォルダも含めてcloneした場合は、そのフォルダの同名スクリプトからも起動できます。

`setup.sh` はこのフォルダの `.venv/` に依存を導入します。uvがあればPython 3.12を必要に応じてダウンロードし、なければインストール済みのPython 3.12と標準のvenv・pipを使用します。既存の `.venv/` は再利用し、システムPythonや親の仮想環境は変更しません。仮想環境の手動有効化は不要です。SDKの映像関連の依存も含むため、初回は数分かかる場合があります。

テスト・ビルド・本体導入も行う場合は `./setup.sh --dev`、PDF生成には `./setup.sh --report` を実行します。両方を同時に指定することもできます。`requirements-mac-tested.txt` は過去のMac検証環境の記録で、通常のセットアップは `pyproject.toml` の依存を使用します。

## デモ起動（実機不要）

```bash
./run.sh
```

ブラウザで <http://127.0.0.1:8765> を開きます。終了は `Ctrl+C`。別ポートは `./run.sh --port 8766` です。2回目以降は `./run.sh` だけで起動します。

1. 「新しい検査基準の名前」を入力し、「基準を作成」を押す。
2. 用意した画像を「正解画像（複数選択可）」から読み込む。付属のデモを使う場合は「赤2×4のサンプル12枚を登録」を押す。
3. 「保存した検査基準」で使用する基準を選ぶ。正解画像8枚以上でAI学習が完了する。
4. デモの検査対象を切り替えて「検査を開始」。対象なし・ぼけた画像ではREVIEWを確認する。
5. 履歴の「実際の状態」と撮影条件を設定し「評価を保存」。必要に応じてCSVを書き出す。

デモは人工的に描画した画像です。データは `data/demo/` に保存します。実機への接続・物理動作は一切ありません。

## 本体IPを確認

Reachy Mini Controlで接続済みの本体IPを確認します。mDNSが使えなくてもIPを指定できます。

```bash
.venv/bin/python scripts/diagnose.py --host ROBOT_IP
```

`robot_confirmed: true`、`wireless_version: true`、`simulation_enabled: false` を確認。MacのIPを本体IPとして流用しないでください。旧Web Dashboardは不要です。

## 本体へ導入

### 開発時：公式SSH手順を使う

公式の[Wireless開発ガイド](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/development_workflow)の共有アプリ環境 `/venvs/apps_venv/` に、このアプリだけをインストールします。daemon自体や既存SDKは変更しません。

```bash
./setup.sh --dev
.venv/bin/python -m build --wheel
ssh pollen@ROBOT_IP
# 初回接続は本体のホスト鍵を確認。接続を確認したら exit
.venv/bin/python scripts/install_robot.py \
  --host ROBOT_IP \
  --wheel dist/reachy_mini_ai_inspector-0.2.0-py3-none-any.whl \
  --token-file .private/robot-token
```

SSHパスワードは対話入力です。初期認証を使用する場合のみ、所有者が確認したうえで `--factory-password` を指定できます。パスワードをコマンドに直接書く必要はありません。

導入スクリプトはSDK `1.12.0`・Pillow・FastAPI・uvicornの存在を確認し、依存を無断更新せず `pip install --no-deps` でアプリを導入します。不足がある場合は停止します。Pillowだけが不足している場合は、本体SSHで `/venvs/apps_venv/bin/python -m pip install --no-deps "pillow>=11,<13"` を実行してから導入を再実行してください。トークンは本体の `~/.config/reachy-mini-ai-inspector/token` とMacの指定ファイルに保存（権限600）し、内容は表示しません。

導入後、Reachy Mini ControlのApplicationsで `reachy_mini_ai_inspector` を起動します。SSHで導入した直後に一覧へ反映されない場合は、Controlを終了・再起動し、IPアドレスで再接続してください（v0.9.35で必要でした）。本体側の小さな案内ページは `http://ROBOT_IP:8042`、検査画面はMac側です。

### 配布時：Applicationsからインストール

現行の公式インストールAPIの配布元はHugging Face Spacesです。GitHub publicリポジトリだけではControlのストアに掲載されません。実機検証・公開範囲の確認後に、公開対象だけを含むクリーンなフォルダから公式CLIでHF Spaceへ公開します。

**この作業フォルダから `reachy-mini-app-assistant publish .` を実行しないでください。** SDK 1.12.0 の公開処理は、Git push に失敗した場合や既存Spaceの更新時などに Hugging Face API のフォルダ一括アップロードへ切り替わります。この経路は `.gitignore` を参照しません。ここには `.private/` のペアリングトークンと実機画像、`data/` の検査記録があるため、直接公開すると漏えいするおそれがあります。

公開時は、レビュー済みの Git コミットを新しい場所へ clone し、そのコピーに `.private/`、`data/`、`.env*`、`.venv/`、`output/` がないことを確認してください。アプリフォルダで公式CLIの `check` を実行し、公開直前にもアップロード対象の全ファイルを確認してから、その**クリーンなコピー**で `publish` を実行します。Git push の成否にかかわらず、アップロード対象フォルダ内には公開可能なファイルだけを置いてください。

その後、ControlのDiscover appsで該当Spaceからインストール・起動・停止を確認します。未公開のローカル導入と「ストアからの新規インストール確認」は別のチェック項目です。

## 実機モード起動

本体アプリを起動してからMacで実行します。

**カメラ用アプリの起動と、本体の起床は別です。** 本アプリは起動時にモーターを有効化せず、スリープ姿勢でも映像を取得できます。頭を起こして使う場合は周囲を確認し、Controlの起床操作を行ってください。検品画面の「Reachyのリアクション」は検査結果に連動する動作の許可で、本体の電源・起床スイッチではありません。

```bash
./run.sh --mode robot \
  --robot-url http://ROBOT_IP:8042 \
  --token-file .private/robot-token
```

<http://127.0.0.1:8765> を開くと **実機モード** と表示されます。接続できない場合はエラーになり、デモへ自動的に切り替わることはありません。履歴は `data/robot/` に保存します。別ポートは `--port 8766`、保存先変更は `--data-dir PATH`。スクリプトに渡す相対パスは、アプリのルートフォルダを基準に解釈します。デモと実機で同じ保存先を使うと拒否します。

## 画像取得が503になる場合

Mac側の検査画面は動いていても、本体への接続やカメラの準備に失敗すると `/api/frame` は503になります。[接続状態](http://127.0.0.1:8765/api/status) の `robot.error` に理由が表示されます。

`http://ROBOT_IP:8042` の `ROBOT_IP` は仮の表記です。そのまま実行せず、Controlに表示された実際の本体IPへ置き換えて起動し直してください。Controlにも「No robot detected」と出る場合は、まず本体の電源と、Mac・本体が同じWi-Fiにつながっているかを確認します。

## ネットワーク・公開物

Mac側はlocalhost限定。本体ブリッジはLAN内の8042番、操作・画像取得にはBearerトークン必須です。HTTP通信なので信頼できる同一LANで使い、インターネットへポートを公開しないでください。

`data/`、`.private/`、トークン、実カメラ画像、ログ、個人情報をGitへ入れません。画面キャプチャ・CSVに映り込むものも公開前に確認してください。本リポジトリに氏名・所属・メールアドレスは記載しません。
