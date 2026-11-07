(function () {
    'use strict';
    const button = document.getElementById('add-scene');
    if (!button) return;
    const total = document.getElementById('id_scenes-TOTAL_FORMS');
    const maximum = Number(document.getElementById('id_scenes-MAX_NUM_FORMS').value);
    button.addEventListener('click', function () {
        const index = Number(total.value);
        if (index >= maximum) return;
        const template = document.getElementById('empty-scene');
        const fragment = template.content.cloneNode(true);
        fragment.querySelectorAll('[name], [id], [for]').forEach(function (node) {
            ['name', 'id', 'for'].forEach(function (attribute) {
                if (node.hasAttribute(attribute)) {
                    node.setAttribute(attribute, node.getAttribute(attribute).replace(/__prefix__/g, String(index)));
                }
            });
        });
        document.getElementById('scene-forms').appendChild(fragment);
        total.value = index + 1;
        button.disabled = Number(total.value) >= maximum;
    });
})();
