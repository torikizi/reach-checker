import csv
import io
import json
import threading
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_ai_inspector.bridge import RobotIO, add_routes
from reachy_mini_ai_inspector.providers import DemoProvider, demo_image, decode, encode
from reachy_mini_ai_inspector.server import create_app
from reachy_mini_ai_inspector.settings import Settings
from reachy_mini_ai_inspector.storage import Store
from reachy_mini_ai_inspector.vision import AnomalyModel, extract
from reachy_mini_ai_inspector.position import InspectionPosition

HEADERS = {"X-Inspector-UI": "1"}


@pytest.fixture
def client(tmp_path):
    app = create_app(DemoProvider(), tmp_path / "data")
    with TestClient(app, headers=HEADERS) as c:
        assert c.post('/api/criteria',json={'name':'赤色2×4'}).status_code==200
        yield c


@pytest.fixture
def trained(client):
    assert client.post('/api/demo/train').status_code == 200
    return client


def test_real_svm_is_fitted_and_three_classes(trained):
    inspector = trained.app.state.inspector
    assert inspector.model.model.__class__.__name__ == 'OneClassSVM'
    assert inspector.model.model.support_vectors_.shape[0] > 0
    for scene, verdict, reason in [('red24', 'OK', '特徴範囲'), ('blue24', 'NG', '色違い'), ('red28', 'NG', '形状違い')]:
        assert trained.post('/api/demo/scene', json={'scene': scene}).status_code == 200
        assert trained.get('/api/status').json()['robot']['scene'] == scene
        r = trained.post('/api/inspect', json={'identifier': scene})
        assert r.status_code == 200, r.text
        r = r.json()
        assert r['verdict'] == verdict, r
        assert r['ai_executed'] is True
        assert isinstance(r['svm_decision'], float)
        assert reason in ' '.join(r['reasons'])
        if scene == 'red28':
            assert not any('色違い' in reason for reason in r['reasons'])
        assert trained.get('/api/images/'+r['image']).content.startswith(b'\xff\xd8')


def test_long_block_clipped_by_roi_is_review(client):
    # A narrow ROI still fits the normal 2x4 but cuts off the longer 2x8.
    settings = client.get('/api/status').json()['settings']
    settings['roi'].update(x=.25, width=.5)
    assert client.post('/api/settings', json=settings).status_code == 200
    assert client.post('/api/demo/train').status_code == 200
    assert client.post('/api/inspect', json={}).json()['verdict'] == 'OK'
    assert client.post('/api/demo/scene', json={'scene': 'red28'}).status_code == 200
    result = client.post('/api/inspect', json={}).json()
    assert result['verdict'] == 'REVIEW'
    assert result['ai_executed']
    assert any('はみ出し' in reason for reason in result['reasons'])


@pytest.mark.parametrize('scene', ['empty', 'blur'])
def test_bad_images_review(trained, scene):
    trained.post('/api/demo/scene', json={'scene': scene})
    r=trained.post('/api/inspect', json={}).json()
    assert r['verdict']=='REVIEW', r


def test_untrained_never_ok(client):
    r=client.post('/api/inspect', json={}).json()
    assert r['verdict']=='REVIEW'
    assert not r['ai_executed']
    assert r['ai_score'] is None


def test_registration_and_rebuild_persist(tmp_path):
    path=tmp_path/'store'
    with TestClient(create_app(DemoProvider(), path),headers=HEADERS) as c:
        assert c.post('/api/criteria',json={'name':'部品A'}).status_code==200
        for i in range(8):
            response=c.post('/api/normal')
            assert response.status_code==200,response.text
        id=c.get('/api/status').json()['model_id']
        assert c.get('/api/status').json()['model_ready']
    with TestClient(create_app(DemoProvider(), path),headers=HEADERS) as c:
        assert c.get('/api/status').json()['model_id']==id
        assert c.post('/api/inspect',json={}).json()['ai_executed']


def test_profile_changes_invalidate_and_preserve(trained):
    original=trained.get('/api/status').json()['settings']
    new={**original,'normal_name':'新しい正常品'}
    assert trained.post('/api/settings',json=new).status_code==200
    # Renaming the same criterion keeps its reference set; its ID is stable.
    assert trained.get('/api/status').json()['model_ready']
    trained.post('/api/settings',json=original)
    assert trained.get('/api/status').json()['model_ready']
    new={**original,'ok_threshold':.30}
    trained.post('/api/settings',json=new)
    assert trained.get('/api/status').json()['model_ready']


