import csv
import io
import json
import threading

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_ai_inspector.bridge import RobotIO, add_routes
from reachy_mini_ai_inspector.providers import DemoProvider, demo_image
from reachy_mini_ai_inspector.server import create_app
from reachy_mini_ai_inspector.sounds import verdict_samples

HEADERS = {"X-Inspector-UI": "1"}


@pytest.mark.parametrize("rate", [16000, 48000])
def test_cues_are_short_distinct_and_fade_without_clipping(rate):
    cues = [verdict_samples(v, rate) for v in ("OK", "NG", "REVIEW")]
    for samples in cues:
        assert samples.dtype == np.float32 and samples.ndim == 1
        assert np.isfinite(samples).all()
        assert .25 < len(samples) / rate < .7
        assert .1 < np.max(np.abs(samples)) < .2
        assert samples[0] == samples[-1] == 0
        # Envelopes also keep note boundaries free of hard clicks.
        assert np.max(np.abs(np.diff(samples))) < .13
    assert len({samples.tobytes() for samples in cues}) == 3


class AudioMini:
    def __init__(self, fail=False):
        self.media = self
        self.fail = fail
        self.events = []

    def get_frame(self):
        return demo_image()

    def get_output_audio_samplerate(self):
        return 16000

    def start_playing(self):
        self.events.append("start")

    def push_audio_sample(self, data):
        self.events.append("samples")
        if self.fail:
            raise RuntimeError("speaker disconnected")
        assert data.dtype == np.float32

    def stop_playing(self):
        self.events.append("stop")

    def goto_target(self, **kwargs):
        pytest.fail("Sound must not move the robot")


@pytest.mark.parametrize("fail", [False, True])
def test_bridge_audio_works_with_motion_off_and_preserves_camera(fail):
    robot, mini, stop = RobotIO("test"), AudioMini(fail), threading.Event()
    app = FastAPI()
    add_routes(app, robot)
    thread = threading.Thread(target=robot.run, args=(mini, stop))
    thread.start()
    try:
        robot.request("snapshot")
        with TestClient(app) as c:
            assert c.post("/api/sound", json={"verdict": "OK"}).status_code == 401
            auth = {"Authorization": "Bearer test"}
            assert c.post("/api/sound", headers=auth, json={"verdict": "HOME"}).status_code == 422
            r = c.post("/api/sound", headers=auth, json={"verdict": "OK"})
            assert r.status_code == 200
            assert r.json()["performed"] is (not fail)
        assert mini.events == ["start", "samples", "stop"]
        assert robot.connected and not robot.motion_enabled
        assert robot.status()["camera_ready"]
        assert bool(robot.audio_error) is fail
    finally:
        stop.set()
        thread.join(timeout=3)
    assert not thread.is_alive()


def test_stopped_app_never_starts_audio():
    robot, mini, stop = RobotIO("test"), AudioMini(), threading.Event()
    stop.set()
    assert not robot.play_sound(mini, "OK", stop)["performed"]
    assert mini.events == []


def test_sound_toggle_persists_without_changing_model_or_creating_records(tmp_path):
    provider = DemoProvider()
    calls = []
    provider.sound = lambda verdict: calls.append(verdict) or {"performed": True, "reason": verdict}
    with TestClient(create_app(provider, tmp_path), headers=HEADERS) as c:
        c.post("/api/demo/train")
        before = c.get("/api/status").json()
        for verdict in ("OK", "NG", "REVIEW"):
            assert c.post("/api/sound/test", json={"verdict": verdict}).json()["performed"]
        assert calls == ["OK", "NG", "REVIEW"]
        assert c.get("/api/history").json() == []
        assert c.post("/api/sound", json={"enabled": False}).status_code == 200
        assert not c.post("/api/sound/test", json={}).json()["performed"]
        assert len(calls) == 3
        with c.app.state.inspector.operation():
            assert c.post("/api/sound/test", json={}).status_code == 409
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        after = c.get("/api/status").json()
        assert not after["sound_enabled"]
        assert before["normal_count"] == after["normal_count"] == 12
        assert before["model_id"] == after["model_id"]


def test_sound_failure_preserves_ai_result_and_motion_and_exports(tmp_path):
    provider = DemoProvider()
    events = []

    def fail(verdict):
        events.append("sound")
        raise RuntimeError("audio unavailable")

    provider.sound = fail
    provider.react = lambda verdict: events.append("motion") or {"performed": False, "reason": "OFF"}
    with TestClient(create_app(provider, tmp_path), headers=HEADERS) as c:
        c.post("/api/demo/train")
        result = c.post("/api/inspect", json={}).json()
        assert events == ["sound", "motion"]
        assert result["verdict"] == "OK" and result["ai_executed"]
        assert not result["sound"]["performed"]
        assert "audio unavailable" in result["sound"]["reason"]
        assert c.get("/api/history").json()[0] == result
        assert c.get("/api/images/" + result["image"]).status_code == 200
        row = next(csv.DictReader(io.StringIO(c.get("/api/export.csv").text.lstrip("\ufeff"))))
        assert json.loads(row["sound"]) == result["sound"]


def test_demo_sound_is_explicitly_not_real(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        result = c.post("/api/sound/test", json={}).json()
        assert not result["performed"] and "デモ" in result["reason"]
