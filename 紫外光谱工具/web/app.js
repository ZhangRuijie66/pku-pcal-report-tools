/* 紫外光谱实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no', 'date',
  'room_temp_1', 'room_temp_2', 'pressure_1', 'pressure_2'];
const PROC_FIELDS = ['data_dir', 'smooth_window', 'voigt_peaks', 'stray_mode',
  'stray', 'stray_a3', 'path_cm', 'anchor_pad', 'box_a', 'box_n_B1', 'box_n_B2'];
// 配置键 -> 页面元素 id（data_dir 的输入框 id 是 dataDir）
const EL_ID = { data_dir: 'dataDir' };

let STATE = null;
let SAVED = false;

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
    if (el.type === 'checkbox') el.checked = !!c[k];
    else el.value = (c[k] === null || c[k] === undefined) ? '' : c[k];
  });
}
function readConfig() {
  const cfg = {};
  COVER_FIELDS.concat(PROC_FIELDS).forEach((k) => {
    const el = $(EL_ID[k] || k);
    if (!el) return;
    if (el.type === 'checkbox') cfg[k] = el.checked;
    else if (el.type === 'number') {
      cfg[k] = el.value === '' ? null : Number(el.value);
    } else cfg[k] = el.value;
  });
  // 测量选择：浓度系列 / 分子
  const md = {};
  document.querySelectorAll('select[data-mol]').forEach((sel) => {
    md[sel.dataset.mol] = sel.value;
  });
  cfg.molecule_default = md;
  const cp = {};
  document.querySelectorAll('select[data-conc]').forEach((sel) => {
    cp[sel.dataset.conc] = sel.value;
  });
  cfg.conc_pick = cp;
  // Beer 拟合所用的浓度
  const bc = [];
  document.querySelectorAll('input[data-beer-conc]').forEach((cb) => {
    if (cb.checked) bc.push(Number(cb.dataset.beerConc));
  });
  cfg.beer_concs = bc;
  return cfg;
}

/* ---------------------------------------------------------------- 渲染 */
function renderCals(s) {
  let html = '<tr><th>标定</th><th>线性关系</th><th>R²</th><th>波长范围 / nm</th></tr>';
  s.cals.forEach((c) => {
    html += '<tr><td>' + esc(c.short) + '</td><td>' +
      'λ = (' + c.a.toFixed(5) + ' ± ' + c.sigma_a.toFixed(5) + ')·pixel + (' +
      c.b.toFixed(1) + ' ± ' + c.sigma_b.toFixed(1) + ')</td>' +
      '<td>' + c.r2.toFixed(5) + '</td><td>' +
      Math.round(c.lam_lo) + ' ~ ' + Math.round(c.lam_hi) + '</td></tr>';
  });
  $('calTable').innerHTML = html;
}

function renderMolecules(s) {
  let html = '<tr><th>编号</th><th>测量</th><th>c / (μmol·L⁻¹)</th>' +
    '<th>λ<sub>max</sub> / nm</th><th>A</th><th>ε / (10⁵ L·mol⁻¹·cm⁻¹)</th></tr>';
  s.molecules.forEach((m) => {
    html += '<tr><td>' + esc(m.code) + '</td><td>' + esc(m.key) + '</td><td>' +
      fmt(m.conc, 1) + '</td><td>' + fmt(m.lam, 1) + '</td><td>' +
      fmt(m.A, 4) + '</td><td>' + fmt(m.eps / 1e5, 2) + '</td></tr>';
  });
  $('molTable').innerHTML = html;
  $('molNote').textContent =
    'ε = A/(c·b)，b = ' + s.config.path_cm + ' cm。A3 使用扣除杂散光后的吸光度。';
}

function renderBeer(s) {
  const b = s.beer;
  if (!b || !b.fit) { $('beerBox').innerHTML = '拟合点不足（至少 2 个）。'; return; }
  const f = b.fit;
  const pts = b.points.map((p) => p.conc + ' → ' + p.A.toFixed(4)).join('；');
  $('beerBox').innerHTML =
    '<div>数据点：' + esc(pts) + '</div>' +
    '<div style="margin-top:6px">A = (' + f.k.toFixed(4) + ' ± ' + f.sigma_k.toFixed(4) +
    ')·c + (' + f.b.toFixed(3) + ' ± ' + f.sigma_b.toFixed(3) + ')，R² = ' +
    f.r2.toFixed(4) + '</div>' +
    '<div style="margin-top:6px">ε = A/(c·b) = <b>(' + (f.eps / 1e5).toFixed(2) +
    ' ± ' + (f.sigma_k / 1e-6 / 1e5).toFixed(2) + ') × 10⁵ L·mol⁻¹·cm⁻¹</b></div>';
}

