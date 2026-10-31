#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$APP_DIR/.venv/bin/python"

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            cat <<'EOF'
使い方: ./run.sh [--mode demo|robot] [オプション]

引数なしで実機不要のデモを起動します。
  --port PORT            ポート番号（既定: 8765）
  --data-dir PATH        データ保存先（既定: data/demo または data/robot）
  --mode robot           実機モード
  --robot-url URL        本体アプリのURL（実機モードで必須）
  --token-file PATH      ペアリングトークンのファイル（実機モードで必須）

相対パスはアプリのフォルダを基準に解釈します。
ブラウザで http://127.0.0.1:8765 を開いてください。
終了は Ctrl+C です。
EOF
            exit 0
            ;;
    esac
done

if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '実行環境がありません。先に ./setup.sh を実行してください。\n' >&2
    exit 1
fi

HAS_MODE=false
for arg in "$@"; do
    case "$arg" in
        --mode|--mode=*) HAS_MODE=true ;;
    esac
done
if [[ "$HAS_MODE" == false ]]; then
    set -- --mode demo "$@"
fi

cd -- "$APP_DIR"
exec "$VENV_PYTHON" -m reachy_mini_ai_inspector.cli "$@"
