/* 双液体系沸点-成分图实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const OPT_FIELDS = ['sigma_n', 'lit_T_K', 'lit_w'];
const DATA_FIELDS = ['n_cyclohexane', 'n_ethanol'];

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
function num(v, d = 4) {
  if (v == null || v === '' || isNaN(v)) return '—';
  return Number(v).toFixed(d);
}
function pm(x, u, d = 4) {
  if (x == null || x === '' || isNaN(x)) return '—';
  if (u == null || u === '' || isNaN(u) || Number(u) === 0) return num(x, d);
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
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  OPT_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  $('composition_mode').value = c.composition_mode || 'ratio';
}
function readConfig() {
  const cfg = {};
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    cfg[k] = el.type === 'number'
      ? (el.value === '' ? null : Number(el.value)) : el.value;
  });
  OPT_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) cfg[k] = el.value === '' ? null : Number(el.value);
  });
  cfg.composition_mode = $('composition_mode').value;
  return cfg;
}

function fillData(d) {
  DATA = d || { curve: [], boiling: [] };
  DATA.curve = DATA.curve || [];
  DATA.boiling = DATA.boiling || [];
  DATA.curve_exclude = DATA.curve_exclude || [];
  DATA_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) el.value = (DATA[k] === null || DATA[k] === undefined) ? '' : DATA[k];
  });
  renderCurve();
  renderBoil();
}

function readBottles() {
  const points = [];
  const exclude = [];
  document.querySelectorAll('#curveTable tbody tr[data-bottle]').forEach((tr) => {
    const m1 = tr.querySelector('input[data-f="m1"]');
    const m2 = tr.querySelector('input[data-f="m2"]');
    const n = tr.querySelector('input[data-f="n"]');
    const m1v = m1 && m1.value !== '' ? Number(m1.value) : null;
    const m2v = m2 && m2.value !== '' ? Number(m2.value) : null;
    const nv = n && n.value !== '' ? Number(n.value) : null;
    if (m1v == null && m2v == null) return;
    points.push({ m1: m1v, m2: m2v, n: nv });
    const ex = tr.querySelector('input[data-f="exclude"]');
    if (ex && ex.checked) exclude.push(points.length);   // 合并序号：0 = 纯环己烷
  });
  return { points, exclude };
}

function readBoils() {
  const out = [];
  document.querySelectorAll('#boilTable tbody tr[data-boil]').forEach((tr) => {
    const g = (f) => {
      const el = tr.querySelector('input[data-f="' + f + '"]');
      return el && el.value !== '' ? Number(el.value) : null;
    };
    const vE = g('v_ethanol'), vC = g('v_cyclohexane');
    if (vE == null && vC == null) return;
    out.push({
      v_ethanol: vE, v_cyclohexane: vC,
      n_g: [g('n_g1'), g('n_g2')].filter((v) => v != null),
      n_l: [g('n_l1'), g('n_l2')].filter((v) => v != null),
      T_c: g('T_c'), p_kpa: g('p_kpa'),
    });
  });
  return out;
}

function readData() {
  const cur = readBottles();
  return {
    n_cyclohexane: $('n_cyclohexane').value === '' ? null : Number($('n_cyclohexane').value),
    n_ethanol: $('n_ethanol').value === '' ? null : Number($('n_ethanol').value),
    curve: cur.points,
    curve_exclude: cur.exclude,
    boiling: readBoils(),
  };
}

/* ---------------------------------------------------------------- 渲染 */
function renderCurve() {
  const rows = DATA.curve || [];
  let html = '<thead><tr><th>#</th><th>m₁ 乙醇 /g</th><th>m₂ 环己烷 /g</th>' +
    '<th>n</th><th>剔除</th><th></th></tr></thead><tbody>';
  html += bottleRow(-1, null);
  rows.forEach((p, i) => { html += bottleRow(i, p); });
  html += '</tbody>';
  $('curveTable').innerHTML = html;

  function bottleRow(i, p) {
    // 合并序号：0 = 纯环己烷锚点，1..N = 滴瓶，N+1 = 纯乙醇锚点
    const idx = i + 1;
    const excl = i >= 0 && (DATA.curve_exclude || []).indexOf(i) >= 0;
    if (i < 0 || i === rows.length) {
      const label = i < 0 ? '纯环己烷（x=0）' : '纯乙醇（x=1）';
      const nVal = i < 0 ? DATA.n_cyclohexane : DATA.n_ethanol;
      return '<tr style="color:#5b6472"><td>' + idx + '</td>' +
        '<td colspan="2">' + label + '</td>' +
        '<td>' + (nVal == null ? '—' : esc(nVal)) + '</td>' +
        '<td></td><td></td></tr>';
    }
    return '<tr data-bottle="' + i + '"><td>' + idx + '</td>' +
      '<td><input type="number" step="any" data-f="m1" value="' +
      (p.m1 == null ? '' : esc(p.m1)) + '"></td>' +
      '<td><input type="number" step="any" data-f="m2" value="' +
      (p.m2 == null ? '' : esc(p.m2)) + '"></td>' +
      '<td><input type="number" step="0.0001" data-f="n" value="' +
      (p.n == null ? '' : esc(p.n)) + '"></td>' +
      '<td><input type="checkbox" data-f="exclude"' + (excl ? ' checked' : '') + '></td>' +
      '<td><button class="btn mini" data-del-bottle="' + i + '">删</button></td></tr>';
  }
  // 纯组分的折射率在左侧「纯组分折射率」卡片里修改
}

