# Reachy Mini AI Inspector

Reachy Miniのカメラ映像をMacで解析する外観検査アプリです。APIキーは不要です。

## 実行方法

uvまたはPython 3.12、初回はインターネット接続が必要です。確認対象はApple Silicon Macです。

### デモ（実機不要）

```bash
./setup.sh  # 初回のみ
./run.sh    # 実機不要のデモを起動
```

ブラウザで <http://127.0.0.1:8765> を開きます。終了は `Ctrl+C`。
画面で基準を作成 → サンプル12枚を登録 → 検査、の順で試せます。

### 実機デモ

MacとReachyを同じLANにつなぎ、Reachy Mini Controlで本体IPを確認します。Applicationsから `reachy_mini_ai_inspector` を起動し、`ROBOT_IP` を本体IPに置き換えて実行します。本体アプリ・トークンが未準備なら [セットアップ手順](reachy-mini-ai-inspector/doc/setup.md) を参照してください。

```bash
./run.sh --mode robot \
  --robot-url http://ROBOT_IP:8042 \
  --token-file .private/robot-token
```

既存の親 `.venv/` を使う場合は、`reachy-mini-ai-inspector/` 内で `./run.sh` を `../.venv/bin/python -m reachy_mini_ai_inspector.cli` に置き換えます。再セットアップは不要です。

同じ検査画面で「実機モード」を確認し、基準作成 → 正解画像8枚以上を登録 → 検査、の順で操作します。撮影位置の復帰は未解決のため、最初は「リアクションOFF」で確認してください。

## リポジトリ構成

```text
setup.sh / run.sh          セットアップ・起動
doc/                      ドキュメントの入口
reachy-mini-ai-inspector/
   reachy_mini_ai_inspector/ Python本体・Web画面
   doc/                    詳しい使い方・検証記録
   scripts/                診断・導入・評価用ツール
   tests/                  自動テスト
   pyproject.toml          依存関係・パッケージ設定
```

詳細は [doc/](doc/README.md) にまとめています。

## OSSクレジット

利用している主なOSSとライセンスは [NOTICE.md](reachy-mini-ai-inspector/NOTICE.md) にまとめています。
