import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reachy_mini_ai_inspector.providers import DemoProvider, demo_image, encode
from reachy_mini_ai_inspector.reference_images import normalize_reference
from reachy_mini_ai_inspector.server import create_app
from reachy_mini_ai_inspector.settings import Settings
from reachy_mini_ai_inspector.storage import Store
from reachy_mini_ai_inspector.vision import extract

HEADERS = {'X-Inspector-UI': '1'}


def images(scene='red24', count=8):
    return [('files', (f'{scene}-{seed}.jpg', encode(demo_image(scene, seed)), 'image/jpeg')) for seed in range(100, 100+count)]


def criterion(client, name):
    response = client.post('/api/criteria', json={'name': name})
    assert response.status_code == 200, response.text
    return response.json()['id']


def upload(client, id, files=None):
    response = client.post(f'/api/criteria/{id}/references', files=images() if files is None else files)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_start_requires_a_criterion_and_never_uses_fixed_lego_normal(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        status = c.get('/api/status').json()
        assert status['active_criterion'] is None and not status['model_ready']
        assert status['settings']['normal_name'] == '正常品'
        assert c.get('/api/criteria').json() == []
        assert c.post('/api/normal').status_code == 409
        assert c.post('/api/inspect', json={}).status_code == 409
        assert c.get('/api/history').json() == []
        assert c.post('/api/criteria', json={'name': '   '}).status_code == 422
        criterion(c, '部品A')
        assert c.post('/api/criteria', json={'name': '部品A'}).status_code == 422


def test_upload_and_switch_change_what_the_ai_treats_as_normal(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        red = criterion(c, '赤い部品')
        result = upload(c, red)
        assert len(result['accepted']) == 8 and result['ready'] and not result['errors']
        c.post('/api/demo/scene', json={'scene': 'red24'})
        red_result = c.post('/api/inspect', json={'identifier': 'A-1'}).json()
        assert red_result['verdict'] == 'OK' and red_result['ai_executed']
        assert red_result['criterion_id'] == red and red_result['criterion_name'] == '赤い部品'
        c.post('/api/demo/scene', json={'scene': 'blue24'})
        assert c.post('/api/inspect', json={}).json()['verdict'] == 'NG'
        blue = criterion(c, '青い部品')
        assert not c.get('/api/status').json()['model_ready']
        assert upload(c, blue, images('blue24'))['ready']
        assert c.post('/api/inspect', json={}).json()['verdict'] == 'OK'
        c.post('/api/demo/scene', json={'scene': 'red24'})
        assert c.post('/api/inspect', json={}).json()['verdict'] == 'NG'
        assert c.post('/api/criteria/select', json={'id': red}).status_code == 200
        assert c.post('/api/inspect', json={}).json()['verdict'] == 'OK'
        rows = c.get('/api/criteria').json()
        assert [(row['name'], row['count']) for row in rows] == [('赤い部品', 8), ('青い部品', 8)]
        assert c.app.state.inspector.model.model.__class__.__name__ == 'OneClassSVM'


def test_each_criterion_keeps_settings_and_rename_keeps_its_references(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        a = criterion(c, 'A'); upload(c, a)
        b = criterion(c, 'B'); upload(c, b, images('blue24'))
        c.post('/api/criteria/select', json={'id': a})
        original = c.get('/api/status').json()['settings']
        changed = {**original, 'normal_name': 'Aの新しい名前', 'ok_threshold': .2}
        assert c.post('/api/settings', json=changed).status_code == 200
        assert c.get('/api/status').json()['normal_count'] == 8
        changed['roi'] = {**original['roi'], 'x': .2, 'width': .6}
        c.post('/api/settings', json=changed)
        assert c.get('/api/status').json()['normal_count'] == 0
        c.post('/api/criteria/select', json={'id': b})
        status = c.get('/api/status').json()
        assert status['settings']['ok_threshold'] == .38 and status['normal_count'] == 8
        assert status['settings']['roi'] == original['roi']
        c.post('/api/criteria/select', json={'id': a})
        assert c.get('/api/status').json()['settings']['ok_threshold'] == .2
        changed['roi'] = original['roi']
        c.post('/api/settings', json=changed)
        assert c.get('/api/status').json()['model_ready']
        assert c.get('/api/status').json()['active_criterion']['id'] == a


def test_reference_files_errors_are_reported_without_discarding_good_images(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        id = criterion(c, '画像の確認')
        one = images(count=1)
        bad = [('files', ('bad.png', b'not an image', 'image/png'))]
        result = upload(c, id, one+one+bad)
        assert len(result['accepted']) == 1 and len(result['errors']) == 2
        assert result['count'] == 1 and not result['ready']
        assert any('登録済み' in row['reason'] for row in result['errors'])
        assert any('読み込めません' in row['reason'] for row in result['errors'])
        gallery = c.get(f'/api/criteria/{id}/references').json()
        reference = gallery['images'][0]
        assert reference['source'] == 'upload' and reference['original_name'] == 'red24-100.jpg'
        assert c.get('/api/images/'+reference['image']).content.startswith(b'\xff\xd8')
        assert c.get('/api/history').json() == []
        assert c.post('/api/inspect', json={}).json()['verdict'] == 'REVIEW'


def test_wrong_criterion_and_excessive_file_count_are_rejected(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        a = criterion(c, 'A'); b = criterion(c, 'B')
        assert c.post(f'/api/criteria/{a}/references', files=images(count=1)).status_code == 409
        assert c.post(f'/api/criteria/{b}/references', files=images(count=21)).status_code == 422
        assert c.post('/api/criteria/select', json={'id': 'missing'}).status_code == 404
        assert c.get('/api/criteria/missing/references').status_code == 404
        assert c.get(f'/api/criteria/{a}/references').json()['count'] == 0
        lock = c.app.state.inspector.lock
        with lock:
            assert c.post(f'/api/criteria/{b}/references', files=images(count=1)).status_code == 409
            assert c.post('/api/criteria/select', json={'id': a}).status_code == 409


def test_selection_and_ai_survive_restart_and_history_keeps_original_criterion_name(tmp_path):
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        id = criterion(c, '基準A'); upload(c, id)
        record = c.post('/api/inspect', json={}).json()
        settings = c.get('/api/status').json()['settings']
        settings['normal_name'] = '名称変更後'
        c.post('/api/settings', json=settings)
        model_id = c.get('/api/status').json()['model_id']
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        status = c.get('/api/status').json()
        assert status['active_criterion'] == {'id': id, 'name': '名称変更後'}
        assert status['normal_count'] == 8 and status['model_id'] == model_id
        assert c.get('/api/history').json()[0]['criterion_name'] == '基準A'
        row = next(csv.DictReader(io.StringIO(c.get('/api/export.csv').text.lstrip('\ufeff'))))
        assert row['criterion_id'] == id and row['criterion_name'] == '基準A'
        assert row['image'] == record['image']


def test_legacy_references_migrate_without_losing_images_or_history(tmp_path):
    store = Store(tmp_path, 'demo'); settings = Settings(normal_name='以前の正常品')
    store.set_meta('settings', settings.model_dump())
    hashes = []
    for seed in range(8):
        frame = demo_image('red24', seed)
        features, measures, issues = extract(frame, settings)
        assert not issues
        reference = store.add_ref(settings.profile(), encode(frame), features, measures)
        hashes.append(reference['sha256'])
    old = store.add_result({'verdict': 'OK', 'settings': settings.model_dump()}, encode(frame))
    store.close()
    before_images = sorted((tmp_path/'images').iterdir())
    with TestClient(create_app(DemoProvider(), tmp_path), headers=HEADERS) as c:
        criteria = c.get('/api/criteria').json()
        assert len(criteria) == 1 and criteria[0]['count'] == 8
        assert c.get('/api/status').json()['active_criterion']['name'] == '以前の正常品'
        assert c.get('/api/status').json()['model_ready']
        inspector = c.app.state.inspector
        assert [r['sha256'] for r in inspector.model.references] == hashes
        assert c.get('/api/history').json()[0]['id'] == old['id']
    assert sorted((tmp_path/'images').iterdir()) == before_images


def test_import_is_available_without_a_robot_camera(tmp_path):
    class NoCamera(DemoProvider):
        mode = 'robot'
        def frame(self, fresh=False):
            raise RuntimeError('camera offline')
        def motion(self, *args):
            raise RuntimeError('robot offline')
        def health(self):
            raise RuntimeError('robot offline')
    with TestClient(create_app(NoCamera(), tmp_path), headers=HEADERS) as c:
        id = criterion(c, '事前準備')
        assert upload(c, id)['ready']
        assert not c.get('/api/status').json()['robot']['connected']
        assert c.post('/api/inspect', json={}).status_code == 503
        assert c.get('/api/history').json() == []


def test_reference_normalization_honors_exif_and_removes_metadata():
    image = Image.new('RGB', (96, 160), 'red')
    exif = Image.Exif(); exif[274] = 6; exif[315] = 'private metadata'
    source = io.BytesIO(); image.save(source, 'JPEG', exif=exif)
    output = Image.open(io.BytesIO(normalize_reference(source.getvalue())))
    assert output.size == (160, 96)
    assert not output.getexif()


@pytest.mark.parametrize('data', [b'', b'x'*(10*1024*1024+1)])
def test_empty_and_oversized_reference_are_rejected(data):
    with pytest.raises(ValueError):
        normalize_reference(data)
