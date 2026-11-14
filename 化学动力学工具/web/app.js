/* 化学反应动力学实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no',
  'date', 'room_temp', 'pressure'];
const COND_FIELDS = ['temperature_c', 'sucrose_stock', 'alpha_inf_measured'];

let STATE = null;
let DATA = null;
let CURRENT_ORDER = '4M';
let PENDING_GROUP = -1;
let DATA_DIR = '';
let FILE_PICKER = null;

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
  if (x == null || x === '' || isNaN(x)) return '—';
  if (u == null || u === '' || isNaN(u) || Number(u) === 0) return num(x, d);
  return num(x, d) + ' ± ' + num(u, d);
}
// 标称酸浓度 → c(H⁺) 的换算系数（与后端 acid_ratio_of 的默认值一致）。
// 界面上可改；这里只负责在没有输入框值时给个显示用的默认。
function ACID_RATIO() {
  const el = document.getElementById('acid_ratio');
  const v = el && el.value !== '' ? Number(el.value) : 0.5;
  return (isFinite(v) && v > 0) ? v : 0.5;
}
const SUP = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
  '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
function sup(n) { return String(n).split('').map((c) => SUP[c] || c).join(''); }
async function api(path, opts) {
  const res = await fetch(path, Object.assign({ cache: 'no-store' }, opts || {}));
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}

/* ---------------------------------------------------------------- 表单 */
function fillConfig(c) {
  // 换算系数回填：读的是本函数的参数 c（不是 readConfig 里的 cfg——
  // 2026-11-14 第一版写成 cfg 直接 ReferenceError，整页卡在「初始化失败」）
  const ar = $('acid_ratio');
  if (ar) ar.value = (c.acid_ratio == null ? 0.5 : c.acid_ratio);

  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
  $('alpha_inf_mode').value = c.alpha_inf_mode || 'measured';
  CURRENT_ORDER = c.order_group || CURRENT_ORDER || '4M';
}
function readConfig() {
  const cfg = {};
  COVER_FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    cfg[k] = el.type === 'number'
      ? (el.value === '' ? null : Number(el.value)) : el.value;
  });
  cfg.alpha_inf_mode = $('alpha_inf_mode').value;
  const lit = $('acid_ratio');
  cfg.acid_ratio = (lit && lit.value !== '') ? Number(lit.value) : null;
  cfg.order_group = $('order_group').value || CURRENT_ORDER;
  cfg.data_dir = DATA_DIR || null;
  return cfg;
}

function fillData(d) {
  DATA = d || { groups: [], calibration: [] };
  DATA.groups = DATA.groups || [];
  DATA.calibration = DATA.calibration || [];
  COND_FIELDS.forEach((k) => {
    const el = $(k);
    if (el) el.value = (DATA[k] === null || DATA[k] === undefined) ? '' : DATA[k];
  });
  renderCal();
  renderGroups();
}

function readCal() {
  const points = [];
  const exclude = [];
  document.querySelectorAll('#calTable tbody tr[data-cal]').forEach((tr) => {
    const c = tr.querySelector('input[data-f="c"]');
    const a = tr.querySelector('input[data-f="alpha"]');
    if (!c || !a || c.value === '' || a.value === '') return;
    const idx = points.length;
    // n（重复次数）与 sd（读数的标准差）必须原样带回后端：报告表 1 只示出
    // 「平均值 + 重复次数」，丢了 n 就会把 10 次测量印成 1 次。
    const nEl = tr.querySelector('input[data-f="n"]');
    const n = nEl && nEl.value !== '' ? Math.max(1, Math.round(Number(nEl.value))) : 1;
    points.push({ c: Number(c.value), alpha: Number(a.value), n: n,
                  sd: (tr._sd === undefined ? null : tr._sd) });
    const ex = tr.querySelector('input[data-f="exclude"]');
    if (ex && ex.checked) exclude.push(idx);
  });
  return { points, exclude };
}

