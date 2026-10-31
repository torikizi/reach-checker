const $ = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
let offset = 0, busy = false, currentStatus = null, frameURL = null, noticeTimer;
let settingsKey = null, referenceKey = null, shownResult = null, statusLoading = false;

$('camera').onload = () => {
  if ($('camera').naturalWidth) $('view').style.aspectRatio = `${$('camera').naturalWidth}/${$('camera').naturalHeight}`;
};

async function api(path, data) {
  const form = data instanceof FormData;
  const headers = {'X-Inspector-UI': '1'};
  if (data !== undefined && !form) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST', headers,
    body: data === undefined ? undefined : form ? data : JSON.stringify(data)
  });
  const text = await response.text();
  let value;
  try { value = JSON.parse(text); } catch { value = {detail: text}; }
  if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '入力内容を確認してください。');
  return value;
}

function notice(text, error = false) {
  clearTimeout(noticeTimer);
  $('notice').textContent = text;
  $('notice').className = error ? 'error' : '';
  $('notice').style.display = 'block';
  noticeTimer = setTimeout(() => { $('notice').style.display = 'none'; }, 10000);
}

function controls() {
  const s = currentStatus, locked = busy || Boolean(s?.busy), selected = Boolean(s?.active_criterion);
  const camera = Boolean(s?.robot.camera_ready), positioned = s?.robot.pose_valid !== false;
  for (const id of ['create-criterion-button','criterion-name','criterion-select','sound','sound-test','sound-verdict','remember-position','return-position','motion','scene']) $(id).disabled = locked;
  $('reference-files').disabled = locked || !selected;
  $('upload-references').disabled = locked || !selected || !$('reference-files').files.length;
  $('register').disabled = locked || !selected || !camera || !positioned;
  $('inspect').disabled = locked || !selected || !s?.model_ready || !camera || !positioned;
  $('snapshot').disabled = locked || !camera;
  $('demo-train').disabled = locked || !selected;
  for (const field of $('settings').elements) field.disabled = locked || !selected;
}

async function action(fn) {
  if (busy) return;
  busy = true; controls();
  try { await fn(); } catch (e) { notice(e.message, true); }
  finally { busy = false; await status(); controls(); }
}

