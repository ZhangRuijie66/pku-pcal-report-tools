/* 物化实验报告工具 —— 通用草稿自动保存
 *
 * 各模块在 boot 末尾调用：
 *   await PcalDraft.init({
 *     key: 'pcal-draft-xxx-v1',
 *     read: () => ({config: readConfig(), data: readData()}),
 *     apply: async (d) => { fillConfig(d.config || {}); fillData(d.data || {}); await recalc(); },
 *   });
 *
 * 之后 recalc() 末尾调 PcalDraft.save()，导出成功后调 PcalDraft.clear()。
 * 只存“未导出的编辑”，不替代 settings.json 的“存为默认”。
 */
(function () {
  'use strict';
  const MAX_AGE = 30 * 864e5;
  let options = null;
  let ready = false;
  let restoring = false;
  let timer = null;

  function readSafe() {
    try { return options.read(); } catch (e) { return null; }
  }

  function save() {
    if (!ready || restoring || !options) return;
    const data = readSafe();
    if (!data) return;
    try {
      localStorage.setItem(options.key,
        JSON.stringify({ savedAt: Date.now(), data }));
    } catch (e) { /* 隐私模式/配额满：不影响正常使用 */ }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(save, 500);
  }

  function clear() {
    if (!options) return;
    try { localStorage.removeItem(options.key); } catch (e) { /* ignore */ }
  }

  async function maybeRestore() {
    let raw = null;
    try { raw = localStorage.getItem(options.key); } catch (e) { return; }
    if (!raw) return;
    let draft = null;
    try { draft = JSON.parse(raw); } catch (e) { clear(); return; }
    if (!draft || !draft.savedAt || !draft.data) { clear(); return; }
    if (Date.now() - draft.savedAt > MAX_AGE) { clear(); return; }
    const when = new Date(draft.savedAt).toLocaleString();
    if (!confirm('发现上次未导出的编辑（' + when + '），是否恢复？\n取消则保留草稿，下次打开再问。')) {
      return;
    }
    restoring = true;
    try {
      await options.apply(draft.data);
    } catch (e) {
      alert('草稿恢复失败：' + (e && e.message ? e.message : e));
    } finally {
      restoring = false;
    }
  }

  async function init(opts) {
    options = opts;
    document.addEventListener('input', schedule);
    document.addEventListener('change', schedule);
    await maybeRestore();
    ready = true;
  }

  window.PcalDraft = { init, save, schedule, clear };
})();
