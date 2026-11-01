import json

import numpy as np
import pytest

from reachy_mini_ai_inspector.position import InspectionPosition, in_position, read_antennas


class MeasuredMini:
    def __init__(self, antennas):
        self.antennas = antennas

    def get_current_head_pose(self):
        return np.eye(4)

    def get_current_joint_positions(self):
        return [0] * 7, self.antennas


def test_saved_antenna_baseline_round_trips_without_changing_head_reference(tmp_path):
    measured = np.deg2rad([0, 1, 2, 3, 4, 5, 6])
    command = measured + .01
    antennas = np.deg2rad([-10, 10])
    position = InspectionPosition(np.eye(4), 0, measured, command_joints=command, antennas=antennas)
    antennas[:] = 0  # Saving a baseline must not retain the caller's mutable array.
    path = tmp_path / 'position.json'
    position.save(path)
    data = json.loads(path.read_text())
    assert data['version'] == 5
    np.testing.assert_allclose(data['antennas'], np.deg2rad([-10, 10]))
    restored = InspectionPosition.load(path)
    np.testing.assert_array_equal(restored.joints, measured)
    np.testing.assert_array_equal(restored.command_joints, command)
    np.testing.assert_array_equal(restored.joint_target, command)
    np.testing.assert_allclose(restored.antennas, np.deg2rad([-10, 10]))


@pytest.mark.parametrize('version', [1, 2, 3, 4])
def test_legacy_position_has_no_invented_antenna_baseline(tmp_path, version):
    joints = np.zeros(7)
    command = joints + .01
    data = {
        'version': version, 'pose': np.eye(4).tolist(), 'body_yaw': 0,
        'joints': joints.tolist(), 'joint_target': command.tolist(),
        'command_joints': command.tolist(), 'antennas': [-1, 1],
    }
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps(data))
    restored = InspectionPosition.load(path)
    assert restored.antennas is None
    np.testing.assert_array_equal(restored.joints, joints)
    np.testing.assert_array_equal(restored.command_joints, command if version == 4 else joints)


@pytest.mark.parametrize('invalid', [[], [0], [0, 0, 0], [0, float('nan')], [0, float('inf')], [0, 3.2]])
def test_invalid_saved_antenna_baseline_is_rejected(invalid):
    with pytest.raises(RuntimeError, match='アンテナ'):
        InspectionPosition(np.eye(4), 0, [0] * 7, antennas=invalid)


@pytest.mark.parametrize('invalid', [None, [], [0], [0, 0, 0], [0, float('nan')], [0, 3.2]])
def test_invalid_measured_antenna_values_are_rejected(invalid):
    with pytest.raises(RuntimeError, match='アンテナ'):
        read_antennas(MeasuredMini(invalid))


def test_antenna_error_blocks_return_even_when_head_is_in_range():
    position = InspectionPosition(np.eye(4), 0, [0] * 7, antennas=[0, 0])
    error = position.error(MeasuredMini(np.deg2rad([0, 6])))
    assert error['joint_max_deg'] == 0
    assert error['antenna_max_deg'] == pytest.approx(6)
    assert not in_position(error)
    assert in_position(position.error(MeasuredMini(np.deg2rad([0, 4]))))


def test_legacy_head_only_gate_is_unchanged_and_nan_antenna_error_is_rejected():
    error = {'joint_max_deg': 1, 'position_mm': 1, 'rotation_deg': 1, 'body_deg': 0}
    assert in_position(error)
    assert not in_position({**error, 'antenna_max_deg': float('nan')})
