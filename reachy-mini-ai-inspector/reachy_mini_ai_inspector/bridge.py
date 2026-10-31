"""Robot IO: every SDK camera/motor call runs on the app's one owner thread."""
import hmac
import io
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from PIL import Image
import numpy as np
from pydantic import BaseModel

from .sounds import verdict_samples
from .position import InspectionPosition, in_position, position_error, read_position, read_joints


@dataclass
class Command:
    kind: str
    value: str = ""
    deadline: float = field(default_factory=lambda: time.monotonic() + 2)
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: str = ""
    cancelled: bool = False
    generation: int = 0


class RobotIO:
    def __init__(self, token: str, position_path=None):
        self.token = token
        self.commands: queue.Queue[Command] = queue.Queue(maxsize=4)
        self.lock = threading.RLock()
        self.frame: bytes | None = None
        self.frame_at = 0.0
        self.sequence = 0
        self.connected = False
        self.error = "アプリ接続準備中"
        self.motion_enabled = False
        self.lease_until = 0.0
        self.moving = False
        self.stopping = False
        self.generation = 0
        self.position_path = position_path
        self.position = InspectionPosition.load(position_path)
        self.pose_valid = True
        self.position_error = None
        self.audio_error = ""

    def status(self):
        with self.lock:
            return {"protocol": 1, "connected": self.connected,
                    "camera_ready": self.frame is not None and time.monotonic()-self.frame_at < 2,
                    "frame_age_seconds": round(time.monotonic()-self.frame_at, 2) if self.frame_at else None,
                    "sequence": self.sequence, "motion_enabled": self.motion_enabled,
                    "moving": self.moving, "pose_valid": self.pose_valid, "error": self.error,
                    "sound_supported": True, "audio_error": self.audio_error,
                    "position_saved": self.position is not None, "position_error": self.position_error}

    def disable(self):
        with self.lock:
            self.motion_enabled = False
            self.lease_until = 0
            self.generation += 1

    def request(self, kind, value=""):
        if self.stopping:
            raise RuntimeError("アプリは停止中です")
        cmd = Command(kind, value, generation=self.generation)
        try:
            self.commands.put_nowait(cmd)
        except queue.Full:
            raise RuntimeError("ロボットは処理中です") from None
        if not cmd.done.wait(12):
            cmd.cancelled = True
            self.disable()
            raise RuntimeError("ロボットの応答がタイムアウトしました。動作を無効化しました")
        if cmd.error:
            raise RuntimeError(cmd.error)
        return cmd.result

    def capture(self, mini):
        frame = mini.media.get_frame()
        if frame is None:
            return False
        image = Image.fromarray(frame[:, :, ::-1])  # SDK = BGR
        image.thumbnail((960, 720))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        if self.position is not None and not self.moving:
            self.position_error = self.position.error(mini)
            # A previous interrupted/failed motion requires an explicit return.
            if not in_position(self.position_error):
                self.pose_valid = False
        with self.lock:
            self.frame, self.frame_at = buffer.getvalue(), time.monotonic()
            self.sequence += 1
            self.connected, self.error = True, ""
        return True

    def snapshot(self, mini, stop_event):
        if self.position is not None and not in_position(self.position.error(mini)):
            self.pose_valid = False
        if not self.pose_valid:
            raise RuntimeError("撮影位置がずれているか、動作が途中で停止しました。「撮影位置へ戻す」で復帰してください")
        # Discard the buffered sample; capture a subsequent sample after this command.
        mini.media.get_frame()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not stop_event.is_set():
            if self.capture(mini):
                if not self.pose_valid:
                    raise RuntimeError("撮影位置がずれています。「撮影位置へ戻す」で復帰してください")
                return self.frame
            stop_event.wait(.03)
        raise RuntimeError("新しいカメラフレームを取得できません")

    def remember_position(self, mini, stop_event):
        pose, body = read_position(mini)
        joints = read_joints(mini)
        if stop_event.wait(.25):
            raise RuntimeError("アプリ停止中")
        if not in_position(position_error(*read_position(mini), pose, body)):
            raise RuntimeError("頭部が動いています。静止してから撮影位置を記憶してください")
        position = InspectionPosition(pose, body, joints)
        if not in_position(position.error(mini)):
            raise RuntimeError("頭部が動いています。静止してから撮影位置を記憶してください")
        position.save(self.position_path)
        self.position = position
        self.pose_valid = True
        self.position_error = position.error(mini)
        return {"saved": True, "reason": "現在の撮影位置を記憶しました"}

    def return_to_position(self, mini, stop_event, allowed):
        position = self.position
        if position.joints is None:
            raise RuntimeError("撮影位置のモーター角度が未記録です。正しい画角で「今の撮影位置を記憶」を押してください")
        target = position.joint_target.copy()
        for attempt in range(3):
            if not allowed():
                return {"returned": False, "reason": "動作停止"}
            # SDK 1.12.0's joint interpolation avoids repeated FK -> IK errors.
            # These underscored SDK methods are version-pinned and hardware-tested.
            mini._goto_joint_positions(head_joint_positions=target.tolist(), duration=1.)
            if not allowed():
                return {"returned": False, "reason": "動作停止"}
            mini._set_joint_positions(head_joint_positions=target.tolist())
            if stop_event.wait(.35) or not allowed():
                return {"returned": False, "reason": "動作停止"}
            self.position_error = position.error(mini)
            if in_position(self.position_error):
                # Two consecutive readings after settling, before releasing the camera.
                if stop_event.wait(.15) or not allowed():
                    return {"returned": False, "reason": "動作停止"}
                self.position_error = position.error(mini)
                if in_position(self.position_error):
                    position.joint_target = target.copy()
                    position.save(self.position_path)
                    self.pose_valid = True
                    return {"returned": True, "return_error": self.position_error, "retries": attempt}
            if attempt < 2:
                correction = np.clip(position.joints-read_joints(mini), -np.deg2rad(2), np.deg2rad(2))
                target += correction
                position.check_joint_target(target)
        raise RuntimeError("撮影位置への復帰を確認できません。次の検査を停止しました。モーターと周囲を確認してください")

    def react(self, mini, verdict, stop_event, manual_return=False):
        from reachy_mini.utils import create_head_pose
        poses = {"OK": [(0, 8, 0), (0, -4, 0)],
                 "NG": [(0, 0, -10), (0, 0, 10), (0, 0, -6)],
                 "REVIEW": [(9, 0, 0)], "HOME": []}
        if not self.motion_enabled and not manual_return:
            return {"performed": False, "reason": "モーション無効"}
        if self.position is None:
            raise RuntimeError("先に撮影位置を記憶してください")
        generation = self.generation
        allowed = lambda: not stop_event.is_set() and self.generation == generation and (manual_return or self.motion_enabled)
        self.moving = True
        self.pose_valid = False
        self.frame = None
        try:
            gesture_error = ""
            try:
                for roll, pitch, yaw in poses[verdict]:
                    if not allowed():
                        return {"performed": False, "returned": False, "reason": "動作停止"}
                    target = self.position.target @ create_head_pose(roll=roll, pitch=pitch, yaw=yaw, degrees=True)
                    mini.goto_target(head=target, duration=.8, method="minjerk", body_yaw=self.position.body_yaw)
            except Exception as exc:
                gesture_error = str(exc)
            returned = self.return_to_position(mini, stop_event, allowed)
            if not returned["returned"]:
                return {"performed": False, **returned}
            return {"performed": not bool(gesture_error), **returned,
                    "reason": (f"動作エラー：{gesture_error} / " if gesture_error else f"{verdict} / ") + "撮影位置へ復帰済み"}
        except Exception as exc:
            self.disable()
            return {"performed": False, "returned": False, "reason": str(exc), "return_error": self.position_error}
        finally:
            self.moving = False
            self.frame = None

    def play_sound(self, mini, verdict, stop_event):
        if stop_event.is_set():
            return {"performed": False, "reason": "アプリ停止中"}
        started = False
        result = {"performed": False, "reason": "判定音は未送信"}
        try:
            rate = mini.media.get_output_audio_samplerate()
            samples = verdict_samples(verdict, rate)
            # One SDK owner thread controls both camera and speaker.
            started = True
            mini.media.start_playing()
            if not stop_event.wait(.08):
                mini.media.push_audio_sample(samples)
                interrupted = stop_event.wait(len(samples) / rate + .15)
                result = {"performed": not interrupted,
                          "reason": "判定音を停止しました" if interrupted else f"{verdict} 判定音を送信",
                          "duration_ms": round(len(samples) / rate * 1000)}
            self.audio_error = ""
        except Exception as exc:
            self.audio_error = str(exc)
            result = {"performed": False, "reason": "判定音の再生に失敗：" + str(exc)}
        finally:
            if started:
                try:
                    mini.media.stop_playing()
                except Exception as exc:
                    self.audio_error = str(exc)
                    result = {"performed": False, "reason": "音声出力の終了に失敗：" + str(exc)}
        return result

    def run(self, mini, stop_event):
        self.connected = True
        try:
            while not stop_event.is_set():
                if self.motion_enabled and time.monotonic() > self.lease_until:
                    self.disable()
                try:
                    cmd = self.commands.get_nowait()
                except queue.Empty:
                    cmd = None
                try:
                    if cmd:
                        if cmd.cancelled or time.monotonic() > cmd.deadline:
                            raise RuntimeError("期限切れ操作を破棄しました")
                        if cmd.kind in ("enable", "react", "home", "remember") and cmd.generation != self.generation:
                            raise RuntimeError("無効化前の操作を破棄しました")
                        if cmd.kind == "snapshot":
                            cmd.result = self.snapshot(mini, stop_event)
                        elif cmd.kind == "sound":
                            cmd.result = self.play_sound(mini, cmd.value, stop_event)
                        elif cmd.kind == "remember":
                            if not self.status()["camera_ready"]:
                                raise RuntimeError("カメラ接続後に撮影位置を記憶してください")
                            cmd.result = self.remember_position(mini, stop_event)
                        elif cmd.kind == "home":
                            cmd.result = self.react(mini, "HOME", stop_event, manual_return=True)
                        elif cmd.kind == "enable":
                            if not self.status()["camera_ready"]:
                                raise RuntimeError("カメラ接続後にモーションを有効化してください")
                            if self.position is None:
                                self.remember_position(mini, stop_event)
                            self.motion_enabled = True
                            self.lease_until = time.monotonic() + 30
                            cmd.result = self.react(mini, "HOME", stop_event)
                        elif cmd.kind == "react":
                            cmd.result = self.react(mini, cmd.value, stop_event)
                    elif not self.capture(mini) and time.monotonic()-self.frame_at > 2:
                        self.frame = None
                        self.connected = False
                        self.error = "カメラ切断 / 新規フレームなし"
                        self.disable()
                except Exception as exc:
                    self.disable()
                    self.frame = None
                    self.connected = False
                    self.error = str(exc)
                    if cmd:
                        cmd.error = str(exc)
                finally:
                    if cmd:
                        cmd.done.set()
                stop_event.wait(.10)
        finally:
            self.stopping = True
            if self.motion_enabled and self.connected and self.position is not None:
                try:
                    # Shutdown is allowed one gentle return, only if motion was enabled.
                    if self.position.joints is not None:
                        mini._goto_joint_positions(head_joint_positions=self.position.joint_target.tolist(), duration=1.)
                except Exception:
                    pass
            self.disable()
            self.connected = False
            self.frame = None
            while not self.commands.empty():
                cmd = self.commands.get_nowait()
                cmd.error = "アプリ停止"
                cmd.done.set()