function parsePairs(text) {
  const out = [];
  String(text || '').split('\n').forEach((line) => {
    const parts = line.trim().split(/[\s,;]+/).filter((x) => x !== '');
    if (parts.length < 2) return;
    const t = Number(parts[0]);
    const a = Number(parts[1]);
    if (isFinite(t) && isFinite(a)) out.push([t, a]);
  });
  return out;
}

function readGroups() {
  const out = [];
  document.querySelectorAll('#groups .group[data-idx]').forEach((box) => {
    const get = (key) => box.querySelector('[data-g="' + key + '"]');
    const label = (get('label').value || '').trim();
    if (!label) return;
    const exTxt = (get('exclude').value || '').trim();
    const exclude = exTxt
      ? exTxt.split(/[\s,;]+/).filter((x) => x !== '').map((x) => Number(x) - 1)
        .filter((x) => x >= 0)
      : [];
    const data = parsePairs(get('data').value);
    out.push({
      label,
      acid_nominal: get('acid_nominal').value === '' ? null : Number(get('acid_nominal').value),
      acid_true: get('acid_true').value === '' ? null : Number(get('acid_true').value),
      alpha_inf: get('alpha_inf').value === '' ? null : Number(get('alpha_inf').value),
      exclude,
      data,
    });
  });
  return out;
}

function readData() {
  const cal = readCal();
  const d = {
    temperature_c: $('temperature_c').value === '' ? null : Number($('temperature_c').value),
    sucrose_stock: $('sucrose_stock').value === '' ? null : Number($('sucrose_stock').value),
    alpha_inf_measured: $('alpha_inf_measured').value === '' ? null : Number($('alpha_inf_measured').value),
    alpha_inf_n: (DATA && DATA.alpha_inf_n) || 1,
    alpha_inf_sd: (DATA && DATA.alpha_inf_sd != null) ? DATA.alpha_inf_sd : null,
    calibration: cal.points,
    calibration_exclude: cal.exclude,
    groups: readGroups(),
  };
  return d;
}

/* ---------------------------------------------------------------- 渲染 */
function renderCal() {
  const rows = DATA.calibration || [];
  let html = '<thead><tr><th>#</th><th>c / (g·mL⁻¹)</th><th>α / (°)</th>' +
    '<th title="这份平均值由几次静态读数平均得到">次数</th>' +
    '<th>剔除</th><th></th></tr></thead><tbody>';
  rows.forEach((p, i) => {
    const n = p.n == null ? 1 : p.n;
    const tie = ' title="' + (p.sd == null ? '' : '读数标准差 ' + Number(p.sd).toFixed(4) + '°') + '"';
    html += '<tr data-cal="' + i + '" data-sd="' + (p.sd == null ? '' : p.sd) + '"><td>' + (i + 1) + '</td>' +
      '<td><input type="number" step="any" data-f="c" value="' +
      (p.c == null ? '' : esc(p.c)) + '"></td>' +
      '<td><input type="number" step="any" data-f="alpha" value="' +
      (p.alpha == null ? '' : esc(p.alpha)) + '"></td>' +
      '<td><input type="number" step="1" min="1" data-f="n" value="' + esc(n) + '"' + tie + '></td>' +
      '<td><input type="checkbox" data-f="exclude"' +
      ((DATA.calibration_exclude || []).indexOf(i) >= 0 ? ' checked' : '') + '></td>' +
      '<td><button class="btn mini" data-del-cal="' + i + '">删</button></td></tr>';
  });
  // 刷新后把 sd 挂回行元素（readCal 从 tr._sd 取），保证来回不丢
  document.querySelectorAll('#calTable tbody tr[data-cal]').forEach((tr) => {
    const v = tr.getAttribute('data-sd');
    tr._sd = (v === null || v === '') ? null : Number(v);
  });
  $('calTable').innerHTML = html + '</tbody>';
}

function renderOrderOptions() {
  const sel = $('order_group');
  const labels = (DATA.groups || []).map((g) => g.label).filter(Boolean);
  sel.innerHTML = labels.map((x) => '<option value="' + esc(x) + '">' +
    esc(x) + '</option>').join('');
  if (labels.indexOf(CURRENT_ORDER) >= 0) sel.value = CURRENT_ORDER;
  else if (labels.length) sel.value = labels[0];
}

