(() => {
  'use strict';
  const buttons = [...document.querySelectorAll('[data-workflow-choice]')];
  const sections = [...document.querySelectorAll('[data-workflow-panel]')];
  if (!buttons.length || sections.length !== buttons.length) return;
  const isValid = key => ['batch','single','saved'].includes(key);
  const show = key => {
    if (!isValid(key)) return;
    buttons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.workflowChoice === key)));
    sections.forEach(panel => { panel.hidden = panel.dataset.workflowPanel !== key; });
  };
  buttons.forEach(b => b.addEventListener('click', () => show(b.dataset.workflowChoice)));
  show('batch');
})();
