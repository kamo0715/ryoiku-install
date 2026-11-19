(() => {
  'use strict';
  const form = document.getElementById('batch-generate-form');
  if (!form) return;
  const rows = [...form.querySelectorAll('[data-batch-row]')];
  const status = document.getElementById('batch-selection-status');
  const submit = document.getElementById('batch-generate-submit');
  const add = document.getElementById('add-batch-activity');
  const enabled = row => row.querySelector('[data-batch-enabled]');
  const chosen = () => rows.filter(row => enabled(row).checked);
  const extra = (row) => {
    const other = row.querySelector('[data-batch-mode]')?.value === 'other';
    const kind = row.querySelector('[data-batch-kind-field]');
    if (kind) kind.hidden = !other;
    const edition = row.querySelector('[name^="batch_edition_"]')?.closest('label');
    if (edition) edition.hidden = other;
  };
  const refresh = () => {
    for (const row of rows) {
      const active = enabled(row).checked;
      row.hidden = !active;
      if (!active) row.open = false;
      const theme = row.querySelector('[data-batch-theme]')?.value.trim();
      const label = row.querySelector('[data-batch-summary-label]');
      if (label) label.textContent = theme || `活動 ${rows.indexOf(row) + 1} の内容`;
      extra(row);
    }
    const selected = chosen();
    const minutes = selected.reduce((sum, row) => sum + (Number(row.querySelector('[data-batch-duration]').value) || 0), 0);
    status.textContent = `新しく作る活動：${selected.length}件　／　合計${minutes}分`;
    const valid = selected.length >= 2 && selected.length <= 8 && minutes <= 720;
    submit.disabled = !valid;
    if (!valid) status.textContent += '　2〜8件、合計720分以内で指定してください。';
    add.hidden = selected.length >= 8;
  };
  add.addEventListener('click', () => {
    const next = rows.find(row => !enabled(row).checked);
    if (!next) return;
    enabled(next).checked = true;
    next.hidden = false;
    next.open = true;
    refresh();
    next.querySelector('summary')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest'});
    next.querySelector('[data-batch-mode]')?.focus({preventScroll:true});
  });
  rows.forEach(row => {
    row.querySelector('[data-remove-batch-row]')?.addEventListener('click', () => {
      if (chosen().length <= 2) return;
      enabled(row).checked = false;
      refresh();
      add.focus();
    });
  });
  form.addEventListener('change', refresh);
  form.addEventListener('input', refresh);
  form.addEventListener('submit', e => {
    const selected = chosen();
    if (selected.length < 2 || selected.length > 8) { e.preventDefault(); refresh(); }
  });
  refresh();
})();
