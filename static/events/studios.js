(() => {
  'use strict';
  const format = new Intl.NumberFormat('fa-IR');
  function setupSelection(container) {
  container.querySelectorAll('[data-studio-selection]').forEach(form => {
    const fields = [...form.querySelectorAll('input[name="slots"]')];
    const error = form.querySelector('[data-selection-error]');
    const button = form.querySelector('button[type="submit"]');
    const ownerDisabled = button.disabled;
    function update() {
      const selected = fields.filter(field => field.checked).sort((a,b) => Date.parse(a.dataset.start)-Date.parse(b.dataset.start));
      const total = selected.reduce((sum, field) => sum + Number(field.dataset.price), 0);
      form.querySelector('[data-selected-hours]').textContent = selected.length ? `${format.format(selected.length)} ساعت انتخاب شده` : 'هنوز ساعتی انتخاب نشده';
      form.querySelector('[data-selected-total]').textContent = `${format.format(total)} تومان`;
      const range = form.querySelector('[data-selected-range]');
      if (range) {
        const clock = new Intl.DateTimeFormat('fa-IR', {timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
        const contiguous = selected.every((field, index) => index === 0 || selected[index - 1].dataset.end === field.dataset.start);
        range.textContent = selected.length && contiguous ? `از ساعت ${clock.format(new Date(selected[0].dataset.start))} تا ${clock.format(new Date(selected[selected.length - 1].dataset.end))}` : '';
      }
      let message = '';
      if (selected.length > 12) message = 'حداکثر ۱۲ ساعت در یک رزرو انتخاب کن.';
      else if (selected.some((field,index) => index > 0 && selected[index-1].dataset.end !== field.dataset.start)) message = 'ساعت‌ها باید پشت‌سرهم باشند.';
      error.textContent = message;
      button.disabled = ownerDisabled || !selected.length || !!message;
      return selected.length > 0 && !message;
    }
    fields.forEach(field => field.addEventListener('change', update));
    form.addEventListener('submit', event => { if (!update()) event.preventDefault(); });
    update();
  });
  }
  setupSelection(document);
  let calendar = document.querySelector('[data-ajax-calendar]');
  if (!calendar) return;
  let controller;
  let generation = 0;
  const notice = document.createElement('p');
  notice.className = 'studio-calendar-feedback';
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  calendar.closest('.studio-detail-layout').before(notice);
  async function loadDay(url, push = true) {
    const target = new URL(url, location.href);
    if (target.origin !== location.origin || target.pathname !== location.pathname) return;
    controller?.abort();
    controller = new AbortController();
    const token = ++generation;
    calendar.setAttribute('aria-busy', 'true');
    calendar.inert = true;
    notice.textContent = 'در حال دریافت ساعت‌های روز انتخاب‌شده…';
    try {
      const response = await fetch(target, {headers: {'X-Studio-Calendar': '1'}, credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok || response.redirected) throw new Error('calendar unavailable');
      const html = await response.text();
      if (token !== generation) return;
      const replacement = new DOMParser().parseFromString(html, 'text/html').querySelector('[data-ajax-calendar]');
      if (!replacement) throw new Error('invalid calendar');
      const top = calendar.getBoundingClientRect().top;
      calendar.replaceWith(replacement);
      calendar = replacement;
      setupSelection(calendar);
      if (push) history.pushState(null, '', target);
      window.scrollBy({top: calendar.getBoundingClientRect().top - top, behavior: 'instant'});
      const active = calendar.querySelector('[aria-current="date"]');
      active?.focus({preventScroll: true});
      notice.textContent = 'ساعت‌های روز انتخاب‌شده به‌روز شد؛ انتخاب ساعت را دوباره انجام دهید.';
    } catch (error) {
      if (error.name === 'AbortError' || token !== generation) return;
      notice.replaceChildren(document.createTextNode('دریافت ساعت‌ها ناموفق بود. '));
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'edu-button edu-button-light'; retry.textContent = 'تلاش دوباره';
      retry.addEventListener('click', () => loadDay(target, push)); notice.append(retry);
      // Keep the URL aligned with the still-visible calendar on a failed Back request.
      if (!push) history.replaceState(null, '', displayedURL);
    } finally {
      if (token === generation) { calendar.removeAttribute('aria-busy'); calendar.inert = false; }
    }
    if (token === generation) displayedURL = location.href;
  }
  let displayedURL = location.href;
  document.addEventListener('click', event => {
    const link = event.target.closest('#studio-calendar .studio-date-list a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault(); loadDay(link.href);
  });
  document.addEventListener('submit', event => {
    if (!event.target.matches('#studio-calendar .studio-date-search')) return;
    event.preventDefault();
    const url = new URL(location.href);
    url.searchParams.set('day', new FormData(event.target).get('day'));
    url.hash = 'studio-calendar';
    loadDay(url);
  });
  window.addEventListener('popstate', () => loadDay(location.href, false));
  window.addEventListener('pagehide', () => controller?.abort());
})();
