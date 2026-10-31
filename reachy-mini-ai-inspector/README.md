---
title: Reachy Mini AI Inspector
emoji: 🔎
colorFrom: green
colorTo: gray
sdk: static
pinned: false
short_description: Local AI visual inspection with Reachy Mini Wireless
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# Reachy Mini AI Inspector

正解画像から学習し、Reachy Miniのカメラ映像をMacでOK・NG・REVIEWに判定する外観検査アプリです。APIキーは不要です。

## 実行方法

uvまたはPython 3.12、初回はインターネット接続が必要です。確認対象はApple Silicon Macです。

### デモ（実機不要）

```bash
./setup.sh  # 初回のみ
./run.sh    # 実機不要のデモを起動
```

<http://127.0.0.1:8765> を開き、基準を作成 → サンプル12枚を登録 → 検査、の順で試します。終了は `Ctrl+C`。

### 実機デモ

MacとReachyを同じLANにつなぎ、Reachy Mini Controlで本体IPを確認します。Applicationsから `reachy_mini_ai_inspector` を起動し、`ROBOT_IP` を本体IPに置き換えて実行します。本体アプリ・トークンが未準備なら [セットアップ手順](doc/setup.md) を参照してください。

```bash
./run.sh --mode robot \
  --robot-url http://ROBOT_IP:8042 \
  --token-file .private/robot-token
```

既存の親 `.venv/` を使う場合は、このフォルダで `./run.sh` を `../.venv/bin/python -m reachy_mini_ai_inspector.cli` に置き換えます。再セットアップは不要です。

同じ検査画面で「実機モード」を確認し、基準作成 → 正解画像8枚以上を登録 → 検査、の順で操作します。撮影位置の復帰は未解決のため、最初は「リアクションOFF」で確認してください。他の起動オプションは `./run.sh --help` を参照してください。

## リポジトリ構成

```text
setup.sh / run.sh        セットアップ・起動
reachy_mini_ai_inspector/
  main.py / bridge.py   Reachy本体のカメラ・動作制御
  cli.py / server.py    Mac側の起動・API
  vision.py             画像解析・AI判定
  storage.py            画像・設定・履歴の保存
  dashboard/            Web画面
scripts/                診断・導入・評価用ツール
tests/                  自動テスト
doc/                    詳細ドキュメント・検証記録
pyproject.toml          依存関係・パッケージ設定
```

詳細は [doc/](doc/README.md) にまとめています。検査データは `data/` に保存し、Git管理から除外します。

## OSSクレジット

自作部分は [MIT License](LICENSE) で公開しています。利用している主なOSSとライセンスは [NOTICE.md](NOTICE.md) にまとめています。