function renderGroups() {
  let html = '';
  (DATA.groups || []).forEach((g, i) => {
    const dataTxt = (g.data || []).map((p) => p[0] + ' ' + p[1]).join('\n');
    const exTxt = (g.exclude || []).map((x) => x + 1).join(', ');
    html += '<div class="group" data-idx="' + i + '">' +
      '<div class="group-head"><b>' + esc(g.label || ('组' + (i + 1))) + '</b>' +
      '<span class="grow"></span>' +
      '<button class="btn mini" data-import-group="' + i + '">导入 xlsx/CSV</button>' +
      '<button class="btn mini" data-del-group="' + i + '">删除</button></div>' +
      '<div class="grid3">' +
      '<div class="field"><label>编号（如 4M）</label><input type="text" data-g="label" value="' +
      esc(g.label || '') + '"></div>' +
      '<div class="field"><label>标称酸浓度 /(mol·L⁻¹)</label><input type="number" step="any" data-g="acid_nominal" value="' +
      (g.acid_nominal == null ? '' : esc(g.acid_nominal)) + '"></div>' +
      '<div class="field"><label>c(H⁺) 真实值</label><input type="number" step="any" data-g="acid_true" value="' +
      (g.acid_true == null ? '' : esc(g.acid_true)) +
      '" placeholder="留空则按 标称×系数 换算"></div></div>' +
      (g.acid_source === 'nominal' ?
        '<p class="hint">本组 c(H⁺) = 标称 ' + esc(g.acid_nominal) + ' × 系数 ' +
        num(ACID_RATIO(), 3) + ' = <b>' + num(g.acid_eff, 4) +
        '</b>（换算所得；手填真实值可覆盖）</p>' : '') +
      '<div class="grid2">' +
      '<div class="field"><label>α∞ 覆盖（可空）</label><input type="number" step="any" data-g="alpha_inf" value="' +
      (g.alpha_inf == null ? '' : esc(g.alpha_inf)) + '"></div>' +
      '<div class="field"><label>剔除点序号（从 1 开始）</label><input type="text" data-g="exclude" value="' +
      esc(exTxt) + '" placeholder="例如 6"></div></div>' +
      '<div class="field"><label>t–α 数据（每行 t α；共 ' +
      ((g.data || []).length) + ' 点）</label><textarea data-g="data" rows="6">' +
      esc(dataTxt) + '</textarea></div></div>';
  });
  $('groups').innerHTML = html || '<p class="hint">还没有分组，点下面的「添加一组」。</p>';
  renderOrderOptions();
}

