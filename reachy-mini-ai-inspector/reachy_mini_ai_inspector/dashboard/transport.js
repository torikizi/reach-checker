(function (root, factory) {
  const transport = factory();
  if (typeof module === 'object' && module.exports) module.exports = transport;
  else root.InspectorTransport = transport;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  async function request(url, options = {}, settings = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const timeoutMs = settings.timeoutMs ?? (method === 'GET' || method === 'HEAD' ? 8000 : 40000);
    const fetchImpl = settings.fetchImpl || globalThis.fetch;
    const read = settings.read || (response => response.text());
    const controller = new AbortController();
    const message = settings.timeoutMessage || (method === 'GET' || method === 'HEAD'
      ? '通信がタイムアウトしました。接続状態を確認してください。'
      : '操作の応答がタイムアウトしました。履歴と状態を確認してから再操作してください。');
    let timer, timedOut = false;
    // The single deadline includes receiving the response body. Aborting fetch
    // alone is insufficient when a browser or a reader ignores its signal.
    const operation = Promise.resolve()
      .then(() => fetchImpl(url, {...options, signal: controller.signal}))
      .then(async response => ({response, body: await read(response)}));
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        timedOut = true;
        reject(new Error(message));
        controller.abort();
      }, timeoutMs);
    });
    try { return await Promise.race([operation, deadline]); }
    catch (error) { if (timedOut) throw new Error(message); throw error; }
    finally { clearTimeout(timer); }
  }

  async function decodeImage(url, settings = {}) {
    const ImageImpl = settings.ImageImpl || globalThis.Image;
    const image = new ImageImpl();
    const timeoutMs = settings.timeoutMs ?? 2000;
    let timer, decoded = false;
    const ready = new Promise((resolve, reject) => {
      const failed = () => reject(new Error('取得した画像を表示できません。再取得します。'));
      const canDecode = typeof image.decode === 'function';
      if (!canDecode) image.onload = resolve;
      image.onerror = failed;
      image.src = url;
      if (canDecode) image.decode().then(resolve, failed);
    });
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('映像の読み込みがタイムアウトしました。再取得します。')), timeoutMs);
    });
    try {
      await Promise.race([ready, deadline]);
      if (!image.naturalWidth || !image.naturalHeight) throw new Error('取得した画像を表示できません。再取得します。');
      decoded = true;
      return image;
    } finally {
      clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      if (!decoded) image.src = '';
    }
  }

  return {request, decodeImage};
});
