#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
EXTRAS="mac"

usage() {
    cat <<'EOF'
使い方: ./setup.sh [--dev] [--report]

アプリ専用の .venv にPython依存をインストールします。
uvがある場合はPython 3.12を自動で準備します。
uvがない場合は、インストール済みのPython 3.12を使います。

  --dev     テスト・ビルド・本体導入用の依存も追加
  --report  PDFレポート生成用の依存も追加
  -h, --help  この説明を表示
EOF
}

for arg in "$@"; do
    case "$arg" in
        --dev) EXTRAS="$EXTRAS,dev" ;;
        --report) EXTRAS="$EXTRAS,report" ;;
        -h|--help) usage; exit 0 ;;
        *) printf '不明なオプション: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -e "$VENV_DIR" || -L "$VENV_DIR" ]]; then
    if [[ ! -x "$VENV_PYTHON" ]]; then
        printf '既存の .venv が使えません。別の場所へ退避してから再実行してください。\n' >&2
        exit 1
    fi
else
    if command -v uv >/dev/null 2>&1; then
        uv venv --python 3.12 "$VENV_DIR"
    else
        BOOTSTRAP_PYTHON=""
        for candidate in python3.12 python3; do
            if command -v "$candidate" >/dev/null 2>&1 &&
                "$candidate" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null; then
                BOOTSTRAP_PYTHON="$candidate"
                break
            fi
        done
        if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
            printf 'uv または Python 3.12 をインストールしてから再実行してください。\n' >&2
            exit 1
        fi
        "$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR"
    fi
fi

if ! "$VENV_PYTHON" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
    printf 'このセットアップはPython 3.12を使用します。既存の .venv のバージョンを確認してください。\n' >&2
    exit 1
fi

if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV_PYTHON" -e "$APP_DIR[$EXTRAS]"
else
    if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        "$VENV_PYTHON" -m ensurepip
    fi
    "$VENV_PYTHON" -m pip install --disable-pip-version-check -e "$APP_DIR[$EXTRAS]"
fi

"$VENV_PYTHON" -c 'import cv2, httpx, multipart, sklearn, uvicorn; from reachy_mini_ai_inspector.server import create_app'
printf '\nセットアップ完了。./run.sh でデモを起動できます。\n'
printf '仮想環境: %s\n' "$VENV_DIR"
