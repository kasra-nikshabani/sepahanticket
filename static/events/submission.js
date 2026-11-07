(() => {
  const form = document.querySelector('[data-submission-form]');
  if (!form) return;
  const submitButtons = [...form.querySelectorAll('button[type="submit"]'),
    ...document.querySelectorAll('button[form="wizard-form"]')];
  const buttonContents = new Map(submitButtons.map(button => [button, button.innerHTML]));
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    submitButtons.forEach(button => {
      button.disabled = false;
      button.innerHTML = buttonContents.get(button);
    });
    form.querySelectorAll('[data-wizard-action]').forEach(input => input.remove());
  });
  let dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  window.addEventListener('beforeunload', event => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  const latin = value => value.replace(/[۰-۹]/g, digit => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(digit))).replace(/[٠-٩]/g, digit => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)));
  const persian = value => value.replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
  form.querySelectorAll('[name="category"]').forEach(radio => {
    radio.addEventListener('change', () => {
      const prefix = form.querySelector('[name="prefix"]');
      if (prefix && ['', 'نمایش', 'کنسرت', 'رویداد'].includes(prefix.value)) {
        prefix.value = { theater: 'نمایش', concert: 'کنسرت', event: 'رویداد' }[radio.value] || '';
      }
    });
  });
  form.querySelectorAll('[data-persian-number]').forEach(input => {
    input.value = persian(input.value);
    input.addEventListener('input', () => {
      const position = input.selectionStart;
      input.value = persian(latin(input.value));
      input.setSelectionRange(position, position);
    });
  });
  ['general', 'group', 'loyalty', 'student'].forEach(kind => {
    const checkbox = form.querySelector(`[name="${kind}_discount"]`);
    if (!checkbox) return;
    const fields = [`${kind}_percent`, ...(kind === 'group' ? ['group_minimum'] : [])];
    const update = () => fields.forEach(name => {
      const wrapper = form.querySelector(`[data-field="${name}"]`);
      if (wrapper) wrapper.hidden = !checkbox.checked;
    });
    checkbox.addEventListener('change', update);
    update();
  });
  form.querySelectorAll('[data-upload-preview]').forEach(input => {
    let urls = [];
    input.addEventListener('change', () => {
      urls.forEach(url => URL.revokeObjectURL(url));
      urls = [];
      const preview = input.closest('.wizard-upload-box').querySelector('.wizard-upload-preview');
      preview.replaceChildren();
      const files = Array.from(input.files || []);
      files.slice(0, 10).forEach(file => {
        const name = document.createElement('span');
        name.textContent = persian(file.name);
        preview.append(name);
        if (file.type.startsWith('image/')) {
          const img = document.createElement('img');
          img.alt = `پیش‌نمایش ${persian(file.name)}`;
          img.src = URL.createObjectURL(file);
          urls.push(img.src);
          preview.append(img);
        }
      });
    });
    window.addEventListener('pagehide', () => urls.forEach(url => URL.revokeObjectURL(url)));
  });
  const errors = document.querySelector('.wizard-error-summary');
  if (errors) errors.focus({ preventScroll: false });
  form.addEventListener('submit', event => {
    dirty = false;
    // Convert visual Persian digits; the server also accepts them without JavaScript.
    form.querySelectorAll('[data-persian-number]').forEach(input => { input.value = latin(input.value); });
    const button = event.submitter;
    if (button) {
      // Keep the clicked action included in POST, while preventing duplicate clicks.
      const action = document.createElement('input');
      action.type = 'hidden'; action.name = button.name; action.value = button.value;
      action.dataset.wizardAction = '';
      form.append(action);
      submitButtons.forEach(item => { item.disabled = true; });
      button.textContent = 'در حال ذخیره…';
    }
  });
})();
