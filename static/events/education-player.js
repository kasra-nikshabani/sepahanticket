(() => {
  'use strict';
  const root = document.querySelector('[data-edu-player]');
  if (!root) return;
  const video = root.querySelector('video');
  const overlay = root.querySelector('.edu-player-overlay');
  const status = root.querySelector('[data-player-status]');
  const start = root.querySelector('[data-start-playback]');
  const csrf = document.querySelector('[data-player-csrf] [name="csrfmiddlewaretoken"]')?.value;
  let hls, renewTimer, saveTimer, manifest, authorizing, started = false, recovering = false, resumeApplied = false;
  const resume = Number(root.dataset.position) || 0;
  function showError(message) {
    video.pause();
    overlay.hidden = false;
    start.disabled = false;
    start.textContent = 'تلاش دوباره';
    status.textContent = message;
  }
  async function authorize() {
    if (authorizing) return authorizing;
    authorizing = (async () => {
      const response = await fetch(root.dataset.authorize, {
        method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf, 'Accept': 'application/json'}
      });
      if (!response.ok || response.redirected) throw new Error('access');
      const data = await response.json();
      if (!data.manifest || !data.manifest.startsWith('/learn/stream/')) throw new Error('access');
      clearTimeout(renewTimer);
      renewTimer = setTimeout(() => {
        if (!video.paused) authorize().catch(() => showError('دسترسی پخش برقرار نشد؛ حساب یا ثبت‌نام خود را بررسی کنید.'));
      }, Math.max(15000, (data.expires_in || 180) * 500));
      return data.manifest;
    })();
    try { return await authorizing; } finally { authorizing = null; }
  }
  async function setup() {
    start.disabled = true;
    status.textContent = 'در حال آماده کردن پخش…';
    try {
      const nextManifest = await authorize();
      // A fresh instance also recovers a native HLS or a fatal MediaSource error.
      {
        if (hls) hls.destroy();
        manifest = nextManifest;
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = manifest;
        } else if (window.Hls && Hls.isSupported()) {
          hls = new Hls({maxBufferLength: 30, xhrSetup: xhr => { xhr.withCredentials = true; }});
          hls.on(Hls.Events.ERROR, async (_, data) => {
            if (!data.fatal || recovering) return;
            recovering = true;
            try {
              const freshManifest = await authorize();
              if (freshManifest !== manifest) {
                manifest = freshManifest;
                hls.loadSource(manifest);
                hls.startLoad();
              } else if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
              else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
              else showError('پخش این ویدئو در مرورگر شما انجام نشد. صفحه را دوباره باز کنید.');
            } catch (_) {
              showError('دسترسی ویدئو قطع شده است؛ وارد حساب شوید یا از پشتیبانی کمک بگیرید.');
            } finally { setTimeout(() => { recovering = false; }, 3000); }
          });
          hls.loadSource(manifest);
          hls.attachMedia(video);
        } else {
          throw new Error('unsupported');
        }
      }
      overlay.hidden = true;
      await video.play();
      started = true;
    } catch (error) {
      if (error.name === 'NotAllowedError') {
        overlay.hidden = true;
        video.controls = true;
      } else {
        showError(error.message === 'unsupported' ? 'این مرورگر پخش این دوره را پشتیبانی نمی‌کند؛ از نسخهٔ تازهٔ Chrome، Firefox یا Safari استفاده کنید.' : 'پخش برقرار نشد؛ اتصال اینترنت و ورود به حساب را بررسی کنید.');
      }
    } finally { start.disabled = false; }
  }
  async function savePosition() {
    if (!root.dataset.progress || !video.duration || !Number.isFinite(video.currentTime)) return;
    try {
      const response = await fetch(root.dataset.progress, {
        method: 'POST', credentials: 'same-origin', keepalive: true,
        headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({action: 'position', position: String(Math.floor(video.currentTime))})
      });
      if (response.status === 403 || response.status === 404) showError('دسترسی شما به این درس تغییر کرده است؛ از پشتیبانی پیگیری کنید.');
    } catch (_) { /* Resume is best effort; streaming errors have their own feedback. */ }
  }
  video.addEventListener('loadedmetadata', () => {
    if (!resumeApplied && resume > 0 && resume < video.duration - 2) video.currentTime = resume;
    resumeApplied = true;
  });
  video.addEventListener('play', () => {
    overlay.hidden = true;
    authorize().catch(() => showError('دسترسی پخش برقرار نشد؛ دوباره تلاش کنید.'));
    clearInterval(saveTimer);
    saveTimer = setInterval(savePosition, 20000);
  });
  video.addEventListener('pause', () => { clearInterval(saveTimer); savePosition(); });
  video.addEventListener('ended', savePosition);
  video.addEventListener('error', () => { if (!hls) showError('بارگذاری ویدئو انجام نشد؛ اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.'); });
  video.addEventListener('contextmenu', event => event.preventDefault());
  start.addEventListener('click', setup);
  const fullscreen = root.querySelector('[data-player-fullscreen]');
  if (!root.requestFullscreen) fullscreen.hidden = true;
  else fullscreen.addEventListener('click', async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await root.requestFullscreen(); } catch (_) { /* Browser can decline fullscreen. */ }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) savePosition();
    else if (started && !video.paused) authorize().catch(() => showError('برای ادامهٔ تماشا، دسترسی پخش را دوباره فعال کنید.'));
  });
  window.addEventListener('pagehide', () => { savePosition(); clearInterval(saveTimer); clearTimeout(renewTimer); });
})();
