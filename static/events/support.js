(() => {
  const form = document.querySelector('[data-support-create]');
  if (!form) return;
  const category = form.querySelector('[name="category"]');
  const wrapper = form.querySelector('[data-support-event]');
  if (!wrapper) return;
  const event = wrapper.querySelector('select');
  const locked = event.disabled;
  const sync = () => {
    const program = category.value === 'program';
    wrapper.hidden = !program;
    event.disabled = locked || !program;
    event.required = program;
  };
  category.addEventListener('change', sync);
  sync();
})();
