/* 溶液表面吸附实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const DATA_FIELDS = ['temperature_bubble', 'temperature_plate', 'gamma_water',
  'sigma_read', 'sigma_plate'];
const PROC_FIELDS = ['conc_axis', 'zero_correction', 'height_mode',
  'repeat_n_bubble', 'repeat_n_plate'];

let STATE = null;
let DATA = null;
let HMODE = 'both';      // 液柱读数方式：both / left / right
let HSUM_AUTO = null;    // 后端由现有读数估计的两臂高度之和 / cm

/* ---------------------------------------------------------------- 小工具 */
function toast(msg, ms = 2800) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), ms);
}
function busy(on, text) {
  $('overlay').classList.toggle('show', !!on);
  if (text) $('overlayText').textContent = text;
}
function setStatus(s, cls) {
  const el = $('status');
  el.textContent = s;
  el.className = 'sub' + (cls ? ' ' + cls : '');
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function num(v, d = 3) {
  if (v == null || v === '' || isNaN(v)) return '—';
  return Number(v).toFixed(d);
}
function pm(x, u, d = 3) {
  if (x == null || isNaN(x)) return '—';
  if (u == null || isNaN(u) || Number(u) === 0) return num(x, d);
  return num(x, d) + ' ± ' + num(u, d);
}
const SUP = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
  '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
function sup(n) { return String(n).split('').map((c) => SUP[c] || c).join(''); }
function sci(x, u, exp = -6) {
  if (x == null || isNaN(x)) return '—';
  const s = Math.pow(10, exp);
  const v = pm(x / s, u == null ? null : u / s, 2);
  return '(' + v + ')×10' + sup(exp);
}
async function api(path, opts) {
  const res = await fetch(path, Object.assign({ cache: 'no-store' }, opts || {}));
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}

/* ---------------------------------------------------------------- 液柱高度换算 */
function derivedSide() {
  return HMODE === 'left' ? 'right' : (HMODE === 'right' ? 'left' : null);
}
function sumValue() {
  const raw = ($('height_sum') || {}).value;
  const v = parseFloat(raw);
  if (raw !== '' && raw !== undefined && isFinite(v) && v > 0) return v;
  return (HSUM_AUTO != null && isFinite(HSUM_AUTO) && HSUM_AUTO > 0) ? HSUM_AUTO : null;
}
function rnd(v) { return Math.round(v * 1e4) / 1e4; }
function range(n) { return Array.from({ length: n }, (_, i) => i); }
function repeatN(kind) {
  const el = $(kind === 'plate' ? 'repeat_n_plate' : 'repeat_n_bubble');
  const v = Number((el || {}).value);
  return (isFinite(v) && v >= 2 && v <= 6) ? Math.round(v) : 3;
}
function autoValue(srcValue) {
  const total = sumValue();
  const v = srcValue === '' || srcValue == null ? null : Number(srcValue);
  if (total == null || v == null || isNaN(v)) return '';
  return rnd(total - v);
}

/* ---------------------------------------------------------------- 表单 */
function fillConfig(c) {
  COVER_FIELDS.concat(PROC_FIELDS).forEach((k) => {
    const el = $(k);
    if (!el) return;
    if (k === 'zero_correction') el.value = c[k] ? '1' : '0';
    else if (k === 'height_sum') {
      const v = Number(c[k]);
      el.value = (c[k] == null || !isFinite(v) || v === 0) ? '' : v;
    } else el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  HMODE = ($('height_mode').value || 'both');
  updateSumPlaceholder();
}
function updateSumPlaceholder() {
  const el = $('height_sum');
  if (!el) return;
  el.placeholder = (HSUM_AUTO != null && isFinite(HSUM_AUTO))
    ? '自动估计 ' + Number(HSUM_AUTO).toFixed(2)
    : '留空 = 自动估计';
  const d = derivedSide();
  const missing = !!(d && sumValue() == null);
  el.classList.toggle('need', missing);
  const hint = $('heightHint');
  if (hint) hint.style.color = missing ? 'var(--err)' : '';
}
function readConfig() {
  const cfg = {};
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    cfg[k] = el.type === 'number'
      ? (el.value === '' ? null : Number(el.value)) : el.value;
  });
  cfg.conc_axis = $('conc_axis').value;
  cfg.zero_correction = $('zero_correction').value === '1';
  cfg.height_mode = $('height_mode').value || 'both';
  cfg.height_sum = $('height_sum').value === '' ? 0 : Number($('height_sum').value);
  cfg.repeat_n_bubble = repeatN('bubble');
  cfg.repeat_n_plate = repeatN('plate');
  return cfg;
}
function fillData(d) {
  DATA = d || {};
  DATA_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) el.value = (DATA[k] === null || DATA[k] === undefined) ? '' : DATA[k];
  });
  renderTrio('zero');
  renderTrio('water');
  renderRows('bubble');
  renderRows('plate');
  updateSumPlaceholder();
}

