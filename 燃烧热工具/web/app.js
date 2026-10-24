/* 燃烧热实验报告一键生成 —— 前端逻辑 */
'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  config: null,
  defaults: null,
  substances: {},
  rounds: [],          // 每轮的输入配置
  datasets: {},        // file -> {t, y, params, name}
  views: [],           // 每轮的计算结果视图
  active: 0,
  dirty: false,
};
const DRAFT_KEY = 'pcal-draft-combustion-v1';
const DRAFT_MAX_AGE = 30 * 864e5;
const undoStack = [];
let restoringDraft = false;
let draftReady = false;
let draftTimer = null;

/* ---------------------------------------------------------------- util */
function toast(msg, ms = 2600) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('on'), ms);
}
function busy(on, text) {
  $('overlay').classList.toggle('on', !!on);
  if (text) $('overlayText').textContent = text;
}
function setStatus(s) { $('status').textContent = s; }

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }));
  if (!r.ok || j.ok === false) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

function fmt(x, n = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  return Number(x).toFixed(n);
}
function esc(s) {
  return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function sci(x, n = 2) {
  if (!x) return '0';
  const e = Math.floor(Math.log10(Math.abs(x)));
  return (x / Math.pow(10, e)).toFixed(n) + '×10' + sup(e);
}
function sup(n) {
  const map = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
                '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
  return String(n).split('').map(c => map[c] || c).join('');
}

/* ---------------------------------------------------------------- 初始化 */
async function boot() {
  const s = await api('/api/state');
  state.config = s.config;
  state.defaults = s.defaults;
  state.substances = s.substances;
  // 从统一入口（物化实验报告工具）跳转过来时带 ?home=…：显示「返回入口」
  const q = new URLSearchParams(location.search);
  if (q.get('home')) {
    $('btnHome').href = q.get('home');
    $('btnHome').style.display = '';
  }
  fillConfigForm(s.config);
  showSavedInfo(s.has_saved, s.settings_file);
  $('dataDir').value = s.config.data_dir || s.default_dir || '';
  $('outInfo').innerHTML = '报告输出到：<code>' + esc(s.output_dir || '—')
    + '</code>（每份报告一个子文件夹，全部实验共用这一个目录）';
  await scanDir($('dataDir').value, true);
  setStatus('就绪 · 数据目录 ' + ($('dataDir').value || '—'));
  await recalc();
  await maybeRestoreDraft();
  draftReady = true;
}

async function scanDir(dir, autoFill) {
  if (!dir) return;
  const files = await api('/api/scan?dir=' + encodeURIComponent(dir));
  state.fileList = files.files;
  state.fileListDir = dir;
  $('fileCount').textContent = files.files.length
    ? '找到 ' + files.files.length + ' 个数据文件：' + files.files.map(f => f.name).join('、')
    : '该文件夹下没有找到课程软件导出的数据 csv（需要包含 time(s),Delta_T(K) 表头）。';
  if (autoFill && files.files.length && !state.rounds.some(r => r.file)) {
    state.rounds = defaultRoundsFromFiles(files.files);
  }
  renderRounds();
  return files.files;
}

/* ---------------------------------------------------------------- 默认值 */
function showSavedInfo(hasSaved, file) {
  $('savedInfo').textContent = hasSaved
    ? '已记住上次「存为默认」的封面与实验条件，打开程序时自动填回。'
    : '还没有存过默认值；填好后点「存为默认」，以后打开会自动填回。';
  $('savedInfo').title = file || '';
}

async function saveAsDefault() {
  const cfg = readConfigForm();
  try {
    await api('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: cfg }),
    });
    showSavedInfo(true, '');
    toast('已存为默认，下次打开自动填回');
  } catch (e) {
    toast('保存失败：' + e.message, 5000);
  }
}

async function resetDefault() {
  if (!confirm('恢复到出厂默认值？已保存的封面 / 实验条件会被清除。')) return;
  try {
    const s = await api('/api/settings', { method: 'DELETE' });
    fillConfigForm(s.config);
    showSavedInfo(false, '');
    toast('已恢复出厂默认');
    recalc();
  } catch (e) {
    toast('恢复失败：' + e.message);
  }
}