function renderWarnings(s) {
  const list = (s.warnings || []).slice();
  if (s.config && !s.config.student_name) list.push('封面「姓名」为空');
  if (s.config && !s.config.student_id) list.push('封面「学号」为空');
  if (!list.length) { $('warnCard').style.display = 'none'; return; }
  $('warnCard').style.display = '';
  $('warns').innerHTML = list.map((w) => '<div class="msg">' + esc(w) + '</div>').join('');
}

function _pickOptions(info, keys, cur) {
  return keys.map((key) => {
    const it = info[key] || {};
    const sel = (key === cur) ? ' selected' : '';
    const extra = (it.lmax != null && isFinite(it.lmax))
      ? ' · ' + fmt(it.lmax, 1) + ' nm' : '';
    return '<option value="' + esc(key) + '"' + sel + '>' + esc(key) + extra + '</option>';
  }).join('');
}

function renderPicks(s) {
  const cfg = s.config || {};
  const choices = s.choices || { conc: {}, mol: {} };
  const info = {};
  (s.samples || []).forEach((x) => { info[x.key] = x; });

  let html = '';
  (s.conc_values || []).forEach((c) => {
    const k = String(c);
    const cur = (cfg.conc_pick || {})[k];
    html += '<div class="field"><label>' + k + ' μmol·L⁻¹</label>' +
      '<select data-conc="' + k + '">' +
      _pickOptions(info, choices.conc[k] || [], cur) + '</select></div>';
  });
  $('concPicks').innerHTML = html;

  html = '';
  (s.molecule_codes || []).forEach((code) => {
    const cur = (cfg.molecule_default || {})[code];
    html += '<div class="field"><label>' + code + ' 的测量</label>' +
      '<select data-mol="' + code + '">' +
      _pickOptions(info, choices.mol[code] || [], cur) + '</select></div>';
  });
  $('molPicks').innerHTML = html;
}

function renderBeerChecks(s) {
  const cur = (s.config.beer_concs || []).map(Number);
  $('beerChecks').innerHTML = (s.conc_values || []).map((c) => {
    const on = cur.indexOf(Number(c)) >= 0 ? ' checked' : '';
    return '<label style="margin-right:10px;white-space:nowrap">' +
      '<input type="checkbox" data-beer-conc="' + c + '"' + on + '> ' + c + '</label>';
  }).join('');
}

function renderState(s) {
  STATE = s;
  fillConfig(s.config);
  $('outInfo').textContent = s.out_dir;
  setStatus('数据目录：' + s.data_dir);
  renderCals(s);
  renderMolecules(s);
  renderBeer(s);
  renderPicks(s);
  renderBeerChecks(s);
  renderWarnings(s);
  $('savedInfo').textContent = s.has_saved ? '已保存默认设置（settings.json）' : '尚未保存默认设置';
  drawChart();
}

/* ---------------------------------------------------------------- 图表 */
function chartQuery() {
  const v = $('chartKind').value;
  const parts = v.split(':');
  const q = new URLSearchParams();
  q.set('kind', parts[0]);
  if (parts[0] === 'cal') q.set('key', parts[1]);
  if (parts[0] === 'spectra') q.set('group', parts[1]);
  q.set('t', Date.now());
  return q.toString();
}
function drawChart() {
  const img = $('chart');
  img.src = '/api/preview?' + chartQuery();
  const hints = {
    cal: '左图：光源谱图与特征峰位置；右图：pixel–波长线性拟合',
    source: '同一浓度 A3 在卤钨灯与卤钨灯+氘灯下的吸收光谱',
    conc: 'A3 不同浓度的吸收光谱（只平滑、未扣基线）',
    beer: '扣除杂散光后的 A–c 线性拟合',
  };
  const kind = $('chartKind').value.split(':')[0];
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
      html += '<br><span class="err">缺少：' + r.missing.length + ' 个文件</span>';
      html += '<br><span style="font-size:11px">' + r.missing.slice(0, 4).map(esc).join('<br>') +
        (r.missing.length > 4 ? '<br>…' : '') + '</span>';
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
    SAVED = true;
    $('savedInfo').textContent = '已保存默认设置（settings.json）';
    toast('已存为默认（换机器不会带走，settings.json 在工具目录里）');
  } catch (e) { toast('保存失败：' + e.message); }
  finally { busy(false); }
}

