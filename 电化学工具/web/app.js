/* 电化学（循环伏安法）实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no', 'date',
  'room_temp', 'pressure'];
const PROC_FIELDS = ['data_dir', 'smooth_window', 'onset_threshold_uA',
  'esa_lo', 'esa_hi', 'esa_baseline_uA', 'dl_lo', 'dl_hi',
  'i_min_uA', 'i_step_uA'];
const FILE_KEYS = [
  ['file_n2_blank', 'N₂ 空白（0.1 V·s⁻¹，也作扣空白基准）'],
  ['file_n2_02', 'N₂ 0.2 V·s⁻¹'],
  ['file_n2_05', 'N₂ 0.5 V·s⁻¹'],
  ['file_o2_fast', 'O₂ 快速搅拌'],
  ['file_o2_slow', 'O₂ 低速搅拌（ORR/DMFC 用）'],
  ['file_o2_still', 'O₂ 电解质静止'],
  ['file_meoh', '甲醇 + 硫酸'],
];
// 配置键 -> 页面元素 id（data_dir 的输入框 id 是 dataDir）
const EL_ID = { data_dir: 'dataDir' };

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
function fmt(x, n = 2) {
  if (x == null || isNaN(x)) return '—';
  return Number(x).toFixed(n);
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
    const el = $(EL_ID[k] || k);
    if (!el) return;
    el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  FILE_KEYS.forEach(([key]) => {
    const sel = $('sel_' + key);
    if (sel && c[key]) sel.value = c[key];
  });
}
function readConfig() {
  const cfg = {};
  COVER_FIELDS.concat(PROC_FIELDS).forEach((k) => {
    const el = $(EL_ID[k] || k);
    if (!el) return;
    if (el.type === 'number') {
      cfg[k] = el.value === '' ? null : Number(el.value);
    } else cfg[k] = el.value;
  });
  FILE_KEYS.forEach(([key]) => {
    const sel = $('sel_' + key);
    if (sel) cfg[key] = sel.value;
  });
  return cfg;
}

/* ---------------------------------------------------------------- 渲染 */
function renderKpi(s) {
  const esa = s.esa || {};
  const orr = s.orr || {};
  const mor = s.mor || {};
  const d = s.dmfc || {};
  const items = [
    ['电化学活性面积 /mm²', fmt(esa.area_mm2, 2)],
    ['ORR 起始还原电位 /V', fmt(orr.onset_red, 3)],
    ['MOR 起始氧化电位 /V', fmt(mor.onset, 3)],
    ['DMFC 交点电位 /V', fmt(d.E_intersect, 3)],
    ['最大输出功率 /W', d.P_max ? d.P_max.toExponential(3) : '—'],
    ['对应输出电压 /V', fmt(d.E_at_Pmax, 3)],
  ];
  $('kpiBox').innerHTML = items.map(([lab, val]) =>
    '<div class="item"><div class="lab">' + lab +
    '</div><div class="val">' + val + '</div></div>').join('');
}

function renderTable1(s) {
  const rows = s.table1 || [];
  let html = '<tr><th>v / (V·s⁻¹)</th><th>Ep / V</th><th>i<sub>pc</sub> / A</th></tr>';
  rows.forEach((r) => {
    html += '<tr><td>' + fmt(r.v, 1) + '</td><td>' + fmt(r.Ep, 3) + '</td><td>' +
      (isFinite(r.ip) ? r.ip.toExponential(4) : '—') + '</td></tr>';
  });
  $('table1').innerHTML = html;
  $('table1Note').textContent = rows.length
    ? 'ipc 取自 CHI 峰分析（相对基线的峰高）；比值 ipc(0.2)/ipc(0.1) ≈ ' +
      (rows.length >= 2 ? (rows[1].ip / rows[0].ip).toFixed(2) : '—') +
      '，接近扫速比 2，为吸附控制特征。'
    : '没有可用的峰分析数据。';
}

function renderResults(s) {
  const esa = s.esa || {};
  const orr = s.orr || {};
  const mor = s.mor || {};
  const d = s.dmfc || {};
  const rows = [
    ['ESA 积分 A / (A·V)', esa.A != null ? esa.A.toExponential(4) : '—'],
    ['峰电量 Q / C', esa.Q != null ? esa.Q.toExponential(4) : '—'],
    ['双电层基线 / μA', esa.baseline != null ? (esa.baseline * 1e6).toFixed(3) : '—'],
    ['ORR 还原支 / 氧化支起始电位 / V',
      fmt(orr.onset_red, 3) + ' / ' + fmt(orr.onset_ox, 3)],
    ['MOR 起始氧化电位 / V', fmt(mor.onset, 3)],
    ['DMFC 交点电位 / V', fmt(d.E_intersect, 3)],
    ['交点电流 / A', d.I_intersect != null ? d.I_intersect.toExponential(3) : '—'],
    ['最大输出功率 P_max / W', d.P_max != null ? d.P_max.toExponential(3) : '—'],
    ['P_max 对应输出电压 / V', fmt(d.E_at_Pmax, 3)],
    ['P_max 对应电流 / A', d.I_at_Pmax != null ? d.I_at_Pmax.toExponential(3) : '—'],
  ];
  $('resTable').innerHTML = rows.map(([k, v]) =>
    '<tr><td style="text-align:left">' + k + '</td><td>' + v + '</td></tr>').join('');
}