function readTrio(kind) {
  const elId = kind === 'zero' ? 'zeroTable' : 'waterTable';
  const left = [], right = [];
  document.querySelectorAll('#' + elId + ' input[data-side]').forEach((inp) => {
    if (inp.disabled) return;                 // 自动换算的一侧不当作实测值
    const v = inp.value === '' ? null : Number(inp.value);
    const arr = inp.dataset.side === 'left' ? left : right;
    const i = Number(inp.dataset.i);
    arr[i] = v;
  });
  return { left: left.filter((v) => v != null), right: right.filter((v) => v != null) };
}

function readRows(kind) {
  const tbl = kind === 'bubble' ? $('bubbleTable') : $('plateTable');
  const rows = [];
  tbl.querySelectorAll('tbody tr[data-row]').forEach((tr) => {
    const cInp = tr.querySelector('input[data-f="c"]');
    const c = cInp && cInp.value !== '' ? Number(cInp.value) : null;
    if (c == null) return;
    if (kind === 'bubble') {
      const left = [], right = [];
      tr.querySelectorAll('input[data-f="left"]').forEach((inp) => {
        if (!inp.disabled && inp.value !== '') left.push(Number(inp.value));
      });
      tr.querySelectorAll('input[data-f="right"]').forEach((inp) => {
        if (!inp.disabled && inp.value !== '') right.push(Number(inp.value));
      });
      const fit = tr.querySelector('input[data-f="fit"]');
      rows.push({ c, left, right, fit: !!(fit && fit.checked) });
    } else {
      const gamma = [];
      tr.querySelectorAll('input[data-f="gamma"]').forEach((inp) => {
        if (inp.value !== '') gamma.push(Number(inp.value));
      });
      const fit = tr.querySelector('input[data-f="fit"]');
      rows.push({ c, gamma, fit: !!(fit && fit.checked) });
    }
  });
  return rows;
}

function readData() {
  const d = Object.assign({}, DATA || {});
  DATA_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) d[k] = el.value === '' ? null : Number(el.value);
  });
  d.zero = readTrio('zero');
  d.water_bubble = readTrio('water');
  d.bubble = readRows('bubble');
  d.plate = readRows('plate');
  return d;
}

/* ---------------------------------------------------------------- 表格渲染 */
function inputCell(kind, field, i, value, extra) {
  return '<td><input type="number" step="any" data-kind="' + kind + '" data-f="' +
    field + '" data-i="' + i + '"' + (extra || '') + ' value="' +
    (value == null || isNaN(value) ? '' : esc(value)) + '"></td>';
}

/* 由另一侧按 S 换算出来的单元格：灰底、不可编辑、不进数据 */
function autoCell(attrs, value) {
  return '<td><input type="number" step="any" disabled class="auto"' +
    attrs + ' value="' + (value === '' || value == null ? '' : esc(value)) + '"></td>';
}

