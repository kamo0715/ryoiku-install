/** Modern Web Guidance: progressive enhancement, safe DOM APIs and focus management. */
(() => {
  'use strict';
  const q = (selector, root = document) => root.querySelector(selector);
  const qa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  // When an error is returned from the server, move focus to its explanation.
  const serverError = q('[data-server-error]');
  if (serverError) serverError.focus({ preventScroll: true });

  // Search is optional; the full list works without JavaScript.
  const filter = q('#filter');
  if (filter) {
    const children = qa('.child[data-search]');
    const count = q('#filter-count');
    const update = () => {
      const query = filter.value.trim().toLocaleLowerCase('ja-JP');
      let visible = 0;
      children.forEach(node => {
        node.hidden = !node.dataset.search.toLocaleLowerCase('ja-JP').includes(query);
        if (!node.hidden) visible++;
      });
      if (count) count.textContent = `${visible}件の利用者が見つかりました`;
    };
    filter.addEventListener('input', update);
    update();
  }

  // Make native validation clear only after interaction. No early error messages.
  qa('input:not([type="hidden"]), select, textarea').forEach(field => {
    const mark = () => {
      const isBad = !field.checkValidity();
      if (isBad) field.setAttribute('aria-invalid', 'true');
      else field.removeAttribute('aria-invalid');
      const errorId = field.dataset.errorId;
      if (!errorId && !isBad) return;
      let status = errorId ? document.getElementById(errorId) : null;
      if (!status && isBad) {
        status = document.createElement('span');
        status.id = `input-error-${Math.random().toString(36).slice(2, 12)}`;
        status.className = 'field-error';
        field.dataset.errorId = status.id;
        const parent = field.closest('label') || field.parentElement;
        parent?.append(status);
      }
      if (status) {
        status.textContent = isBad ? field.validationMessage : '';
        const current = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        if (isBad && !current.includes(status.id)) current.push(status.id);
        if (!isBad) {
          const i = current.indexOf(status.id);
          if (i !== -1) current.splice(i, 1);
        }
        if (current.length) field.setAttribute('aria-describedby', current.join(' '));
        else field.removeAttribute('aria-describedby');
      }
    };
    field.addEventListener('blur', mark);
    field.addEventListener('change', () => { if (field.hasAttribute('aria-invalid')) mark(); });
    field.addEventListener('input', () => { if (field.hasAttribute('aria-invalid')) mark(); });
  });

  // Confirm potentially irreversible actions with a native <dialog>.
  const dialog = q('#confirm-dialog');
  let confirmState = null;
  if (dialog) {
    q('[data-dialog-cancel]', dialog)?.addEventListener('click', () => dialog.close('cancel'));
    q('[data-dialog-accept]', dialog)?.addEventListener('click', () => dialog.close('accept'));
    dialog.addEventListener('close', () => {
      const state = confirmState;
      confirmState = null;
      if (!state) return;
      if (dialog.returnValue === 'accept') {
        state.form.dataset.confirmed = 'true';
        state.form.requestSubmit(state.submitter || undefined);
      } else {
        state.submitter?.focus();
      }
    });
  }
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.confirmed === 'true') { delete form.dataset.confirmed; return; }
    if (form.dataset.confirm) {
      if (!form.reportValidity()) return;
      event.preventDefault();
      if (!dialog?.showModal) {
        if (window.confirm(form.dataset.confirm)) {
          form.dataset.confirmed = 'true';
          form.requestSubmit(event.submitter || undefined);
        }
        return;
      }
      confirmState = { form, submitter: event.submitter };
      q('#confirm-message').textContent = form.dataset.confirm;
      dialog.showModal();
      q('[data-dialog-cancel]', dialog)?.focus();
    }
  }, true);

  // AI提供元を切り替えると、以前その提供元で設定したモデルIDを復元する。
  const aiProvider = q('#ai-provider');
  const aiModel = q('#ai-model');
  if (aiProvider && aiModel) {
    aiProvider.addEventListener('change', () => {
      const option = aiProvider.selectedOptions[0];
      const saved = option?.dataset.model || '';
      const example = option?.dataset.example || '';
      aiModel.value = saved || (/^[\w.\-:/]{2,120}$/.test(example) ? example : '');
      aiModel.placeholder = example || '公式モデルIDを入力';
      aiModel.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  // Progressive enhancement of the curriculum selector.
  const form = q('#genform');
  if (form) {
    const mode = q('#activity_mode');
    const kind = q('#kind_code');
    const group = q('#kind_group');
    const kindWrap = q('#kind_wrap');
    const custom = q('#custom_wrap');
    const edition = q('#edition_wrap');
    const hint = q('#category_hint');
    const hintText = q('#category_hint_text');
    const customActivity = q('#custom_activity');
    let focusByGroup = {}, safetyByGroup = {};
    try { focusByGroup = JSON.parse(form.dataset.focusByGroup || '{}'); } catch (_) { /* fallback */ }
    try { safetyByGroup = JSON.parse(form.dataset.safetyByGroup || '{}'); } catch (_) { /* fallback */ }
    const options = Array.from(kind.options, item => item.cloneNode(true));
    const syncKinds = () => {
      const selected = kind.value;
      kind.replaceChildren(...options.filter(item => item.dataset.group === group.value).map(item => item.cloneNode(true)));
      if (Array.from(kind.options).some(item => item.value === selected)) kind.value = selected;
    };
    const update = () => {
      const other = mode.value === 'other';
      kindWrap.hidden = !other;
      edition.hidden = other;
      hint.hidden = !other;
      custom.hidden = !other || kind.value !== 'other';
      customActivity.required = other && kind.value === 'other';
      kind.disabled = !other;
      if (other) {
        hintText.textContent = [group.value,kind.selectedOptions[0]?.textContent || '選択してください',
          `着目点：${focusByGroup[group.value] || '個別支援計画を確認'}`,
          `安全面：${safetyByGroup[group.value] || '活動に応じて確認'}`].join(' ／ ');
      }
    };
    group.addEventListener('change', () => { syncKinds(); update(); });
    mode.addEventListener('change', update);
    kind.addEventListener('change', update);
    syncKinds();
    update();
    form.addEventListener('submit', () => {
      const button = q('#generateButton');
      if (button && form.checkValidity()) {
        button.disabled = true;
        button.textContent = '計画案を作成しています…';
        const status = q('#generation-status');
        if (status) status.textContent = '計画案を作成しています。画面を閉じずにお待ちください。';
      }
    });
  }
})();