function renderFileMap(s) {
  const box = $('fileMap');
  if (box.dataset.built) { return; }
  const files = s.txt_files || [];
  let html = '';
  FILE_KEYS.forEach(([key, label]) => {
    const cur = (s.config || {})[key] || '';
    const opts = files.map((f) =>
      '<option value="' + esc(f) + '"' + (f === cur ? ' selected' : '') + '>' +
      esc(f) + '</option>').join('');
    html += '<div class="field"><label>' + label + '</label>' +
      '<select id="sel_' + key + '">' + (opts || '<option value="">' + esc(cur) + '</option>') +
      '</select></div>';
  });
  box.innerHTML = html;
  box.dataset.built = '1';
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
  renderFileMap(s);
  $('outInfo').textContent = s.out_dir;
  setStatus('数据目录：' + s.data_dir);
  renderKpi(s);
  renderTable1(s);
  renderResults(s);
  renderWarnings(s);
  $('savedInfo').textContent = s.has_saved ? '已保存默认设置（settings.json）' : '尚未保存默认设置';
  drawChart();
}

/* ---------------------------------------------------------------- 图表 */
function drawChart() {
  const img = $('chart');
  const kind = $('chartKind').value;
  img.src = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
  const hints = {
    n2: '三个扫速的整圈 CV（0.5 黑 / 0.2 红 / 0.1 蓝），纵轴倒置',
    esa: '阴影 = 氢脱附峰积分区（扣双电层基线）',
    o2: '不同搅拌条件的还原支与 N₂ 空白',
    orr: 'O₂ 低速搅拌与 N₂ 空白的整圈对比',
    meoh: '甲醇+硫酸的整圈 CV（主氧化峰 + 次氧化峰）',
    mor: '甲醇与空白对比；氢区差异方向相反，不会误触发判据',
    curves: '扣空白后的 ORR / MOR 电流量值曲线，中间三角区即电池工作区',
    polarization: 'MOR 0.248~交点、ORR 交点~0.517 V 单提出来即 DMFC',
    power: 'P = I·E_cell，顶点即最大输出功率',
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

async function recalc() {
  busy(true, '重新计算中…');
  setStatus('计算中…');
  try {
    const s = await api('/api/calc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
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
      body: JSON.stringify({ config: readConfig() }),
    });
    busy(false);
    setStatus('已生成报告');
    const logs = (r.logs || []).slice(-3).join('；');
    $('overlay').classList.remove('show');
    toast('已生成：' + r.path, 7000);
    alert('报告已生成：\n' + r.path + (r.note ? '\n\n' + r.note : '') +
      (logs ? '\n\n' + logs : ''));
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
      await scanDir();
    } else {
      toast('已取消');
    }
  } catch (e) {
    busy(false);
    toast('打开选择窗口失败：' + e.message, 5000);
  }
}

async function scanDir() {
  const dir = $('dataDir').value.trim();
  try {
    const r = await api('/api/scan?dir=' + encodeURIComponent(dir));
    if (!r.ok) { $('scanInfo').innerHTML = '<span class="err">' + esc(r.error) + '</span>'; return; }
    let html = '找到 ' + r.count + ' 个 txt 文件；需要 ' + r.expected + ' 个。';
    if (r.missing && r.missing.length) {
      html += '<br><span class="err">缺少：' + esc(r.missing.join('、')) + '</span>';
    } else {
      html += '<br><span class="ok">数据齐全，可以计算。</span>';
    }
    $('scanInfo').innerHTML = html;
  } catch (e) { $('scanInfo').textContent = '扫描失败：' + e.message; }
}

async function saveDefault() {
  busy(true, '保存中…');
  try {
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig() }),
    });
    $('savedInfo').textContent = '已保存默认设置（settings.json）';
    toast('已存为默认（settings.json 在工具目录里，不进可移植包）');
  } catch (e) { toast('保存失败：' + e.message); }
  finally { busy(false); }
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnScan').onclick = scanDir;
  $('btnBrowse').onclick = pickDir;
  $('chartKind').onchange = drawChart;
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
