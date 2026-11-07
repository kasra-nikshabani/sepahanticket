(function () {
    'use strict';
    const links = Array.from(document.querySelectorAll('.detail-tabs a'));
    if (!links.length) return;
    function activate(link) {
        links.forEach(function (item) {
            const active = item === link;
            item.classList.toggle('active', active);
            if (active) item.setAttribute('aria-current', 'location');
            else item.removeAttribute('aria-current');
        });
    }
    links.forEach(function (link) { link.addEventListener('click', function () { activate(link); }); });
    if (!('IntersectionObserver' in window)) return;
    const visible = new Set();
    const observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) visible.add(entry.target.id);
            else visible.delete(entry.target.id);
        });
        const current = links.find(function (link) { return visible.has(link.hash.slice(1)); });
        if (current) activate(current);
    }, { rootMargin: '-15% 0px -45% 0px', threshold: 0 });
    links.forEach(function (link) {
        const section = document.getElementById(link.hash.slice(1));
        if (section) observer.observe(section);
    });
})();
(() => {
    const picker = document.querySelector('[data-session-picker]');
    if (!picker) return;
    const buttons = Array.from(picker.querySelectorAll('[data-session-filter]'));
    const groups = Array.from(document.querySelectorAll('[data-session-day]'));
    const feedback = document.querySelector('[data-session-feedback]');
    picker.hidden = false;
    buttons.forEach(button => button.addEventListener('click', () => {
        buttons.forEach(item => { const selected = item === button; item.classList.toggle('is-active', selected); item.setAttribute('aria-pressed', String(selected)); });
        let count = 0;
        groups.forEach(group => {
            group.hidden = button.dataset.sessionFilter !== 'all' && group.dataset.sessionDay !== button.dataset.sessionFilter;
            if (!group.hidden) count += group.querySelectorAll('.detail-session').length;
        });
        feedback.textContent = String(count).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]) + ' سانس نمایش داده می‌شود';
    }));
})();
(() => {
    const panel = document.querySelector('[data-session-layout]');
    const toggles = Array.from(document.querySelectorAll('[data-show-layout]'));
    if (!panel || !toggles.length) return;
    const maps = Array.from(panel.querySelectorAll('[data-layout-for]'));
    const empty = panel.querySelector('[data-layout-empty]');
    const caption = panel.querySelector('[data-layout-caption]');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    toggles.forEach(button => button.addEventListener('click', () => {
        const id = button.dataset.showLayout;
        const already = button.getAttribute('aria-expanded') === 'true';
        toggles.forEach(item => {
            item.setAttribute('aria-expanded', 'false');
            item.closest('.detail-session')?.classList.remove('is-selected');
        });
        if (already) { panel.hidden = true; return; }
        button.setAttribute('aria-expanded', 'true');
        button.closest('.detail-session')?.classList.add('is-selected');
        let shown = false;
        maps.forEach(map => {
            const match = map.dataset.layoutFor === id;
            map.hidden = !match;
            if (match) shown = true;
        });
        if (empty) empty.hidden = shown;
        if (caption) caption.textContent = button.dataset.layoutTitle || '';
        panel.hidden = false;
        panel.scrollIntoView({ behavior: motion.matches ? 'auto' : 'smooth', block: 'nearest' });
    }));
})();
