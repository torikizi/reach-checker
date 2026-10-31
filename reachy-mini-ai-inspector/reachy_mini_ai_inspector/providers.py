import io
import threading
import time

import cv2
import httpx
import numpy as np


def decode(data):
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("画像を読み込めません")
    return frame


def encode(image):
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("画像保存に失敗しました")
    return data.tobytes()


def demo_image(scene="red24", seed=0):
    rng = np.random.default_rng(seed)
    image = np.full((480, 640, 3), 218, np.uint8)
    cv2.rectangle(image, (60, 60), (580, 420), (203, 209, 213), 2)
    if scene == "empty":
        return image
    # Keep the same stud pitch and height: 2x8 is twice as long as normal 2x4.
    columns = 8 if scene == "red28" else 4
    width = 420 if scene == "red28" else 210
    dx, dy = rng.integers(-5, 6, 2)
    x, y = int(320-width//2+dx), int(240-54+dy)
    color = (45, 46, int(rng.integers(184, 204))) if scene != "blue24" else (194, 80, 35)
    cv2.rectangle(image, (x+7, y+9), (x+width+7, y+117), (168, 174, 178), -1)
    cv2.rectangle(image, (x, y), (x+width, y+108), color, -1)
    cv2.rectangle(image, (x, y+98), (x+width, y+108), tuple(int(c*.76) for c in color), -1)
    for col in range(columns):
        for row in range(2):
            center = (x+27+col*52, y+27+row*50)
            cv2.circle(image, (center[0]+2, center[1]+3), 17, tuple(int(c*.65) for c in color), -1)
            cv2.circle(image, center, 16, tuple(min(255, int(c*1.10)) for c in color), -1)
            cv2.ellipse(image, center, (12, 12), 0, 190, 270, (96, 102, 238) if scene != "blue24" else (240, 140, 90), 2)
    noise = rng.normal(0, 1.2, image.shape)
    image = np.clip(image.astype(float)+noise, 0, 255).astype(np.uint8)
    if scene == "blur":
        image = cv2.GaussianBlur(image, (41, 41), 15)
    return image


class DemoProvider:
    mode = "demo"

    def __init__(self):
        self.scene = "red24"
        self.counter = 0
        self.enabled = False
        self.position_saved = False

    def frame(self, fresh=False):
        self.counter += 1
        return encode(demo_image(self.scene, self.counter))

    def health(self):
        return {"connected": True, "camera_ready": True, "motion_enabled": self.enabled,
                "error": "", "source": "合成画像（実機ではありません）", "scene": self.scene,
                "position_saved": self.position_saved, "pose_valid": True}

    def motion(self, enabled, checked=False):
        self.enabled = enabled and checked
        return {"enabled": self.enabled}

    def react(self, verdict):
        return {"performed": False, "reason": "デモ：実機モーションなし", "requested": verdict}

    def sound(self, verdict):
        return {"performed": False, "reason": "デモ：本体の判定音なし", "requested": verdict}

    def remember_position(self):
        self.position_saved = True
        return {"saved": True, "reason": "デモ：撮影位置の記憶（実機操作なし）"}

    def return_position(self):
        return {"performed": False, "reason": "デモ：実機の位置復帰なし"}

    def close(self):
        pass


class BridgeProvider:
    mode = "robot"

    def __init__(self, url, token):
        self.client = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                   timeout=httpx.Timeout(15, connect=3), trust_env=False)

    def call(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", str(exc))
            except ValueError:
                detail = "本体アプリの応答を確認してください"
            raise RuntimeError(str(detail)) from exc
        except httpx.RequestError as exc:
            raise RuntimeError("本体アプリに接続できません。電源・Wi-Fi・Applicationsの起動を確認してください") from exc

    def frame(self, fresh=False):
        return self.call("POST" if fresh else "GET", "/api/snapshot" if fresh else "/api/frame").content

    def health(self):
        return self.call("GET", "/api/health").json()

    def motion(self, enabled, checked=False):
        return self.call("POST", "/api/motion", json={"enabled": enabled, "physically_checked": checked}).json()

    def react(self, verdict):
        return self.call("POST", "/api/react", json={"verdict": verdict}).json()

    def sound(self, verdict):
        return self.call("POST", "/api/sound", json={"verdict": verdict}).json()

    def remember_position(self):
        return self.call("POST", "/api/position/remember").json()

    def return_position(self):
        return self.call("POST", "/api/position/return", json={"physically_checked": True}).json()

    def close(self):
        try:
            self.motion(False)
        except RuntimeError:
            pass
        self.client.close()
