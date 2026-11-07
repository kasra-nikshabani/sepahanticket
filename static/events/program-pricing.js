(function () {
    'use strict';
    const form = document.querySelector('[data-pricing-form]');
    if (!form) return;
    const target = form.querySelector('#id_target');
    const row = form.querySelector('#id_row');
    const options = JSON.parse(document.getElementById('pricing-row-options').textContent);
    const fa = n => String(n).replace(/[0-9]/g, d => '۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
    function update() {
        form.querySelector('[data-pricing-row]').hidden = target.value === 'base';
        form.querySelector('[data-pricing-seats]').hidden = target.value !== 'seats';
        const seats = options[row.value] || [];
        const visible = seats.slice(0, 40).map(fa).join('، ');
        form.querySelector('[data-seat-hint]').textContent = seats.length ?
            `صندلی‌های این ردیف: ${visible}${seats.length > 40 ? ' …' : ''}` : 'ابتدا ردیف را انتخاب کن.';
    }
    target.addEventListener('change', update);
    row.addEventListener('change', update);
    const price = form.querySelector('#id_price');
    price.addEventListener('input', () => {
        const start = price.selectionStart, end = price.selectionEnd;
        price.value = fa(price.value);
        price.setSelectionRange(start, end);
    });
    price.value = fa(price.value);
    update();
})();
