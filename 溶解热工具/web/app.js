/* 溶解热实验报告一键生成 —— 前端逻辑 */
'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  config: null, defaults: null, substances: {}, water: null, constants: null,
  rounds: [], views: [], fit: null, active: 0,
  fileList: [], software: {},
};
const DRAFT_KEY = 'pcal-draft-dissolution-v1';
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
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ---------------------------------------------------------------- 初始化 */
async function boot() {
  const s = await api('/api/state');
  state.config = s.config;
  state.defaults = s.defaults;
  state.substances = s.substances;
  state.water = s.water;
  state.constants = s.constants;
  fillSubstances(s.config.solute);
  fillConfigForm(s.config);
  showSavedInfo(s.has_saved, s.settings_file);
  $('dataDir').value = s.config.data_dir || s.default_dir || '';
  $('outInfo').innerHTML = '报告输出到：<code>' + esc(s.output_dir || '—')
    + '</code>（每份报告一个子文件夹，全部实验共用这一个目录）';
  // 从入口页跳转过来时带 ?base=…：显示「返回入口」
  const q = new URLSearchParams(location.search);
  if (q.get('home')) { $('btnHome').href = q.get('home'); $('btnHome').style.display = ''; }
  await scanDir(s.default_dir, true);
  setStatus('就绪 · 数据目录 ' + (s.default_dir || '—'));
  await recalc();
  await maybeRestoreDraft();
  draftReady = true;
}