@pytest.mark.parametrize('changes',[{'ok_threshold':.9,'ng_threshold':.2},{'roi':{'x':.8,'width':.5}},{'normal_name':''}])
def test_invalid_settings_rejected(client,changes):
    assert client.post('/api/settings',json=changes).status_code==422


def test_no_cross_origin_write(client):
    assert client.post('/api/normal',headers={'X-Inspector-UI':'0'}).status_code==403
    assert client.post('/api/normal',headers={'Origin':'https://example.com'}).status_code==403
    assert client.get('/api/status',headers={'Host':'evil.test'}).status_code==400


def test_concurrent_inspection_rejected(client):
    lock=client.app.state.inspector.lock
    with lock:
        assert client.post('/api/inspect',json={}).status_code==409
        assert client.post('/api/settings',json={}).status_code==409
        assert client.post('/api/motion',json={'enabled':False}).status_code==200


def test_csv_and_metrics(trained):
    records=[]
    for scene, truth in [('red24','OK'),('blue24','NG'),('empty','NG')]:
        trained.post('/api/demo/scene',json={'scene':scene})
        r=trained.post('/api/inspect',json={'identifier':'=SUM(1,2)'}).json();records.append(r)
        assert trained.post('/api/history/'+r['id']+'/label',json={'truth':truth,'condition':'照明A'}).status_code==200
    m=trained.get('/api/metrics').json()
    assert m['labeled']==3 and m['reviews']==1 and m['missed_defects']==0
    assert m['normal_recall']==1 and m['defect_recall']==.5
    assert m['accuracy']==.6667 and m['coverage']==.6667
    csv_text=trained.get('/api/export.csv').text.lstrip('\ufeff')
    rows=list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows)==3 and rows[0]['identifier'].startswith("'")
    assert json.loads(rows[0]['settings'])['normal_name']=='赤色2×4'
    assert trained.post('/api/history/missing/label',json={'truth':'OK'}).status_code==404


def test_mode_separation(tmp_path):
    s=Store(tmp_path,'demo');s.close()
    with pytest.raises(ValueError,match='分けて'):
        Store(tmp_path,'robot')


def test_robot_disconnect_no_fake_result(tmp_path):
    class Offline(DemoProvider):
        mode='robot'
        def frame(self, fresh=False): raise RuntimeError('offline')
        def health(self): raise RuntimeError('offline')
    with TestClient(create_app(Offline(),tmp_path),headers=HEADERS) as c:
        assert c.post('/api/criteria',json={'name':'切断試験'}).status_code==200
        assert not c.get('/api/status').json()['robot']['connected']
        assert c.post('/api/inspect',json={}).status_code==503
        assert c.get('/api/history').json()==[]
        assert c.post('/api/demo/train').status_code==404


def test_motion_failure_preserves_result(trained):
    def fail(verdict): raise RuntimeError('motion disconnected')
    trained.app.state.inspector.provider.react=fail
    r=trained.post('/api/inspect',json={}).json()
    assert r['verdict']=='OK'
    assert not r['motion']['performed']
    assert trained.get('/api/history').json()[0]['id']==r['id']


def test_snapshot_and_pagination(trained):
    r=trained.post('/api/snapshot').json()
    assert trained.get('/api/images/'+r['image']).status_code==200
    assert trained.get('/api/images/missing.jpg').status_code==404
    for i in range(3): trained.post('/api/inspect',json={'identifier':str(i)})
    assert [r['identifier'] for r in trained.get('/api/history?limit=2&offset=1').json()]==['1','0']


class FakeMini:
    def __init__(self):
        self.media=self
        self.calls=[]
        self.available=True
        self.pose=np.eye(4)
        self.body_yaw=0.
        self.joint_calls=[]
    def get_frame(self): return demo_image() if self.available else None
    def goto_target(self,**kwargs):
        self.calls.append(kwargs)
        self.pose=np.array(kwargs['head'])
        if kwargs.get('body_yaw') is not None:self.body_yaw=kwargs['body_yaw']
    def get_current_head_pose(self): return self.pose.copy()
    def get_current_joint_positions(self):
        return [self.body_yaw,*self.pose[:3,3],*Rotation.from_matrix(self.pose[:3,:3]).as_euler('xyz')],[0,0]
    def _set_joint_positions(self,head_joint_positions):
        joints=head_joint_positions;self.body_yaw=joints[0]
        self.pose=np.eye(4);self.pose[:3,3]=joints[1:4];self.pose[:3,:3]=Rotation.from_euler('xyz',joints[4:7]).as_matrix()
    def _goto_joint_positions(self,head_joint_positions,duration):
        self.joint_calls.append(head_joint_positions)
        self._set_joint_positions(head_joint_positions)


