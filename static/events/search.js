(function () {
    'use strict';
    document.querySelectorAll('[data-discovery-search]').forEach(function (root) {
        const form = root.querySelector('form');
        const input = root.querySelector('[name=q]');
        const panel = root.querySelector('.discovery-panel');
        const toggle = root.querySelector('.search-panel-toggle');
        const feedback = root.querySelector('.discovery-feedback');
        const suggestions = root.querySelector('[data-search-suggestions]');
        const quick = root.querySelector('[data-search-quick]');
        const filters = Array.from(panel.querySelectorAll('select'));
        const indicator = root.querySelector('.search-filter-indicator');
        let timer, controller, generation = 0, composing = false, suppressFocus = false;
        const fa = value => String(value).replace(/[0-9]/g, n => '۰۱۲۳۴۵۶۷۸۹'[n]);
        const queryLength = () => input.value.replace(/[\s\u200c-\u200f\u064b-\u0652\u0640]/g, '').length;

        function place() {
            if (panel.hidden) return;
            const rect = form.getBoundingClientRect();
            const width = Math.min(620, window.innerWidth - 32);
            panel.style.width = width + 'px';
            panel.style.left = Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16)) + 'px';
            panel.style.top = (rect.bottom + 9) + 'px';
            panel.style.maxHeight = Math.max(130, window.innerHeight - rect.bottom - 25) + 'px';
        }
        function open() {
            panel.hidden = false;
            input.setAttribute('aria-expanded', 'true');
            toggle.setAttribute('aria-expanded', 'true');
            place();
        }
        function cancel() {
            clearTimeout(timer);
            generation += 1;
            if (controller) controller.abort();
            suggestions.setAttribute('aria-busy', 'false');
        }
        function close(returnFocus) {
            cancel();
            panel.hidden = true;
            input.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-expanded', 'false');
            if (returnFocus) {
                suppressFocus = true;
                input.focus({preventScroll: true});
                suppressFocus = false;
            }
        }
        function node(tag, className, text) {
            const item = document.createElement(tag);
            item.className = className;
            if (text) item.textContent = fa(text);
            return item;
        }
        function renderGroup(title, items, artist) {
            if (!items.length) return;
            const group = node('div', 'discovery-group');
            group.append(node('h3', '', title));
            items.forEach(function (item) {
                const link = node('a', 'discovery-result');
                // Only local detail URLs from our public endpoint are navigable.
                if (!item.url || !item.url.startsWith('/') || item.url.startsWith('//')) return;
                link.href = item.url;
                link.dataset.searchResult = '';
                const artwork = node('span', 'discovery-artwork' + (artist ? ' is-artist' : ''));
                if (item.image) {
                    const img = document.createElement('img');
                    img.src = item.image; img.alt = ''; img.loading = 'lazy';
                    artwork.append(img);
                } else {
                    const icon = node('i', artist ? 'fa-solid fa-palette' : 'fa-solid fa-ticket');
                    icon.setAttribute('aria-hidden', 'true'); artwork.append(icon);
                }
                const text = node('div', 'discovery-result-text');
                text.append(node('strong', '', item.title));
                text.append(node('small', '', artist ? item.specialty : [item.city, item.venue, item.date].filter(Boolean).join(' · ')));
                link.append(artwork, text, node('span', 'discovery-result-type', artist ? 'هنرمند' : item.category));
                group.append(link);
            });
            suggestions.append(group);
        }
        async function fetchSuggestions(current) {
            controller = new AbortController();
            const url = new URL(root.dataset.suggestionsUrl, window.location.origin);
            const data = new FormData(form);
            ['q', 'category', 'city', 'period'].forEach(key => {
                const value = data.get(key);
                if (value) url.searchParams.set(key, value);
            });
            try {
                const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
                if (!response.ok) throw new Error('Search unavailable');
                const result = await response.json();
                if (current !== generation || panel.hidden) return;
                suggestions.replaceChildren();
                renderGroup('برنامه‌ها', result.events || [], false);
                renderGroup('هنرمندان', result.artists || [], true);
                const count = (result.events || []).length + (result.artists || []).length;
                feedback.textContent = count ? fa(count) + ' پیشنهاد' + (result.has_more ? '؛ نتایج بیشتر در صفحهٔ جست‌وجو' : ' برای شما پیدا شد') : 'پیشنهادی پیدا نشد؛ عبارت کوتاه‌تر یا فیلتر دیگری را امتحان کنید.';
                quick.hidden = count > 0;
                place();
            } catch (error) {
                if (error.name !== 'AbortError' && current === generation && !panel.hidden) {
                    feedback.textContent = 'پیشنهادهای سریع در دسترس نیست؛ با دکمهٔ جست‌وجو نتایج را ببینید.';
                    quick.hidden = false;
                }
            } finally {
                if (current === generation) suggestions.setAttribute('aria-busy', 'false');
            }
        }
        function update() {
            cancel();
            suggestions.replaceChildren();
            quick.hidden = false;
            indicator.hidden = !filters.some(field => field.value);
            if (composing || queryLength() < 2) {
                feedback.textContent = 'حداقل دو حرف بنویسید تا پیشنهادها نمایش داده شوند.';
                return;
            }
            feedback.textContent = 'در حال پیدا کردن پیشنهادها…';
            suggestions.setAttribute('aria-busy', 'true');
            quick.hidden = true;
            const current = generation;
            timer = setTimeout(() => fetchSuggestions(current), 280);
        }
        toggle.hidden = false;
        input.addEventListener('focus', function () { if (panel.hidden && !suppressFocus) { open(); update(); } });
        input.addEventListener('click', function () { if (panel.hidden) { open(); update(); } });
        input.addEventListener('input', function () { open(); update(); });
        input.addEventListener('compositionstart', function () { composing = true; cancel(); });
        input.addEventListener('compositionend', function () { composing = false; update(); });
        toggle.addEventListener('click', function () { if (panel.hidden) { open(); update(); } else close(false); });
        root.querySelector('.search-close').addEventListener('click', () => close(true));
        filters.forEach(field => field.addEventListener('change', update));
        form.addEventListener('submit', cancel);
        root.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            if (panel.hidden) return;
            if (event.target !== input && !event.target.matches('[data-search-result]')) return;
            const links = Array.from(suggestions.querySelectorAll('[data-search-result]'));
            if (!links.length) return;
            event.preventDefault();
            const index = links.indexOf(event.target);
            const next = event.key === 'ArrowDown' ? index + 1 : index - 1;
            if (next < 0) input.focus({preventScroll: true});
            else links[Math.min(next, links.length - 1)].focus();
        });
        document.addEventListener('pointerdown', event => { if (!root.contains(event.target)) close(false); });
        root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) close(false); });
        window.addEventListener('resize', place, {passive: true});
        window.addEventListener('scroll', place, {passive: true});
    });
})();