function renderTrio(kind) {
  const el = kind === 'zero' ? $('zeroTable') : $('waterTable');
  const key = kind === 'zero' ? 'zero' : 'water_bubble';
  const obj = (DATA && DATA[key]) || {};
  const left = obj.left || [], right = obj.right || [];
  const dside = derivedSide();
  const n = repeatN('bubble');
  let html = '<thead><tr><th>组别</th><th>h_left / cm</th><th>h_right / cm</th></tr></thead><tbody>';
  for (let i = 0; i < n; i += 1) {
    const cells = ['left', 'right'].map((side) => {
      const attrs = ' data-side="' + side + '" data-i="' + i + '"';
      if (side === dside) return autoCell(attrs, autoValue(side === 'right' ? left[i] : right[i]));
      const v = side === 'left' ? left[i] : right[i];
      return '<td><input type="number" step="any"' + attrs + ' value="' +
        (v == null ? '' : esc(v)) + '"></td>';
    }).join('');
    html += '<tr data-trio="' + i + '"><td>' + (i + 1) + '</td>' + cells + '</tr>';
  }
  el.innerHTML = html + '</tbody>';
}

function renderRows(kind) {
  const tbl = kind === 'bubble' ? $('bubbleTable') : $('plateTable');
  const rows = (DATA && DATA[kind]) || [];
  const dside = derivedSide();
  const n = repeatN(kind);
  let html;
  if (kind === 'bubble') {
    html = '<thead><tr><th>#</th><th>c / (mol·dm⁻³)</th>' +
      range(n).map((j) => '<th>h_l' + (j + 1) + '</th>').join('') +
      range(n).map((j) => '<th>h_r' + (j + 1) + '</th>').join('') +
      '<th>拟合</th><th></th></tr></thead><tbody>';
    rows.forEach((r, i) => {
      const left = r.left || [], right = r.right || [];
      const cell = (side, j) => {
        if (side === dside) {
          const src = side === 'right' ? left[j] : right[j];
          return autoCell(' data-kind="bubble" data-f="' + side + '" data-i="' + j + '"',
            autoValue(src));
        }
        return inputCell('bubble', side, j, side === 'left' ? left[j] : right[j]);
      };
      html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
        inputCell('bubble', 'c', i, r.c) +
        range(n).map((j) => cell('left', j)).join('') +
        range(n).map((j) => cell('right', j)).join('') +
        '<td><input type="checkbox" data-f="fit"' + (r.fit ? ' checked' : '') + '></td>' +
        '<td><button class="btn mini" data-del="bubble" data-i="' + i + '">删</button></td></tr>';
    });
  } else {
    html = '<thead><tr><th>#</th><th>c / (mol·dm⁻³)</th>' +
      range(n).map((j) => '<th>γ' + (j + 1) + '</th>').join('') +
      '<th>拟合</th><th></th></tr></thead><tbody>';
    rows.forEach((r, i) => {
      const gamma = r.gamma || [];
      html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
        inputCell('plate', 'c', i, r.c) +
        range(n).map((j) => inputCell('plate', 'gamma', j, gamma[j])).join('') +
        '<td><input type="checkbox" data-f="fit"' + (r.fit ? ' checked' : '') + '></td>' +
        '<td><button class="btn mini" data-del="plate" data-i="' + i + '">删</button></td></tr>';
    });
  }
  tbl.innerHTML = html + '</tbody>';
}

/* 输入已测一侧时，实时刷新同一行的换算值 */
function syncDerivedInRow(row) {
  const dside = derivedSide();
  if (!dside) return;
  const src = dside === 'right' ? 'left' : 'right';
  const sideInp = row.querySelector('input[data-side="' + src + '"]');
  if (sideInp) {
    const dst = row.querySelector('input[data-side="' + dside + '"]');
    if (dst) dst.value = autoValue(sideInp.value);
    return;
  }
  row.querySelectorAll('input[data-f="' + src + '"]').forEach((si) => {
    const di = row.querySelector('input[data-f="' + dside +
      '"][data-i="' + si.dataset.i + '"]');
    if (di) di.value = autoValue(si.value);
  });
}

function refreshTables() {
  renderTrio('zero');
  renderTrio('water');
  renderRows('bubble');
  renderRows('plate');
  updateSumPlaceholder();
}