function defaultRoundsFromFiles(files) {
  // 依据文件名猜测角色：含“苯甲酸”的是标准物质
  const order = ['方糖', '苯甲酸', '黄冰糖'];
  const ranked = files.slice().sort((a, b) => {
    const ia = order.findIndex(k => a.name.includes(k));
    const ib = order.findIndex(k => b.name.includes(k));
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return ranked.map((f, i) => {
    const r = mkRound(i + 1);
    r.file = f.path;
    r.name = f.name.replace(/\.csv$/i, '');
    r.role = /苯甲酸|benzoic/i.test(f.name) ? 'standard' : 'sample';
    return r;
  });
}

function mkRound(i) {
  return {
    index: i, enabled: true, role: 'sample', name: '第' + i + '轮',
    substance: 'sucrose', file: null, params: {}, points: null,
    sample_mass: null, note: '',
  };
}

function fillConfigForm(c) {
  ['student_name', 'student_id', 'group', 'group_no', 'date'].forEach(k => {
    if (c[k]) $(k).value = c[k];
  });
  const set = (id, v) => {
    if (v !== null && v !== undefined && v !== '') $(id).value = v;
    else $(id).value = '';
  };
  set('water_volume_mL', c.water_volume_mL);
  set('pressure_kPa', c.pressure_kPa);
  set('temperature_C', c.temperature_C);
  set('water_density', c.water_density);
  set('water_capacity', c.water_capacity);
  set('cotton_heat', c.cotton_heat);
  set('nickel_heat', c.nickel_heat);
  set('benzoic_enthalpy', c.benzoic_enthalpy);
  set('e_balance', c.e_balance);
  set('e_temperature', c.e_temperature);
  set('std_limit', c.std_limit);
  if (c.point_prefer) $('point_prefer').value = c.point_prefer;
  $('force_temperature').checked = !!c.force_temperature;
}

function readConfigForm() {
  const num = (id) => {
    const v = $(id).value.trim();
    return v === '' ? null : Number(v);
  };
  const txt = (id) => $(id).value.trim() || null;
  return {
    student_name: txt('student_name'), student_id: txt('student_id'),
    group: txt('group'), group_no: txt('group_no'), date: txt('date'),
    pressure_kPa: num('pressure_kPa'),
    water_volume_mL: num('water_volume_mL'),
    temperature_C: num('temperature_C'),      // 界面用摄氏度
    force_temperature: $('force_temperature').checked,
    water_density: num('water_density'),
    water_capacity: num('water_capacity'),
    cotton_heat: num('cotton_heat'),
    nickel_heat: num('nickel_heat'),
    benzoic_enthalpy: num('benzoic_enthalpy'),
    e_balance: num('e_balance'),
    e_temperature: num('e_temperature'),
    std_limit: num('std_limit'),
    point_prefer: $('point_prefer').value,
    data_dir: $('dataDir').value.trim() || null,   // 记住数据文件夹，下次打开直接定位
  };
}

/* ---------------------------------------------------------------- 轮次 UI */
function renderRounds() {
  const host = $('rounds');
  host.innerHTML = '';
  state.rounds.forEach((r, i) => {
    const div = document.createElement('div');
    div.className = 'round' + (i === state.active ? ' active' : '');
    const subOpts = Object.entries(state.substances)
      .map(([k, v]) => `<option value="${k}"${r.substance === k ? ' selected' : ''}>${v.label}</option>`)
      .join('');
    div.innerHTML = `
      <div class="head">
        <input type="text" value="${r.name}" data-i="${i}" data-k="name">
        <span class="tag ${r.role === 'standard' ? 'std' : 'sam'}">${r.role === 'standard' ? '标准物质' : '待测样品'}</span>
      </div>
      <div class="row"><label>数据文件</label>
        <select data-i="${i}" data-k="file" style="flex:1">
          <option value="">— 选择 —</option>
          ${(state.fileList || []).map(f =>
            `<option value="${f.path}"${r.file === f.path ? ' selected' : ''}>${f.name}</option>`).join('')}
        </select>
      </div>
      <div class="row"><label>角色</label>
        <select data-i="${i}" data-k="role" style="flex:1">
          <option value="standard"${r.role === 'standard' ? ' selected' : ''}>标准物质（苯甲酸）</option>
          <option value="sample"${r.role === 'sample' ? ' selected' : ''}>待测样品</option>
        </select>
      </div>
      ${r.role === 'standard' ? `
      <div class="row"><label>主成分</label>
        <span class="fixed">苯甲酸 C<sub>7</sub>H<sub>6</sub>O<sub>2</sub>
          （M<sub>r</sub> = 122.123 g/mol，用于标定量热计常数 W）</span>
      </div>` : `
      <div class="row"><label>主成分</label>
        <select data-i="${i}" data-k="substance" style="flex:1">${subOpts}</select>
      </div>`}
      <div class="row"><label>样品质量 /g</label>
        <input type="number" step="0.0001" data-i="${i}" data-k="sample_mass"
               value="${r.sample_mass ?? ''}" placeholder="留空=可燃物-棉线">
      </div>
      <div style="display:flex;gap:6px;margin-top:4px">
        <button class="btn" data-act="show" data-i="${i}" style="flex:1">查看该轮曲线</button>
        <button class="btn" data-act="del" data-i="${i}">删除</button>
      </div>`;
    host.appendChild(div);
  });
  host.querySelectorAll('input,select').forEach(el => {
    el.addEventListener('input', onRoundField);
    el.addEventListener('change', onRoundField);
  });
  host.querySelectorAll('button[data-act]').forEach(b => {
    b.addEventListener('click', () => {
      const i = Number(b.dataset.i);
      if (b.dataset.act === 'del') {
        if (state.rounds.length <= 1) return toast('至少保留一轮数据');
        state.rounds.splice(i, 1);
        state.active = Math.max(0, Math.min(state.active, state.rounds.length - 1));
        renderRounds(); recalc();
      } else {
        state.active = i; renderRounds(); showRound(i);
      }
    });
  });
}

function onRoundField(e) {
  const i = Number(e.target.dataset.i);
  const k = e.target.dataset.k;
  let v = e.target.value;
  if (k === 'sample_mass' || k === 'index') v = v === '' ? null : Number(v);
  state.rounds[i][k] = v;
  if (['name', 'role', 'substance'].includes(k)) { renderRounds(); }
  if (['file', 'role', 'sample_mass', 'substance'].includes(k)) recalc();
}

/* ---------------------------------------------------------------- 计算 */
async function recalc() {
  const payload = {
    config: readConfigForm(),
    rounds: state.rounds.map(r => ({
      name: r.name, role: r.role, substance: r.substance, file: r.file,
      params: r.params || {}, points: r.points, sample_mass: r.sample_mass,
      enabled: r.enabled !== false,
    })),
  };
  if (!payload.rounds.some(r => r.file)) { setStatus('请选择数据文件'); return; }
  try {
    const res = await api('/api/calc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.views = res.rounds;
    state.dirty = false;
    state.active = Math.min(state.active, res.rounds.length - 1);
    setStatus('计算完成 · ' + new Date().toLocaleTimeString());
    showRound(state.active);
    renderResults(res);
    saveDraft();
  } catch (err) {
    setStatus('计算失败');
    toast('计算失败：' + err.message, 5000);
  }
}

/* ---------------------------------------------------------------- 展示 */
function showRound(i, keepSelection) {
  const v = state.views[i];
  if (!v) return;
  const switched = i !== state.active;
  state.active = i;
  renderRounds();
  $('chartTitle').textContent = `${v.name} · ${v.role === 'standard' ? '标准物质' : '待测样品'}`;

  // 重算时保持“微调序号 / 数值”不变，除非换到了另一轮数据
  const keep = keepSelection || !switched;
  const keptWhich = $('whichPoint').value;
  const keptValue = $('pointValue').value;

  drawChart(v);
  renderStats(v);
  renderRaw(v);

  if (keep && keptWhich !== '') {
    $('whichPoint').value = keptWhich;
    const idx = Number(keptWhich);
    $('pointValue').value = (Number(keptValue) === v.points[idx] || keptValue === '')
      ? v.points[idx] : keptValue;
  } else {
    $('whichPoint').value = '1';
    $('pointValue').value = v.points[1];
  }

  const info = [];
  const names = ['S1', 'E1', 'S2', 'E2'];
  info.push(v.is_auto ? ('自动取点：' + (v.auto_method || '—')) : '取点方式：手动指定');
  info.push(names.map((n, k) => `${n}=${v.points[k]} (${fmt(v.points_t[k], 1)} s)`).join('　'));
  if (v.auto_warning) info.push('<b style="color:#b45309">⚠ ' + v.auto_warning + '</b>');
  $('autoInfo').innerHTML = info.join('　·　');

  const cfg = readConfigForm();
  const fn = reportFilename(cfg);
  $('exportName').textContent = fn;
  $('exportName').title = '输出到 ' + (state.outputDir || '输出目录') + '\\' + fn;
}

function renderStats(v) {
  const R = v.results || {};
  const rows = [
    ['T_l / K', fmt(v.T_left, 3)], ['T_r / K', fmt(v.T_right, 3)],
    ['Δt₀（雷诺垂线）/ s', fmt(v.x0, 2)], ['ΔT / K', fmt(v.dT, 4)],
    ['Σq_V / J', fmt(R.sum_q, 2)], ['样品质量 / g', fmt(v.sample_mass, 4)],
    ['D·C_w / (J/K)', fmt(R.D_Cw, 0)],
    [`采用室温 / K`, fmt(v.temperature_used_K, 2) + (v.temperature_source ? '（' + v.temperature_source + '）' : '')],
    ['拟合1 R²', fmt(v.R2_1, 4)], ['拟合2 R²', fmt(v.R2_2, 4)],
  ];
  $('stats').innerHTML = rows.map(([k, val]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${val}</div></div>`).join('');
}

function renderResults(res) {
  const std = res.rounds.find(r => r.role === 'standard');
  let html = '';
  if (std) {
    html += `<p>量热计常数 <b>W = ${fmt(std.results.W, 1)} ± ${fmt(Math.abs(std.results.sigma_W), 0)} J/K</b>
      <span class="pill">由 ${std.name} 标定</span></p>`;
  }
  res.rounds.filter(r => r.role !== 'standard').forEach(r => {
    const R = r.results;
    let line = `<p><b>${r.name}</b>：ΔT = ${fmt(r.dT, 3)} K，
      Q<sub>V</sub> = ${fmt(R.Qv_per_gram, 1)} ± ${fmt(R.sigma_Qv_per_gram, 1)} J/g`;
    if (R.molar) {
      line += `，即 <b>Q<sub>p</sub> = ${fmt(R.molar.Qp_kJ_per_mol, 0)} ± ${fmt(R.molar.sigma_kJ_per_mol, 1)} kJ/mol</b>`;
      if (R.molar.literature)
        line += `（文献 ${fmt(R.molar.literature, 0)}，相对误差 ${fmt(R.molar.error_percent, 2)}%）`;
    }
    line += '</p>';
    html += line;
  });
  html += `<p class="hint">不确定度模型：天平允差 ${fmt(readConfigForm().e_balance, 4)} g、
    温差仪允差 ${fmt(readConfigForm().e_temperature, 3)} K，
    σ<sub>ΔT</sub> = ${fmt(res.sigma_dT, 4)} K，σ<sub>Σq</sub> = ${fmt(res.sigma_sumq, 2)} J，
    σ<sub>m,tot</sub> = ${fmt(res.sigma_msam, 5)} g（按均匀分布取 1/√3，两次测量按 √2 合成）。</p>`;
  const host = $('results');
  if (host) host.innerHTML = html;
}

function renderRaw(v) {
  const rows = (v.chart && v.chart.t || []).slice(0, 30);
  const ys = (v.chart && v.chart.y || []).slice(0, 30);
  const host = $('rawtable');
  if (!host) return;
  let html = '<table><thead><tr><th>#</th><th>t / s</th><th>ΔT / K</th></tr></thead><tbody>';
  rows.forEach((t, i) => {
    html += `<tr><td>${i}</td><td>${fmt(t, 3)}</td><td>${fmt(ys[i], 3)}</td></tr>`;
  });
  html += '</tbody></table><p class="hint">共 ' + v.n + ' 个数据点，此处仅显示前 30 个。</p>';
  $('rawtable').innerHTML = html;
}

/* ---------------------------------------------------------------- SVG 图 */
const CH = { w: 940, h: 430, l: 70, r: 150, t: 18, b: 46 };
let drag = null;

function drawChart(v) {
  const c = v.chart;
  const host = $('chartHost');
  if (!c || !c.t || !c.t.length || !host) return;
  const xs = c.t, ys = c.y;
  const xmin = Math.min(xs[0], c.curve_t[0]);
  const xmax = Math.max(xs[xs.length - 1], c.curve_t[c.curve_t.length - 1]);
  let ymin = Math.min(...ys), ymax = Math.max(...ys);
  for (const seg of c.area.lin) { ymin = Math.min(ymin, ...seg); ymax = Math.max(ymax, ...seg); }
  const pad = (ymax - ymin) * 0.08 || 0.1;
  ymin -= pad; ymax += pad;
  const P = CH;
  const X = (t) => P.l + (t - xmin) / (xmax - xmin) * (P.w - P.l - P.r);
  const Y = (y) => P.h - P.b - (y - ymin) / (ymax - ymin) * (P.h - P.t - P.b);
  const path = (ax, ay) => ax.map((t, i) => (i ? 'L' : 'M') + X(t).toFixed(2) + ' ' + Y(ay[i]).toFixed(2)).join(' ');

  let g = '';
  // 网格 + 刻度
  const xt = niceTicks(xmin, xmax, 8), yt = niceTicks(ymin, ymax, 6);
  for (const t of xt) {
    g += `<line x1="${X(t)}" y1="${P.t}" x2="${X(t)}" y2="${P.h - P.b}" stroke="#eef0f3"/>`;
    g += `<text x="${X(t)}" y="${P.h - P.b + 17}" font-size="11" fill="#5b6472" text-anchor="middle">${t}</text>`;
  }
  for (const y of yt) {
    g += `<line x1="${P.l}" y1="${Y(y)}" x2="${P.w - P.r}" y2="${Y(y)}" stroke="#eef0f3"/>`;
    g += `<text x="${P.l - 8}" y="${Y(y) + 4}" font-size="11" fill="#5b6472" text-anchor="end">${y}</text>`;
  }
  // 等面积填充
  for (let k = 0; k < c.area.x.length; k++) {
    const ax = c.area.x[k], lin = c.area.lin[k], cur = c.area.curve[k];
    if (!ax || ax.length < 2) continue;
    const top = ax.map((t, i) => X(t).toFixed(2) + ' ' + Y(Math.max(lin[i], cur[i])).toFixed(2));
    const bot = ax.map((t, i) => X(t).toFixed(2) + ' ' + Y(Math.min(lin[i], cur[i])).toFixed(2)).reverse();
    g += `<polygon points="${top.concat(bot).join(' ')}" fill="dimgray" fill-opacity="0.2"/>`;
  }
  // 散点
  const st = Math.max(1, Math.floor(xs.length / 2200));
  let dots = '';
  for (let i = 0; i < xs.length; i += st)
    dots += `<circle cx="${X(xs[i]).toFixed(2)}" cy="${Y(ys[i]).toFixed(2)}" r="1.6" fill="dimgray"/>`;
  // 平滑曲线
  g += `<path d="${path(c.curve_t, c.curve_y)}" fill="none" stroke="#1f77b4" stroke-width="1.3"/>`;
  // 拟合直线
  const [t1, t2] = c.fit_lines_t;
  g += `<line x1="${X(t1)}" y1="${Y(c.fit1[0] * t1 + c.fit1[1])}" x2="${X(t2)}" y2="${Y(c.fit1[0] * t2 + c.fit1[1])}" stroke="#e08214" stroke-width="1.2" stroke-dasharray="6 4"/>`;
  g += `<line x1="${X(t1)}" y1="${Y(c.fit2[0] * t1 + c.fit2[1])}" x2="${X(t2)}" y2="${Y(c.fit2[0] * t2 + c.fit2[1])}" stroke="#3aa93a" stroke-width="1.2" stroke-dasharray="6 4"/>`;
  g += dots;
  // 雷诺线
  const yl0 = Math.min(c.T_left, c.T_right), yl1 = Math.max(c.T_left, c.T_right);
  const d = (yl1 - yl0) * 0.12 || 0.05;
  g += `<line x1="${X(c.x0)}" y1="${Y(yl0 - d)}" x2="${X(c.x0)}" y2="${Y(yl1 + d)}" stroke="#d62728" stroke-width="1.2" stroke-dasharray="6 4"/>`;
  // 端点
  c.endpoints.forEach((e, i) => {
    const col = e.c === 1 ? '#e08214' : '#3aa93a';
    g += `<circle class="ep" data-i="${i}" cx="${X(e.t)}" cy="${Y(e.y)}" r="7" fill="${col}" fill-opacity="0.85" stroke="#fff" stroke-width="1.5" style="cursor:ew-resize"/>`;
  });
  // 坐标轴
  g += `<line x1="${P.l}" y1="${P.h - P.b}" x2="${P.w - P.r}" y2="${P.h - P.b}" stroke="#8b93a1"/>`;
  g += `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.h - P.b}" stroke="#8b93a1"/>`;
  g += `<text x="${(P.l + P.w - P.r) / 2}" y="${P.h - 8}" font-size="12" fill="#1f2328" text-anchor="middle">t (s)</text>`;
  g += `<text x="16" y="${(P.t + P.h - P.b) / 2}" font-size="12" fill="#1f2328" text-anchor="middle" transform="rotate(-90 16 ${(P.t + P.h - P.b) / 2})">ΔT (K)</text>`;
  // 图例
  const lg = [
    ['ΔT–t 数据', 'dimgray', 'dot'], ['拟合1端点', '#e08214', 'dot'], ['拟合2端点', '#3aa93a', 'dot'],
    ['平滑曲线', '#1f77b4', 'line'], ['拟合直线1', '#e08214', 'line'], ['拟合直线2', '#3aa93a', 'line'],
    ['雷诺校正线', '#d62728', 'line'],
  ];
  lg.forEach(([txt, col, kind], i) => {
    const y = P.t + 14 + i * 20, x = P.w - P.r + 12;
    g += kind === 'dot'
      ? `<circle cx="${x}" cy="${y - 4}" r="4" fill="${col}"/>`
      : `<line x1="${x - 6}" y1="${y - 4}" x2="${x + 8}" y2="${y - 4}" stroke="${col}" stroke-width="1.6"/>`;
    g += `<text x="${x + 15}" y="${y}" font-size="11.5" fill="#5b6472">${txt}</text>`;
  });
  // 十字光标读数
  g += `<g id="readout" style="display:none"><line id="cx" y1="${P.t}" y2="${P.h - P.b}" stroke="#9aa3b1" stroke-dasharray="3 3"/>
        <text id="ct" font-size="11" fill="#1f2328" text-anchor="start"></text></g>`;

  const svg = `<svg id="chart" viewBox="0 0 ${P.w} ${P.h}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`;
  $('chartHost').innerHTML = svg;
  attachChartEvents(v, { X, Y, xmin, xmax });
}

function niceTicks(a, b, n) {
  const span = b - a;
  if (!isFinite(span) || span <= 0) return [a];
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || mag * 10;
  const out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

function attachChartEvents(v, tr) {
  const svg = $('chart');
  const c = v.chart, xs = c.t;
  const scale = () => svg.getBoundingClientRect().width / CH.w;
  const toData = (ev) => {
    const rect = svg.getBoundingClientRect();
    const s = scale();
    const px = (ev.clientX - rect.left) / s, py = (ev.clientY - rect.top) / s;
    const t = tr.xmin + (px - CH.l) / (CH.w - CH.l - CH.r) * (tr.xmax - tr.xmin);
    return { t, px, py };
  };
  const nearest = (t) => {
    let lo = 0, hi = xs.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (xs[m] < t) lo = m + 1; else hi = m; }
    if (lo > 0 && Math.abs(xs[lo - 1] - t) < Math.abs(xs[lo] - t)) lo -= 1;
    return lo;
  };

  svg.addEventListener('pointerdown', (ev) => {
    const target = ev.target.closest('.ep');
    if (target) {
      drag = { ep: Number(target.dataset.i) };
      svg.setPointerCapture(ev.pointerId);
      ev.preventDefault();
      return;
    }
    // 空白处点击 = 将该点吸附到最近的雷诺位置？不处理，仅显示读数
  });
  svg.addEventListener('pointermove', (ev) => {
    const { t, px } = toData(ev);
    const i = nearest(t);
    const ro = $('readout');
    if (ro) {
      ro.style.display = '';
      const cx = $('cx'); if (cx) { cx.setAttribute('x1', px); cx.setAttribute('x2', px); }
      const ct = $('ct');
      if (ct) {
        ct.setAttribute('x', Math.min(px + 6, CH.w - CH.r - 10));
        ct.setAttribute('y', CH.t + 12);
        ct.textContent = `t=${xs[i].toFixed(2)}s  ΔT=${c.y[i].toFixed(4)}K`;
      }
    }
    if (drag) {
      const map = [0, 1, 2, 3];
      const idx = map[drag.ep];
      const pts = v.points.slice();
      pts[idx] = i;
      // 合法性：Start1<End1<Start2<End2
      const ok = pts[0] < pts[1] && pts[1] < pts[2] && pts[2] < pts[3]
        && pts[0] >= 0 && pts[3] < xs.length;
      if (ok) {
        if (!drag.undoPushed) { pushUndoAll(); drag.undoPushed = true; }
        v.points = pts;
        $('pointValue').value = pts[Number($('whichPoint').value)];
        state.rounds[state.active].points = pts;
        debouncedRecalc();
      }
    }
  });
  const end = (ev) => {
    if (drag) { drag = null; try { svg.releasePointerCapture(ev.pointerId); } catch (e) {} recalc(); }
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('pointerleave', () => { const ro = $('readout'); if (ro) ro.style.display = 'none'; });
}

let recalcTimer = null;
function debouncedRecalc() {
  clearTimeout(recalcTimer);
  recalcTimer = setTimeout(() => { /* 拖动结束再算 */ }, 10);
}

/* ------------------------------------------------ 草稿与撤销 */
function draftSnapshot() {
  return {
    savedAt: Date.now(),
    active: state.active,
    dataDir: $('dataDir').value.trim(),
    config: readConfigForm(),
    rounds: state.rounds.map(r => ({
      index: r.index, enabled: r.enabled !== false, role: r.role,
      name: r.name, substance: r.substance, file: r.file,
      params: r.params || {}, points: r.points, sample_mass: r.sample_mass,
      note: r.note || '',
    })),
  };
}

function saveDraft() {
  if (!draftReady || restoringDraft || !state.config) return;
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draftSnapshot()));
  } catch (e) { /* 隐私模式/配额满：草稿失败不影响正常使用 */ }
}

function scheduleDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(saveDraft, 500);
}

function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ }
}

