(function () {
    'use strict';
    function latin(value) {
        return value.replace(/[۰-۹]/g, function (digit) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit); })
            .replace(/[٠-٩]/g, function (digit) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(digit); });
    }
    function persian(value) { return String(value).replace(/[0-9]/g, function (digit) { return '۰۱۲۳۴۵۶۷۸۹'[digit]; }); }
    document.querySelectorAll('[data-auth-form]').forEach(function (form) {
        form.querySelectorAll('[data-numeric]').forEach(function (input) {
            input.addEventListener('input', function () {
                const position = input.selectionStart;
                const before = input.value;
                input.value = persian(latin(before).replace(/\D/g, ''));
                if (position !== null) {
                    const next = persian(latin(before.slice(0, position)).replace(/\D/g, '')).length;
                    input.setSelectionRange(next, next);
                }
            });
        });
        form.addEventListener('submit', function () {
            form.querySelectorAll('[data-numeric]').forEach(function (input) { input.value = latin(input.value); });
        });
    });
    document.querySelectorAll('[data-password-toggle]').forEach(function (button) {
        button.addEventListener('click', function () {
            const input = document.getElementById(button.getAttribute('aria-controls'));
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.setAttribute('aria-pressed', String(show));
            button.setAttribute('aria-label', show ? 'پنهان کردن رمز عبور' : 'نمایش رمز عبور');
            button.querySelector('i').className = show ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye';
        });
    });
    const otp = document.querySelector('[data-otp-input]');
    if (otp) {
        const control = otp.closest('[data-otp-control]');
        const slots = Array.from(control.querySelectorAll('.otp-code-slots span'));
        control.dataset.enhanced = 'true';
        function paintCode() {
            const digits = persian(latin(otp.value));
            const active = Math.min(otp.selectionStart === null ? digits.length : otp.selectionStart, 3);
            slots.forEach(function (slot, index) {
                slot.textContent = digits[index] || '';
                slot.toggleAttribute('data-filled', Boolean(digits[index]));
                slot.toggleAttribute('data-active', index === active);
            });
        }
        otp.addEventListener('input', function () {
            control.classList.remove('has-error');
            otp.removeAttribute('aria-invalid');
            document.getElementById('otp-error').textContent = '';
            paintCode();
        });
        otp.addEventListener('paste', function (event) {
            const code = latin(event.clipboardData.getData('text')).replace(/\D/g, '').slice(0, 4);
            if (!code) return;
            event.preventDefault();
            otp.value = persian(code);
            otp.dispatchEvent(new Event('input', { bubbles: true }));
            otp.setSelectionRange(code.length, code.length);
            paintCode();
        });
        ['focus', 'keyup', 'select'].forEach(function (event) { otp.addEventListener(event, paintCode); });
        otp.addEventListener('click', function (event) {
            const bounds = control.getBoundingClientRect();
            const cell = Math.max(0, Math.min(3, Math.floor((event.clientX - bounds.left) / (bounds.width / 4))));
            const position = Math.min(cell, otp.value.length);
            otp.setSelectionRange(position, position);
            paintCode();
        });
        paintCode();
    }
    const resend = document.querySelector('[data-resend-url]');
    if (!resend) return;
    const feedback = document.querySelector('.auth-resend-feedback');
    let remaining = Math.max(0, Number(resend.dataset.remaining) || 0);
    let pending = false;
    let expires = Date.now() + remaining * 1000;
    function render() {
        remaining = Math.max(0, Math.ceil((expires - Date.now()) / 1000));
        resend.disabled = pending || remaining > 0;
        resend.textContent = pending ? 'در حال ارسال…' : remaining > 0 ? 'ارسال مجدد (' + persian(Math.floor(remaining / 60) + ':' + String(remaining % 60).padStart(2, '0')) + ')' : 'ارسال مجدد کد';
    }
    render();
    window.setInterval(render, 1000);
    resend.addEventListener('click', async function () {
        if (pending || remaining > 0) return;
        pending = true; feedback.textContent = ''; render();
        try {
            const response = await fetch(resend.dataset.resendUrl, {
                method: 'POST', headers: { 'X-CSRFToken': resend.closest('form').querySelector('[name=csrfmiddlewaretoken]').value, 'Content-Type': 'application/x-www-form-urlencoded' }, body: ''
            });
            const data = await response.json();
            feedback.textContent = persian(data.message || 'ارسال کد ممکن نشد. دوباره تلاش کنید.');
            if (data.status === 'success') {
                expires = Date.now() + 60000;
                const development = document.querySelector('[data-dev-otp-display]');
                if (development) {
                    development.hidden = !data.dev_otp_code;
                    development.querySelector('[data-dev-otp-code]').textContent = persian(data.dev_otp_code || '');
                }
            }
            else if (data.retry_after) expires = Date.now() + Number(data.retry_after) * 1000;
        } catch (_) { feedback.textContent = 'ارتباط برقرار نشد. دوباره تلاش کنید.'; }
        finally { pending = false; render(); }
    });
})();
