(() => {
  'use strict';
  const form = document.getElementById('day-flow-form');
  if (!form) return;
  const group = form.querySelector('.audience-selector');
  const sections = [...form.querySelectorAll('[data-audience-fields]')];
  if (!group || sections.length !== 3) return;
  function update() {
    const target = group.querySelector('input[name="audience"]:checked')?.value || 'child';
    sections.forEach(section => {
      const visible = section.dataset.audienceFields === target;
      section.hidden = !visible;
      section.querySelectorAll('[name="child_review"], [name="share_review"]').forEach(box => {
        box.required = visible;
        if (!visible) box.checked = false;
      });
    });
  }
  group.addEventListener('change', update);
  update();
})();