async function restoreDraft(draft) {
  restoringDraft = true;
  try {
    fillConfigForm(draft.config || {});
    if (draft.dataDir) $('dataDir').value = draft.dataDir;
    if (Array.isArray(draft.rounds) && draft.rounds.length) {
      state.rounds = draft.rounds.map((r, i) => Object.assign(mkRound(i + 1), r));
    }
    state.active = Math.min(draft.active || 0, Math.max(0, state.rounds.length - 1));
    renderRounds();
    if (draft.dataDir) {
      try { await scanDir(draft.dataDir, false); } catch (e) { /* 目录暂时不可用也能恢复 */ }
    }
    await recalc();
    toast('已恢复上次未导出的编辑');
  } finally {
    restoringDraft = false;
  }
}

async function maybeRestoreDraft() {
  let raw = null;
  try { raw = localStorage.getItem(DRAFT_KEY); } catch (e) { return; }
  if (!raw) return;
  let draft = null;
  try { draft = JSON.parse(raw); } catch (e) { clearDraft(); return; }
  if (!draft || !draft.savedAt) { clearDraft(); return; }
  if (Date.now() - draft.savedAt > DRAFT_MAX_AGE) { clearDraft(); return; }
  const when = new Date(draft.savedAt).toLocaleString();
  if (confirm('发现上次未导出的编辑（' + when + '），是否恢复？\n取消则保留草稿，下次打开再问。')) {
    await restoreDraft(draft);
  }
}

