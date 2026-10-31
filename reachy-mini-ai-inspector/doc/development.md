# 開発・テスト・公開

[ドキュメント一覧](README.md)

コマンドはアプリのルートフォルダ（`setup.sh` がある場所）で実行します。

## テスト

```bash
./setup.sh --dev
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/evaluate_demo.py
.venv/bin/reachy-mini-app-assistant check .
.venv/bin/python -m build --wheel
```

自動テストはAI実行、3種の判定、品質REVIEW、学習永続化、設定変更、同時実行、切断、履歴・画像・CSV、評価集計、モーション範囲・停止・認証を検証します。モーターテストはFake SDKです。

合成評価は正常学習12枚とは異なるseedで各条件30枚、計150枚。結果は [合成評価結果](synthetic-evaluation.json)。実機の評価は [実機チェックリスト](hardware-checklist.md) に従って実施してください。

## GitHubへの公開準備

ソース・テスト・使い方・検証資料を共有し、次はGit管理から除外します。

- `.venv/`、`.reference/`、キャッシュ、ビルド生成物、`*.egg-info/`。
- `.env`・`.env.*`、`.private/`、秘密鍵、端末固有の設定。
- `data/` の正解画像・検査履歴・SQLiteファイル、ログ。
- `output/` の生成レポート、`plan.md`、内部提出メモ。

公開用の合成画像 `doc/dashboard-demo.jpg` と、合成評価JSONは公開対象です。`.env.example` を追加する場合は秘密値を含めず、設定名と例だけを記載してください。本アプリの起動に `.env` は不要です。

親フォルダ全体でも、このアプリのフォルダ単体でもGitで公開できます。どちらにも `.gitignore` と起動スクリプトがあります。ファイルは削除せず、Gitの対象から除外しています。既にGitへ追加済みのファイルにはignoreが効かないため、公開先のルートで次を確認してください。

```bash
git status --short --ignored
git ls-files
git diff --cached --stat
```

`git ls-files` に秘密情報や実データが含まれる場合は、該当ファイルを個別に `git rm --cached -- PATH` で管理対象から外してください。過去にcommitした秘密情報は履歴にも残るため、ignoreの追加だけでは解消しません。

Hugging Face Spaceへの公開はGitへの追加と異なります。Reachy SDK 1.12.0 の公開CLIは、APIアップロードに切り替わると `.gitignore` を参照しません。作業フォルダから直接 `publish .` を実行せず、[セットアップ手順](setup.md#配布時applicationsからインストール)のとおり、公開ファイルだけを含むクリーンなコピーを使ってください。

## PDFレポート生成

レポートの下書きは次の手順で `output/pdf/reachy-mini-ai-inspector-report-draft.pdf` に生成できます。生成物はGit管理に含めません。内容は途中版で、実物評価の最終結果ではありません。

```bash
./setup.sh --report
.venv/bin/python scripts/build_report.py
```

macOSのArial UnicodeをPDFへ埋め込みます。別環境では `--font /path/to/JapaneseFont.ttf` で日本語TrueTypeフォントを指定してください。実物の測定が終わったら、生成スクリプトの検証結果と未完了項目を更新して最終版を作成します。
