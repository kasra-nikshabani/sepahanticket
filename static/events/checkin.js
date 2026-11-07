(() => {
  const root = document.querySelector('[data-checkin]');
  if (!root) return;

  const form = root.querySelector('[data-ticket-form]');
  const input = form.elements.ticket_code;
  const result = root.querySelector('[data-result]');
  const confirmButton = root.querySelector('[data-confirm]');
  const details = root.querySelector('[data-ticket-details]');
  const video = root.querySelector('[data-camera]');
  const placeholder = root.querySelector('[data-camera-placeholder]');
  const startButton = root.querySelector('[data-camera-start]');
  const stopButton = root.querySelector('[data-camera-stop]');
  const cameraHelp = root.querySelector('[data-camera-help]');
  const sessionSelect = document.querySelector('#checkin-session-select');
  const checkinMap = document.querySelector('[data-checkin-map]');
  const mapFeedback = checkinMap?.querySelector('[data-map-feedback]');
  let stream = null;
  let frame = 0;
  let detector = null;
  let busy = false;
  let verifiedCode = '';

  const text = (selector, value) => {
    const el = root.querySelector(selector);
    if (el) el.textContent = value || '—';
  };

  function stopCamera() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    placeholder.hidden = false;
    startButton.hidden = false;
    stopButton.hidden = true;
  }

  function renderResponse(data) {
    result.hidden = false;
    result.dataset.state = data.status || 'invalid';
    confirmButton.hidden = data.status !== 'valid';
    details.hidden = !data.ticket_number;
    root.querySelector('[data-result-title]').textContent = ({
      valid: 'بلیط معتبر است',
      checked_in: 'ورود ثبت شد',
      used: 'این بلیط قبلاً استفاده شده',
      invalid: 'بلیط معتبر نیست',
    })[data.status] || 'بررسی بلیط';
    text('[data-result-message]', data.message);
    text('[data-ticket-holder]', data.holder);
    text('[data-ticket-number]', data.ticket_number);
    text('[data-ticket-seat]', data.seat);
    text('[data-ticket-used-at]', data.used_at);
    root.querySelector('[data-used-row]').hidden = !data.used_at;
    const icon = root.querySelector('[data-result-icon] i');
    icon.className = data.status === 'valid' || data.status === 'checked_in'
      ? 'fa-solid fa-circle-check'
      : data.status === 'used' ? 'fa-solid fa-circle-exclamation' : 'fa-solid fa-circle-xmark';
    if (checkinMap && data.map_seat_id) {
      checkinMap.querySelectorAll('[data-checkin-seat].is-current-ticket').forEach(seat => {
        seat.classList.remove('is-current-ticket');
        seat.removeAttribute('aria-current');
      });
      const seat = checkinMap.querySelector(`[data-checkin-seat][data-seat-id="${CSS.escape(String(data.map_seat_id))}"]`);
      if (seat) {
        seat.classList.add('is-current-ticket');
        seat.setAttribute('aria-current', 'true');
        if (data.status === 'checked_in' || data.status === 'used') seat.classList.add('checkin-seat-used');
        mapFeedback.textContent = `${data.status === 'checked_in' || data.status === 'used' ? 'ورود ثبت‌شده' : 'بلیط بررسی‌شده'}: ${seat.dataset.seatLabel}`;
        seat.scrollIntoView({behavior: 'smooth', block: 'nearest', inline: 'center'});
      } else {
        mapFeedback.textContent = 'این بلیط صندلی شماره‌دار ندارد؛ نقشه فقط برای سانس‌های صندلی‌دار نمایش داده می‌شود.';
      }
    } else if (checkinMap && data.status === 'valid') {
      mapFeedback.textContent = 'این بلیط معتبر است، اما صندلی شماره‌دار ندارد.';
    }
  }

  async function submitCode(action, code) {
    if (busy) return;
    if (!code.trim()) {
      input.focus();
      input.setCustomValidity('شمارهٔ بلیط را وارد کن.');
      input.reportValidity();
      input.setCustomValidity('');
      return;
    }
    busy = true;
    confirmButton.disabled = true;
    try {
      const body = new URLSearchParams(new FormData(form));
      body.set('ticket_code', code.trim());
      body.set('action', action);
      const response = await fetch(root.dataset.endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        body,
      });
      const data = await response.json();
      renderResponse(data);
      if (data.status === 'valid') verifiedCode = code.trim();
      else verifiedCode = '';
      if (data.status === 'checked_in' || data.status === 'used') stopCamera();
    } catch (error) {
      renderResponse({status: 'invalid', message: 'ارتباط با سامانه برقرار نشد. دوباره تلاش کن.'});
      verifiedCode = '';
    } finally {
      busy = false;
      confirmButton.disabled = false;
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    verifiedCode = '';
    submitCode('verify', input.value);
  });
  input.addEventListener('input', () => {
    verifiedCode = '';
    confirmButton.hidden = true;
    result.hidden = true;
    checkinMap?.querySelectorAll('.is-current-ticket').forEach(seat => {
      seat.classList.remove('is-current-ticket');
      seat.removeAttribute('aria-current');
    });
    if (mapFeedback) mapFeedback.textContent = 'پس از اسکن، صندلی مربوط به بلیط روی نقشه برجسته می‌شود.';
  });
  confirmButton.addEventListener('click', () => {
    if (verifiedCode) submitCode('check_in', verifiedCode);
  });

  async function scanFrame() {
    if (!stream || busy || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      if (stream) frame = requestAnimationFrame(scanFrame);
      return;
    }
    try {
      const codes = await detector.detect(video);
      if (codes.length && codes[0].rawValue) {
        const code = codes[0].rawValue;
        input.value = code;
        stopCamera();
        submitCode('verify', code);
        return;
      }
    } catch (_) {
      // A frame may be undecodable while the camera is moving; keep scanning.
    }
    if (stream) frame = requestAnimationFrame(scanFrame);
  }

  startButton.addEventListener('click', async () => {
    if (!('BarcodeDetector' in window)) {
      cameraHelp.textContent = 'مرورگرت اسکن مستقیم QR را پشتیبانی نمی‌کند؛ شمارهٔ بلیط را در کادر پایین وارد کن.';
      cameraHelp.dataset.state = 'notice';
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraHelp.textContent = 'دسترسی دوربین در این مرورگر ممکن نیست. شمارهٔ بلیط را دستی وارد کن.';
      return;
    }
    try {
      detector = new BarcodeDetector({formats: ['qr_code']});
      stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}}, audio: false});
      video.srcObject = stream;
      video.hidden = false;
      placeholder.hidden = true;
      startButton.hidden = true;
      stopButton.hidden = false;
      await video.play();
      cameraHelp.textContent = 'QR را داخل قاب دوربین نگه دار؛ پس از بررسی می‌توانی ورود را تأیید کنی.';
      frame = requestAnimationFrame(scanFrame);
    } catch (error) {
      stopCamera();
      cameraHelp.textContent = error.name === 'NotAllowedError'
        ? 'دسترسی دوربین داده نشد. مجوز دوربین را در مرورگر فعال کن یا شمارهٔ بلیط را دستی وارد کن.'
        : 'دوربین در دسترس نیست؛ شمارهٔ بلیط را دستی وارد کن.';
    }
  });
  stopButton.addEventListener('click', stopCamera);
  window.addEventListener('pagehide', stopCamera);
  sessionSelect?.addEventListener('change', () => { window.location.assign(sessionSelect.value); });
})();