function renderResults(s) {
  const cal = s.calibration || {};
  const ainf = s.alpha_inf || {};
  const rows = (s.groups || []).map((g) => (
    '<tr><td>' + esc(g.label) + '</td><td>' +
    (g.acid_eff == null ? '—' : num(g.acid_eff, 3)) +
    // 换算来的组把标称值一并显示，读者不用回头翻分组卡片
    (g.acid_source === 'nominal'
      ? '<span class="hint" title="由标称酸浓度换算">*（标称 ' +
        num(g.acid_nominal, 1) + '）</span>' : '') +
    '</td>' +
    '<td>' + pm(g.k1 * 1e3, g.sigma_k1 * 1e3, 3) + '</td>' +
    '<td>' + pm(g.t_half, g.sigma_t_half, 1) + '</td>' +
    '<td>' + (g.fits && g.fits['1'] ? num(g.r2['1'], 4) : '—') + '</td>' +
    '<td>' + g.n + '</td></tr>'
  )).join('');
  $('fitTable').innerHTML = '<thead><tr><th>编号</th><th>c(H⁺)</th>' +
    '<th>k₁ / (10⁻³ s⁻¹)</th><th>t₁/₂ / s</th><th>R²</th><th>n</th></tr></thead><tbody>' +
    rows + '</tbody>';
  let note = '';
  if (cal.fit) {
    note += '标定：α = (' + num(cal.fit.slope, 2) + ' ± ' + num(cal.fit.sigma_slope, 2) +
      ')c + (' + num(cal.fit.intercept, 3) + ' ± ' + num(cal.fit.sigma_intercept, 3) +
      ')，R² = ' + num(cal.fit.r2, 5) + '。';
  }
  if (s.acid_derived && s.acid_derived.length) {
    note += ' c(H⁺) 中标 * 的 ' + s.acid_derived.length + ' 组由标称酸浓度 × ' +
      num(s.acid_ratio, 3) + ' 换算；';
  }
  note += ' c₀ = ' + num(s.c0, 4) + ' g·mL⁻¹，α₀ = ' + num(s.alpha0, 2) + '°，' +
    'α∞ 实验 ' + num(ainf.measured, 2) + '° / 理论 ' + num(ainf.theory, 2) + '°。';
  if (s.rate_law) {
    const rl = s.rate_law;
    // sigma_n 为 null = 数据组数恰好等于参数个数（残差自由度 0），
    // 点估计成立但不确定度无定义。此时只显示值，并明确写「无自由度」，
    // 不能显示成 "4 ± —" 或干脆漏掉（SKILL §27 点估计与不确定度分开）。
    const hasSig = rl.sigma_ok && rl.sigma_n != null;
    note += ' k₁–c(H⁺)：k₀ = ' + rl.k0.toExponential(2) + ' s⁻¹，n = ' +
      num(rl.n, 2) + (hasSig ? ' ± ' + num(rl.sigma_n, 2) : '（无不确定度）') +
      '，R² = ' + num(rl.r2, 4) + '。';
    if (!hasSig) {
      note += ' 只有 ' + rl.n_points + ' 组数据却拟合 ' + rl.n_params +
        ' 个参数，残差自由度为 0：点估计是唯一解，但给不出误差棒。';
    }
    if (rl.at_bound) {
      note += ' n 顶到拟合上界 4，只能当下限看待。';
    }
  }
  if (s.loglog) {
    note += ' lg–lg：n = ' + num(s.loglog.slope, 2) + ' ± ' +
      num(s.loglog.sigma_slope, 2) + '，R² = ' + num(s.loglog.r2, 4) + '。';
  }
  $('fitNote').textContent = note;

  const o = s.order;
  let orows = '';
  if (o) {
    const names = { '0': '零级', '1': '一级', '2': '二级' };
    const expr = { '0': 'α–t', '1': 'ln(α−α∞)–t', '2': '1/(α−α∞)–t' };
    ['0', '1', '2'].forEach((i) => {
      orows += '<tr><td>' + names[i] + '</td><td>' + expr[i] + '</td><td>' +
        num(o.r2[i], 5) + '</td><td>' +
        (String(o.best) === i ? '最接近直线' : '明显弯曲') + '</td></tr>';
    });
  }
  $('orderTable').innerHTML = orows
    ? '<thead><tr><th>级数</th><th>线性化关系</th><th>R²</th><th>判断</th></tr></thead><tbody>' +
      orows + '</tbody>'
    : '<tr><td class="hint">还没有可用于级数判定的数据。</td></tr>';
  $('orderNote').textContent = o
    ? ('判定所用组：' + o.group + '；蔗糖的反应级数为 ' + o.best +
       ' 级。' + (o.is_first ? '' : ' 一级拟合 R² 未达到 0.99，请检查数据。'))
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

function mergeAcid(s) {
  // 把后端算出的 acid_eff / acid_source 回填进 DATA.groups。
  //
  // renderGroups() 用的是 DATA.groups（提交给后端的原始输入），里面没有
  // 这两个字段——它们是后端算完才有的。不回填的话，卡片上那行
  // 「本组 c(H⁺) = 标称 × 系数 = …」永远不显示（用户 2026-11-14 报的就是这个）。
  //
  // 按 label 对齐；label 重复时按出现次序一一对应，不能按下标硬对
  // （后端会按 c(H⁺) 从小到大重排）。
  const got = (s && s.groups) || [];
  if (!got.length) return;
  const pool = {};
  got.forEach((g) => {
    const k = String(g.label || '');
    (pool[k] = pool[k] || []).push(g);
  });
  (DATA.groups || []).forEach((g) => {
    const arr = pool[String(g.label || '')];
    if (!arr || !arr.length) return;
    const src = arr.shift();           // 同名组按出现次序一一对应
    g.acid_eff = src.acid_eff;
    g.acid_source = src.acid_source;
  });
}

function renderState(s) {
  STATE = s;
  fillConfig(s.config);
  fillData(s.data);
  mergeAcid(s);
  renderGroups();                      // 回填后重绘，卡片才显示换算结果
  $('dataFile').textContent = s.data_file || '';
  DATA_DIR = s.data_dir || DATA_DIR || '';
  paintDataDir();
  refreshFileTargets();
  setStatus('数据文件：' + (s.data_file || '—'));
  renderResults(s);
  renderWarnings(s);
  drawChart();
}

/* ---------------------------------------------------------------- 图表 */
function drawChart() {
  const kind = $('chartKind').value;
  let url = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
  if (kind === 'order') {
    url += '&group=' + encodeURIComponent($('order_group').value || CURRENT_ORDER);
  }
  $('chart').src = url;
  const hints = {
    calibration: '全部标定点 + 95% 置信带；空心点为剔除点',
    alpha_t: '不同盐酸浓度下的 α–t 曲线；× 为剔除点',
    order: '零级、一级、二级三种线性化；一级的 R² 最高',
    first_order: '各组 ln(α−α∞)–t 拟合',
    rate_law: 'k₁–c(H⁺) 非线性拟合，注记为 n 与 R²',
    loglog: 'lg(k₁−k₀)–lg c(H⁺) 线性拟合，斜率为 n',
  };
  $('chartHint').textContent = hints[kind] || '';
}

/* ---------------------------------------------------------------- 动作 */
async function boot() {
  setStatus('正在初始化…');
  try {
    const s = await api('/api/state');
    renderState(s);
    await initFiles();
    const q = new URLSearchParams(location.search);
    const home = q.get('home');
    if (home) {
      $('btnHome').href = home;
      $('btnHome').style.display = '';
    }
    setStatus('就绪');
    if (window.PcalDraft) {
      await PcalDraft.init({
        key: 'pcal-draft-kinetics-v1',
        read: () => ({config: readConfig(), data: readData()}),
        apply: async (d) => {
          fillConfig(d.config || {});
          fillData(d.data || {});
          await recalc();
        },
      });
    }
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
    toast('已载入 2025 年示例数据');
  } catch (e) { toast('载入失败：' + e.message); }
  finally { busy(false); }
}

async function importFile(kind, file, groupIndex) {
  const buf = await file.arrayBuffer();
  const url = '/api/import?kind=' + encodeURIComponent(kind) +
    '&filename=' + encodeURIComponent(file.name);
  const r = await api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: buf,
  });
  // 标定：可能是整张 c–α 表（mode='table'），也可能是**一个静态重复读数**
  // （mode='point'，浓度从文件名猜）。后者追加成一行，不覆盖已有标定点。
  if (kind === 'calibration') {
    if (r.mode === 'point') {
      const p = r.point || {};
      if (p.c == null) {
        // 文件名里没有唯一明确的浓度 → 让用户填，绝不自己编一个
        toast('已读入 ' + (p.n || 0) + ' 次读数（α = ' +
          (p.alpha == null ? '—' : Number(p.alpha).toFixed(3)) +
          '°），但文件名里认不出浓度，请在该行手填 c', 6500);
      } else {
        toast('已加入一个标定点：c = ' + p.c + ' g·mL⁻¹，α = ' +
          Number(p.alpha).toFixed(3) + '°（' + p.n + ' 次读数平均）', 5000);
      }
      DATA.calibration = (DATA.calibration || []).concat([
        { c: p.c, alpha: p.alpha, n: p.n || 1, sd: p.sd }]);
      renderCal();
      await recalc();
      return;
    }
    DATA.calibration = r.rows || [];
    DATA.calibration_exclude = [];
    renderCal();
    await recalc();
    toast('已导入 ' + r.count + ' 个标定点');
    return;
  }
  // α∞：静态重复读数 → 只留平均值与次数
  if (kind === 'alpha_inf') {
    const a = r.alpha || {};
    $('alpha_inf_measured').value = a.mean == null ? '' : Number(a.mean).toFixed(4);
    DATA.alpha_inf_n = a.n || 1;
    DATA.alpha_inf_sd = a.sd == null ? null : a.sd;
    $('alpha_inf_mode').value = 'measured';
    await recalc();
    toast('α∞ = ' + Number(a.mean).toFixed(3) + '°（' + (a.n || 1) +
      ' 次读数的平均值）', 5000);
    return;
  }
  if (kind === 'static') {
    const a = r.alpha || {};
    toast('静态读数：α = ' + Number(a.mean).toFixed(3) + '°（' + (a.n || 1) +
      ' 次，标准差 ' + (a.sd == null ? '—' : Number(a.sd).toFixed(4)) + '°）', 6000);
    return;
  }
  const g = DATA.groups[groupIndex];
  if (!g) { toast('目标分组不存在'); return; }
  g.data = r.points || [];
  if (r.temperature != null && $('temperature_c').value === '') {
    $('temperature_c').value = r.temperature;
  }
  if (r.acid != null && g.acid_nominal == null) g.acid_nominal = r.acid;
  renderGroups();
  await recalc();
  toast('已导入 ' + r.count + ' 个数据点' +
    (r.temperature != null ? '（实验温度 ' + r.temperature + ' ℃）' : ''));
}