function renderBoil() {
  const rows = DATA.boiling || [];
  let html = '<thead><tr><th>#</th><th>V 乙醇 /mL</th><th>V 环己烷 /mL</th>' +
    '<th>n_g1</th><th>n_g2</th><th>n_l1</th><th>n_l2</th>' +
    '<th>T /℃</th><th>p /kPa</th><th></th></tr></thead><tbody>';
  rows.forEach((b, i) => {
    const ng = b.n_g || [], nl = b.n_l || [];
    html += '<tr data-boil="' + i + '"><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-f="v_ethanol" value="' +
      (b.v_ethanol == null ? '' : esc(b.v_ethanol)) + '"></td>' +
      '<td><input type="number" step="any" data-f="v_cyclohexane" value="' +
      (b.v_cyclohexane == null ? '' : esc(b.v_cyclohexane)) + '"></td>' +
      '<td><input type="number" step="0.0001" data-f="n_g1" value="' +
      (ng[0] == null ? '' : esc(ng[0])) + '"></td>' +
      '<td><input type="number" step="0.0001" data-f="n_g2" value="' +
      (ng[1] == null ? '' : esc(ng[1])) + '"></td>' +
      '<td><input type="number" step="0.0001" data-f="n_l1" value="' +
      (nl[0] == null ? '' : esc(nl[0])) + '"></td>' +
      '<td><input type="number" step="0.0001" data-f="n_l2" value="' +
      (nl[1] == null ? '' : esc(nl[1])) + '"></td>' +
      '<td><input type="number" step="0.01" data-f="T_c" value="' +
      (b.T_c == null ? '' : esc(b.T_c)) + '"></td>' +
      '<td><input type="number" step="0.1" data-f="p_kpa" value="' +
      (b.p_kpa == null ? '' : esc(b.p_kpa)) + '"></td>' +
      '<td><button class="btn mini" data-del-boil="' + i + '">删</button></td></tr>';
  });
  $('boilTable').innerHTML = html + '</tbody>';
}

