/* 电导率实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no', 'date',
  'room_temp', 'pressure'];
const DATA_FIELDS = ['cell_constant_label', 'cell_constant', 'kcl_label_uS',
  'kcl_theory_uS', 'kcl_after_uS', 'kappa_w_uS', 'temp_c', 'compensation'];
const SOLUTIONS = [
  ['NaNO3', 'NaNO₃'], ['NaAc', 'NaAc'], ['HNO3', 'HNO₃'], ['HAc', 'HAc'],
];

let STATE = null;

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
function fmt(x, n = 4) {
  if (x == null || isNaN(x)) return '—';
  return Number(x).toPrecision ? Number(x).toFixed(n) : '—';
}
async function api(path, opts) {
  const res = await fetch(path, Object.assign({ cache: 'no-store' }, opts || {}));
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}

/* ---------------------------------------------------------------- 表单 */
function fillForms(s) {
  const c = s.config || {};
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  const d = s.data || {};
  DATA_FIELDS.forEach((k) => {
    const el = $('d_' + k);
    if (el) el.value = (d[k] === null || d[k] === undefined) ? '' : d[k];
  });
}

function readConfig() {
  const cfg = {};
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    if (el.type === 'number') cfg[k] = el.value === '' ? null : Number(el.value);
    else cfg[k] = el.value;
  });
  cfg.data_dir = $('dataDir').value.trim();
  return cfg;
}

function readData() {
  const d = {};
  DATA_FIELDS.forEach((k) => {
    const el = $('d_' + k);
    if (el) d[k] = el.value;
  });
  d.solutions = {};
  SOLUTIONS.forEach(([key]) => {
    const conc = [], kappa = [];
    for (let i = 0; i < 5; i++) {
      conc.push($(`cell_${key}_c_${i}`).value);
      kappa.push($(`cell_${key}_k_${i}`).value);
    }
    d.solutions[key] = { conc, kappa };
  });
  return d;
}

/* ---------------------------------------------------------------- 渲染 */
function renderSolTables(data) {
  const box = $('solTables');
  const sols = (data && data.solutions) || {};
  let html = '';
  SOLUTIONS.forEach(([key, label]) => {
    const sol = sols[key] || { conc: [], kappa: [] };
    html += '<div class="field"><label><b>' + label + '</b></label>' +
      '<table><tr><th>瓶号</th><th>浓度 / (mol·m⁻³)</th><th>κ 测量 / (S·m⁻¹)</th></tr>';
    for (let i = 0; i < 5; i++) {
      html += '<tr><td>' + (i + 1) + '</td>' +
        '<td><input id="cell_' + key + '_c_' + i + '" value="' +
        esc(sol.conc[i] != null ? sol.conc[i] : '') + '"></td>' +
        '<td><input id="cell_' + key + '_k_' + i + '" value="' +
        esc(sol.kappa[i] != null ? sol.kappa[i] : '') + '"></td></tr>';
    }
    html += '</table></div>';
  });
  box.innerHTML = html;
}

function renderKpi(s) {
  const fits = s.fits || {};
  const items = [];
  SOLUTIONS.forEach(([key, label]) => {
    const f = fits[key];
    if (!f) return;
    if (key === 'HAc') return;
    items.push([label + ' Λ<sub>m</sub><sup>∞</sup> / (S·m²·mol⁻¹)',
                '(' + Number(f.lam_inf).toFixed(5) + ' ± ' +
                Number(f.sigma_inf).toFixed(5) + ')']);
  });
  items.push(['Λ<sub>m</sub><sup>∞</sup>(HAc) / (S·m²·mol⁻¹)',
              s.lam_hac != null ? '(' + Number(s.lam_hac).toFixed(5) + ' ± ' +
              Number(s.sigma_hac).toFixed(5) + ')' : '—']);
  if (s.kmean) {
    items.push(['K° 求平均法', '(' + Number(s.kmean.mean * 1e5).toFixed(3) +
                ' ± ' + Number(s.kmean.sigma * 1e5).toFixed(3) + ')×10⁻⁵']);
  }
  if (s.kfit) {
    items.push(['K° 拟合直线法', '(' + Number(s.kfit.K * 1e5).toFixed(3) +
                ' ± ' + Number(s.kfit.sigma_K * 1e5).toFixed(3) + ')×10⁻⁵']);
  }
  $('kpiBox').innerHTML = items.map(([lab, val]) =>
    '<div class="item"><div class="lab">' + lab +
    '</div><div class="val">' + val + '</div></div>').join('');
}

