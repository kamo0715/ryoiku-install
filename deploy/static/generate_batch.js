(() => {
  'use strict';
  const form = document.getElementById('batch-generate-form');
  if (!form) return;
  const rows = Array.from(form.querySelectorAll('[data-batch-row]'));
  const status = document.getElementById('batch-selection-status');
  const button = document.getElementById('batch-generate-submit');
  function update() {
    const selected = rows.filter(row => row.querySelector('[data-batch-enabled]').checked);
    const minutes = selected.reduce((sum,row) => sum + (parseInt(row.querySelector('[data-batch-duration]').value, 10) || 0), 0);
    status.textContent = `新しく生成する活動：${selected.length}件 ／ 活動時間合計：${minutes}分（休憩・移動は次画面で追加）`;
    const good = selected.length >= 2 && selected.length <= 8 && minutes <= 720;
    button.disabled = !good;
    if (!good) status.textContent += '　2～8件を選び、活動時間の合計を720分以内にしてください。';
  }
  form.addEventListener('change',update);
  form.addEventListener('input',update);
  update();
})();