function renderROI(roi) {
  Object.assign($('roi').style, {left:`${roi.x*100}%`, top:`${roi.y*100}%`, width:`${roi.width*100}%`, height:`${roi.height*100}%`});
}
function fillSettings(settings) {
  const form = $('settings');
  for (const [key,value] of Object.entries(settings)) {
    if (key === 'roi') for (const [name,number] of Object.entries(value)) form.elements['roi_'+name].value = number;
    else if (form.elements[key]) form.elements[key].value = value;
  }
  renderROI(settings.roi);
}
function pendingResult(s) {
  if (shownResult?.criterion_id === s.active_criterion?.id && shownResult?.model_id === s.model_id) return;
  shownResult = null;
  $('verdict').className = 'verdict waiting';
  $('verdict').replaceChildren(document.createTextNode('READY'), el('span','','検査待ち'));
  $('score').textContent = '—'; $('score-bar').style.width = '0';
  $('reason').textContent = !s.active_criterion ? '検査基準を作成または選択してください。'
    : !s.model_ready ? `異なる正解画像をあと${Math.max(0,s.minimum_references-s.normal_count)}枚登録してください。`
    : '対象を検査範囲に置き、「検査を開始」を押してください。';
  $('result-meta').textContent = s.active_criterion ? `検査基準：${s.active_criterion.name}` : '検査基準：未選択';
}
async function criteriaList() {
  const rows = await api('/api/criteria');
  const select = $('criterion-select');
  select.replaceChildren(Object.assign(el('option','','検査基準を選択してください'), {value:'',disabled:true}));
  for (const row of rows) select.append(Object.assign(el('option','',`${row.name}（正解画像${row.count}枚）`), {value:row.id}));
  select.value = currentStatus?.active_criterion?.id || '';
}
async function references() {
  const list = $('reference-list'); list.replaceChildren();
  const id = currentStatus?.active_criterion?.id;
  if (!id) { list.append(el('p','empty','検査基準を選ぶと、登録した正解画像を表示します。')); return; }
  const data = await api(`/api/criteria/${encodeURIComponent(id)}/references`);
  if (!data.images.length) list.append(el('p','empty','正解画像はまだ登録されていません。'));
  for (const reference of data.images) {
    const figure = el('figure','reference-image'), link = el('a');
    link.href = '/api/images/'+encodeURIComponent(reference.image); link.target = '_blank'; link.rel = 'noopener';
    const image = el('img'); image.src = link.href; image.loading = 'lazy';
    const label = reference.original_name || (reference.source === 'demo' ? 'デモ画像' : 'カメラ画像');
    image.alt = `${currentStatus.active_criterion.name}の正解画像：${label}`;
    link.append(image); figure.append(link, el('figcaption','',label)); list.append(figure);
  }
}
async function status() {
  if (statusLoading) return;
  statusLoading = true;
  try {
    const s = await api('/api/status'); currentStatus = s;
    const demo = s.mode === 'demo', selected = s.active_criterion;
    $('demo-panel').hidden = !demo;
    if (demo && s.robot.scene) $('scene').value = s.robot.scene;
    $('mode-banner').textContent = demo ? 'デモモード：合成画像で操作を確認できます。' : '実機モード：Reachyのカメラ映像を使い、MacでAI判定します。';
    $('mode-banner').className = 'banner '+(demo ? '' : 'real');
    $('connection').textContent = s.robot.connected ? (demo ? '● デモ接続済み' : '● Reachy 接続済み') : '● Reachy 未接続';
    $('connection').className = 'connection '+(s.robot.connected ? 'online' : '');
    $('source-label').textContent = demo ? 'デモ用の合成画像' : 'Reachy Mini Wireless カメラ';
    $('camera-label').textContent = demo ? 'デモ画像' : 'ライブ映像';
    $('normal-count').replaceChildren(document.createTextNode(s.normal_count+' '), el('small','',`/ ${s.minimum_references}枚以上`));
    $('criterion-summary').textContent = !selected ? '検査基準を作成してください' : `${selected.name}：正解画像${s.normal_count}枚`;
    $('inspection-criterion').textContent = selected ? `検査基準：${selected.name}` : '検査基準：未選択';
    $('normal-copy').textContent = !selected ? '検査基準を作成または選択してから、正解画像を登録してください。'
      : s.model_ready ? 'AIの学習が完了しました。この基準で検査できます。'
      : `AIの学習には、異なる正解画像が${s.minimum_references}枚以上必要です。`;
    $('model-label').textContent = !selected ? '検査基準が必要です' : s.model_ready ? 'AI学習済み' : '正解画像が不足しています';
    $('sound').checked = s.sound_enabled; $('sound-state').textContent = s.sound_enabled ? 'ON' : 'OFF';
    $('motion').checked = s.robot.motion_enabled; $('motion-state').textContent = s.robot.motion_enabled ? '有効' : '無効';
    $('position-state').textContent = s.robot.position_saved ? (s.robot.pose_valid ? '撮影位置：記憶済み' : '撮影位置：復帰が必要です') : '撮影位置：未記憶';
    $('position-state').className = s.robot.position_saved && !s.robot.pose_valid ? 'danger' : '';
    const key = selected?.id || '';
    if (settingsKey !== key) {
      fillSettings(s.settings); settingsKey = key; shownResult = null;
      $('reference-files').value = ''; $('upload-results').replaceChildren();
    }
    const nextKey = JSON.stringify([key,selected?.name,s.normal_count,s.settings.roi]);
    if (referenceKey !== nextKey) { await criteriaList(); await references(); referenceKey = nextKey; }
    pendingResult(s); controls();
  } catch (e) {
    $('connection').textContent = '● 検品サーバーに接続できません'; $('connection').className = 'connection';
    $('camera-error').textContent = 'Macの検品サーバーを起動してください。'; $('camera-error').style.display = 'grid';
  } finally { statusLoading = false; }
}
async function frameLoop() {
  try {
    const response = await fetch('/api/frame',{cache:'no-store'});
    if (!response.ok) throw Error(currentStatus?.robot.moving ? '動作中です。撮影位置への復帰後に映像を更新します。' : '映像を取得できません。Reachyの接続とアプリの起動を確認してください。');
    const next = URL.createObjectURL(await response.blob()); $('camera').src = next;
    if (frameURL) URL.revokeObjectURL(frameURL); frameURL = next; $('camera-error').style.display = 'none';
  } catch (e) { $('camera-error').textContent = e.message; $('camera-error').style.display = 'grid'; }
  finally { setTimeout(frameLoop,300); }
}
function result(record) {
  shownResult = record; $('verdict').className = 'verdict '+record.verdict;
  $('verdict').replaceChildren(document.createTextNode(record.verdict), el('span','',{OK:'基準内',NG:'基準外',REVIEW:'判定保留'}[record.verdict]));
  $('score').textContent = record.ai_score === null ? '—' : record.ai_score.toFixed(3);
  $('score-bar').style.width = (record.ai_score || 0)*100+'%';
  $('score-bar').style.background = {OK:'var(--green)',NG:'var(--red)',REVIEW:'var(--amber)'}[record.verdict];
  $('reason').textContent = record.reasons.join(' / ');
  $('result-meta').textContent = `${record.criterion_name} · #${record.id} · ${record.ai_executed?'AI判定済み':'AI未判定'} · ${record.motion.reason} · ${record.sound?.reason||'判定音の記録なし'}`;
}
$('create-criterion').onsubmit = event => {
  event.preventDefault(); action(async () => {
    const name = $('criterion-name').value.trim(); if (!name) throw Error('検査基準名を入力してください。');
    await api('/api/criteria',{name}); $('criterion-name').value = ''; referenceKey = null;
    notice(`検査基準「${name}」を作成しました。正解画像を登録してください。`);
  });
};
$('criterion-select').onchange = () => action(async () => {
  const id = $('criterion-select').value; if (!id) { $('criterion-select').value = currentStatus?.active_criterion?.id || ''; return; }
  const selected = await api('/api/criteria/select',{id}); referenceKey = null;
  notice(`検査基準「${selected.name}」を選択しました。`);
});
$('reference-files').onchange = controls;
$('upload-form').onsubmit = event => {
  event.preventDefault(); action(async () => {
    const files = [...$('reference-files').files];
    if (!files.length) throw Error('読み込む正解画像を選択してください。');
    if (files.length > 20) throw Error('1回に読み込める画像は20枚までです。');
    if (files.some(file => file.size > 10*1024*1024)) throw Error('画像は1枚10MB以下にしてください。');
    if (files.reduce((sum,file)=>sum+file.size,0) > 50*1024*1024) throw Error('画像の合計を50MB以下にしてください。');
    const form = new FormData(); for (const file of files) form.append('files',file);
    const response = await api(`/api/criteria/${currentStatus.active_criterion.id}/references`,form);
    $('upload-results').replaceChildren();
    for (const error of response.errors) $('upload-results').append(el('li','error',`${error.name}：${error.reason}`));
    $('reference-files').value = ''; referenceKey = null; shownResult = null;
    notice(`${response.accepted.length}枚を登録しました。${response.errors.length ? response.errors.length+'枚は登録できませんでした。' : ''}`,response.accepted.length === 0);
  });
};
$('register').onclick = () => action(async () => {
  const r = await api('/api/normal',{}); referenceKey = null; shownResult = null;
  notice(`カメラ画像を登録しました。正解画像は${r.count}枚です。`);
});
$('inspect').onclick = () => action(async () => {
  const record = await api('/api/inspect',{identifier:$('identifier').value}); result(record); offset = 0;
  await history(); notice(`検査結果を保存しました。判定：${record.verdict}`);
});
$('snapshot').onclick = () => action(async () => {
  const r = await api('/api/snapshot',{}), a = document.createElement('a');
  a.href = '/api/images/'+encodeURIComponent(r.image); a.download = r.image; a.click(); notice('静止画を保存しました。');
});
$('demo-train').onclick = () => action(async () => {
  const r = await api('/api/demo/train',{}); referenceKey = null; shownResult = null; notice(`合成画像を登録しました。正解画像は${r.count}枚です。`);
});
$('scene').onchange = () => action(()=>api('/api/demo/scene',{scene:$('scene').value}));
$('sound').onchange = () => action(async () => {
  const enabled = $('sound').checked; await api('/api/sound',{enabled}); notice(enabled?'判定音を有効にしました。':'判定音を無効にしました。');
});
$('sound-test').onclick = () => action(async () => {
  const r = await api('/api/sound/test',{verdict:$('sound-verdict').value}); notice(r.reason,!r.performed && currentStatus?.mode==='robot' && currentStatus?.sound_enabled);
});
$('motion').onchange = () => {
  const enabled = $('motion').checked;
  if (enabled && !confirm('Reachyが撮影位置へ動きます。頭部とアンテナの周囲に障害物がないことを確認しましたか？')) { $('motion').checked = false; return; }
  action(async () => { await api('/api/motion',{enabled,physically_checked:enabled}); notice(enabled?'判定時の動作を有効にしました。':'判定時の動作を無効にしました。'); });
};
$('stop-motion').onclick = async () => {
  try { await api('/api/motion',{enabled:false}); notice('判定時の動作を無効にしました。実行中の短い動作が終わると停止します。'); await status(); }
  catch (e) { notice(e.message,true); }
};
$('remember-position').onclick = () => {
  if (!confirm('現在の撮影位置を記憶します。正解画像と同じ画角になっていますか？')) return;
  action(async () => { const r = await api('/api/position/remember',{}); notice(r.reason); });
};
$('return-position').onclick = () => {
  if (!confirm('記憶した撮影位置へReachyが動きます。頭部とアンテナの周囲に障害物がないことを確認しましたか？')) return;
  action(async () => { const r = await api('/api/position/return',{physically_checked:true}); notice(r.reason,!r.returned && currentStatus?.mode==='robot'); });
};
$('settings').onsubmit = event => {
  event.preventDefault();
  const data = new FormData(event.target);
  action(async () => {
    const body = {roi:{}};
    for (const [key,value] of data) {
      if (key.startsWith('roi_')) body.roi[key.slice(4)] = Number(value);
      else body[key] = key === 'normal_name' ? value : Number(value);
    }
    const settings = await api('/api/settings',body); fillSettings(settings); referenceKey = null; shownResult = null;
    notice('選択中の検査基準の設定を保存しました。');
  });
};
for (const key of ['x','y','width','height']) $('settings').elements['roi_'+key].oninput = () => {
  const roi = {}; for (const name of ['x','y','width','height']) roi[name] = Number($('settings').elements['roi_'+name].value); renderROI(roi);
};
async function history() {
  const [rows,metrics] = await Promise.all([api('/api/history?offset='+offset),api('/api/metrics')]);
  $('history-list').replaceChildren();
  if (!rows.length) $('history-list').append(el('p','empty','検査履歴はありません。'));
  for (const record of rows) {
    const row = el('article','history-row'), link = el('a');
    link.href = '/api/images/'+encodeURIComponent(record.image); link.target = '_blank'; link.rel = 'noopener';
    const image = el('img'); image.src = link.href; image.alt = `${record.identifier||record.id}の検査画像`; link.append(image);
    const identity = el('div','identity');
    identity.append(el('b','',record.identifier||'識別名なし'),el('small','',record.criterion_name||record.settings?.normal_name||'以前の検査基準'),el('small','',new Date(record.created_at).toLocaleString('ja-JP')),el('small','','#'+record.id));
    const score = el('div'); score.append(el('span','pill '+record.verdict,record.verdict),el('small','',record.ai_score===null?'AI未判定':'AI '+record.ai_score.toFixed(3)));
    const editor = el('div','label-controls'), select = el('select'); select.setAttribute('aria-label',`${record.identifier||record.id}の実際の状態`);
    for (const [value,label] of [['','未評価'],['OK','実際はOK'],['NG','実際はNG']]) select.append(Object.assign(el('option','',label),{value,selected:(record.truth||'')===value}));
    const condition = el('input'); condition.placeholder = '照明や配置など'; condition.maxLength = 120; condition.value = record.condition; condition.setAttribute('aria-label','撮影条件');
    const save = el('button','','評価を保存'); save.onclick = () => action(async () => {
      await api(`/api/history/${record.id}/label`,{truth:select.value||null,condition:condition.value}); await history(); notice('評価を保存しました。');
    });
    editor.append(select,condition,save); row.append(link,identity,score,el('p','',record.reasons.join(' / ')),editor); $('history-list').append(row);
  }
  const pct = value => value === null ? '—' : (value*100).toFixed(1)+'%'; $('metrics').replaceChildren();
  for (const [label,value] of [['評価済み',metrics.labeled+'件'],['正解率',pct(metrics.accuracy)],['正常検出率',pct(metrics.normal_recall)],['異常検出率',pct(metrics.defect_recall)],['見逃し／判定保留',metrics.missed_defects+'／'+metrics.reviews]]) {
    const metric = el('div','metric'); metric.append(el('span','',label),el('b','',value)); $('metrics').append(metric);
  }
  $('page-number').textContent = Math.floor(offset/30)+1; $('prev').disabled = offset===0; $('next').disabled = rows.length<30;
}
$('prev').onclick = () => { offset = Math.max(0,offset-30); history().catch(e=>notice(e.message,true)); };
$('next').onclick = () => { offset += 30; history().catch(e=>notice(e.message,true)); };
controls(); status(); history().catch(e=>notice(e.message,true)); frameLoop(); setInterval(status,3000);