/* ---------------------------------------------------------------- 结果 */
function renderResults(s) {
  const b = s.bubble, p = s.plate;
  const rows = [b, p].map((m) => (
    '<tr><td>' + esc(m.label) + '</td><td>' + num(m.temperature, 2) + '</td>' +
    '<td>' + sci(m.gamma_inf, m.sigma_gamma_inf) + ' mol·m⁻²</td>' +
    '<td>' + pm(m.q, m.sigma_q, 4) + ' nm²</td>' +
    '<td>' + (m.fit ? num(m.fit.r2, 4) : '—') + '</td>' +
    '<td>' + (m.fit ? m.fit.n : '—') + '</td></tr>'
  )).join('');
  $('resultTable').innerHTML =
    '<thead><tr><th>方法</th><th>T /℃</th><th>Γ∞</th><th>q</th>' +
    '<th>R²</th><th>拟合点数</th></tr></thead><tbody>' + rows + '</tbody>';
  let note = 'q = 1/(Γ∞N_A)；q_c 见下表。';
  if (s.comparison) {
    note += ' 两法 Γ∞ 相差 ' + num(Math.abs(s.comparison.rel_gamma), 1) +
      '%，q 相差 ' + num(Math.abs(s.comparison.rel_q), 1) + '%。';
  }
  $('resultNote').textContent = note;

  const qrows = [];
  [b, p].forEach((m) => {
    (m.qc_rows || []).forEach((r) => {
      qrows.push('<tr><td>' + esc(m.label) + '</td><td>' + esc(r.c) + '</td>' +
        '<td>' + pm(r.qc, r.sigma, 4) + '</td>' +
        '<td>' + (r.rel == null || isNaN(r.rel) ? '—' :
          (r.rel >= 0 ? '+' : '') + num(r.rel, 1) + '%') + '</td></tr>');
    });
  });
  $('qcTable').innerHTML = qrows.length
    ? '<thead><tr><th>方法</th><th>c / (mol·dm⁻³)</th><th>q_c / nm²</th><th>相对偏差</th></tr></thead><tbody>' +
      qrows.join('') + '</tbody>'
    : '<tr><td class="hint">还没有可用的拟合结果。</td></tr>';
}

function renderWarnings(s) {
  const list = (s.warnings || []).slice();
  if (s.config && !s.config.student_name) list.push('封面「姓名」为空');
  if (s.config && !s.config.student_id) list.push('封面「学号」为空');
  if (!list.length) { $('warnCard').style.display = 'none'; return; }
  $('warnCard').style.display = '';
  $('warns').innerHTML = list.map((w) => '<div class="msg">' + esc(w) + '</div>').join('');
}

function renderState(s) {
  STATE = s;
  HSUM_AUTO = (s.height && s.height.estimate != null) ? s.height.estimate : null;
  fillConfig(s.config);
  fillData(s.data);
  $('dataFile').textContent = s.data_file || '';
  setStatus('数据文件：' + (s.data_file || '—'));
  renderResults(s);
  renderWarnings(s);
  drawChart();
}

/* ---------------------------------------------------------------- 图表 */
function drawChart() {
  const kind = $('chartKind').value;
  $('chart').src = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
  const hints = {
    bubble_curve: '全部浓度点 + 误差棒；实心方块为参与拟合的线性区选点',
    bubble_fit: '高浓度线性区拟合；注记为拟合式、R² 与 Γ∞',
    plate_curve: '吊片法全部数据；空心圆为未参与拟合的点',
    plate_fit: '吊片法线性区拟合',
    qc: '两种方法经浓度修正后的分子面积随浓度的变化',
  };
  $('chartHint').textContent = hints[kind] || '';
}

/* ---------------------------------------------------------------- 动作 */
async function boot() {
  setStatus('正在初始化…');
  try {
    const s = await api('/api/state');
    renderState(s);
    const q = new URLSearchParams(location.search);
    const home = q.get('home');
    if (home) {
      $('btnHome').href = home;
      $('btnHome').style.display = '';
    }
    setStatus('就绪');
    await PcalDraft.init({
      key: 'pcal-draft-adsorption-v1',
      read: () => ({config: readConfig(), data: readData()}),
      apply: async (d) => {
        fillConfig(d.config || {});
        fillData(d.data || {});
        await recalc();
      },
    });
  } catch (e) {
    setStatus('初始化失败：' + e.message, 'err');
    toast('初始化失败：' + e.message, 5000);
  }
}