function addGroup() {
  const d = readData();
  d.groups.push({ label: '新组', acid_nominal: null, acid_true: null,
    alpha_inf: null, exclude: [], data: [] });
  DATA = d;
  renderGroups();
}

function deleteGroup(i) {
  const d = readData();
  d.groups.splice(i, 1);
  DATA = d;
  renderGroups();
  recalc();
}

function addCal() {
  const d = readData();
  d.calibration.push({ c: null, alpha: null });
  DATA = d;
  renderCal();
}

function deleteCal(i) {
  const d = readData();
  d.calibration.splice(i, 1);
  DATA = d;
  renderCal();
}

/* ---------------------------------------------------------------- 数据目录
 * 数据本体在 data/化学动力学数据.json；「数据目录」只用来翻/挑要**导入**的
 * xlsx/csv（Polariputer 导出）。默认由后端 dataloc.find_data_dir 运行时推导，
 * 换机器解压后一定指到一个存在的目录，不会开天窗。
 * 选定文件后一律调现成的 importFile()，不另写一套解析。
 */
function paintDataDir() {
  const el = $('dataDir');
  if (el) el.textContent = DATA_DIR || '—';
}

/* 「导入到」下拉的值 → 后端 kind。负数分别是标定表 / α∞ / 只查看。
 * 单独抽出来：文件选择器与「导入」按钮两条路径必须用同一套映射，
 * 以前各写一遍 `target < 0 ? 'calibration' : 'group'`，加第三档就漏一处。 */