def test_bridge_auth_stale_and_motion_defaults():
    robot=RobotIO('test-token');app=FastAPI();add_routes(app,robot)
    with TestClient(app) as c:
        assert c.get('/api/health').status_code==401
        auth={'Authorization':'Bearer test-token'}
        assert not c.get('/api/health',headers=auth).json()['motion_enabled']
        assert c.get('/api/frame',headers=auth).status_code==503
        assert c.post('/api/motion',headers=auth,json={'enabled':True}).status_code==422
        robot.frame=b'old';robot.frame_at=time.monotonic()-3
        assert c.get('/api/frame',headers=auth).status_code==503
        assert c.post('/api/react',headers=auth,json={'verdict':'unsafe'}).status_code==422


def test_bridge_queue_camera_motion_stop():
    robot=RobotIO('test');mini=FakeMini();stop=threading.Event()
    t=threading.Thread(target=robot.run,args=(mini,stop));t.start()
    try:
        data=robot.request('snapshot')
        assert decode(data).shape[1]==640 and mini.calls==[]
        assert robot.request('react','OK')['performed'] is False
        robot.request('enable')
        assert robot.motion_enabled
        result=robot.request('react','NG')
        assert result['performed'] and len(mini.calls)==3 and len(mini.joint_calls)==2
        for call in mini.calls:
            rot=call['head'][:3,:3]
            angle=np.arccos(np.clip((np.trace(rot)-1)/2,-1,1))
            assert angle <= np.deg2rad(11)
            assert call['duration']>=.5
        robot.disable()
        assert not robot.request('react','OK')['performed']
    finally:
        stop.set();t.join(timeout=5)
    assert not t.is_alive() and not robot.connected and not robot.motion_enabled


def test_bridge_disconnect_disables_motion():
    robot=RobotIO('test');mini=FakeMini();mini.available=False
    robot.motion_enabled=True;robot.lease_until=time.monotonic()+30
    stop=threading.Event();t=threading.Thread(target=robot.run,args=(mini,stop));t.start()
    time.sleep(.25);stop.set();t.join(timeout=3)
    assert not robot.connected and not robot.motion_enabled and mini.calls==[]


def test_reaction_returns_to_inspection_pose():
    from reachy_mini.utils import create_head_pose
    robot=RobotIO('test');mini=FakeMini();stop=threading.Event()
    mini.pose=create_head_pose(pitch=15,degrees=True);mini.body_yaw=.1
    robot.position=InspectionPosition(mini.pose,.1,mini.get_current_joint_positions()[0])
    robot.motion_enabled=True
    robot.react(mini,'OK',stop)
    np.testing.assert_allclose(mini.pose,robot.position.pose,atol=1e-12)
    assert all(c['body_yaw'] == .1 for c in mini.calls)
    assert robot.pose_valid


def test_motion_near_limit_rejected():
    from reachy_mini.utils import create_head_pose
    mini=FakeMini();mini.get_current_head_pose=lambda:create_head_pose(pitch=35,degrees=True)
    robot=RobotIO('test');stop=threading.Event();t=threading.Thread(target=robot.run,args=(mini,stop));t.start()
    try:
        robot.request('snapshot')
        with pytest.raises(RuntimeError,match='範囲'):
            robot.request('enable')
        assert not mini.calls and not robot.motion_enabled
    finally:
        stop.set();t.join(timeout=3)


def test_interrupted_motion_blocks_snapshot_until_home():
    robot=RobotIO('test');mini=FakeMini();stop=threading.Event()
    robot.position=InspectionPosition(np.eye(4),0,[0]*7)
    robot.motion_enabled=True
    original=mini.goto_target
    def interrupt(**kw):
        original(**kw);robot.disable()
    mini.goto_target=interrupt
    assert not robot.react(mini,'NG',stop)['performed']
    assert not robot.pose_valid
    with pytest.raises(RuntimeError,match='途中'):
        robot.snapshot(mini,stop)
    mini.goto_target=original;robot.motion_enabled=True
    robot.react(mini,'HOME',stop)
    assert robot.pose_valid
