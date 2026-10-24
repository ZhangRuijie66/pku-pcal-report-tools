/* 液体饱和蒸气压实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const COND_FIELDS = ['p1', 'trouton', 'lit_tb_water', 'lit_dh_water',
  'lit_tb_cyclo', 'lit_dh_cyclo', 'shift_check'];
const LIQUIDS = ['water', 'cyclo'];
const NAME_CN = { water: '水', cyclo: '环己烷' };

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
async function api(path, opts) {
  const res = await fetch(path, Object.assign({ cache: 'no-store' }, opts || {}));
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}

/* ---------------------------------------------------------------- 表单 */
function fillConfig(c) {
  COVER_FIELDS.concat(COND_FIELDS).forEach((k) => {
    const el = $(k);
    if (!el) return;
    el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
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
  COND_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    cfg[k] = el.value === '' ? null : Number(el.value);
  });
  return cfg;
}

function fillData(d) {
  DATA = d || {};
  LIQUIDS.forEach((key) => {
    renderAtm(key);
    renderSeries(key);
  });
}

function readBranch(key) {
  const atm = [];
  document.querySelectorAll('#' + key + 'AtmTable input[data-r]').forEach((inp) => {
    const i = Number(inp.dataset.r);
    atm[i] = atm[i] || [null, null];
    atm[i][Number(inp.dataset.c)] = inp.value === '' ? null : Number(inp.value);
  });
  const series = [];
  document.querySelectorAll('#' + key + 'SeriesTable tbody tr[data-row]').forEach((tr) => {
    const cells = [];
    tr.querySelectorAll('input[data-f]').forEach((inp) => {
      cells[Number(inp.dataset.f)] = inp.value === '' ? null : Number(inp.value);
    });
    if (cells[0] != null && cells[1] != null) series.push([cells[0], cells[1]]);
  });
  return {
    atm: (atm || []).filter((r) => r && (r[0] != null || r[1] != null)),
    series,
  };
}

function readData() {
  const d = {};
  LIQUIDS.forEach((key) => { d[key] = readBranch(key); });
  return d;
}

/* ---------------------------------------------------------------- 表格渲染 */
function renderAtm(key) {
  const el = $(key + 'AtmTable');
  const rows = (DATA && DATA[key] && DATA[key].atm) || [];
  let html = '<thead><tr><th>组别</th><th>p₀ /kPa</th><th>t /℃</th></tr></thead><tbody>';
  for (let i = 0; i < 3; i += 1) {
    const r = rows[i] || [];
    html += '<tr><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-r="' + i + '" data-c="0" value="' +
      (r[0] == null ? '' : esc(r[0])) + '"></td>' +
      '<td><input type="number" step="any" data-r="' + i + '" data-c="1" value="' +
      (r[1] == null ? '' : esc(r[1])) + '"></td></tr>';
  }
  el.innerHTML = html + '</tbody>';
}

function renderSeries(key) {
  const tbl = $(key + 'SeriesTable');
  const rows = (DATA && DATA[key] && DATA[key].series) || [];
  let html = '<thead><tr><th>#</th><th>p /kPa</th><th>t /℃</th><th></th></tr></thead><tbody>';
  rows.forEach((r, i) => {
    html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-f="0" value="' +
      (r[0] == null ? '' : esc(r[0])) + '"></td>' +
      '<td><input type="number" step="any" data-f="1" value="' +
      (r[1] == null ? '' : esc(r[1])) + '"></td>' +
      '<td><button class="btn mini" data-del="' + key + '" data-i="' + i + '">删</button></td></tr>';
  });
  tbl.innerHTML = html + '</tbody>';
}