function fillSubstances(cur) {
  $('solute').innerHTML = Object.entries(state.substances)
    .map(([k, v]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(v.label)}</option>`)
    .join('');
}

async function scanDir(dir, autoFill) {
  if (!dir) return;
  const res = await api('/api/scan?dir=' + encodeURIComponent(dir));
  state.fileList = res.files;
  state.software = res.software || {};
  $('fileCount').textContent = res.files.length
    ? '找到 ' + res.files.length + ' 个溶解热数据文件：' + res.files.map(f => f.name).join('、')
    : '该文件夹下没有找到溶解热数据 csv（需要含 time(s),Delta_T(K),solute_mass(g) 表头）。';
  const nsw = Object.keys(state.software).length;
  $('swInfo').innerHTML = nsw
    ? `同目录的 <code>dissolution.csv</code> 记录了 ${nsw} 轮你当时在课程软件里选定的取点，`
      + '已按它取点（可在下面切换为自动寻点）。'
    : '没有找到 <code>dissolution.csv</code>，将按曲线自动寻点。';
  if (autoFill && res.files.length && !state.rounds.some(r => r.file)) {
    state.rounds = defaultRoundsFromFiles(res.files);
  }
  renderRounds();
  return res.files;
}

/* ---------------------------------------------------------------- 默认值 */
function showSavedInfo(hasSaved, file) {
  $('savedInfo').textContent = hasSaved
    ? '已记住上次「存为默认」的封面与实验条件，打开程序时自动填回。'
    : '还没有存过默认值；填好后点「存为默认」，以后打开会自动填回。';
  $('savedInfo').title = file || '';
}

async function saveAsDefault() {
  try {
    await api('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfigForm() }),
    });
    showSavedInfo(true, '');
    toast('已存为默认，下次打开自动填回');
  } catch (e) { toast('保存失败：' + e.message, 5000); }
}

async function resetDefault() {
  if (!confirm('恢复到出厂默认值？已保存的封面 / 实验条件会被清除。')) return;
  try {
    const s = await api('/api/settings', { method: 'DELETE' });
    fillConfigForm(s.config);
    showSavedInfo(false, '');
    toast('已恢复出厂默认');
    recalc();
  } catch (e) { toast('恢复失败：' + e.message); }
}

function swPoints(path) {
  const name = String(path).replace(/^.*[\\/]/, '').replace(/\.csv$/i, '');
  return state.software[name] || {};
}

function defaultRoundsFromFiles(files) {
  // 文件名带时间戳，按名字排序就是实验先后顺序（累加法要求顺序正确）
  const sorted = files.slice().sort((a, b) => a.name.localeCompare(b.name));
  return sorted.map((f, i) => {
    const r = mkRound(i + 1);
    r.file = f.path;
    r.name = '第' + (i + 1) + '轮';
    const sw = swPoints(f.path);
    if (sw.points && $('point_source').value === 'file') {
      r.points = sw.points;
      r.ref_Q_kJ = sw.Q_kJ;
    }
    return r;
  });
}

function mkRound(i) {
  return { index: i, enabled: true, name: '第' + i + '轮', file: null,
           params: {}, points: null, solute_mass: null, ref_Q_kJ: null };
}

function fillConfigForm(c) {
  ['student_name', 'student_id', 'group', 'group_no', 'date'].forEach(k => {
    if (c[k]) $(k).value = c[k];
  });
  const set = (id, v) => { $(id).value = (v === null || v === undefined) ? '' : v; };
  ['water_volume_mL', 'pressure_kPa', 'temperature_C', 'water_density', 'water_capacity',
   'solute_molarmass', 'literature_Qs0', 'sigma_current', 'sigma_resistance',
   'sigma_time', 'sigma_dt', 'e_balance'].forEach(k => set(k, c[k]));
  if (c.point_source) $('point_source').value = c.point_source;
  $('force_temperature').checked = !!c.force_temperature;
}

function readConfigForm() {
  const num = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  const txt = (id) => $(id).value.trim() || null;
  return {
    student_name: txt('student_name'), student_id: txt('student_id'),
    group: txt('group'), group_no: txt('group_no'), date: txt('date'),
    pressure_kPa: num('pressure_kPa'), water_volume_mL: num('water_volume_mL'),
    temperature_C: num('temperature_C'), force_temperature: $('force_temperature').checked,
    water_density: num('water_density'), water_capacity: num('water_capacity'),
    solute: $('solute').value, solute_molarmass: num('solute_molarmass'),
    literature_Qs0: num('literature_Qs0'),
    sigma_current: num('sigma_current'), sigma_resistance: num('sigma_resistance'),
    sigma_time: num('sigma_time'), sigma_dt: num('sigma_dt'),
    e_balance: num('e_balance'),
    point_source: $('point_source').value,
    data_dir: txt('dataDir'),      // 记住数据文件夹，下次打开直接定位
  };
}

/* ---------------------------------------------------------------- 轮次 UI */
function renderRounds() {
  const host = $('rounds');
  host.innerHTML = '';
  state.rounds.forEach((r, i) => {
    const div = document.createElement('div');
    div.className = 'round' + (i === state.active ? ' active' : '');
    const v = state.views[i];
    const auto = r.points ? false : (v ? v.is_auto : true);
    div.innerHTML = `
      <div class="head">
        <input type="text" value="${esc(r.name)}" data-i="${i}" data-k="name">
        <span class="tag ${auto ? 'auto' : 'ok'}">${auto ? '自动寻点' : '文件记录取点'}</span>
      </div>
      <div class="row"><label>数据文件</label>
        <select data-i="${i}" data-k="file" style="flex:1">
          <option value="">— 选择 —</option>
          ${state.fileList.map(f =>
            `<option value="${esc(f.path)}"${r.file === f.path ? ' selected' : ''}>${esc(f.name)}</option>`).join('')}
        </select>
      </div>
      <div class="row"><label>溶质质量 /g</label>
        <input type="number" step="0.0001" data-i="${i}" data-k="solute_mass"
               value="${r.solute_mass ?? ''}" placeholder="留空=用文件中的值">
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
  if (k === 'solute_mass') v = v === '' ? null : Number(v);
  state.rounds[i][k] = v;
  if (k === 'file') {
    const sw = swPoints(v);
    if ($('point_source').value === 'file' && sw.points) {
      state.rounds[i].points = sw.points;
      state.rounds[i].ref_Q_kJ = sw.Q_kJ;
    } else {
      state.rounds[i].points = null;
      state.rounds[i].ref_Q_kJ = null;
    }
  }
  if (k === 'name') { renderRounds(); }
  if (['file', 'solute_mass'].includes(k)) recalc();
}

/* ---------------------------------------------------------------- 计算 */
function payloadRounds() {
  return state.rounds.map(r => ({
    name: r.name, file: r.file, params: r.params || {}, points: r.points,
    solute_mass: r.solute_mass, ref_Q_kJ: r.ref_Q_kJ, enabled: r.enabled !== false,
  }));
}

async function recalc() {
  const payload = { config: readConfigForm(), rounds: payloadRounds() };
  if (!payload.rounds.some(r => r.file)) { setStatus('请选择数据文件'); return; }
  try {
    const res = await api('/api/calc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.views = res.rounds;
    state.fit = res.fit;
    state.active = Math.min(state.active, res.rounds.length - 1);
    setStatus('计算完成 · ' + new Date().toLocaleTimeString());
    showRound(state.active, true);
    renderResults(res);
    saveDraft();
  } catch (err) {
    setStatus('计算失败');
    toast('计算失败：' + err.message, 6000);
  }
}

/* ---------------------------------------------------------------- 展示 */
function showRound(i, keepSelection) {
  const v = state.views[i];
  if (!v) return;
  const switched = i !== state.active && !keepSelection;
  state.active = i;
  renderRounds();
  $('chartTitle').textContent = v.name + (v.is_auto ? ' · 自动寻点' : ' · 文件记录取点');
  const keptWhich = $('whichPoint').value;
  const keptValue = $('pointValue').value;

  drawChart(v);
  renderStats(v);
  renderRaw(v);
  renderDiffTable();

  if (!switched && keptWhich !== '') {
    $('whichPoint').value = keptWhich;
    const idx = Number(keptWhich);
    $('pointValue').value = (Number(keptValue) === v.points[idx] || keptValue === '')
      ? v.points[idx] : keptValue;
  } else {
    $('whichPoint').value = '1';
    $('pointValue').value = v.points[1];
  }

  const names = ['S1', 'E1', 'S2', 'E2', 'S3', 'E3'];
  const info = [v.is_auto ? '取点方式：自动寻点' : '取点方式：文件记录 / 手动指定'];
  info.push(names.map((n, k) => `${n}=${v.points[k]} (${fmt(v.points_t[k], 1)} s)`).join('　'));
  $('autoInfo').innerHTML = info.join('　·　');

  const fn = reportFilename(readConfigForm());
  $('exportName').textContent = fn;
}

function renderStats(v) {
  const rows = [
    ['溶解温差 ΔT_d / K', fmt(v.dT_diss, 4)],
    ['加热温差 ΔT_h / K', fmt(v.dT_heat, 4)],
    ['雷诺垂线 t₁ / s', fmt(v.x1, 2)],
    ['雷诺垂线 t₂ / s', fmt(v.x2, 2)],
    ['电热 Q′ / J', fmt(v.Q_elec, 1)],
    ['溶解热 Q / kJ', fmt(v.Q / 1000, 4)],
    ['σ_Q / kJ', fmt(v.sigma_Q / 1000, 4)],
    ['n₀', fmt(v.n0, 2)],
    ['Q_s /(kJ·mol⁻¹)', fmt(v.Qs, 3)],
    ['采用室温 / K', fmt(v.temperature_used_K, 2) + (v.temperature_source ? '（' + v.temperature_source + '）' : '')],
  ];
  $('stats').innerHTML = rows.map(([k, val]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${val}</div></div>`).join('');
}

function renderResults(res) {
  const f = res.fit;
  let html = `<p>共 ${res.rounds.length} 轮累加实验，得到 ${res.rounds.length} 个浓度下的积分溶解热。</p>`;
  html += `<p>无限稀释积分溶解热 <b>Q<sub>s</sub><sup>0</sup> = ${fmt(f.Qs0, 2)} ± ${fmt(f.sigma_Qs0, 2)} kJ/mol</b>，`
        + `<b>a = ${fmt(f.a, 4)} ± ${fmt(f.sigma_a, 4)}</b>，R² = ${fmt(f.r_square, 4)}。</p>`;
  const m = f.marks;
  html += '<table><thead><tr><th>n<sub>0</sub></th><th>Q<sub>s</sub><br>kJ/mol</th>'
        + '<th>微分溶解热<br>kJ/mol</th><th>微分冲淡热<br>J/mol</th>'
        + '<th>积分冲淡热<br>J/mol</th></tr></thead><tbody>';
  m.n0.forEach((n, i) => {
    html += `<tr><td>${fmt(n, 0)}</td><td>${fmt(m.Qs[i], 2)}</td><td>${fmt(m.Qs_n2[i], 2)}</td>`
          + `<td>${fmt(m.Qs_n0[i], 2)}</td><td>${i ? fmt(m.Qd[i - 1], 1) : '—'}</td></tr>`;
  });
  html += '</tbody></table>';
  html += `<p class="hint">a 的物理意义：n<sub>0</sub> = 1/a ≈ ${fmt(f.n_half, 2)} 时 Q<sub>s</sub> 降到
    Q<sub>s</sub><sup>0</sup>/2；本实验数据都在 n<sub>0</sub> 较大的一侧，落在曲线的平缓段。
    误差分析口径（报告 4.3.1）：σ<sub>I</sub> = ${fmt(readConfigForm().sigma_current, 2)} A、
    σ<sub>R</sub> = ${fmt(readConfigForm().sigma_resistance, 2)} Ω、
    σ<sub>t</sub> = ${fmt(readConfigForm().sigma_time, 2)} s、
    σ<sub>ΔT</sub> = ${fmt(readConfigForm().sigma_dt, 3)} K。</p>`;
  $('results').innerHTML = html;

  // 逐轮表
  let t = '<table><thead><tr><th>轮次</th><th>m<sub>sam</sub>/g</th><th>ΔT<sub>d</sub>/K</th>'
        + '<th>ΔT<sub>h</sub>/K</th><th>Q/kJ</th><th>Σm₂/g</th><th>ΣQ/J</th>'
        + '<th>n<sub>0</sub></th><th>Q<sub>s</sub>/(kJ/mol)</th><th>软件/kJ</th></tr></thead><tbody>';
  res.rounds.forEach(r => {
    t += `<tr><td>${esc(r.name)}</td><td>${fmt(r.solute_mass, 4)}</td>`
       + `<td>${fmt(r.dT_diss, 4)}</td><td>${fmt(r.dT_heat, 4)}</td>`
       + `<td>${fmt(r.Q / 1000, 4)}</td><td>${fmt(r.cum_m2, 4)}</td>`
       + `<td>${fmt(r.cum_Q * 1000, 1)}</td><td>${fmt(r.n0, 2)}</td>`
       + `<td>${fmt(r.Qs, 3)}</td>`
       + `<td>${r.software_Q_kJ === null || r.software_Q_kJ === undefined ? '—' : fmt(r.software_Q_kJ, 4)}</td></tr>`;
  });
  t += '</tbody></table><p class="hint">「软件/kJ」是课程软件在同一取点下给出的溶解热，用于核对。</p>';
  $('roundTable').innerHTML = t;

  // 拟合图（服务端 matplotlib 出图，和报告里的图完全一致）
  const img = document.createElement('img');
  img.src = '/api/fitplot?t=' + Date.now();
  img.style.width = '100%';
  img.alt = 'Qs-n0 拟合图';
  $('fitChart').innerHTML = '';
  $('fitChart').appendChild(img);
}

function renderDiffTable() { /* 已并入 renderResults 的表格 */ }

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
  host.innerHTML = html;
}

/* ---------------------------------------------------------------- SVG 图 */
const CH = { w: 940, h: 430, l: 70, r: 150, t: 18, b: 46 };
const EP_COLOR = { 1: '#e08214', 2: '#3aa93a', 3: '#6b7280' };
let drag = null;

function drawChart(v) {
  const c = v.chart;
  const host = $('chartHost');
  if (!c || !c.t || !c.t.length || !host) return;
  const xs = c.t, ys = c.y;
  const xmin = Math.min(xs[0], c.curve1_t[0], c.curve2_t[0]);
  const xmax = Math.max(xs[xs.length - 1], c.curve1_t[c.curve1_t.length - 1],
                        c.curve2_t[c.curve2_t.length - 1]);
  let ymin = Math.min(...ys), ymax = Math.max(...ys);
  for (const seg of c.area.lin) { ymin = Math.min(ymin, ...seg); ymax = Math.max(ymax, ...seg); }
  const pad = (ymax - ymin) * 0.08 || 0.1;
  ymin -= pad; ymax += pad;
  const P = CH;
  const X = (t) => P.l + (t - xmin) / (xmax - xmin) * (P.w - P.l - P.r);
  const Y = (y) => P.h - P.b - (y - ymin) / (ymax - ymin) * (P.h - P.t - P.b);
  const path = (ax, ay) => ax.map((t, i) => (i ? 'L' : 'M') + X(t).toFixed(2) + ' ' + Y(ay[i]).toFixed(2)).join(' ');

  let g = '';
  const xt = niceTicks(xmin, xmax, 8), yt = niceTicks(ymin, ymax, 6);
  for (const t of xt) {
    g += `<line x1="${X(t)}" y1="${P.t}" x2="${X(t)}" y2="${P.h - P.b}" stroke="#eef0f3"/>`;
    g += `<text x="${X(t)}" y="${P.h - P.b + 17}" font-size="11" fill="#5b6472" text-anchor="middle">${t}</text>`;
  }
  for (const y of yt) {
    g += `<line x1="${P.l}" y1="${Y(y)}" x2="${P.w - P.r}" y2="${Y(y)}" stroke="#eef0f3"/>`;
    g += `<text x="${P.l - 8}" y="${Y(y) + 4}" font-size="11" fill="#5b6472" text-anchor="end">${y}</text>`;
  }
  for (let k = 0; k < c.area.x.length; k++) {
    const ax = c.area.x[k], lin = c.area.lin[k], cur = c.area.curve[k];
    if (!ax || ax.length < 2) continue;
    const top = ax.map((t, i) => X(t).toFixed(2) + ' ' + Y(Math.max(lin[i], cur[i])).toFixed(2));
    const bot = ax.map((t, i) => X(t).toFixed(2) + ' ' + Y(Math.min(lin[i], cur[i])).toFixed(2)).reverse();
    g += `<polygon points="${top.concat(bot).join(' ')}" fill="dimgray" fill-opacity="0.2"/>`;
  }
  const st = Math.max(1, Math.floor(xs.length / 2200));
  let dots = '';
  for (let i = 0; i < xs.length; i += st)
    dots += `<circle cx="${X(xs[i]).toFixed(2)}" cy="${Y(ys[i]).toFixed(2)}" r="1.6" fill="dimgray"/>`;
  g += `<path d="${path(c.curve1_t, c.curve1_y)}" fill="none" stroke="#1f77b4" stroke-width="1.3"/>`;
  g += `<path d="${path(c.curve2_t, c.curve2_y)}" fill="none" stroke="#1f77b4" stroke-width="1.3"/>`;
  g += dots;
  const [t1, t2] = c.fit_lines_t;
  const lines = [[c.fit1, '#e08214'], [c.fit2, '#3aa93a'], [c.fit3, '#6b7280']];
  lines.forEach(([f, col]) => {
    g += `<line x1="${X(t1)}" y1="${Y(f[0] * t1 + f[1])}" x2="${X(t2)}" y2="${Y(f[0] * t2 + f[1])}"`
       + ` stroke="${col}" stroke-width="1.2" stroke-dasharray="6 4"/>`;
  });
  [[c.x1, c.T1_left, c.T1_right], [c.x2, c.T2_left, c.T2_right]].forEach(([x0, a, b]) => {
    const lo = Math.min(a, b), hi = Math.max(a, b), d = (hi - lo) * 0.12 || 0.05;
    g += `<line x1="${X(x0)}" y1="${Y(lo - d)}" x2="${X(x0)}" y2="${Y(hi + d)}"`
       + ` stroke="#d62728" stroke-width="1.2" stroke-dasharray="6 4"/>`;
  });
  c.endpoints.forEach((e, i) => {
    const col = EP_COLOR[e.c] || '#888';
    g += `<circle class="ep" data-i="${i}" cx="${X(e.t)}" cy="${Y(e.y)}" r="7" fill="${col}"`
       + ` fill-opacity="0.85" stroke="#fff" stroke-width="1.5" style="cursor:ew-resize"/>`;
  });
  g += `<line x1="${P.l}" y1="${P.h - P.b}" x2="${P.w - P.r}" y2="${P.h - P.b}" stroke="#8b93a1"/>`;
  g += `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.h - P.b}" stroke="#8b93a1"/>`;
  g += `<text x="${(P.l + P.w - P.r) / 2}" y="${P.h - 8}" font-size="12" fill="#1f2328" text-anchor="middle">t (s)</text>`;
  g += `<text x="16" y="${(P.t + P.h - P.b) / 2}" font-size="12" fill="#1f2328" text-anchor="middle"`
     + ` transform="rotate(-90 16 ${(P.t + P.h - P.b) / 2})">ΔT (K)</text>`;
  const lg = [
    ['ΔT–t 数据', 'dimgray', 'dot'], ['平台1端点', '#e08214', 'dot'],
    ['平台2端点', '#3aa93a', 'dot'], ['平台3端点', '#6b7280', 'dot'],
    ['平滑曲线', '#1f77b4', 'line'], ['拟合直线 A', '#e08214', 'line'],
    ['拟合直线 B', '#3aa93a', 'line'], ['拟合直线 C', '#6b7280', 'line'],
    ['雷诺校正线', '#d62728', 'line'],
  ];
  lg.forEach(([txt, col, kind], i) => {
    const y = P.t + 14 + i * 20, x = P.w - P.r + 12;
    g += kind === 'dot'
      ? `<circle cx="${x}" cy="${y - 4}" r="4" fill="${col}"/>`
      : `<line x1="${x - 6}" y1="${y - 4}" x2="${x + 8}" y2="${y - 4}" stroke="${col}" stroke-width="1.6"/>`;
    g += `<text x="${x + 15}" y="${y}" font-size="11.5" fill="#5b6472">${txt}</text>`;
  });
  g += `<g id="readout" style="display:none"><line id="cx" y1="${P.t}" y2="${P.h - P.b}" stroke="#9aa3b1" stroke-dasharray="3 3"/>`
     + `<text id="ct" font-size="11" fill="#1f2328" text-anchor="start"></text></g>`;

  host.innerHTML = `<svg id="chart" viewBox="0 0 ${P.w} ${P.h}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`;
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
  const toData = (ev) => {
    const rect = svg.getBoundingClientRect();
    const s = rect.width / CH.w;
    const px = (ev.clientX - rect.left) / s;
    const t = tr.xmin + (px - CH.l) / (CH.w - CH.l - CH.r) * (tr.xmax - tr.xmin);
    return { t, px };
  };
  const nearest = (t) => {
    let lo = 0, hi = xs.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (xs[m] < t) lo = m + 1; else hi = m; }
    if (lo > 0 && Math.abs(xs[lo - 1] - t) < Math.abs(xs[lo] - t)) lo -= 1;
    return lo;
  };
  svg.addEventListener('pointerdown', (ev) => {
    const target = ev.target.closest('.ep');
    if (target) { drag = { ep: Number(target.dataset.i) }; svg.setPointerCapture(ev.pointerId); ev.preventDefault(); }
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
      const pts = v.points.slice();
      pts[drag.ep] = i;
      const ok = pts[0] < pts[1] && pts[1] < pts[2] && pts[2] < pts[3]
              && pts[3] < pts[4] && pts[4] < pts[5] && pts[0] >= 0 && pts[5] < xs.length;
      if (ok) {
        if (!drag.undoPushed) { pushUndoAll(); drag.undoPushed = true; }
        v.points = pts;
        $('pointValue').value = pts[Number($('whichPoint').value)];
        state.rounds[state.active].points = pts;
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

/* ---------------------------------------------------------------- 草稿与撤销 */
function draftSnapshot() {
  return {
    savedAt: Date.now(),
    active: state.active,
    dataDir: $('dataDir').value.trim(),
    config: readConfigForm(),
    rounds: state.rounds.map(r => ({
      index: r.index, enabled: r.enabled !== false, name: r.name, file: r.file,
      params: r.params || {}, points: r.points, solute_mass: r.solute_mass,
      ref_Q_kJ: r.ref_Q_kJ,
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
    if (draft.config && draft.config.solute) fillSubstances(draft.config.solute);
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
function applyPointSource() {
  const useFile = $('point_source').value === 'file';
  state.rounds.forEach(r => {
    const sw = swPoints(r.file || '');
    if (useFile && sw.points) {
      r.points = sw.points;
      r.ref_Q_kJ = sw.Q_kJ;
    } else {
      r.points = null;
      r.ref_Q_kJ = null;
    }
  });
}

function bindUI() {
  $('btnCalc').addEventListener('click', recalc);
  $('btnAddRound').addEventListener('click', () => {
    state.rounds.push(mkRound(state.rounds.length + 1));
    renderRounds();
    saveDraft();
  });
  $('solute').addEventListener('change', () => {
    const s = state.substances[$('solute').value] || {};
    $('solute_molarmass').value = s.Mr || '';
    recalc();
  });
  $('point_source').addEventListener('change', () => {
    pushUndoAll();
    applyPointSource();
    recalc();
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
      if (!files || !files.length) return toast('该文件夹下没有找到溶解热数据文件');
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
    const pts = v.points.slice();
    pts[idx] = Number($('pointValue').value);
    if (!(pts[0] < pts[1] && pts[1] < pts[2] && pts[2] < pts[3] && pts[3] < pts[4] && pts[4] < pts[5])) {
      return toast('必须满足 Start1 < End1 < Start2 < End2 < Start3 < End3');
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
    state.rounds[state.active].points = null;   // 交给服务端自动寻点
    state.rounds[state.active].ref_Q_kJ = null;
    await recalc();
    const nv = state.views[state.active];
    if (nv) { state.rounds[state.active].points = nv.auto_points; }
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
  const payload = { config: cfg, rounds: payloadRounds(), filename: reportFilename(cfg) };
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

function reportFilename(cfg) {
  const parts = [];
  const id = (cfg.student_id || '').trim();
  const name = (cfg.student_name || '').trim();
  if (id) parts.push(id);
  if (name) parts.push(name);
  parts.push('溶解热');
  return parts.join('-') + '.docx';
}

window.addEventListener('DOMContentLoaded', () => {
  bindUI();
  $('#btnHome') && ($('#btnHome').style.display = 'none');
  boot().catch(e => { setStatus('初始化失败'); toast(e.message, 6000); });
});
