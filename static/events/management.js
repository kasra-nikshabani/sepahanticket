(() => {
  'use strict';
  const toggle = document.querySelector('[data-panel-toggle]');
  const close = document.querySelector('[data-panel-close]');
  const overlay = document.querySelector('[data-panel-overlay]');
  const sidebar = document.getElementById('panel-sidebar');
  const desktop = window.matchMedia('(min-width: 1101px)');
  function opened(value) {
    document.body.classList.toggle('panel-menu-open', value);
    overlay.hidden = !value;
    toggle.setAttribute('aria-expanded', String(value));
    sidebar.inert = !desktop.matches && !value;
    if (value) close.focus();
  }
  toggle?.addEventListener('click', () => opened(!document.body.classList.contains('panel-menu-open')));
  close?.addEventListener('click', () => { opened(false); toggle.focus(); });
  overlay?.addEventListener('click', () => opened(false));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('panel-menu-open')) {
      opened(false); toggle.focus();
    }
    if (event.key === 'Tab' && document.body.classList.contains('panel-menu-open')) {
      const focusable = [...sidebar.querySelectorAll('a,button')];
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  desktop.addEventListener('change', () => opened(false));
  opened(false);
})();