/* ---------------------------------------------------------------- 结果 */
function renderResults(s) {
  const rows = LIQUIDS.map((key) => {
    const m = s[key];
    const f = m && m.fit;
    if (!f) {
      return '<tr><td>' + esc(NAME_CN[key]) + '</td><td colspan="7" class="hint">' +
        '数据不足（变压系列 + 大气压沸点合计至少 3 个点）</td></tr>';
    }
    return '<tr><td>' + esc(NAME_CN[key]) + '</td>' +
      '<td>' + num(f.A / 1e3, 3) + ' ± ' + num(f.sigma_A / 1e3, 3) + '×10³</td>' +
      '<td>' + num(f.B, 3) + ' ± ' + num(f.sigma_B, 3) + '</td>' +
      '<td>' + num(f.r2, 5) + '</td>' +
      '<td>' + pm(f.tb, f.sigma_tb, 2) + '</td>' +
      '<td>' + pm(f.dh_kJ, f.sigma_dh_kJ, 3) + '</td>' +
      '<td>' + pm(f.ds, f.sigma_ds, 2) + '</td></tr>';
  }).join('');
  $('resultTable').innerHTML =
    '<thead><tr><th>液体</th><th>A /(10³ K)</th><th>B</th><th>R²</th>' +
    '<th>T_b /K</th><th>ΔH /(kJ·mol⁻¹)</th><th>ΔS /(J·mol⁻¹·K⁻¹)</th></tr></thead>' +
    '<tbody>' + rows + '</tbody>';
  let note = '';
  LIQUIDS.forEach((key) => {
    const m = s[key];
    if (m && m.fit) {
      note += NAME_CN[key] + '：T_b 相对偏差 ' + num(m.rel_tb, 2) + '%，' +
        'ΔH 相对偏差 ' + num(m.rel_dh, 2) + '%。';
      if (m.shift) {
        note += ' 温度整体偏高 ' + num(m.shift.shift, 1) +
          '℃ 复算 ΔH = ' + num(m.shift.dh_kJ, 3) + ' kJ·mol⁻¹。';
      }
    }
  });
  $('resultNote').textContent = note;
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
    water_curve: '全部数据点 + B 样条光滑曲线（含大气压沸点）',
    water_fit: 'ln(p/p⊖)–1/T 线性拟合；注记为拟合式与 R²',
    cyclo_curve: '环己烷全部数据点 + B 样条光滑曲线',
    cyclo_fit: '环己烷的 ln(p/p⊖)–1/T 线性拟合',
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
      key: 'pcal-draft-vapor-v1',
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
    fillData(DATA);
    await recalc();
    toast('已载入示例数据（蒸发热数据处理.xlsx 口径）');
  } catch (e) { toast('载入失败：' + e.message); }
  finally { busy(false); }
}

async function importFile() {
  const f = $('fileInput').files[0];
  if (!f) { toast('先选择一个 xlsx/csv 文件'); return; }
  busy(true, '读取文件…');
  try {
    const buf = await f.arrayBuffer();
    let binary = '';
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    const r = await api('/api/import?kind=file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ b64: btoa(binary), name: f.name }),
    });
    DATA = { water: r.water, cyclo: r.cyclo };
    fillData(DATA);
    await recalc();
    toast('已从 ' + f.name + ' 读到 ' + r.count + ' 行并自动分两支');
  } catch (e) { toast('导入失败：' + e.message, 5000); }
  finally { busy(false); $('fileInput').value = ''; }
}

async function importPaste() {
  const kind = $('importKind').value;
  const text = $('pasteText').value;
  busy(true, '导入中…');
  try {
    const r = await api('/api/import?kind=' + encodeURIComponent(kind), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!r.count) throw new Error('没有读到数字');
    DATA = DATA || { water: { atm: [], series: [] }, cyclo: { atm: [], series: [] } };
    DATA[kind] = { atm: (DATA[kind] && DATA[kind].atm) || [], series: r.rows };
    fillData(DATA);
    await recalc();
    toast('已导入 ' + r.count + ' 行到「' + NAME_CN[kind] + '」变压系列');
  } catch (e) { toast('导入失败：' + e.message, 5000); }
  finally { busy(false); }
}

function addRow(key) {
  const d = readData();
  d[key].series.push([null, null]);
  DATA = d;
  renderSeries(key);
}

function deleteRow(key, i) {
  const d = readData();
  d[key].series.splice(i, 1);
  DATA = d;
  renderSeries(key);
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnSample').onclick = loadSample;
  $('fileInput').onchange = importFile;
  $('btnPaste').onclick = importPaste;
  $('btnAddWater').onclick = () => addRow('water');
  $('btnAddCyclo').onclick = () => addRow('cyclo');
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
