import threading

import numpy as np
from scipy.spatial.transform import Rotation
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reachy_mini.utils import create_head_pose

from reachy_mini_ai_inspector.bridge import RobotIO, add_routes
from reachy_mini_ai_inspector.position import InspectionPosition, checked_pose, in_position
from reachy_mini_ai_inspector.providers import DemoProvider, demo_image
from reachy_mini_ai_inspector.server import create_app


class BiasedMini:
    """The measured pose differs from the command, as on calibrated hardware."""
    def __init__(self):
        self.media = self
        self.pose = create_head_pose(pitch=5, degrees=True)
        self.body = .1
        self.calls = []
        self.joint_calls = []
        self.antennas = np.zeros(2)
        self.motor_enable_calls = 0
        self.bias = create_head_pose(x=4, roll=2, pitch=1, mm=True, degrees=True)

    def set_automatic_body_yaw(self, enabled):
        self.auto_yaw = enabled

    def disable_wobbling(self):
        self.wobbling = False

    def stop_head_tracking(self):
        self.head_tracking = False

    def enable_motors(self):
        self.motor_enable_calls += 1

    def get_frame(self):
        return demo_image()

    def get_current_head_pose(self):
        return self.pose.copy()

    def get_current_joint_positions(self):
        return [self.body, *self.pose[:3,3], *Rotation.from_matrix(self.pose[:3,:3]).as_euler('xyz')], self.antennas.tolist()

    def _set_joint_positions(self, head_joint_positions, antennas_joint_positions=None):
        if antennas_joint_positions is not None:
            self.antennas = np.asarray(antennas_joint_positions, dtype=float)
        joints = head_joint_positions
        self.body = joints[0]
        self.pose = np.eye(4)
        self.pose[:3, 3] = joints[1:4]
        self.pose[:3, :3] = Rotation.from_euler('xyz', joints[4:7]).as_matrix()

    def _goto_joint_positions(self, head_joint_positions, duration, antennas_joint_positions=None):
        self.joint_calls.append(head_joint_positions)
        self._set_joint_positions(head_joint_positions, antennas_joint_positions=antennas_joint_positions)

    def goto_target(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get('antennas') is not None:
            self.antennas = np.asarray(kwargs['antennas'], dtype=float)
        self.pose = kwargs['head'].copy()
        self.pose[:3, :3] = self.bias[:3, :3] @ self.pose[:3, :3]
        self.pose[:3, 3] += self.bias[:3, 3]
        self.body = kwargs['body_yaw']


def test_measured_return_corrects_offset_and_remains_stable_across_gestures(tmp_path):
    mini, stop = BiasedMini(), threading.Event()
    path = tmp_path / 'position.json'
    robot = RobotIO('test', path)
    robot.remember_position(mini, stop)
    reference = mini.pose.copy()
    robot.motion_enabled = True
    for verdict in ('OK', 'NG', 'REVIEW'):
        result = robot.react(mini, verdict, stop)
        assert result['performed'] and result['returned'], result
        assert in_position(result['return_error']) and robot.pose_valid
        np.testing.assert_allclose(mini.pose, reference, atol=1e-6)
        assert all(c['body_yaw'] == .1 for c in mini.calls)
    restored = RobotIO('test', path)
    np.testing.assert_allclose(restored.position.pose, reference)
    np.testing.assert_allclose(restored.position.joints, robot.position.joints, atol=1e-12)
    assert not restored.motion_enabled


def test_return_failure_keeps_camera_preview_but_blocks_inspection():
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test')
    robot.position = InspectionPosition(np.eye(4), .1, [.1,0,0,0,0,0,0])
    robot.motion_enabled = True
    # A disabled/stuck motor accepts commands but never reaches the target.
    mini.pose = create_head_pose(pitch=12, degrees=True)
    mini.goto_target = lambda **kw: mini.calls.append(kw)
    mini._goto_joint_positions = lambda **kw: mini.joint_calls.append(kw)
    mini._set_joint_positions = lambda **kw: None
    result = robot.react(mini, 'HOME', stop)
    assert not result['performed'] and not result['returned']
    assert not robot.pose_valid and not robot.motion_enabled
    assert robot.capture(mini) and robot.status()['camera_ready']
    with pytest.raises(RuntimeError, match='撮影位置'):
        robot.snapshot(mini, stop)
    assert len(mini.joint_calls) <= 3


def test_manual_return_does_not_enable_future_reactions():
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test')
    robot.remember_position(mini, stop)
    mini.pose = create_head_pose(pitch=-3, degrees=True)
    result = robot.react(mini, 'HOME', stop, manual_return=True)
    assert result['returned'] and robot.pose_valid
    assert not robot.motion_enabled
    assert not robot.react(mini, 'OK', stop)['performed']


def test_gesture_exception_still_returns_when_not_cancelled():
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test')
    robot.remember_position(mini, stop)
    robot.motion_enabled = True
    goto = mini.goto_target
    calls = 0

    def fail_once(**kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('gesture failed')
        goto(**kw)

    mini.goto_target = fail_once
    result = robot.react(mini, 'OK', stop)
    assert not result['performed'] and result['returned']
    assert 'gesture failed' in result['reason'] and robot.pose_valid


def test_external_pose_change_blocks_next_snapshot():
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test')
    robot.remember_position(mini, stop)
    mini.pose = create_head_pose(pitch=12, degrees=True)
    with pytest.raises(RuntimeError, match='撮影位置'):
        robot.snapshot(mini, stop)
    assert not robot.pose_valid


def test_disable_during_return_never_runs_correction():
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test')
    robot.remember_position(mini, stop)
    goto = mini._goto_joint_positions

    def interrupt(**kw):
        goto(**kw)
        robot.disable()

    mini._goto_joint_positions = interrupt
    mini.pose = create_head_pose(pitch=-3, degrees=True)
    result = robot.react(mini, 'HOME', stop, manual_return=True)
    assert not result['returned'] and not robot.pose_valid
    assert len(mini.joint_calls) == 1


def test_position_api_requires_readiness_and_preserves_model(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers={'X-Inspector-UI': '1'}) as c:
        c.post('/api/demo/train')
        before = c.get('/api/status').json()
        assert c.post('/api/position/return', json={}).status_code == 422
        assert c.post('/api/position/remember', json={}).status_code == 422
        assert c.post('/api/position/remember', json={'physically_checked': True}).json()['saved']
        assert c.post('/api/position/return', json={'physically_checked': True}).status_code == 200
        after = c.get('/api/status').json()
        assert before['model_id'] == after['model_id']
        assert before['normal_count'] == after['normal_count'] == 12
        assert c.get('/api/history').json() == []


def test_saved_position_rejects_corrupt_or_unsafe_transform(tmp_path):
    with pytest.raises(RuntimeError):
        InspectionPosition(np.zeros((4, 4)), 0)
    with pytest.raises(RuntimeError, match='範囲'):
        InspectionPosition(create_head_pose(pitch=40, degrees=True), 0)
    with pytest.raises(RuntimeError, match='モーター'):
        InspectionPosition(np.eye(4), 0, [10]*7)


def test_small_fk_numerical_error_is_normalized_without_hiding_a_real_rotation():
    measured = create_head_pose(roll=3.4, pitch=3.5, degrees=True)
    measured[:3, :3] *= 1.00025
    normalized = checked_pose(measured)
    np.testing.assert_allclose(normalized[:3, :3].T @ normalized[:3, :3], np.eye(3), atol=1e-12)
    reference = InspectionPosition(np.eye(4), 0)
    mini = BiasedMini()
    mini.pose = measured
    mini.body = 0
    assert reference.error(mini)['rotation_deg'] > 4


def test_enable_failure_is_reported_instead_of_claiming_motion_is_enabled():
    robot = RobotIO('test')
    robot.request = lambda *args: {'performed': False, 'returned': False, 'reason': 'return failed'}
    app = FastAPI()
    add_routes(app, robot)
    with TestClient(app) as c:
        response = c.post('/api/motion', headers={'Authorization': 'Bearer test'}, json={'enabled': True, 'physically_checked': True})
        assert response.status_code == 503 and response.json()['detail'] == 'return failed'
    assert not robot.motion_enabled


def test_motor_bias_is_corrected_without_moving_the_saved_reference(tmp_path):
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test', tmp_path/'position.json')
    robot.remember_position(mini, stop)
    reference = robot.position.joints.copy()
    set_joints = mini._set_joint_positions
    bias = np.deg2rad([.08, .08, 2.46, -1.58, .52, -1.14, .08])
    mini._set_joint_positions = lambda head_joint_positions, antennas_joint_positions=None: set_joints(np.array(head_joint_positions)+bias, antennas_joint_positions=antennas_joint_positions)
    for _ in range(2):
        mini.pose = create_head_pose(pitch=-3, degrees=True)
        result = robot.react(mini, 'HOME', stop, manual_return=True)
        assert result['returned'], result
        assert result['return_error']['joint_max_deg'] <= .35
        np.testing.assert_allclose(robot.position.joints, reference)
    saved = RobotIO('test', tmp_path/'position.json').position
    np.testing.assert_allclose(saved.joints, reference)
    assert np.max(np.abs(saved.joint_target-reference)) > .02


def test_joint_correction_remains_bounded():
    position = InspectionPosition(np.eye(4), 0, [0]*7)
    with pytest.raises(RuntimeError, match='補正範囲'):
        position.check_joint_target(np.deg2rad([0, 0, 7, 0, 0, 0, 0]))


def test_return_waits_for_async_motors_before_correcting(monkeypatch):
    from reachy_mini_ai_inspector import bridge

    clock = [0.0]
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: clock[0])

    class ClockStop:
        def is_set(self):
            return False

        def wait(self, duration):
            clock[0] += duration
            return False

    mini, robot = BiasedMini(), RobotIO('test')
    robot.remember_position(mini, ClockStop())
    apply = mini._set_joint_positions
    reference = robot.position.joints.copy()
    mini.pose = create_head_pose(pitch=-3, degrees=True)
    pending = [None, 0.0]

    def command(head_joint_positions, antennas_joint_positions=None):
        pending[:] = [head_joint_positions, clock[0] + .8]

    read = mini.get_current_joint_positions

    def measured():
        if pending[0] is not None and clock[0] >= pending[1]:
            apply(pending[0])
            pending[0] = None
        return read()

    mini._set_joint_positions = command
    mini.get_current_joint_positions = measured
    result = robot.react(mini, 'HOME', ClockStop(), manual_return=True)
    assert result['returned'], result
    assert result['retries'] == 0
    assert len(mini.joint_calls) == 1
    np.testing.assert_allclose(robot.position.joints, reference)


def test_already_home_does_not_command_measured_angles_again():
    mini, robot, stop = BiasedMini(), RobotIO('test'), threading.Event()
    robot.remember_position(mini, stop)
    result = robot.react(mini, 'HOME', stop, manual_return=True)
    assert result['returned'] and robot.pose_valid
    assert mini.motor_enable_calls == 1
    assert mini.joint_calls == []
    assert not robot.motion_enabled


def test_disabled_reaction_does_not_enable_motors():
    mini, robot = BiasedMini(), RobotIO('test')
    result = robot.react(mini, 'HOME', threading.Event())
    assert not result['performed']
    assert mini.motor_enable_calls == 0


def test_calibrated_command_returns_loaded_motors_without_absorbing_residual(tmp_path):
    mini, stop = BiasedMini(), threading.Event()
    robot = RobotIO('test', tmp_path/'position.json')
    apply = mini._set_joint_positions
    bias = np.deg2rad([0, 0, 0, 0, 9, -8, 0])
    mini._set_joint_positions = lambda head_joint_positions, antennas_joint_positions=None: apply(np.array(head_joint_positions)+bias, antennas_joint_positions=antennas_joint_positions)
    robot.calibrate_position(mini, stop)
    reference = robot.position.joints.copy()
    anchor = robot.position.command_joints.copy()
    np.testing.assert_allclose(reference-anchor, bias, atol=1e-12)
    robot.motion_enabled = True
    for verdict in ['OK', 'NG', 'REVIEW']:
        result = robot.react(mini, verdict, stop)
        assert result['returned'] and result['performed'], result
        np.testing.assert_allclose(robot.position.command_joints, anchor)
        np.testing.assert_allclose(robot.position.joints, reference)
    saved = RobotIO('test', tmp_path/'position.json').position
    np.testing.assert_allclose(saved.command_joints, anchor)


def test_calibration_requires_explicit_surroundings_confirmation():
    robot, app = RobotIO('test'), FastAPI()
    add_routes(app, robot)
    with TestClient(app) as c:
        auth = {'Authorization': 'Bearer test'}
        assert c.post('/api/position/calibrate', headers=auth, json={}).status_code == 422
        assert c.post('/api/position/calibrate', json={'physically_checked': True}).status_code == 401


def test_happy_expression_uses_antennas_and_automatically_restores_camera_pose():
    mini, robot, stop = BiasedMini(), RobotIO('test'), threading.Event()
    mini.antennas = np.deg2rad([-10, 10])
    robot.remember_position(mini, stop)
    original_pose = robot.position.pose.copy()
    original_antennas = robot.position.antennas.copy()
    robot.motion_enabled = True
    result = robot.react(mini, 'OK', stop)
    assert result['performed'] and result['returned'], result
    assert len(mini.calls) >= 5  # Celebration plus a distinct return waypoint.
    excursions = [np.max(np.abs(np.asarray(call['antennas'])-original_antennas)) for call in mini.calls[:-1]]
    assert sum(value >= np.deg2rad(20) for value in excursions) >= 2
    np.testing.assert_allclose(mini.calls[-1]['head'], original_pose)
    np.testing.assert_allclose(mini.calls[-1]['antennas'], original_antennas)
    np.testing.assert_allclose(mini.pose, original_pose, atol=1e-12)
    np.testing.assert_allclose(mini.antennas, original_antennas)
    np.testing.assert_allclose(robot.position.pose, original_pose)
    assert robot.pose_valid


def test_stop_during_celebration_does_not_send_new_return_movements():
    mini, robot, stop = BiasedMini(), RobotIO('test'), threading.Event()
    robot.remember_position(mini, stop)
    robot.motion_enabled = True
    move = mini.goto_target

    def stop_after_first_beat(**kwargs):
        move(**kwargs)
        robot.disable()

    mini.goto_target = stop_after_first_beat
    result = robot.react(mini, 'OK', stop)
    assert not result['returned'] and not robot.pose_valid
    assert len(mini.calls) == 1
    assert mini.joint_calls == []


def test_manual_home_does_not_skip_actual_return_near_photo_envelope_boundary():
    mini, robot, stop = BiasedMini(), RobotIO('test'), threading.Event()
    robot.remember_position(mini, stop)
    mini.pose = create_head_pose(pitch=9.7, degrees=True)
    result = robot.react(mini, 'HOME', stop, manual_return=True)
    assert result['returned'], result
    assert mini.joint_calls  # Broad 5-degree acceptance must not skip return.
    np.testing.assert_allclose(mini.pose, robot.position.pose, atol=1e-12)


def test_return_does_not_accept_small_adjacent_deltas_while_head_keeps_creeping(monkeypatch):
    from reachy_mini_ai_inspector import bridge

    clock = [0.0]
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: clock[0])

    class ClockStop:
        def is_set(self): return False
        def wait(self, duration):
            clock[0] += duration
            return False

    mini, robot = BiasedMini(), RobotIO('test')
    robot.remember_position(mini, ClockStop())
    read = mini.get_current_joint_positions
    started = clock[0]

    def creeping_joints():
        head, antennas = read()
        head[5] += np.deg2rad(1.2 * min(clock[0]-started, 1.0))
        return head, antennas

    mini.get_current_joint_positions = creeping_joints
    result = robot.return_to_position(mini, ClockStop(), lambda: True)
    assert result['returned'], result
    assert clock[0]-started >= 1.5
