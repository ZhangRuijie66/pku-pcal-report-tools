/* 稀溶液法偶极矩实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const COND_FIELDS = ['M1', 'M2', 'lit_mu', 'sigma_n', 'sigma_rho2',
  'sigma_c_check', 'sigma_T_check'];

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
  const g = (v) => (v == null ? '' : v);
  $('T').value = g(DATA.T);
  const ce = DATA.c_empty || [];
  $('c_empty_0').value = g(ce[0]);
  $('c_empty_1').value = g(ce[1]);
  const cy = DATA.cyclo || {};
  $('rho_cyc').value = g(cy.rho);
  const cc = cy.c_sample || [];
  $('c_cyc').value = g(cc[0]);
  const bu = DATA.butanol || {};
  $('rho_but').value = g(bu.rho_de45);
  $('n_but').value = g(bu.n);
  const py = DATA.pycno || {};
  $('m0').value = g(py.m0);
  $('mw').value = (py.mw && py.mw[0] != null) ? py.mw[0] : '';
  $('mB').value = g(py.mB);
  renderSolutions();
}

function readData() {
  const solutions = [];
  document.querySelectorAll('#solTable tbody tr[data-row]').forEach((tr) => {
    const get = (f) => {
      const el = tr.querySelector('input[data-f="' + f + '"]');
      return el && el.value !== '' ? Number(el.value) : null;
    };
    const cs = [];
    [2, 3].forEach((f) => {
      const el = tr.querySelector('input[data-f="' + f + '"]');
      if (el && el.value !== '') cs.push(Number(el.value));
    });
    const row = { m1: get(0), m2: get(1), c_sample: cs, rho: get(4) };
    if (row.m1 != null || row.m2 != null || cs.length || row.rho != null) {
      solutions.push(row);
    }
  });
  const d = {
    T: $('T').value === '' ? null : Number($('T').value),
    c_empty: [$('c_empty_0').value, $('c_empty_1').value]
      .filter((v) => v !== '').map(Number),
    cyclo: { rho: $('rho_cyc').value === '' ? null : Number($('rho_cyc').value),
             c_sample: [$('c_cyc').value].filter((v) => v !== '').map(Number) },
    butanol: {
      rho_de45: $('rho_but').value === '' ? null : Number($('rho_but').value),
      n: $('n_but').value === '' ? null : Number($('n_but').value),
    },
    pycno: {
      m0: $('m0').value === '' ? null : Number($('m0').value),
      mw: [$('mw').value].filter((v) => v !== '').map(Number),
      mB: $('mB').value === '' ? null : Number($('mB').value),
    },
    solutions,
  };
  return d;
}

/* ---------------------------------------------------------------- 表格渲染 */
function renderSolutions() {
  const tbl = $('solTable');
  const rows = (DATA && DATA.solutions) || [];
  let html = '<thead><tr><th>#</th><th>m₁ /g</th><th>m₂ /g</th>' +
    '<th>C′样₁</th><th>C′样₂</th><th>ρ /(g·cm⁻³)</th><th></th></tr></thead><tbody>';
  rows.forEach((r, i) => {
    const cs = r.c_sample || [];
    html += '<tr data-row="' + i + '"><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-f="0" value="' +
      (r.m1 == null ? '' : esc(r.m1)) + '"></td>' +
      '<td><input type="number" step="any" data-f="1" value="' +
      (r.m2 == null ? '' : esc(r.m2)) + '"></td>' +
      '<td><input type="number" step="any" data-f="2" value="' +
      (cs[0] == null ? '' : esc(cs[0])) + '"></td>' +
      '<td><input type="number" step="any" data-f="3" value="' +
      (cs[1] == null ? '' : esc(cs[1])) + '"></td>' +
      '<td><input type="number" step="any" data-f="4" value="' +
      (r.rho == null ? '' : esc(r.rho)) + '"></td>' +
      '<td><button class="btn mini" data-del="' + i + '">删</button></td></tr>';
  });
  tbl.innerHTML = html + '</tbody>';
}

/* ---------------------------------------------------------------- 结果 */
function renderResults(s) {
  const r = s.result || {};
  const rows = [];
  if (r.eps_fit) {
    rows.push(['ε–x 拟合', pm(r.a, r.s_a, 4), pm(r.eps1, r.s_eps1, 4),
               num(r.eps_fit.r2, 4)]);
    rows.push(['ρ–x 拟合', pm(r.b, r.s_b, 5), pm(r.rho1, r.s_rho1, 5),
               num(r.rho_fit.r2, 4)]);
  }
  $('resultTable').innerHTML =
    '<thead><tr><th>拟合</th><th>斜率</th><th>截距</th><th>R²</th></tr></thead>' +
    '<tbody>' + rows.map((x) => '<tr><td>' + x.join('</td><td>') + '</td></tr>')
      .join('') + '</tbody>';
  let note = '';
  if (r.P_inf != null) {
    note += 'P̄₂^∞ = ' + pm(r.P_inf, r.s_P, 2) + ' cm³·mol⁻¹；' +
      'R = ' + pm(r.R_molar, r.s_R, 2) + ' cm³·mol⁻¹。';
  }
  if (r.mu != null) {
    note += ' μ = ' + pm(r.mu, r.s_mu, 3) + ' D（文献 ' + num(r.lit_mu, 2) +
      ' D），比重瓶对比相对偏差 ' + num(r.E_r_pyc, 4) + '%。';
    if (r.c_check) {
      note += ' 若每个电容读数有 ' + num(r.c_check.sigma_c, 2) +
        ' pF 误差，σ_μ 会变成 ' + num(r.c_check.s_mu, 4) + ' D。';
    }
  }
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
  $('chartHint').textContent = kind === 'eps_fit'
    ? 'ε 对 x 的线性拟合（Hedestrand：斜率 a、截距 ε₁）'
    : 'ρ 对 x 的线性拟合（斜率 b、截距 ρ₁）';
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
    toast('已载入示例数据（数据处理2.xlsx 口径）');
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
    const rows = r.rows;
    DATA = DATA || {};
    if (rows.solutions && rows.solutions.length) {
      DATA.solutions = rows.solutions.map((x) => ({
        m1: x.m1, m2: x.m2, rho: x.rho, c_sample: x.c_sample || [],
      }));
    }
    if (rows.cyclo) {
      DATA.cyclo = Object.assign(DATA.cyclo || {}, rows.cyclo);
      if (rows.cyclo.rho != null) DATA.cyclo.rho = rows.cyclo.rho;
    }
    if (rows.butanol) {
      DATA.butanol = Object.assign(DATA.butanol || {}, rows.butanol);
    }
    fillData(DATA);
    await recalc();
    toast('已从 ' + f.name + ' 导入（温度、C′空、比重瓶数据保持原值）');
  } catch (e) { toast('导入失败：' + e.message, 5000); }
  finally { busy(false); $('fileInput').value = ''; }
}

function addRow() {
  const d = readData();
  d.solutions.push({ m1: null, m2: null, c_sample: [], rho: null });
  DATA = d;
  renderSolutions();
}

function deleteRow(i) {
  const d = readData();
  d.solutions.splice(i, 1);
  DATA = d;
  renderSolutions();
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnSample').onclick = loadSample;
  $('fileInput').onchange = importFile;
  $('btnAddSol').onclick = addRow;
  $('chartKind').onchange = drawChart;
  document.querySelectorAll('table').forEach((tbl) => {
    tbl.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-del]');
      if (btn) deleteRow(Number(btn.dataset.del));
    });
  });
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