function targetKind(target) {
  if (target === -2) return 'alpha_inf';
  if (target === -3) return 'static';
  if (target < 0) return 'calibration';
  return 'group';
}

/* 「导入到」下拉：标定表 + 每个动力学分组，跟着分组增删刷新 */
function refreshFileTargets() {
  const sel = $('fileTarget');
  if (!sel) return;
  const keep = sel.value;
  const labels = (STATE && STATE.group_labels) || [];
  // ⚠ 静态读数（只有 steps/angle、没有 time）必须导到标定表 / α∞ / 查看这几档，
  // 导到动力学分组后端会直接报错（步数被当成时间就是 2026-11-10 那个 bug）。
  let html = '<option value="-1">旋光度–浓度标定表（c–α 表 或 静态读数）</option>' +
    '<option value="-2">α∞（反应终了静态读数）</option>' +
    '<option value="-3">只查看静态读数（不改数据）</option>';
  labels.forEach((lab, i) => {
    html += '<option value="' + i + '">动力学分组 ' + esc(lab) + '（动态 xlsx）</option>';
  });
  sel.innerHTML = html;
  if (keep !== '' && Array.prototype.some.call(sel.options,
    (o) => o.value === keep)) sel.value = keep;
}

async function fileFromDir(rel) {
  const r = await api('/api/fileb64?dir=' + encodeURIComponent(DATA_DIR)
    + '&rel=' + encodeURIComponent(rel));
  const bin = atob(r.b64 || '');
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new File([bytes], r.name || String(rel).split('/').pop());
}