/* ---------------------------------------------------------------- 高斯计算 (TD-DFT) */
function gcalcBase(name) {
  return String(name || '').replace(/_(td|gs|fc|freq|opt)$/i, '');
}

async function openGcalc() {
  busy(true, '启动高斯计算工具…');
  try {
    const r = await api('/api/gcalc/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    window.open(r.url, '_blank');
    toast(r.started ? '已启动高斯计算工具' : '高斯计算工具已在运行');
  } catch (e) { toast('启动失败：' + e.message); }
  finally { busy(false); }
}

function renderGcalc(res) {
  const box = $('gcalcTable');
  const mols = (res && res.molecules) || [];
  if (!mols.length) {
    box.innerHTML = '<tr><td class="hint">没读到 TD-DFT 结果。' +
      (res && res.dir ? '目录：' + esc(res.dir) : '') + '</td></tr>';
    $('gcalcNote').textContent = '提示：先在高斯计算工具里跑完 TD 单点，再回到这里读取。';
    return;
  }
  let html = '<thead><tr><th>分子</th><th>计算 λmax / nm</th><th>f</th>' +
             '<th>S1 / nm</th><th>态</th></tr></thead><tbody>';
  mols.forEach((m) => {
    const b = m.bright || {}; const s1 = m.s1 || {};
    html += '<tr data-name="' + esc(m.name) + '" style="cursor:pointer">' +
      '<td>' + esc(gcalcBase(m.name)) + '</td>' +
      '<td>' + (b.wavelength_nm ? b.wavelength_nm.toFixed(1) : '—') + '</td>' +
      '<td>' + (b.f != null ? b.f.toFixed(3) : '—') + '</td>' +
      '<td>' + (s1.wavelength_nm ? s1.wavelength_nm.toFixed(1) : '—') + '</td>' +
      '<td>S' + (b.state || '—') + '</td></tr>';
  });
  html += '</tbody>';
  box.innerHTML = html;
  box.querySelectorAll('tr[data-name]').forEach((tr) => {
    tr.addEventListener('click', () => showGcalcFigure(tr.dataset.name));
  });
  $('gcalcNote').textContent = '共 ' + mols.length + ' 个分子（目录：' + (res.dir || '') +
    '）。点任意一行看它的计算谱；点「一键生成报告」时 3.5 节会自动带上对照表。';
  showGcalcFigure(mols[0].name);
}

function showGcalcFigure(name) {
  const box = $('gcalcChartBox');
  if (!name) { box.style.display = 'none'; return; }
  box.style.display = '';
  $('gcalcChart').src = '/api/gcalc/figure?name=' + encodeURIComponent(name) + '&t=' + Date.now();
}

async function readGcalc() {
  busy(true, '读取 TD-DFT 结果…');
  try {
    const dir = $('gcalcLogs').value.trim();
    const r = await api('/api/gcalc/read' + (dir ? '?dir=' + encodeURIComponent(dir) : ''));
    if (!r.ok) { toast('读取失败：' + r.error); return; }
    renderGcalc(r);
    toast('读到 ' + r.molecules.length + ' 个 TD-DFT 结果');
  } catch (e) { toast('读取失败：' + e.message); }
  finally { busy(false); }
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnScan').onclick = scanDir;
  $('btnBrowse').onclick = pickDir;
  $('btnPickLast').onclick = () => {
    document.querySelectorAll('select[data-conc], select[data-mol]').forEach((sel) => {
      sel.selectedIndex = sel.options.length - 1;
    });
    toast('已把每个槽位设为最后一次测量，点「重新计算」生效');
  };
  $('chartKind').onchange = drawChart;
  $('btnGcalcOpen').onclick = openGcalc;
  $('btnGcalcRead').onclick = readGcalc;
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
