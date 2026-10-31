"""Measured inspection position, including the original motor encoder angles."""
import json
from pathlib import Path

import numpy as np


POSITION_TOLERANCE_MM = 1.5
ANGLE_TOLERANCE_DEG = .6
JOINT_TOLERANCE_DEG = .35


def checked_pose(value):
    pose = np.asarray(value, dtype=float)
    if pose.shape != (4, 4) or not np.isfinite(pose).all():
        raise RuntimeError("頭部の現在姿勢を取得できません")
    rotation = pose[:3, :3]
    if not np.allclose(pose[3], [0, 0, 0, 1]) or not np.allclose(rotation.T @ rotation, np.eye(3), atol=.01) or not .99 < np.linalg.det(rotation) < 1.01:
        raise RuntimeError("頭部の姿勢データが不正です")
    # The robot's FK can return a slightly non-orthogonal matrix (about 5e-4
    # observed). Project only small numerical errors onto SO(3) before comparing.
    u, _, vt = np.linalg.svd(rotation)
    pose = pose.copy()
    pose[:3, :3] = u @ vt
    return pose


def angle_degrees(rotation):
    return float(np.rad2deg(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1, 1))))


def read_position(mini):
    pose = checked_pose(mini.get_current_head_pose())
    joints, _ = mini.get_current_joint_positions()
    if len(joints) != 7 or not np.isfinite(joints).all():
        raise RuntimeError("胴体の現在位置を取得できません")
    return pose, float(joints[0])


def read_joints(mini):
    joints = np.asarray(mini.get_current_joint_positions()[0], dtype=float)
    if joints.shape != (7,) or not np.isfinite(joints).all() or np.max(np.abs(joints)) > np.pi:
        raise RuntimeError("頭部モーターの現在角度を取得できません")
    return joints


def position_error(actual, body_yaw, desired, desired_body):
    delta = np.arctan2(np.sin(body_yaw-desired_body), np.cos(body_yaw-desired_body))
    return {"position_mm": float(np.linalg.norm(actual[:3, 3]-desired[:3, 3])*1000),
            "rotation_deg": angle_degrees(desired[:3, :3] @ actual[:3, :3].T),
            "body_deg": float(abs(np.rad2deg(delta)))}


def in_position(error):
    if "joint_max_deg" in error:
        return error["joint_max_deg"] <= JOINT_TOLERANCE_DEG
    return error["position_mm"] <= POSITION_TOLERANCE_MM and max(error["rotation_deg"], error["body_deg"]) <= ANGLE_TOLERANCE_DEG


class InspectionPosition:
    def __init__(self, pose, body_yaw, joints=None, joint_target=None):
        self.pose = checked_pose(pose)
        self.body_yaw = float(body_yaw)
        if not np.isfinite(self.body_yaw) or abs(self.body_yaw) > np.pi:
            raise RuntimeError("胴体の撮影位置が不正です")
        if angle_degrees(self.pose[:3, :3]) > 25 or np.linalg.norm(self.pose[:3, 3]) > .025:
            raise RuntimeError("姿勢が動作範囲の端に近いため記憶できません。中央付近へ戻してください")
        self.target = self.pose.copy()
        self.joints = None if joints is None else np.asarray(joints, dtype=float)
        if self.joints is not None and (self.joints.shape != (7,) or not np.isfinite(self.joints).all() or np.max(np.abs(self.joints)) > np.pi):
            raise RuntimeError("保存したモーター角度が不正です")
        self.joint_target = None if self.joints is None else self.joints.copy()
        if joint_target is not None:
            self.joint_target = np.asarray(joint_target, dtype=float)
            self.check_joint_target(self.joint_target)

    def check_joint_target(self, target):
        if self.joints is None or target.shape != (7,) or not np.isfinite(target).all() or np.max(np.abs(target)) > np.pi or np.max(np.abs(target-self.joints)) > np.deg2rad(6):
            raise RuntimeError("撮影位置の補正範囲を超えました。モーターと周囲を確認してください")

    def error(self, mini):
        error = position_error(*read_position(mini), self.pose, self.body_yaw)
        if self.joints is not None:
            error["joint_max_deg"] = float(np.rad2deg(np.max(np.abs(read_joints(mini)-self.joints))))
        return error

    def save(self, path):
        if path is None:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 3, "pose": self.pose.tolist(), "body_yaw": self.body_yaw, "joints": None if self.joints is None else self.joints.tolist(), "joint_target": None if self.joint_target is None else self.joint_target.tolist()}))
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        if path is None or not Path(path).exists():
            return None
        data = json.loads(Path(path).read_text())
        if data.get("version") not in (1, 2, 3):
            raise RuntimeError("保存した撮影位置の形式を確認してください")
        return cls(data["pose"], data["body_yaw"], data.get("joints"), data.get("joint_target"))