async function pickDataDir() {
  if (!window.PcalFiles) { toast('文件选择组件未加载'); return; }
  const dir = await PcalFiles.pickFolder(DATA_DIR);
  if (!dir) return;
  DATA_DIR = dir;
  paintDataDir();
  await saveDefault();                    // 记住这个目录（与「存为默认」同一条路）
  if (FILE_PICKER) await FILE_PICKER.load(DATA_DIR);
  toast('数据目录已切换到 ' + dir, 4000);
}

async function initFiles() {
  if (!window.PcalFiles) return;
  refreshFileTargets();
  try {
    FILE_PICKER = PcalFiles.mount($('filePick'), {
      placeholder: '搜索文件名，如 4M / 蔗糖 / 2026-10',
      exts: ['.xlsx', '.xlsm', '.csv', '.txt', '.tsv'],
      onPick: async (rel) => {
        const target = Number($('fileTarget').value);
        const kind = targetKind(target);
        busy(true, '从数据目录读取文件…');
        try { await importFile(kind, await fileFromDir(rel), target); }
        catch (e) { toast('导入失败：' + e.message, 6000); }
        finally { busy(false); }
      },
    });
    await FILE_PICKER.load(DATA_DIR);
  } catch (e) {
    // 选择器坏掉不该拖垮整个页面：原有 <input type=file> 仍然可用
    toast('文件选择器初始化失败：' + e.message, 5000);
  }
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnSaveData').onclick = saveData;
  $('btnSample').onclick = loadSample;
  $('btnAddCal').onclick = addCal;
  $('btnAddGroup').onclick = addGroup;
  $('btnPickDir').onclick = pickDataDir;
  $('btnImportCal').onclick = () => $('calFile').click();
  $('calFile').onchange = async () => {
    const f = $('calFile').files[0];
    if (!f) return;
    busy(true, '读取标定表…');
    try { await importFile('calibration', f, -1); }
    catch (e) { toast('导入失败：' + e.message, 5000); }
    finally { busy(false); $('calFile').value = ''; }
  };
  $('groupFile').onchange = async () => {
    const f = $('groupFile').files[0];
    if (!f || PENDING_GROUP < 0) return;
    busy(true, '读取动力学数据…');
    try { await importFile('group', f, PENDING_GROUP); }
    catch (e) { toast('导入失败：' + e.message, 5000); }
    finally { busy(false); $('groupFile').value = ''; PENDING_GROUP = -1; }
  };
  $('groups').addEventListener('click', (e) => {
    const imp = e.target.closest('button[data-import-group]');
    if (imp) {
      PENDING_GROUP = Number(imp.dataset.importGroup);
      $('groupFile').click();
      return;
    }
    const del = e.target.closest('button[data-del-group]');
    if (del) deleteGroup(Number(del.dataset.delGroup));
  });
  $('calTable').addEventListener('click', (e) => {
    const del = e.target.closest('button[data-del-cal]');
    if (del) deleteCal(Number(del.dataset.delCal));
  });
  $('chartKind').onchange = drawChart;
  $('order_group').onchange = () => { CURRENT_ORDER = $('order_group').value; drawChart(); };
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
