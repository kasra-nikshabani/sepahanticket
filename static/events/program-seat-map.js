(() => {
  const root = document.querySelector('[data-program-seat-map]');
  const source = document.getElementById('program-seat-data');
  if (!root || !source) return;
  let seats;
  try { seats = JSON.parse(source.textContent); } catch { return; }
  const get = name => root.querySelector(`[data-seat-${name}]`);
  const fa = value => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
  const set = (name, value, visible = true) => {
    const field = get(name);
    field.textContent = fa(value);
    field.parentElement.hidden = !visible;
  };
  const selectSeat = button => {
    const seat = seats[button.dataset.seatId];
    if (!seat) return;
    root.querySelectorAll('[data-seat-id][aria-pressed="true"]').forEach(previous => {
      previous.setAttribute('aria-pressed', 'false');
      previous.classList.remove('is-selected');
    });
    button.setAttribute('aria-pressed', 'true'); button.classList.add('is-selected');
    get('heading').textContent = fa(`${seat.section} · ردیف ${seat.row} · صندلی ${seat.number}`);
    get('intro').hidden = true; get('info').hidden = false;
    const issued = seat.state === 'sold' || seat.state === 'complimentary';
    set('state', seat.label);
    set('holder', seat.holder || 'نام ثبت نشده', issued);
    set('buyer', seat.buyer || 'نام ثبت نشده', issued);
    set('reserver', seat.reserver || 'نام رزروکننده در دسترس نیست', seat.state === 'reserved');
    set('amount', seat.amount === null ? '—' : `${new Intl.NumberFormat('fa-IR').format(seat.amount / 10)} تومان`, issued);
    set('used', seat.used ? 'ورود ثبت شده' : 'وارد نشده', issued);
    let expiry = '';
    if (seat.expires) {
      const date = new Date(seat.expires);
      if (!Number.isNaN(date.getTime())) expiry = new Intl.DateTimeFormat('fa-IR', {
        timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit', second: '2-digit'
      }).format(date);
    }
    set('expiry', expiry, seat.state === 'reserved' && Boolean(expiry));
  };
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-seat-id]');
    if (button && root.contains(button)) selectSeat(button);
  });
  root.addEventListener('keydown', event => {
    const button = event.target.closest('[data-seat-id]');
    if (!button || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...button.closest('.program-map-row').querySelectorAll('[data-seat-id]')];
    const rtl = root.querySelector('.program-map-canvas').dir !== 'ltr';
    let index = buttons.indexOf(button);
    if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = buttons.length - 1;
    else index += (event.key === 'ArrowLeft') === rtl ? 1 : -1;
    if (buttons[index]) { event.preventDefault(); buttons[index].focus(); }
  });
})();