def add_routes(app: FastAPI, robot: RobotIO):
    def auth(authorization):
        if not robot.token or not hmac.compare_digest(authorization or "", f"Bearer {robot.token}"):
            raise HTTPException(401, "ペアリングトークンが一致しません")

    def command(kind, value=""):
        try:
            return robot.request(kind, value)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/health")
    def health(authorization: str | None = Header(default=None)):
        auth(authorization)
        if robot.motion_enabled:
            robot.lease_until = time.monotonic() + 30
        return robot.status()

    @app.get("/api/frame")
    def frame(authorization: str | None = Header(default=None)):
        auth(authorization)
        with robot.lock:
            if not robot.status()["camera_ready"] or robot.moving:
                raise HTTPException(503, "カメラ準備中・停止中")
            return Response(robot.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/snapshot")
    def snapshot(authorization: str | None = Header(default=None)):
        auth(authorization)
        return Response(command("snapshot"), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    class Reaction(BaseModel):
        verdict: Literal["OK", "NG", "REVIEW", "HOME"]

    @app.post("/api/react")
    def react(body: Reaction, authorization: str | None = Header(default=None)):
        auth(authorization)
        return command("react", body.verdict)

    class Sound(BaseModel):
        verdict: Literal["OK", "NG", "REVIEW"]

    @app.post("/api/sound")
    def sound(body: Sound, authorization: str | None = Header(default=None)):
        auth(authorization)
        return command("sound", body.verdict)

    class PositionAction(BaseModel):
        physically_checked: bool = False

    @app.post("/api/position/remember")
    def remember(authorization: str | None = Header(default=None)):
        auth(authorization)
        return command("remember")

    @app.post("/api/position/return")
    def return_position(body: PositionAction, authorization: str | None = Header(default=None)):
        auth(authorization)
        if not body.physically_checked:
            raise HTTPException(422, "実機周囲を確認してください")
        return command("home")

    class Enable(BaseModel):
        enabled: bool
        physically_checked: bool = False

    @app.post("/api/motion")
    def motion(body: Enable, authorization: str | None = Header(default=None)):
        auth(authorization)
        if not body.enabled:
            robot.disable()
            return {"enabled": False}
        if not body.physically_checked:
            raise HTTPException(422, "実機周囲を確認してください")
        result = command("enable")
        if not result.get("returned"):
            raise HTTPException(503, result.get("reason", "撮影位置へ復帰できません"))
        return {"enabled": robot.motion_enabled}
