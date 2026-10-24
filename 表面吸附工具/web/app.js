/* 溶液表面吸附实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const DATA_FIELDS = ['temperature_bubble', 'temperature_plate', 'gamma_water',
  'sigma_read', 'sigma_plate'];
const PROC_FIELDS = ['conc_axis', 'zero_correction'];

let STATE = null;
let DATA = null;

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

/* ---------------------------------------------------------------- 表单 */
function fillConfig(c) {
  COVER_FIELDS.concat(PROC_FIELDS).forEach((k) => {
    const el = $(k);
    if (!el) return;
    if (k === 'zero_correction') el.value = c[k] ? '1' : '0';
    else el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
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
}

function readTrio(kind) {
  const elId = kind === 'zero' ? 'zeroTable' : 'waterTable';
  const left = [], right = [];
  document.querySelectorAll('#' + elId + ' input[data-side]').forEach((inp) => {
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
        if (inp.value !== '') left.push(Number(inp.value));
      });
      tr.querySelectorAll('input[data-f="right"]').forEach((inp) => {
        if (inp.value !== '') right.push(Number(inp.value));
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

function renderTrio(kind) {
  const el = kind === 'zero' ? $('zeroTable') : $('waterTable');
  const key = kind === 'zero' ? 'zero' : 'water_bubble';
  const obj = (DATA && DATA[key]) || {};
  const left = obj.left || [], right = obj.right || [];
  let html = '<thead><tr><th>组别</th><th>h_left / cm</th><th>h_right / cm</th></tr></thead><tbody>';
  for (let i = 0; i < 3; i += 1) {
    html += '<tr data-trio="' + i + '"><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-side="left" data-i="' + i +
      '" value="' + (left[i] == null ? '' : esc(left[i])) + '"></td>' +
      '<td><input type="number" step="any" data-side="right" data-i="' + i +
      '" value="' + (right[i] == null ? '' : esc(right[i])) + '"></td></tr>';
  }
  el.innerHTML = html + '</tbody>';
}

function renderRows(kind) {
  const tbl = kind === 'bubble' ? $('bubbleTable') : $('plateTable');
  const rows = (DATA && DATA[kind]) || [];
  let html;
  if (kind === 'bubble') {
    html = '<thead><tr><th>#</th><th>c / (mol·dm⁻³)</th>' +
      '<th>h_l1</th><th>h_l2</th><th>h_l3</th>' +
      '<th>h_r1</th><th>h_r2</th><th>h_r3</th><th>拟合</th><th></th></tr></thead><tbody>';
    rows.forEach((r, i) => {
      const left = r.left || [], right = r.right || [];
      html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
        inputCell('bubble', 'c', i, r.c) +
        [0, 1, 2].map((j) => inputCell('bubble', 'left', j, left[j])).join('') +
        [0, 1, 2].map((j) => inputCell('bubble', 'right', j, right[j])).join('') +
        '<td><input type="checkbox" data-f="fit"' + (r.fit ? ' checked' : '') + '></td>' +
        '<td><button class="btn mini" data-del="bubble" data-i="' + i + '">删</button></td></tr>';
    });
  } else {
    html = '<thead><tr><th>#</th><th>c / (mol·dm⁻³)</th>' +
      '<th>γ1</th><th>γ2</th><th>γ3</th><th>拟合</th><th></th></tr></thead><tbody>';
    rows.forEach((r, i) => {
      const gamma = r.gamma || [];
      html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
        inputCell('plate', 'c', i, r.c) +
        [0, 1, 2].map((j) => inputCell('plate', 'gamma', j, gamma[j])).join('') +
        '<td><input type="checkbox" data-f="fit"' + (r.fit ? ' checked' : '') + '></td>' +
        '<td><button class="btn mini" data-del="plate" data-i="' + i + '">删</button></td></tr>';
    });
  }
  tbl.innerHTML = html + '</tbody>';
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
    if (kind === 'bubble') DATA.bubble = r.rows;
    else if (kind === 'plate') DATA.plate = r.rows;
    else DATA[kind] = { left: r.left, right: r.right };
    fillData(DATA);
    await recalc();
    toast('已导入 ' + r.count + ' 行');
  } catch (e) { toast('导入失败：' + e.message, 5000); }
  finally { busy(false); $('fileInput').value = ''; }
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
}

function deleteRow(kind, i) {
  const d = readData();
  const rows = kind === 'bubble' ? d.bubble : d.plate;
  rows.splice(i, 1);
  DATA = d;
  renderRows(kind);
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnSample').onclick = loadSample;
  $('fileInput').onchange = importFile;
  $('btnAddBubble').onclick = () => addRow('bubble');
  $('btnAddPlate').onclick = () => addRow('plate');
  $('chartKind').onchange = drawChart;
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