async function recalc() {
  busy(true, '重新计算中…');
  setStatus('计算中…');
  try {
    const s = await api('/api/calc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig(), data: readData() }),
    });
    STATE = s;
    HSUM_AUTO = (s.height && s.height.estimate != null) ? s.height.estimate : null;
    fillConfig(s.config);
    fillData(s.data);
    renderResults(s);
    renderWarnings(s);
    drawChart();
    setStatus('已重新计算');
    toast('计算完成');
    if (window.PcalDraft) PcalDraft.save();
  } catch (e) {
    setStatus('计算失败：' + e.message, 'err');
    toast('计算失败：' + e.message, 5000);
  } finally { busy(false); }
}

async function doExport() {
  busy(true, '生成 Word 报告中…');
  try {
    const r = await api('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig(), data: readData() }),
    });
    busy(false);
    setStatus('已生成报告');
    const logs = (r.logs || []).slice(-3).join('；');
    toast('已生成：' + r.path, 7000);
    if (window.PcalDraft) PcalDraft.clear();
    alert('报告已生成：\n' + r.path + (r.note ? '\n\n' + r.note : '') +
      (logs ? '\n\n' + logs : ''));
  } catch (e) {
    busy(false);
    setStatus('生成失败：' + e.message, 'err');
    toast('生成失败：' + e.message, 5000);
  }
}

/* 把计算结果导出成数据表（xlsx 多工作表 / csv 单张长表） */
async function exportTable(fmt) {
  busy(true, '导出数据表…');
  setStatus('导出中…');
  try {
    const r = await api('/api/export_data?fmt=' + encodeURIComponent(fmt), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig(), data: readData() }),
    });
    busy(false);
    setStatus('已导出数据表');
    toast('已导出：' + r.path + (r.note ? '（' + r.note + '）' : ''), 7000);
  } catch (e) {
    busy(false);
    setStatus('导出失败：' + e.message, 'err');
    toast('导出失败：' + e.message, 5000);
  }
}

async function saveDefault() {
  busy(true, '保存中…');
  try {
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
    });
    toast('已存为默认（settings.json 在工具目录里）');
  } catch (e) { toast('保存失败：' + e.message); }
  finally { busy(false); }
}

async function saveData() {
  busy(true, '保存数据…');
  try {
    await api('/api/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: readData() }),
    });
    toast('数据已保存到 ' + ($('dataFile').textContent || 'data/'));
  } catch (e) { toast('保存失败：' + e.message); }
  finally { busy(false); }
}

async function loadSample() {
  busy(true, '载入示例数据…');
  try {
    const r = await api('/api/sample');
    DATA = r.data;
    $('zero_correction').value = '0';
    fillData(DATA);
    await recalc();
    toast('已载入 2025 年示例数据（不扣零点口径）');
  } catch (e) { toast('载入失败：' + e.message); }
  finally { busy(false); }
}

