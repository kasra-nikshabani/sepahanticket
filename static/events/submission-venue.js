(() => {
  const root = document.querySelector('[data-venue-editor]');
  const api = window.DidavarVenuePlan;
  if (!root || !api) return;
  const get = name => root.querySelector(`[data-${name}]`);
  const fa = value => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
  const integer = value => Number(String(value).replace(/[۰-۹]/g, digit => '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit)).replace(/[٠-٩]/g, digit => '٠١٢٣٤٥٦٧٨٩'.indexOf(digit)).replace(/[−–]/g, '-').trim());
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const raw = root.querySelector('[name="seat_layout"]');
  let plan;
  try {
    const parsed = JSON.parse(raw.value || '{}');
    plan = parsed && Object.keys(parsed).length === 0 ? api.empty() : parsed;
    api.validateSize(plan);
  } catch {
    // Preserve the rejected bound value until the organizer deliberately builds a replacement.
    plan = api.empty();
    get('layout-status').textContent = 'نقشه قابل خواندن نیست؛ برای اصلاح، بخش‌های سالن را دوباره بساز.';
  }
  let selected = plan.sections[0]?.id || '';
  const history = [];
  let editingSeat = null;
  const current = () => plan.sections.find(section => section.id === selected);
  const status = text => { get('layout-status').textContent = fa(text); };
  const save = () => {
    raw.value = JSON.stringify(plan);
    raw.dispatchEvent(new Event('change', { bubbles: true }));
    get('layout-capacity').textContent = `${fa(api.capacity(plan))} صندلی`;
    get('layout-undo').disabled = history.length === 0;
  };
  const change = (operation, message) => {
    const before = { plan: api.clone(plan), selected };
    try {
      operation();
      api.validateSize(plan);
      history.push(before);
      if (history.length > 20) history.shift();
      editingSeat = null; get('seat-editor').hidden = true;
      save(); render(); status(message);
    } catch (error) {
      plan = before.plan; selected = before.selected;
      status(error.message);
    }
  };
  const button = (label, attr, value, className = 'venue-row-action') => {
    const element = node('button', label, className);
    element.type = 'button'; element.dataset[attr] = value;
    return element;
  };
  const stage = () => node('div', 'صحنه / محل اجرا', 'venue-stage');
  const renderMap = previewCurvature => {
    const map = get('layout-map'); map.replaceChildren();
    const section = current();
    if (!section) { map.append(node('p', 'هنوز بخشی ساخته نشده است.', 'venue-map-empty')); return; }
    const scroll = node('div', undefined, 'venue-map-scroll');
    const content = node('div', undefined, 'venue-map-content');
    content.dir = plan.direction;
    const stageLine = () => {
      const line = node('div', undefined, 'venue-stage-positioned');
      line.append(stage()); return line;
    };
    if (plan.stage === 'top') content.append(stageLine());
    section.rows.forEach(row => {
      const line = node('div', undefined, 'venue-map-row venue-row-positioned');
      line.append(node('span', `ردیف ${fa(row.number)}`, 'venue-row-label'));
      const alignment = row.alignment || 'start';
      const track = node('div', undefined, `venue-row-track align-${alignment}`);
      const cells = node('div', undefined, 'venue-row-seats');
      if (alignment === 'start') cells.style.marginInlineStart = `${row.offset * 32}px`;
      row.seats.forEach((number, index) => {
        const seat = button(number === null ? '·' : fa(number), 'seatPosition', String(index), `venue-seat ${number === null ? 'is-gap' : ''}`);
        seat.dataset.rowNumber = row.number;
        seat.setAttribute('aria-label', `${section.name}، ردیف ${fa(row.number)}، ${number === null ? 'راهرو؛ افزودن صندلی' : `صندلی ${fa(number)}؛ ویرایش شماره`}`);
        seat.setAttribute('aria-pressed', number === null ? 'false' : 'true');
        cells.append(seat);
      });
      api.curveCells(cells, { ...row, curvature: previewCurvature ?? row.curvature ?? 0 }, plan.direction);
      track.append(cells); line.append(track);
      const tools = node('div', undefined, 'venue-row-tools');
      const add = button('+', 'rowAddSeat', String(row.number));
      add.setAttribute('aria-label', `افزودن صندلی به ردیف ${fa(row.number)}`);
      const remove = button('−', 'rowRemoveSeat', String(row.number));
      remove.setAttribute('aria-label', `حذف آخرین جایگاه ردیف ${fa(row.number)}`);
      const del = button('×', 'rowDelete', String(row.number), 'venue-row-action venue-danger');
      del.setAttribute('aria-label', `حذف ردیف ${fa(row.number)}`);
      const offset = node('select');
      offset.setAttribute('aria-label', `فاصله ردیف ${fa(row.number)} از لبه`);
      offset.dataset.rowOffset = row.number;
      for (let number = 0; number <= 20; number++) { const option = node('option', fa(number)); option.value = number; offset.append(option); }
      offset.value = row.offset;
      offset.disabled = alignment !== 'start';
      const align = node('select', undefined, 'venue-row-alignment');
      align.setAttribute('aria-label', `چینش ردیف ${fa(row.number)}`);
      align.dataset.rowAlignment = row.number;
      for (const [value, text] of [['start', 'ابتدا'], ['center', 'وسط'], ['end', 'انتها']]) {
        const option = node('option', text); option.value = value; align.append(option);
      }
      align.value = alignment;
      const curvature = node('input', undefined, 'venue-row-curvature');
      curvature.type = 'text'; curvature.inputMode = 'numeric'; curvature.dataset.rowCurvature = row.number;
      curvature.setAttribute('aria-label', `انحنای ردیف ${fa(row.number)}؛ منفی ۱۰۰ تا ۱۰۰`);
      curvature.title = 'انحنا: منفی ۱۰۰ تا ۱۰۰؛ صفر یعنی صاف';
      curvature.value = fa(row.curvature || 0);
      tools.append(add, remove, align, offset, curvature, del); line.append(tools); content.append(line);
    });
    const addRow = button('افزودن ردیف', 'addRow', 'true', 'venue-add-row');
    content.append(addRow);
    if (plan.stage === 'bottom') content.append(stageLine());
    scroll.append(content); map.append(scroll);
  };
  const render = () => {
    const select = get('layout-section'); select.replaceChildren();
    if (!plan.sections.length) { const option = node('option', 'بخشی ساخته نشده'); option.value = ''; select.append(option); }
    plan.sections.forEach(section => { const option = node('option', fa(section.name)); option.value = section.id; select.append(option); });
    select.value = selected;
    const section = current();
    get('layout-section-name').value = section?.name || 'همکف';
    if (section?.rows.length) {
      get('layout-rows').value = fa(section.rows.length);
      get('layout-seats').value = fa(section.rows[0].seats.filter(value => value !== null).length);
    }
    get('layout-stage').value = plan.stage;
    get('layout-direction').value = plan.direction;
    const alignments = new Set(section?.rows.map(row => row.alignment || 'start') || []);
    get('layout-alignment').value = alignments.size > 1 ? 'mixed' : [...alignments][0] || 'start';
    const curvatures = new Set(section?.rows.map(row => row.curvature || 0) || []);
    get('layout-curvature').value = curvatures.size === 1 ? [...curvatures][0] : 0;
    get('layout-curvature-value').textContent = curvatures.size > 1 ? 'متفاوت' : fa(get('layout-curvature').value);
    get('layout-delete').disabled = !section;
    get('layout-apply').disabled = !section;
    get('layout-rename').disabled = !section;
    get('layout-capacity').textContent = `${fa(api.capacity(plan))} صندلی`;
    renderMap();
  };
  const settings = id => ({
    id, name: get('layout-section-name').value, rows: integer(get('layout-rows').value), seats: integer(get('layout-seats').value),
    aisle: integer(get('layout-aisle').value), width: integer(get('layout-aisle-width').value),
    curvature: Number(get('layout-curvature').value),
    alignment: get('layout-alignment').value === 'mixed' ? 'start' : get('layout-alignment').value
  });
  get('layout-add').addEventListener('click', () => change(() => {
    selected = crypto.randomUUID();
    plan.sections.push(api.build(settings(selected)));
  }, 'بخش جدید اضافه شد؛ برای ثبت دائمی، پیش‌نویس را ذخیره کن.'));
  get('layout-apply').addEventListener('click', () => change(() => {
    const index = plan.sections.findIndex(section => section.id === selected);
    if (index >= 0) {
      const old = plan.sections[index];
      const mixed = get('layout-alignment').value === 'mixed';
      const rebuilt = api.build(settings(selected));
      if (new Set(old.rows.map(row => row.curvature || 0)).size > 1) rebuilt.rows.forEach(row => { row.curvature = old.rows.find(item => item.number === row.number)?.curvature || 0; });
      if (mixed) rebuilt.rows.forEach(row => { row.alignment = old.rows.find(item => item.number === row.number)?.alignment || 'start'; });
      plan.sections[index] = rebuilt;
    }
  }, 'چیدمان بخش به‌روزرسانی شد.'));
  get('layout-rename').addEventListener('click', () => change(() => {
    if (current()) current().name = get('layout-section-name').value.trim();
  }, 'نام بخش تغییر کرد؛ چیدمان صندلی‌ها حفظ شد.'));
  get('layout-delete').addEventListener('click', () => change(() => {
    plan.sections = plan.sections.filter(section => section.id !== selected);
    selected = plan.sections[0]?.id || '';
  }, 'بخش حذف شد؛ با بازگردانی می‌توانی آن را برگردانی.'));
  get('layout-section').addEventListener('change', event => { selected = event.target.value; editingSeat = null; get('seat-editor').hidden = true; render(); });
  get('layout-stage').addEventListener('change', event => change(() => { plan.stage = event.target.value; }, 'موقعیت صحنه تغییر کرد.'));
  get('layout-direction').addEventListener('change', event => change(() => { plan.direction = event.target.value; }, 'جهت شماره‌گذاری تغییر کرد.'));
  get('layout-alignment').addEventListener('change', event => {
    if (!current()) return;
    const alignment = event.target.value;
    change(() => { current().rows.forEach(row => { row.alignment = alignment; }); }, 'چینش همه ردیف‌های این بخش تغییر کرد.');
  });
  get('layout-curvature').addEventListener('input', event => {
    const value = Number(event.target.value);
    get('layout-curvature-value').textContent = fa(value);
    renderMap(value);
  });
  get('layout-curvature').addEventListener('change', event => {
    const curvature = Number(event.target.value);
    if (!current()) return;
    change(() => { current().rows.forEach(row => { row.curvature = curvature; }); }, 'انحنای ردیف‌های بخش تغییر کرد؛ برای ثبت، فرم را ذخیره کن.');
  });
  get('layout-undo').addEventListener('click', () => {
    const previous = history.pop(); if (!previous) return;
    plan = previous.plan; selected = previous.selected; save(); render(); status('آخرین تغییر برگردانده شد.');
  });
  get('layout-map').addEventListener('click', event => {
    const target = event.target.closest('button'); if (!target || !current()) return;
    const section = current();
    if (target.dataset.seatPosition !== undefined) {
      const rowNumber = Number(target.dataset.rowNumber), position = Number(target.dataset.seatPosition);
      const row = current().rows.find(item => item.number === rowNumber);
      if (row.seats[position] !== null) {
        editingSeat = { section: selected, rowNumber, position };
        get('seat-caption').textContent = `ردیف ${fa(rowNumber)} · صندلی ${fa(row.seats[position])}`;
        get('seat-number').value = fa(row.seats[position]);
        get('seat-editor').hidden = false;
        get('seat-number').focus(); get('seat-number').select();
        return;
      }
      change(() => api.toggle(plan, selected, rowNumber, position), 'صندلی اضافه شد.');
      get('layout-map').querySelector(`[data-row-number="${rowNumber}"][data-seat-position="${position}"]`)?.focus({ preventScroll: true });
      return;
    }
    if (target.dataset.addRow) return change(() => {
      if (section.rows.length >= api.limits.rows) throw new Error('هر بخش حداکثر ۶۰ ردیف دارد.');
      const number = Math.max(0, ...section.rows.map(row => row.number)) + 1;
      const count = section.rows.at(-1)?.seats.length || 10;
      section.rows.push({ number, offset: 0, curvature: section.rows.at(-1)?.curvature || 0, alignment: section.rows.at(-1)?.alignment || 'start', seats: Array.from({ length: count }, (_, index) => index + 1) });
    }, 'ردیف جدید اضافه شد.');
    const number = Number(target.dataset.rowAddSeat || target.dataset.rowRemoveSeat || target.dataset.rowDelete);
    const row = section.rows.find(item => item.number === number); if (!row) return;
    change(() => {
      if (target.dataset.rowAddSeat) {
        if (row.seats.length >= api.limits.columns) throw new Error('هر ردیف حداکثر ۸۰ جایگاه دارد.');
        row.seats.push(Math.max(0, ...row.seats.filter(value => value !== null)) + 1);
      } else if (target.dataset.rowRemoveSeat) {
        if (row.seats.length <= 1) throw new Error('برای حذف آخرین جایگاه، خود ردیف را حذف کن.');
        row.seats.pop();
      } else if (target.dataset.rowDelete) section.rows = section.rows.filter(item => item.number !== number);
    }, 'ردیف به‌روزرسانی شد.');
  });
  get('layout-map').addEventListener('change', event => {
    const curvedRow = event.target.dataset.rowCurvature;
    if (curvedRow && current()) {
      const row = current().rows.find(item => item.number === Number(curvedRow));
      const curvature = integer(event.target.value);
      if (row) change(() => { row.curvature = curvature; }, 'انحنای ردیف تغییر کرد.');
      get('layout-map').querySelector(`[data-row-curvature="${curvedRow}"]`)?.focus({ preventScroll: true });
      return;
    }
    const alignedRow = event.target.dataset.rowAlignment;
    if (alignedRow && current()) {
      const row = current().rows.find(item => item.number === Number(alignedRow));
      if (row) {
        const alignment = event.target.value;
        change(() => { row.alignment = alignment; }, 'چینش ردیف تغییر کرد.');
        get('layout-map').querySelector(`[data-row-alignment="${alignedRow}"]`)?.focus({ preventScroll: true });
      }
      return;
    }
    const number = event.target.dataset.rowOffset; if (!number || !current()) return;
    const row = current().rows.find(item => item.number === Number(number));
    if (row) change(() => { row.offset = Number(event.target.value); }, 'فاصله ردیف تغییر کرد.');
  });
  const editSeat = gap => {
    if (!editingSeat || selected !== editingSeat.section) return;
    const { rowNumber, position } = editingSeat;
    change(() => {
      const row = current().rows.find(item => item.number === rowNumber);
      row.seats[position] = gap ? null : integer(get('seat-number').value);
    }, gap ? 'صندلی به راهرو تبدیل شد.' : 'شماره صندلی ذخیره شد.');
  };
  get('seat-save').addEventListener('click', () => editSeat(false));
  get('seat-gap').addEventListener('click', () => editSeat(true));
  get('seat-close').addEventListener('click', () => { editingSeat = null; get('seat-editor').hidden = true; });
  get('seat-number').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); editSeat(false); }
    if (event.key === 'Escape') { event.preventDefault(); get('seat-close').click(); }
  });
  get('layout-raw').hidden = true;
  get('designer').hidden = false;
  render();

  // The staff hall builder shares the designer without organizer venue modes.
  if (root.dataset.mode === 'admin') return;

  const presetPanel = get('preset-panel'), customPanel = get('custom-panel'), meta = get('custom-meta');
  const modeRadios = root.querySelectorAll('[name="venue_mode"]');
  const select = root.querySelector('[name="venue_preset"]');
  const reference = get('venue-reference');
  let controller, requestNumber = 0;
  const admissionRadios = root.querySelectorAll('[name="admission_mode"]');
  const quantityPanel = get('quantity-panel');
  const capacityInput = root.querySelector('[name="ticket_capacity"]');
  const isQuantity = () => Array.from(admissionRadios).some(radio => radio.checked && radio.value === 'quantity');
  const renderReference = data => {
    reference.replaceChildren();
    const info = node('div', undefined, 'venue-reference-info');
    info.append(node('strong', fa(data.name)), node('p', `${fa(data.city || 'شهر ثبت نشده')} · ${fa(data.address || 'نشانی ثبت نشده')}`),
      node('small', `ظرفیت ثبت‌شده: ${fa(data.capacity)} · صندلی‌های نقشه: ${fa(data.seat_count)}`));
    reference.append(info);
    if (!isQuantity() && !data.seat_count) reference.append(node('p', 'چیدمان صندلی‌های این سالن هنوز توسط ادمین ثبت نشده است.', 'wizard-help'));
    if (!isQuantity() && data.truncated) reference.append(node('p', 'این سالن بزرگ است؛ در پیش‌نمایش، فقط بخشی از صندلی‌ها نمایش داده می‌شوند. ظرفیت واقعی حفظ می‌شود.', 'wizard-help'));
    const sections = data.sections.filter(section => section.rows.length);
    if (!isQuantity() && sections.length) {
      const picker = node('select', undefined, 'venue-reference-section');
      picker.setAttribute('aria-label', 'بخش سالن آماده برای مشاهده');
      sections.forEach(section => { const option = node('option', `${fa(section.name)} · ${fa(section.seat_count)} صندلی`); option.value = section.id; picker.append(option); });
      const preview = node('div', undefined, 'venue-reference-map');
      const show = () => {
        preview.replaceChildren(); const section = sections.find(item => String(item.id) === picker.value);
        const scroll = node('div', undefined, 'venue-map-scroll'); const content = node('div', undefined, 'venue-map-content');
        content.dir = data.direction || 'rtl';
        if (data.stage !== 'bottom') content.append(stage());
        section.rows.forEach(row => {
          const line = node('div', undefined, 'venue-map-row venue-row-positioned venue-row-readonly'); line.append(node('span', `ردیف ${fa(row.number)}`, 'venue-row-label'));
          const cells = node('div', undefined, 'venue-row-seats');
          row.seats.forEach(seat => { if (seat === null) { cells.append(node('span', '', 'venue-seat is-gap')); return; } const item = node('span', fa(seat.number), `venue-seat venue-seat-reference ${seat.enabled ? '' : 'is-disabled'}`); item.title = `صندلی ${fa(seat.number)}${seat.enabled ? '' : ' · غیرفعال در نقشه سالن'}`; cells.append(item); });
          api.curveCells(cells, { ...row, seats: row.seats }, data.direction || 'rtl');
          const track = node('div', undefined, `venue-row-track align-${row.alignment || 'start'}`);
          if ((row.alignment || 'start') === 'start') cells.style.marginInlineStart = `${(row.offset || 0) * 32}px`;
          track.append(cells); line.append(track, node('span')); content.append(line);
        });
        if (data.stage === 'bottom') content.append(stage());
        scroll.append(content); preview.append(scroll);
      };
      picker.addEventListener('change', show); reference.append(picker, preview); show();
    }
    reference.append(node('p', 'چیدمان سالن آماده فقط قابل مشاهده است؛ تغییر آن با ادمین سامانه است.', 'wizard-help'));
  };
  const loadPreset = async () => {
    controller?.abort(); const serial = ++requestNumber;
    if (!select.value) { reference.replaceChildren(node('p', 'یک سالن از فهرست انتخاب کن.')); return; }
    controller = new AbortController(); reference.replaceChildren(node('p', 'در حال دریافت مشخصات سالن…'));
    try {
      const response = await fetch(root.dataset.presetBase.replace('/0/', `/${encodeURIComponent(select.value)}/`), { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal });
      if (!response.ok) throw new Error('اطلاعات سالن دریافت نشد.');
      const data = await response.json(); if (serial !== requestNumber) return;
      renderReference(data);
    } catch (error) {
      if (error.name === 'AbortError') return;
      reference.replaceChildren(node('p', 'دریافت مشخصات سالن ناموفق بود؛ انتخابت در فرم حفظ شده است.'));
      const retry = button('تلاش دوباره', 'retry', 'true', 'venue-text-btn'); retry.addEventListener('click', loadPreset); reference.append(retry);
    }
  };
  const updateMode = () => {
    const online = root.dataset.online === 'true';
    const mode = Array.from(modeRadios).find(radio => radio.checked)?.value || 'preset';
    const quantity = isQuantity();
    quantityPanel.hidden = !quantity; capacityInput.disabled = !quantity;
    presetPanel.hidden = online || mode !== 'preset'; customPanel.hidden = online || mode !== 'custom' || quantity; meta.hidden = !online && mode !== 'custom';
    select.disabled = online || mode !== 'preset'; raw.disabled = online || mode !== 'custom' || quantity;
    meta.querySelectorAll('input,textarea').forEach(input => { input.disabled = !online && mode !== 'custom'; });
    if (!online && mode === 'preset') loadPreset();
    else { controller?.abort(); requestNumber++; }
  };
  admissionRadios.forEach(radio => radio.addEventListener('change', updateMode));
  modeRadios.forEach(radio => radio.addEventListener('change', updateMode));
  select.addEventListener('change', loadPreset);
  updateMode();
})();