function renderResults(s) {
  const rows = [];
  (s.lit_table || []).forEach((r) => {
    const label = { NaNO3: 'NaNO₃', NaAc: 'NaAc', HNO3: 'HNO₃', HAc: 'HAc' }[r.key];
    rows.push(['Λ<sub>m</sub><sup>∞</sup>(' + label + ') 实验值 / 理论值',
      '(' + Number(r.exp).toFixed(5) + ' ± ' + Number(r.sigma).toFixed(5) + ') / ' +
      Number(r.theo).toFixed(5)]);
    rows.push(['　' + label + ' 相对误差 E<sub>r</sub>',
               (r.er >= 0 ? '+' : '') + Number(r.er).toFixed(2) + '%']);
  });
  if (s.kfit) {
    rows.push(['拟合直线斜率 k', Number(s.kfit.k).toExponential(4) +
               ' ± ' + Number(s.kfit.sigma_k).toExponential(2)]);
    rows.push(['拟合相关系数 r', Number(s.kfit.r).toFixed(5)]);
  }
  $('resTable').innerHTML = rows.map(([k, v]) =>
    '<tr><td style="text-align:left">' + k + '</td><td>' + v + '</td></tr>').join('');
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
  fillForms(s);
  renderSolTables(s.data);
  $('dataPath').textContent = s.data_path || '（还没有落盘）';
  $('outInfo').textContent = s.out_dir;
  setStatus('数据目录：' + s.data_dir);
  renderKpi(s);
  renderResults(s);
  renderWarnings(s);
  $('savedInfo').textContent = s.has_saved ? '已保存封面默认设置（settings.json）'
                                           : '尚未保存封面默认设置';
  drawChart();
}

function drawChart() {
  const kind = $('chartKind').value;
  $('chart').src = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
  const hints = {
    kappa_c: '三溶液的 κ校–c 曲线（黑方 NaNO₃ / 红圆 HNO₃ / 蓝三角 HAc）',
    'fit:NaNO3': 'Λm–√c 拟合，截距即 Λm∞',
    'fit:NaAc': 'Λm–√c 拟合，截距即 Λm∞',
    'fit:HNO3': 'HNO₃ 线性较差（挥发），注意看点是否贴合直线',
    kfit: '(c/c°)Λm–1/Λm 拟合，斜率 = (Λm∞)²K°',
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
      const a = $('btnHome');
      a.href = home;
      a.style.display = '';
    }
    setStatus('就绪');
  } catch (e) {
    setStatus('初始化失败：' + e.message, 'err');
    toast('初始化失败：' + e.message, 5000);
  }
}

async function recalc(cfgOnly) {
  busy(true, '重新计算中…');
  try {
    const body = { config: readConfig() };
    if (!cfgOnly) body.data = readData();
    const s = await api('/api/calc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    renderState(s);
    setStatus('已重新计算');
    toast('计算完成');
  } catch (e) {
    setStatus('计算失败：' + e.message, 'err');
    toast('计算失败：' + e.message, 5000);
  } finally { busy(false); }
}

async function saveData() {
  busy(true, '保存测量数据…');
  try {
    const s = await api('/api/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig(), data: readData() }),
    });
    renderState(s);
    toast('已保存到 ' + (s.saved_path || '数据文件'), 5000);
  } catch (e) { toast('保存失败：' + e.message, 5000); }
  finally { busy(false); }
}

async function saveDefault() {
  busy(true, '保存中…');
  try {
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
    });
    $('savedInfo').textContent = '已保存封面默认设置（settings.json）';
    toast('已存为默认（settings.json 在工具目录里）');
  } catch (e) { toast('保存失败：' + e.message); }
  finally { busy(false); }
}

async function doExport() {
  busy(true, '生成 Word 报告中…');
  try {
    const r = await api('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
    });
    busy(false);
    setStatus('已生成报告');
    $('overlay').classList.remove('show');
    toast('已生成：' + r.path, 7000);
    alert('报告已生成：\n' + r.path + (r.note ? '\n\n' + r.note : '') +
      ((r.logs || []).length ? '\n\n' + r.logs.slice(-3).join('；') : ''));
  } catch (e) {
    busy(false);
    setStatus('生成失败：' + e.message, 'err');
    toast('生成失败：' + e.message, 5000);
  }
}

async function pickDir() {
  const cur = $('dataDir').value.trim();
  busy(true, '请在弹出的窗口里选择数据文件夹…');
  try {
    const r = await api('/api/pickdir?initial=' + encodeURIComponent(cur));
    busy(false);
    if (r.path) {
      $('dataDir').value = r.path;
      toast('已选择：' + r.path, 4000);
      await recalc(true);
    } else {
      toast('已取消');
    }
  } catch (e) {
    busy(false);
    toast('打开选择窗口失败：' + e.message, 5000);
  }
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnExport').onclick = doExport;
  $('btnSaveData').onclick = saveData;
  $('btnSaveData2').onclick = saveData;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnBrowse').onclick = pickDir;
  $('chartKind').onchange = drawChart;
  document.querySelectorAll('.field input').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(true); });
  });
}

bindUI();
boot();
