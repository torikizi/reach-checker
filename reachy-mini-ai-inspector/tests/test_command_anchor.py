import json

import numpy as np
import pytest

from reachy_mini_ai_inspector.position import InspectionPosition, in_position


def test_observed_command_anchor_is_separate_from_measured_reference(tmp_path):
    measured = np.zeros(7)
    command = np.deg2rad([0, 0, 0, 0, 0, 9, 0])
    position = InspectionPosition(np.eye(4), 0, measured, command_joints=command)
    np.testing.assert_array_equal(position.joints, measured)
    np.testing.assert_array_equal(position.joint_target, command)
    position.check_joint_target(command + np.deg2rad([0, 0, 0, 0, 0, 5.9, 0]))
    with pytest.raises(RuntimeError, match='補正範囲'):
        position.check_joint_target(command + np.deg2rad([0, 0, 0, 0, 0, 7, 0]))

    class AtMeasuredReference:
        def get_current_head_pose(self):
            return np.eye(4)

        def get_current_joint_positions(self):
            return measured.tolist(), [0, 0]

    # A distinct command never changes what counts as reaching the reference.
    assert in_position(position.error(AtMeasuredReference()))
    path = tmp_path / 'position.json'
    position.save(path)
    assert json.loads(path.read_text())['version'] == 5
    restored = InspectionPosition.load(path)
    np.testing.assert_array_equal(restored.joints, measured)
    np.testing.assert_array_equal(restored.command_joints, command)
    np.testing.assert_array_equal(restored.joint_target, command)


@pytest.mark.parametrize('version', [1, 2, 3])
def test_legacy_position_keeps_measured_anchor_and_existing_target(tmp_path, version):
    joints = np.deg2rad([0, 2, 3, 4, 5, 6, 7])
    target = joints + np.deg2rad([0, .5, 0, 0, 0, 0, 0])
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps({
        'version': version, 'pose': np.eye(4).tolist(), 'body_yaw': 0,
        'joints': joints.tolist(), 'joint_target': target.tolist(),
    }))
    restored = InspectionPosition.load(path)
    np.testing.assert_array_equal(restored.joints, joints)
    np.testing.assert_array_equal(restored.command_joints, joints)
    np.testing.assert_array_equal(restored.joint_target, target)
    with pytest.raises(RuntimeError, match='補正範囲'):
        restored.check_joint_target(joints + np.deg2rad([0, 7, 0, 0, 0, 0, 0]))


@pytest.mark.parametrize('anchor', [[0] * 6, [0] * 6 + [float('nan')], [0] * 6 + [4]])
def test_invalid_observed_command_anchor_is_rejected(anchor):
    with pytest.raises(RuntimeError, match='指令角度'):
        InspectionPosition(np.eye(4), 0, [0] * 7, command_joints=anchor)


def test_command_anchor_requires_measured_reference():
    with pytest.raises(RuntimeError, match='指令角度'):
        InspectionPosition(np.eye(4), 0, command_joints=[0] * 7)


def test_persisted_correction_outside_command_anchor_is_rejected(tmp_path):
    position = InspectionPosition(np.eye(4), 0, [0] * 7, command_joints=np.deg2rad([9] * 7))
    path = tmp_path / 'position.json'
    position.save(path)
    data = json.loads(path.read_text())
    data['joint_target'][1] += np.deg2rad(7)
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match='補正範囲'):
        InspectionPosition.load(path)


def test_return_requires_camera_pose_and_body_in_addition_to_motor_angles():
    within = {'joint_max_deg': 7.5, 'position_mm': 4.0, 'rotation_deg': 4.5, 'body_deg': .2}
    assert in_position(within)
    for key, value in [('joint_max_deg', 8.1), ('position_mm', 5.1), ('rotation_deg', 5.1), ('body_deg', .7)]:
        assert not in_position({**within, key: value})
