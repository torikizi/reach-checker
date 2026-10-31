"""Official Reachy Mini app entry point. No inference runs on the robot."""
import os
from pathlib import Path
import signal
import threading

from reachy_mini import ReachyMini, ReachyMiniApp
from .bridge import RobotIO, add_routes


class ReachyMiniAiInspector(ReachyMiniApp):
    custom_app_url = "http://0.0.0.0:8042"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        token_path = Path(os.environ.get("INSPECTOR_TOKEN_FILE", "~/.config/reachy-mini-ai-inspector/token")).expanduser()
        token = token_path.read_text().strip() if token_path.exists() else ""
        self.robot = RobotIO(token, token_path.parent / "inspection-position.json")
        add_routes(self.settings_app, self.robot)

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        if not self.robot.token:
            raise RuntimeError("ペアリングトークン未設定。READMEの本体導入手順を実行してください")
        # Applications starts wrapped_run() directly, bypassing our CLI main().
        reachy_mini.set_automatic_body_yaw(False)
        reachy_mini.disable_wobbling()
        reachy_mini.stop_head_tracking()
        self.robot.run(reachy_mini, stop_event)


def main():
    app = ReachyMiniAiInspector()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.stop())
    try:
        app.wrapped_run(automatic_body_yaw=False)
    finally:
        app.stop()


if __name__ == "__main__":
    main()
