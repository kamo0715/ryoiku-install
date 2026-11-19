(() => {
  'use strict';
  const form = document.getElementById('curriculum-multi-form');
  if (!form) return;
  const list = document.getElementById('curriculum-multi-items');
  const status = document.getElementById('curriculum-multi-status');
  const submit = document.getElementById('curriculum-multi-submit');
  const maximum = 8;
  const items = () => Array.from(list.querySelectorAll('[data-curriculum-item]'));
  const checkbox = item => item.querySelector('[data-curriculum-checkbox]');
  const chosen = () => items().filter(item => checkbox(item).checked);
  const update = () => {
    const selected = chosen();
    const titles = selected.map((item, i) => `${i + 1}. ${item.querySelector('strong')?.textContent.trim() || '活動'}`);
    status.textContent = `選択 ${selected.length}/${maximum} 件（予定の実施順）\n${titles.join(' → ') || '活動を選択してください'}`;
    submit.disabled = selected.length === 0 || selected.length > maximum;
  };
  list.addEventListener('change', e => {
    if (!e.target.matches('[data-curriculum-checkbox]')) return;
    if (chosen().length > maximum) {
      e.target.checked = false;
      status.textContent = `1日のカリキュラムは最大${maximum}件です。`;
      return;
    }
    update();
  });
  list.addEventListener('click', e => {
    const btn = e.target.closest('[data-selection-up],[data-selection-down]');
    if (!btn) return;
    const item = btn.closest('[data-curriculum-item]');
    if (!checkbox(item).checked) return;
    const seq = chosen();
    const i = seq.indexOf(item);
    const target = i + (btn.matches('[data-selection-up]') ? -1 : 1);
    if (target < 0 || target >= seq.length) return;
    const other = seq[target];
    if (target < i) list.insertBefore(item, other);
    else list.insertBefore(other, item);
    update();
  });
  form.addEventListener('submit', e => {
    if (chosen().length < 1 || chosen().length > maximum) {
      e.preventDefault();
      update();
    }
  });
  const search = document.getElementById('saved-curriculum-search');
  search?.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase('ja');
    items().forEach(item => {
      // An already-selected item must remain visible even when filtered.
      item.hidden = !checkbox(item).checked && !item.textContent.toLocaleLowerCase('ja').includes(query);
    });
  });
  update();
})();
