(function () {
    'use strict';
    document.querySelectorAll('[data-close-welcome]').forEach(function (button) {
        button.addEventListener('click', function (event) {
            button.closest('[data-welcome-notice]').remove();
            if (event.detail === 0) {
                const main = document.querySelector('main');
                if (main) {
                    main.setAttribute('tabindex', '-1');
                    main.focus({ preventScroll: true });
                }
            }
        });
    });
})();