function pushUndoAll() {
  undoStack.push({
    active: state.active,
    points: state.rounds.map(r => (r.points ? r.points.slice() : null)),
  });
  if (undoStack.length > 50) undoStack.shift();
}

async function undoPoints() {
  if (!undoStack.length) return toast('没有可撤销的取点');
  const snap = undoStack.pop();
  state.rounds.forEach((r, i) => {
    r.points = snap.points[i] ? snap.points[i].slice() : null;
  });
  const v = state.views[state.active];
  if (v && state.rounds[state.active]) {
    v.points = state.rounds[state.active].points;
  }
  await recalc();
  toast('已撤销上一步取点');
}

/* ---------------------------------------------------------------- 事件 */
function bindUI() {
  $('btnCalc').addEventListener('click', recalc);
  $('btnAddRound').addEventListener('click', () => {
    state.rounds.push(mkRound(state.rounds.length + 1));
    renderRounds();
    saveDraft();
  });
  $('btnPick').addEventListener('click', async () => {
    try {
      const r = await fetch('/api/pickdir?initial=' + encodeURIComponent($('dataDir').value.trim()),
                            { cache: 'no-store' });
      const data = await r.json();
      if (data.path) { $('dataDir').value = data.path; toast('已选择：' + data.path, 4000); }
    } catch (e) { toast('打开选择窗口失败：' + e.message); }
  });
  $('btnScan').addEventListener('click', async () => {
    const dir = $('dataDir').value.trim();
    if (!dir) return toast('请先填写数据文件夹路径');
    try {
      const files = await scanDir(dir, true);
      if (!files || !files.length) return toast('该文件夹下没有找到数据文件');
      toast('找到 ' + files.length + ' 个数据文件');
      recalc();
    } catch (e) { toast('扫描失败：' + e.message); }
  });
  $('whichPoint').addEventListener('change', () => {
    const v = state.views[state.active];
    if (v) $('pointValue').value = v.points[Number($('whichPoint').value)];
  });
  $('btnApplyPoint').addEventListener('click', async () => {
    const v = state.views[state.active];
    if (!v) return;
    const idx = Number($('whichPoint').value);
    const val = Number($('pointValue').value);
    const pts = v.points.slice();
    pts[idx] = val;
    if (!(pts[0] < pts[1] && pts[1] < pts[2] && pts[2] < pts[3])) {
      return toast('必须满足 Start1 < End1 < Start2 < End2');
    }
    pushUndoAll();
    v.points = pts;
    state.rounds[state.active].points = pts;
    await recalc();
  });
  $('btnAutoPoint').addEventListener('click', async () => {
    const v = state.views[state.active];
    if (!v) return;
    pushUndoAll();
    const pts = v.auto_points;
    state.rounds[state.active].points = pts;
    await recalc();
  });
  const undoBtn = document.createElement('button');
  undoBtn.className = 'btn';
  undoBtn.textContent = '撤销取点 (Ctrl+Z)';
  undoBtn.addEventListener('click', undoPoints);
  $('btnAutoPoint').insertAdjacentElement('afterend', undoBtn);
  $('btnExport').addEventListener('click', doExport);
  $('btnSaveDefault').addEventListener('click', saveAsDefault);
  $('btnResetDefault').addEventListener('click', resetDefault);
  document.addEventListener('input', scheduleDraft);
  document.addEventListener('change', scheduleDraft);
  document.addEventListener('keydown', (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== 'z') return;
    const tag = (ev.target && ev.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    ev.preventDefault();
    undoPoints();
  });
}

