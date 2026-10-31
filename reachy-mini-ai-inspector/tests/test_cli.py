import subprocess
import sys

import pytest


@pytest.mark.parametrize("host", ["ROBOT_IP", "robot_ip"])
def test_placeholder_robot_url_fails_before_reading_token(tmp_path, host):
    result = subprocess.run(
        [sys.executable, "-m", "reachy_mini_ai_inspector.cli", "--mode", "robot",
         "--robot-url", f"http://{host}:8042", "--token-file", str(tmp_path / "missing-token")],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "ROBOT_IPは仮の表記です" in result.stderr
    assert "本体IPに置き換えてください" in result.stderr
    assert "Traceback" not in result.stderr