function renderResults(s) {
  const curve = s.curve || {};
  const fit = curve.fit || {};
  const fitAll = curve.fit_all || {};
  const rows = (curve.points || []).map((p) => (
    '<tr><td>' + p.index + '</td><td>' + esc(p.label) + '</td>' +
    '<td>' + num(p.x, 4) + '</td><td>' + num(p.n, 4) + '</td>' +
    '<td>' + (p.resid_all == null ? '—' : num(p.resid_all, 2)) + '</td>' +
    '<td>' + (p.in_fit ? '是' : '否') + '</td></tr>'
  )).join('');
  $('curveTableResult').innerHTML =
    '<thead><tr><th>i</th><th>样品</th><th>x</th><th>n</th><th>r（全部点拟合）</th><th>参与拟合</th></tr></thead><tbody>' +
    rows + '</tbody>';
  let note = '';
  if (fit.A != null) {
    note += '采用曲线：n = (' + num(fit.A, 5) + '±' + num(fit.se_A, 5) + ')x² + (' +
      num(fit.B, 5) + '±' + num(fit.se_B, 5) + ')x + (' + num(fit.C, 5) + '±' +
      num(fit.se_C, 5) + ')，R² = ' + num(fit.r2, 5) +
      '；全部点拟合 R² = ' + num(fitAll.r2, 5) + '。';
  }
  if ((curve.outliers || []).length) {
    note += ' 学生化残差 |r|>2：' + curve.outliers.map((o) =>
      o.label + '（r=' + num(o.r, 2) + '）').join('、') +
      '；>3 基本可认定为离群点。';
  }
  $('curveNote').textContent = note;

  const a = s.azeotrope || {};
  let arows = '';
  if (a.ok) {
    arows += '<tr><td>恒沸温度 T</td><td>' + num(a.T_K, 2) + ' K</td></tr>';
    arows += '<tr><td>恒沸组成 x</td><td>' + pm(a.w, a.sigma_w) + '</td></tr>';
    if (a.vapor_min) arows += '<tr><td>气相线最低点</td><td>' +
      num(a.vapor_min.w, 4) + ' / ' + num(a.vapor_min.T_K, 2) + ' K</td></tr>';
    if (a.liquid_min) arows += '<tr><td>液相线最低点</td><td>' +
      num(a.liquid_min.w, 4) + ' / ' + num(a.liquid_min.T_K, 2) + ' K</td></tr>';
    if (s.lit_x != null) arows += '<tr><td>文献组成（本口径）</td><td>' +
      num(s.lit_x, 4) + '，偏差 ' + (s.deviation == null ? '—' : num(s.deviation * 100, 1) + '%') + '</td></tr>';
  } else {
    arows = '<tr><td class="hint">' + esc(a.reason || '数据不足') + '</td></tr>';
  }
  $('azeoTable').innerHTML = '<tbody>' + arows + '</tbody>';
  $('azeoNote').textContent = a.ok
    ? ('恒沸点定位：气相线与液相线（弧长参数化 B 样条）相差最小的位置；'
       + '两线差约 ' + num(a.gap, 3) + ' K。组成不确定度由拟合系数与 σ_n 传播得到。')
    : '';

  const brow = (s.rows || []).map((r) => (
    '<tr><td>' + (r.index + 1) + '</td><td>' + num(r.n_g, 4) + '</td>' +
    '<td>' + num(r.n_l, 4) + '</td><td>' + num(r.wg, 4) + '</td>' +
    '<td>' + num(r.wl, 4) + '</td><td>' + num(r.T_K, 2) + '</td></tr>'
  )).join('');
  $('boilResult').innerHTML =
    '<thead><tr><th>#</th><th>n_g</th><th>n_l</th><th>x_g</th><th>x_l</th><th>T /K</th></tr></thead><tbody>' +
    (brow || '<tr><td class="hint">还没有数据</td></tr>') + '</tbody>';
  $('boilNote').textContent = s.rows && s.rows.length
    ? '平行读数分别反推后取平均；表中的行序与左侧「沸点测定」一致。'
    : '';
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
  $('chart').src = '/api/preview?kind=' + encodeURIComponent(kind) +
    '&t=' + Date.now();
  const hints = {
    curve: '实心点参与拟合，空心点被剔除；虚线注释为拟合方程与 R²',
    curve_refit: '剔除离群点后重新拟合的工作曲线',
    phase: '圆点 = 液相，三角 = 气相；星号为最低恒沸点',
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
    renderState(s);
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
    toast('已载入示例数据（2025 年参照数据）');
  } catch (e) { toast('载入失败：' + e.message); }
  finally { busy(false); }
}

function addBottle() {
  const d = readData();
  d.curve.push({ m1: null, m2: null, n: null });
  DATA = d;
  renderCurve();
}

function deleteBottle(i) {
  const d = readData();
  d.curve.splice(i, 1);
  d.curve_exclude = (d.curve_exclude || [])
    .map((x) => (x > i ? x - 1 : x)).filter((x) => x !== i);
  DATA = d;
  renderCurve();
}

function addBoil() {
  const d = readData();
  d.boiling.push({ v_ethanol: null, v_cyclohexane: null,
    n_g: [], n_l: [], T_c: null, p_kpa: null });
  DATA = d;
  renderBoil();
}

function deleteBoil(i) {
  const d = readData();
  d.boiling.splice(i, 1);
  DATA = d;
  renderBoil();
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnSample').onclick = loadSample;
  $('btnAddBottle').onclick = addBottle;
  $('btnAddBoil').onclick = addBoil;
  $('curveTable').addEventListener('click', (e) => {
    const del = e.target.closest('button[data-del-bottle]');
    if (del) deleteBottle(Number(del.dataset.delBottle));
  });
  $('boilTable').addEventListener('click', (e) => {
    const del = e.target.closest('button[data-del-boil]');
    if (del) deleteBoil(Number(del.dataset.delBoil));
  });
  $('chartKind').onchange = drawChart;
  $('composition_mode').onchange = recalc;
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
