(() => {
    'use strict';
    const form = document.getElementById('cultural-checkout');
    const timer = document.getElementById('reservation-time');
    if (!form || !timer) return;
    const submit = document.getElementById('checkout-submit');
    const expiry = document.getElementById('reservation-expiry');
    const originalButton = submit.innerHTML;
    const expiresAt = Date.now() + Number(timer.dataset.seconds) * 1000;
    const fa = value => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
    let submitting = false;
    function update() {
        const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
        timer.textContent = fa(Math.floor(remaining / 60) + ':' + String(remaining % 60).padStart(2, '0'));
        expiry.hidden = remaining > 0;
        submit.disabled = !remaining || submitting;
        return remaining;
    }
    update();
    const interval = setInterval(update, 1000);
    const wallet = document.getElementById('use-wallet');
    const walletFields = document.getElementById('wallet-fields');
    const amount = document.getElementById('wallet-amount');
    function syncWallet() {
        if (!wallet || !amount) return;
        walletFields.hidden = !wallet.checked;
        amount.disabled = !wallet.checked;
    }
    wallet?.addEventListener('change', syncWallet);
    syncWallet();
    form.addEventListener('submit', event => {
        if (!update()) { event.preventDefault(); return; }
        submitting = true;
        submit.disabled = true;
        submit.textContent = 'در حال ثبت سفارش…';
    });
    window.addEventListener('pageshow', () => {
        submitting = false;
        submit.innerHTML = originalButton;
        update();
    });
    window.addEventListener('pagehide', event => { if (!event.persisted) clearInterval(interval); });
})();
