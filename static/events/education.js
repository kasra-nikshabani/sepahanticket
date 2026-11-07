(() => {
  'use strict';
  document.querySelectorAll('[data-edu-course-form]').forEach(form => {
    const kind = form.querySelector('[name="kind"]');
    const fields = ['city', 'address', 'schedule', 'start_date', 'start_time', 'end_date', 'end_time', 'registration_deadline', 'capacity'];
    function update() {
      const isClass = kind && kind.value === 'class';
      fields.forEach(name => {
        const wrapper = form.querySelector(`[data-edu-field="${name}"]`);
        if (!wrapper) return;
        wrapper.hidden = !isClass;
        wrapper.querySelectorAll('input, select, textarea').forEach(input => { input.disabled = !isClass; });
      });
      const heading = form.querySelector('[data-class-heading]');
      if (heading) heading.hidden = !isClass;
    }
    if (kind) kind.addEventListener('change', update);
    update();
  });
  document.querySelectorAll('[data-edu-upload]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity()) return;
      const feedback = form.querySelector('[data-upload-feedback]');
      if (feedback) feedback.hidden = false;
      const button = event.submitter;
      if (button) { button.disabled = true; button.textContent = 'در حال ارسال…'; }
      form.setAttribute('aria-busy', 'true');
    });
  });
})();
