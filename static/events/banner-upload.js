(() => {
  const input = document.querySelector('[data-banner-upload]');
  const preview = document.querySelector('[data-banner-preview]');
  const empty = document.querySelector('[data-banner-empty]');
  if (!input || !preview || !empty) return;
  const original = preview.getAttribute('src');
  let localUrl;
  input.addEventListener('change', () => {
    if (localUrl) URL.revokeObjectURL(localUrl);
    localUrl = undefined;
    const file = input.files?.[0];
    if (file && ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      localUrl = URL.createObjectURL(file);
      preview.src = localUrl; preview.hidden = false; empty.hidden = true;
    } else {
      if (original) preview.src = original;
      else preview.removeAttribute('src');
      preview.hidden = !original; empty.hidden = Boolean(original);
    }
  });
  window.addEventListener('pagehide', () => { if (localUrl) URL.revokeObjectURL(localUrl); });
})();
