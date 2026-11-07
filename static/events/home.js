(function () {
    'use strict';
    const slider = document.querySelector('[data-slider]');
    if (!slider) return;
    const slides = Array.from(slider.querySelectorAll('.featured-slide'));
    if (!slides.length) return;
    const dots = Array.from(slider.querySelectorAll('[data-slide]'));
    const pause = slider.querySelector('[data-pause]');
    const progress = slider.querySelector('[data-slider-progress]');
    const counter = slider.querySelector('[data-slider-current]');
    const caption = slider.querySelector('[data-slider-caption]');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const interval = 5000;
    let current = 0;
    let paused = motion.matches;
    let hovering = false;
    let focused = false;
    let timer;
    let progressAnimation;
    let transitions = [];
    let generation = 0;
    const fa = value => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);

    function schedule() {
        window.clearTimeout(timer);
        progressAnimation?.cancel();
        if (!paused && !hovering && !focused && !document.hidden && slides.length > 1) {
            timer = window.setTimeout(() => show(current + 1), interval);
            if (progress && !motion.matches && progress.animate) {
                progressAnimation = progress.animate([
                    { transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }
                ], { duration: interval, fill: 'forwards' });
            }
        }
    }
    function update() {
        slides.forEach((slide, index) => {
            const active = index === current;
            slide.inert = !active;
            slide.setAttribute('aria-hidden', String(!active));
            slide.classList.toggle('is-active', active);
        });
        dots.forEach((dot, index) => dot.setAttribute('aria-current', String(index === current)));
        if (counter) counter.textContent = fa(current + 1);
        if (caption) caption.textContent = slides[current].dataset.title || '';
    }
    function finishTransition() {
        transitions.forEach(animation => animation.cancel());
        transitions = [];
        slides.forEach((slide, index) => { slide.hidden = index !== current; });
    }
    function show(index) {
        const target = (index + slides.length) % slides.length;
        const previous = current;
        const token = ++generation;
        finishTransition();
        if (target === previous) { schedule(); return; }
        const direction = index < previous ? -1 : 1;
        current = target;
        slides[current].hidden = false;
        update();
        if (!motion.matches && slides[current].animate) {
            const options = { duration: 760, easing: 'cubic-bezier(.22,.61,.36,1)', fill: 'both' };
            transitions = [
                slides[previous].animate([
                    { opacity: 1, transform: 'translateX(0)' },
                    { opacity: 0, transform: `translateX(${-direction * 35}px)` }
                ], options),
                slides[current].animate([
                    { opacity: 0, transform: `translateX(${direction * 45}px)` },
                    { opacity: 1, transform: 'translateX(0)' }
                ], options)
            ];
            Promise.all(transitions.map(animation => animation.finished)).then(() => {
                if (token === generation) finishTransition();
            }).catch(() => {});
        } else {
            finishTransition();
        }
        schedule();
    }
    function setPaused(value) {
        paused = value;
        pause.setAttribute('aria-pressed', String(paused));
        pause.setAttribute('aria-label', paused ? 'شروع پخش خودکار' : 'توقف پخش خودکار');
        pause.firstElementChild.className = 'fa-solid ' + (paused ? 'fa-play' : 'fa-pause');
        schedule();
    }
    slides.forEach(slide => {
        const image = slide.querySelector('img');
        if (image) image.loading = 'eager';
    });
    slider.querySelector('[data-prev]').addEventListener('click', () => show(current - 1));
    slider.querySelector('[data-next]').addEventListener('click', () => show(current + 1));
    dots.forEach((dot, index) => dot.addEventListener('click', () => show(index)));
    pause.addEventListener('click', () => setPaused(!paused));
    slider.addEventListener('mouseenter', () => { hovering = true; schedule(); });
    slider.addEventListener('mouseleave', () => { hovering = false; schedule(); });
    slider.addEventListener('focusin', () => { focused = true; schedule(); });
    slider.addEventListener('focusout', event => { focused = slider.contains(event.relatedTarget); schedule(); });
    slider.addEventListener('keydown', event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault(); show(current + (event.key === 'ArrowLeft' ? 1 : -1));
        }
    });
    document.addEventListener('visibilitychange', schedule);
    motion.addEventListener('change', () => {
        if (motion.matches) { ++generation; finishTransition(); setPaused(true); }
    });
    window.addEventListener('pagehide', () => {
        window.clearTimeout(timer); progressAnimation?.cancel(); ++generation; finishTransition();
    });
    window.addEventListener('pageshow', event => { if (event.persisted) schedule(); });
    update();
    setPaused(paused);
})();

(function () {
    'use strict';
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    document.querySelectorAll('[data-rail]').forEach(function (rail) {
        const section = rail.closest('.home-event-section');
        if (!section) return;
        const prev = section.querySelector('[data-rail-prev]');
        const next = section.querySelector('[data-rail-next]');
        const rtl = getComputedStyle(rail).direction === 'rtl';
        function step(direction) {
            const amount = Math.max(rail.clientWidth * 0.72, 220);
            const delta = direction * amount * (rtl ? -1 : 1);
            rail.scrollBy({ left: delta, behavior: motion.matches ? 'auto' : 'smooth' });
        }
        if (prev) prev.addEventListener('click', function () { step(-1); });
        if (next) next.addEventListener('click', function () { step(1); });
    });
})();
