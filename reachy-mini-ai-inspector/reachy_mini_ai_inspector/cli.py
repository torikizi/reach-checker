import argparse
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Reachy Mini AI Inspector / Macダッシュボード")
    parser.add_argument("--mode", choices=["demo", "robot"], required=True)
    parser.add_argument("--robot-url", help="本体アプリのURL（http://本体IP:8042）")
    parser.add_argument("--token-file", type=Path, help="ペアリング用トークンファイル")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from .providers import BridgeProvider, DemoProvider
    from .server import create_app
    if args.mode == "robot":
        if not args.robot_url or not args.token_file:
            parser.error("実機モードでは --robot-url と --token-file が必要です")
        url = urlsplit(args.robot_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.path not in ("", "/"):
            parser.error("本体アプリの正しいURLを指定してください")
        if url.hostname.lower() == "robot_ip":
            parser.error("ROBOT_IPは仮の表記です。Reachy Mini Controlに表示された本体IPに置き換えてください")
        token = args.token_file.expanduser().read_text().strip()
        if len(token) < 24:
            parser.error("ペアリングトークンが短すぎます")
        provider = BridgeProvider(args.robot_url, token)
    else:
        provider = DemoProvider()
    data_dir = args.data_dir or Path("data") / args.mode
    uvicorn.run(create_app(provider, data_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
