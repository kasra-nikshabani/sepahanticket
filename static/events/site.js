(function () {
    'use strict';
    const filters = document.querySelector('.filters');
    if (filters && window.matchMedia('(max-width: 760px)').matches) {
        filters.open = false;
    }
    const sort = document.getElementById('sort');
    if (sort) {
        sort.addEventListener('change', function () {
            sort.form.requestSubmit();
        });
    }
    document.querySelectorAll('[data-card-info]').forEach(function (button) {
        const card = button.closest('.compact-card');
        const preview = card.querySelector('.card-preview');
        function close() {
            card.classList.remove('is-expanded');
            button.setAttribute('aria-expanded', 'false');
            button.querySelector('span').textContent = 'جزئیات';
            preview.setAttribute('aria-hidden', 'true');
        }
        button.addEventListener('click', function () {
            const expanded = !card.classList.contains('is-expanded');
            card.classList.toggle('is-expanded', expanded);
            button.setAttribute('aria-expanded', String(expanded));
            preview.setAttribute('aria-hidden', String(!expanded));
            button.querySelector('span').textContent = expanded ? 'بستن' : 'جزئیات';
        });
        card.addEventListener('mouseenter', function () {
            if (window.matchMedia('(hover: hover) and (pointer: fine)').matches) preview.setAttribute('aria-hidden', 'false');
        });
        card.addEventListener('mouseleave', function () {
            if (!card.classList.contains('is-expanded')) preview.setAttribute('aria-hidden', 'true');
        });
        card.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') close();
        });
        card.addEventListener('focusout', function (event) {
            if (!card.contains(event.relatedTarget)) close();
        });
    });
})();
