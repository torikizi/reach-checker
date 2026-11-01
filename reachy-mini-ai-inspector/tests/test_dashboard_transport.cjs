const test = require('node:test');
const assert = require('node:assert/strict');
const {setTimeout: delay} = require('node:timers/promises');
const {request, decodeImage} = require('../reachy_mini_ai_inspector/dashboard/transport.js');

const never = () => new Promise(() => {});

test('a fetch that ignores abort still reaches its deadline and is aborted', {timeout:1000}, async () => {
  let signal;
  const pending = request('/status', {}, {
    timeoutMs:20,
    fetchImpl: (_url, options) => { signal = options.signal; return never(); }
  });
  await assert.rejects(pending, /通信がタイムアウト/);
  assert.equal(signal.aborted, true);
});

test('the same deadline covers a body reader that never resolves', {timeout:1000}, async () => {
  let signal, reading = false;
  const pending = request('/frame', {}, {
    timeoutMs:20,
    fetchImpl: async (_url, options) => {
      signal = options.signal;
      return {blob: () => { reading = true; return never(); }};
    },
    read: response => response.blob(),
    timeoutMessage:'映像の受信がタイムアウトしました。'
  });
  await assert.rejects(pending, /映像の受信がタイムアウト/);
  assert.equal(reading, true);
  assert.equal(signal.aborted, true);
});

test('a successful read clears the deadline without a later abort', async () => {
  let signal;
  const response = {ok:true, text: async () => 'complete'};
  const result = await request('/status', {}, {
    timeoutMs:20,
    fetchImpl: async (_url, options) => { signal = options.signal; return response; }
  });
  assert.equal(result.response, response);
  assert.equal(result.body, 'complete');
  await delay(40);
  assert.equal(signal.aborted, false);
});

test('a reader failure is preserved and clears its deadline', async () => {
  let signal;
  const failure = new Error('body failed');
  await assert.rejects(request('/status', {}, {
    timeoutMs:20,
    fetchImpl: async (_url, options) => {
      signal = options.signal;
      return {text: async () => { throw failure; }};
    }
  }), error => error === failure);
  await delay(40);
  assert.equal(signal.aborted, false);
});

test('a fetch failure clears its deadline without masking the original failure', async () => {
  let signal;
  const failure = new Error('offline');
  await assert.rejects(request('/status', {}, {
    timeoutMs:20,
    fetchImpl: async (_url, options) => { signal = options.signal; throw failure; }
  }), error => error === failure);
  await delay(40);
  assert.equal(signal.aborted, false);
});

test('an early image load event cannot bypass a stalled decoder', {timeout:1000}, async () => {
  let image;
  class StalledImage {
    constructor() { image = this; this.naturalWidth = 960; this.naturalHeight = 540; }
    set src(value) { this.url = value; if (value) queueMicrotask(() => this.onload?.()); }
    decode() { return never(); }
  }
  await assert.rejects(decodeImage('blob:next', {ImageImpl:StalledImage, timeoutMs:20}), /映像の読み込みがタイムアウト/);
  assert.equal(image.url, '');
  assert.equal(image.onload, null);
  assert.equal(image.onerror, null);
});

test('a decoded image is returned intact and its timer is cleared', async () => {
  class ReadyImage {
    constructor() { this.naturalWidth = 960; this.naturalHeight = 540; }
    decode() { return Promise.resolve(); }
  }
  const image = await decodeImage('blob:good', {ImageImpl:ReadyImage, timeoutMs:20});
  await delay(40);
  assert.equal(image.src, 'blob:good');
  assert.equal(image.naturalWidth, 960);
});

test('zero-size images are rejected before a preview can be replaced', async () => {
  let image;
  class EmptyImage {
    constructor() { image = this; this.naturalWidth = 0; this.naturalHeight = 0; }
    decode() { return Promise.resolve(); }
  }
  await assert.rejects(decodeImage('blob:empty', {ImageImpl:EmptyImage, timeoutMs:20}), /取得した画像を表示できません/);
  assert.equal(image.src, '');
});