async function doExport() {
  const cfg = readConfigForm();
  const payload = {
    config: cfg,
    rounds: state.rounds.map(r => ({
      name: r.name, role: r.role, substance: r.substance, file: r.file,
      params: r.params || {}, points: r.points, sample_mass: r.sample_mass,
      enabled: r.enabled !== false,
    })),
    // 文件名：学号-姓名-燃烧热
    filename: reportFilename(cfg),
  };
  busy(true, '正在排版 Word 文档…');
  try {
    const res = await api('/api/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    busy(false);
    toast('已生成：' + res.path, 6000);
    clearDraft();
    setStatus('报告已生成：' + res.filename);
    const note = (res.messages || []).find(m => m.indexOf('占用') >= 0);
    if (note) toast(note, 9000);
  } catch (e) {
    busy(false);
    toast('生成失败：' + e.message, 6000);
  }
}

/** 报告文件名：“学号-姓名-燃烧热”，缺项自动跳过。 */
function reportFilename(cfg) {
  const parts = [];
  const id = (cfg.student_id || '').trim();
  const name = (cfg.student_name || '').trim();
  if (id) parts.push(id);
  if (name) parts.push(name);
  parts.push('燃烧热');
  return parts.join('-') + '.docx';
}

window.addEventListener('DOMContentLoaded', () => {
  bindUI();
  boot().catch(e => { setStatus('初始化失败'); toast(e.message, 6000); });
});