async function importFile() {
  const f = $('fileInput').files[0];
  if (!f) { toast('先选择一个 CSV/TXT 文件'); return; }
  const kind = $('importKind').value;
  busy(true, '读取文件…');
  try {
    const text = await f.text();
    const r = await api('/api/import?kind=' + encodeURIComponent(kind), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (kind === 'bubble') {
      DATA.bubble = r.rows;
      syncRepeatN('bubble', r.rows.map((x) => (x.left || []).length));
    } else if (kind === 'plate') {
      DATA.plate = r.rows;
      syncRepeatN('plate', r.rows.map((x) => (x.gamma || []).length));
    } else DATA[kind] = { left: r.left, right: r.right };
    fillData(DATA);
    await recalc();
    toast('已导入 ' + r.count + ' 行');
  } catch (e) { toast('导入失败：' + e.message, 5000); }
  finally { busy(false); $('fileInput').value = ''; }
}

/* 导入的数据若是 5 次平行，自动把对应方法的次数下拉调过去 */
function syncRepeatN(kind, lengths) {
  const el = $(kind === 'plate' ? 'repeat_n_plate' : 'repeat_n_bubble');
  const n = Math.max(0, ...lengths.filter((v) => isFinite(v)));
  if (el && n >= 2 && n <= 6 && String(n) !== el.value) {
    el.value = String(n);
    toast('已按导入数据把' + (kind === 'plate' ? '吊片法' : '气泡法')
      + '平行次数设为 ' + n + ' 次');
  }
}

function addRow(kind) {
  const d = readData();
  if (kind === 'bubble') {
    d.bubble.push({ c: null, left: [], right: [], fit: false });
  } else {
    d.plate.push({ c: null, gamma: [], fit: false });
  }
  DATA = d;
  renderRows(kind);
  updateSumPlaceholder();
}

function deleteRow(kind, i) {
  const d = readData();
  const rows = kind === 'bubble' ? d.bubble : d.plate;
  rows.splice(i, 1);
  DATA = d;
  renderRows(kind);
}

/* 从当前表格里两侧都填了的读数估一个 S（切换读数方式时用，免得丢 S） */
function estimateSumFromDom() {
  const sums = [];
  const push = (a, b) => {
    if (a && b && a.value !== '' && b.value !== '') {
      const v = Number(a.value) + Number(b.value);
      if (isFinite(v)) sums.push(v);
    }
  };
  document.querySelectorAll('#zeroTable tr, #waterTable tr').forEach((tr) => {
    push(tr.querySelector('input[data-side="left"]'),
      tr.querySelector('input[data-side="right"]'));
  });
  document.querySelectorAll('#bubbleTable tbody tr').forEach((tr) => {
    for (let j = 0; j < repeatN('bubble'); j += 1) {
      push(tr.querySelector('input[data-f="left"][data-i="' + j + '"]'),
        tr.querySelector('input[data-f="right"][data-i="' + j + '"]'));
    }
  });
  if (!sums.length) return null;
  sums.sort((a, b) => a - b);
  return rnd(sums[Math.floor(sums.length / 2)]);
}

function onModeChange() {
  const next = $('height_mode').value || 'both';
  // 先把当前表格里两侧都有的读数综合出来的 S 固化下来，避免切换后无从换算
  const guess = estimateSumFromDom();
  if ($('height_sum').value === '' && guess != null) $('height_sum').value = guess;
  DATA = readData();               // 旧模式下可编辑的读数先落盘
  HMODE = next;
  refreshTables();
  recalc();
  persistConfig();
  if (HMODE !== 'both') {
    const ok = sumValue() != null;
    toast(ok
      ? '已切换：' + (HMODE === 'left' ? '右侧' : '左侧') + '液柱由 S 自动换算（灰色列不用填）'
      : '已切换，但还缺两臂高度总和 S：请在右侧填入，否则算不出 Δh', 5000);
  }
}

/* 读数方式与 S 影响能否复算，静默写回 settings.json，免得下次打开模式丢了 */
async function persistConfig() {
  try {
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
    });
  } catch (e) { /* 静默 */ }
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnXlsx').onclick = () => exportTable('xlsx');
  $('btnCsv').onclick = () => exportTable('csv');
  $('btnSample').onclick = loadSample;
  $('fileInput').onchange = importFile;
  $('btnAddBubble').onclick = () => addRow('bubble');
  $('btnAddPlate').onclick = () => addRow('plate');
  $('chartKind').onchange = drawChart;
  $('height_mode').onchange = onModeChange;
  const onRepeatChange = (kind) => {
    DATA = readData();                 // 先按旧列数把已填的读数收进 DATA
    refreshTables();
    recalc();
    persistConfig();
    toast((kind === 'plate' ? '吊片法' : '气泡法') + '已切换为每点 '
      + repeatN(kind) + ' 次平行（多出的列不再显示）');
  };
  $('repeat_n_bubble').onchange = () => onRepeatChange('bubble');
  $('repeat_n_plate').onchange = () => onRepeatChange('plate');
  $('height_sum').onchange = () => {
    DATA = readData();
    refreshTables();
    recalc();
    persistConfig();
  };
  document.addEventListener('input', (e) => {
    const t = e.target;
    if (!t.matches || !t.matches('input[data-side], input[data-f="left"], input[data-f="right"]')) return;
    if (t.disabled) return;
    const row = t.closest('tr');
    if (row) syncDerivedInRow(row);
  });
  document.querySelectorAll('table').forEach((tbl) => {
    tbl.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-del]');
      if (btn) deleteRow(btn.dataset.del, Number(btn.dataset.i));
    });
  });
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
