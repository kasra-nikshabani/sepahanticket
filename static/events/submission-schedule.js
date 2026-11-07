(() => {
  const root = document.querySelector('[data-opening-picker]');
  if (!root) return;
  const form = root.closest('form');
  const input = root.querySelector('[name="opening_sessions"]');
  const days = root.querySelector('[data-opening-days]');
  const status = root.querySelector('[data-opening-status]');
  const names = ['start_date', 'end_date', 'time', 'second_time', 'third_time'];
  const fa = value => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
  let selected;
  try { selected = new Set(JSON.parse(input.value || '[]')); } catch { selected = new Set(); }
  let sessions = [], controller, timer;
  const save = (dirty = true) => {
    input.value = JSON.stringify([...selected].sort());
    if (dirty) input.dispatchEvent(new Event('change', { bubbles: true }));
    status.textContent = `${fa(selected.size)} سانس از ${fa(sessions.length)} سانس برای شروع فروش انتخاب شده است.`;
  };
  const render = () => {
    days.replaceChildren();
    let day, section;
    sessions.forEach(item => {
      if (day !== item.day) {
        day = item.day;
        section = document.createElement('fieldset');
        const legend = document.createElement('legend');
        legend.textContent = fa(item.day_label);
        section.append(legend); days.append(section);
      }
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = selected.has(item.key);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) selected.add(item.key); else selected.delete(item.key);
        save();
      });
      const text = document.createElement('span');
      text.textContent = `ساعت ${fa(item.time)}`;
      label.append(checkbox, text); section.append(label);
    });
  };
  const refresh = async () => {
    if (controller) controller.abort();
    controller = new AbortController();
    const current = controller;
    const params = new URLSearchParams();
    names.forEach(name => params.set(name, form.elements[name]?.value || ''));
    status.textContent = 'در حال آماده‌سازی سانس‌ها…';
    try {
      const response = await fetch(`${root.dataset.optionsUrl}?${params}`, { credentials: 'same-origin', signal: current.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'تاریخ و ساعت‌ها را بررسی کنید.');
      sessions = data.sessions;
      const allowed = new Set(sessions.map(item => item.key));
      const previous = selected.size;
      selected = new Set([...selected].filter(key => allowed.has(key)));
      render(); save(previous !== selected.size);
      if (previous !== selected.size) status.textContent += ' انتخاب‌های خارج از بازه جدید حذف شدند؛ سانس‌ها را بازبینی کنید.';
    } catch (error) {
      if (current.signal.aborted) return;
      sessions = []; days.replaceChildren();
      status.textContent = error instanceof SyntaxError || error instanceof TypeError
        ? 'بارگذاری سانس‌ها انجام نشد؛ دوباره تلاش کنید یا وارد حساب شوید.' : error.message;
    }
  };
  names.forEach(name => form.elements[name]?.addEventListener('input', () => {
    clearTimeout(timer); timer = setTimeout(refresh, 350);
  }));
  root.querySelector('[data-opening-all]').addEventListener('click', () => { selected = new Set(sessions.map(item => item.key)); render(); save(); });
  root.querySelector('[data-opening-clear]').addEventListener('click', () => { selected.clear(); render(); save(); });
  refresh();
})();
