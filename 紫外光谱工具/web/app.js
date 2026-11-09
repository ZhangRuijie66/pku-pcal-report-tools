/* 紫外光谱实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'partner_name', 'group', 'group_no', 'date',
  'room_temp_1', 'room_temp_2', 'pressure_1', 'pressure_2'];
const PROC_FIELDS = ['data_dir', 'voigt_peaks', 'stray_mode',
  'stray', 'stray_a3', 'path_cm', 'anchor_pad', 'box_a', 'box_n_B1', 'box_n_B2',
  // 高斯 TD-DFT 日志目录：进 PROC_FIELDS 才会被 fillConfig/readConfig 带上，
  // 否则选完的目录刷新页面就丢了
  'gcalc_logs_dir'];
// 配置键 -> 页面元素 id（data_dir 的输入框 id 是 dataDir）
const EL_ID = { data_dir: 'dataDir', gcalc_logs_dir: 'gcalcLogs' };

let STATE = null;
let SAVED = false;
let FILE_FILES = [];        // 数据目录里的 txt（相对路径）
let FILE_AUTO = {};         // 槽位 -> 自动匹配结果（来自 /api/files）
let MAP_EDIT = {};          // 槽位 -> 用户在界面里选的 rel（'' = 恢复默认）
let MAP_BUILT = false;

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
  // 数据文件映射（槽位 -> 相对数据目录的 txt）
  cfg.file_map = fileMapValue();
  // 每条曲线用哪条标定
  const cc = {};
  document.querySelectorAll('select[data-curve-cal]').forEach((sel) => {
    cc[sel.dataset.curveCal] = sel.value;
  });
  cfg.curve_cal = cc;
  // 自定义标定条目（出厂三条不在里面；由「删除」按钮维护）
  cfg.calibrations = (STATE && STATE.custom_cals) ? STATE.custom_cals.slice() : [];
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

/* ---------------------------------------------------------------- 标定 */
function _calOptionsHtml(sel) {
  const opts = (STATE && STATE.cal_options) || [];
  return opts.map((c) => {
    const on = c.key === sel ? ' selected' : '';
    const tag = c.custom ? '（自定义）' : '';
    return '<option value="' + esc(c.key) + '"' + on + '>' +
      esc(c.short || c.key) + tag + '</option>';
  }).join('');
}

/* 每条曲线选标定：按用途分组、每组排成两列网格。
 *
 * ⚠️ 不要用 `class="field"` 加内联 `display:flex` 来排这一行：
 * `.field{display:flex;flex-direction:column}` 的内联覆盖只改了 display、
 * 没改 direction，于是 label / select / 提示各占一整行，每行被撑到 175 px
 * （下拉框本身只有 35 px），一屏只放得下两条曲线——用户报的「间隔太大」
 * 就是这个。（2026-11-09）
 * 现在用专用类 `.curvecal-*`，样式写在 index.html 的 CSS 里。
 *
 * 条数是**数据驱动**的：这里遍历后端给的 `s.curve_rows`，没有写死 18 条，
 * 所以别人用这套工具、重复测量次数不同（每个浓度只测一次 / 某个浓度测 4 次 /
 * 只测了部分浓度）时，行数与分组都会跟着变。网格是
 * `repeat(auto-fill,minmax(270px,1fr))`，条数变了自动增减列数。
 */
function renderCurveCals(s) {
  const box = $('curveCalPicks');
  if (!box) return;
  const cur = s.curve_cal || {};
  const rows = s.curve_rows || [];
  const groups = [['conc', 'A3 浓度系列'], ['molecule', '各分子'],
                  ['source', '光源对比']];
  // 组内按「实验顺序」排，而不是按 SAMPLES 的声明顺序：
  // 声明顺序里 A3c5b 写在 50 之后（当初是补测的），直接铺开会让 5 μmol/L
  // 的两条隔着一张表——看着像两个不同的浓度。
  const sortKey = (r) => {
    const kind = r.kind || '';
    const isConc = kind.indexOf('conc') === 0;
    return [isConc ? 0 : 1, Number(r.conc) || 0, String(r.key)];
  };
  let html = '';
  let changed = 0;
  groups.forEach(([kind, title]) => {
    // ⚠️ filter 已经返回新数组，但保险起见排序仍只作用于副本：
    // s.curve_rows 是 STATE 里的引用，就地 sort 会改掉别处读到的顺序。
    const items = rows.filter((r) =>
      kind === 'molecule' ? (r.kind || '').indexOf('molecule') === 0 :
      kind === 'conc' ? (r.kind || '').indexOf('conc') === 0 :
      (r.kind || '') === 'source');
    if (!items.length) return;
    items.sort((a, b) => {
      const ka = sortKey(a); const kb = sortKey(b);
      for (let i = 0; i < ka.length; i += 1) {
        if (ka[i] < kb[i]) return -1;
        if (ka[i] > kb[i]) return 1;
      }
      return 0;
    });
    html += '<div class="curvecal-group"><span class="curvecal-title">' +
      esc(title) + '</span><span class="curvecal-count">' +
      items.length + ' 条</span></div><div class="curvecal-grid">';
    items.forEach((r) => {
      const sel = cur[r.key] || '';
      const def = (s.curve_cal_default || {})[r.key] || '';
      const isCustom = !!(sel && def && sel !== def);
      if (isCustom) changed += 1;
      // 标签：主名（大字）+ 测量代号（小字）。两组风格统一，列表读起来才整齐。
      // ⚠️ 浓度组以前只印 conc，于是 A3c20 与 A3c20b 两行都写「20 μmol·L⁻¹」，
      // 分不清是哪次测量；分子组的重复测量（A2b / B1b / B1c）也容易读成
      // 「另一个分子」。现在两组的代号位置一致。
      const isConc = (r.kind || '').indexOf('conc') === 0;
      const isRep = (r.kind || '').indexOf('_rep') > 0;
      const main = isConc ? (r.conc + ' μmol·L⁻¹') : (r.mol || r.key);
      let sub = '';
      if (isConc) sub = r.key;
      else if (isRep) sub = r.key;              // A2b：重复测量的代号
      html += '<div class="curvecal-row' + (isCustom ? ' changed' : '') + '">' +
        '<label title="' + esc(r.key + (r.day ? ' · 第 ' + r.day + ' 天' : '')) + '">' +
        esc(main) + (sub ? '<span class="curvecal-key">' + esc(sub) + '</span>' : '') +
        '</label>' +
        '<select data-curve-cal="' + esc(r.key) + '">' +
        _calOptionsHtml(sel) + '</select>' +
        '</div>';
    });
    html += '</div>';
  });
  box.innerHTML = html || '<p class="hint">还没有可选的曲线。</p>';
  const note = $('calCurveNote');
  if (note) {
    note.textContent = changed
      ? ('有 ' + changed + ' 条曲线用了非默认标定')
      : '当前全部使用默认标定';
    note.className = 'hint' + (changed ? ' warn' : '');
  }
}

/* 自定义标定条目：列出 + 可删除 */
function renderCustomCals(s) {
  const box = $('customCalList');
  if (!box) return;
  const custom = s.custom_cals || [];
  if (!custom.length) {
    box.innerHTML = '<p class="hint">还没有添加自定义标定（出厂三条始终可用）。</p>';
    return;
  }
  box.innerHTML = custom.map((c, i) =>
    '<div class="field" style="display:flex;gap:8px;align-items:center">' +
    '<span style="flex:1"><code>' + esc(c.key) + '</code> ' + esc(c.label || '') +
    '<span class="hint"> · ' + esc(c.file || '') + '</span></span>' +
    '<button class="btn" data-del-cal="' + i + '">删除</button></div>'
  ).join('');
  box.querySelectorAll('[data-del-cal]').forEach((b) => {
    b.addEventListener('click', () => {
      const i = Number(b.dataset.delCal);
      const custom2 = (STATE.custom_cals || []).slice();
      const gone = custom2.splice(i, 1)[0];
      STATE.custom_cals = custom2;
      // 被删的标定若还被某条曲线选中，回落到该曲线的默认值
      const cc = {};
      document.querySelectorAll('select[data-curve-cal]').forEach((sel) => {
        cc[sel.dataset.curveCal] = sel.value;
      });
      Object.keys(cc).forEach((k) => {
        if (cc[k] === (gone && gone.key)) {
          cc[k] = (STATE.curve_cal_default || {})[k] || STATE.default_cal_key;
        }
      });
      STATE.curve_cal = cc;
      recalc();
    });
  });
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
  if (s.config && !s.config.partner_name) list.push('封面「合作者」为空（本实验两人合作，导出时留「（待填）」占位）');
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
  renderCurveCals(s);
  renderCustomCals(s);
  renderMolecules(s);
  renderBeer(s);
  renderPicks(s);
  renderBeerChecks(s);
  renderWarnings(s);
  renderFileMap(s);
  renderFileSummary(s);
  loadFileList();
  $('savedInfo').textContent = s.has_saved ? '已保存默认设置（settings.json）' : '尚未保存默认设置';
  drawChart();
}

function renderFileSummary(s) {
  const fs = s.file_summary || {};
  const fuzzy = fs.fuzzy_items || [];
  const box = $('fileSummaryBox');
  if (!box) return;
  if (!fuzzy.length) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.style.display = '';
  box.innerHTML = '<div class="msg">' + fuzzy.length +
    ' 个数据文件是按文件名自动匹配的（换了日期/改了名时会出现），请核对：<br>' +
    fuzzy.slice(0, 8).map((x) =>
      '· ' + esc(x.label) + ' → <code>' + esc(shortName(x.rel)) + '</code>' +
      '（' + ((x.score || 0) * 100).toFixed(0) + '%）').join('<br>') +
    (fuzzy.length > 8 ? '<br>…' : '') +
    '<br>不对就在「数据文件映射」里改，或点「全部恢复默认」。</div>';
}

/* ---------------------------------------------------------------- 数据文件映射 */
const STATUS_LABEL = {
  default: ['默认', ''],
  manual: ['手动指定', 'ok'],
  fuzzy: ['自动匹配', 'warn'],
  ambiguous: ['多候选', 'err'],
  missing: ['没找到', 'err'],
};

function fileMapValue() {
  const out = {};
  Object.keys(MAP_EDIT).forEach((k) => { if (MAP_EDIT[k]) out[k] = MAP_EDIT[k]; });
  return out;
}

function _slotControl(slot) {
  const cur = MAP_EDIT[slot.key];
  const st = slot.status || 'default';
  const info = STATUS_LABEL[st] || STATUS_LABEL.default;
  const files = FILE_FILES.slice();
  // 当前值不在清单里（绝对路径 / 已被删掉）也要显示出来，别静默变成空
  const shown = cur || slot.rel || '';
  if (shown && files.indexOf(shown) < 0) files.unshift(shown);
  const defOpt = '<option value="">（默认：' + esc(shortName(slot.default)) + '）</option>';
  let opts = defOpt;
  // 模糊匹配候选排在最前面，方便一键采用
  const sugg = slot.suggestions || [];
  const seen = {};
  sugg.forEach((x) => {
    if (seen[x.rel]) return;
    seen[x.rel] = 1;
    if (files.indexOf(x.rel) < 0) files.push(x.rel);
    opts += '<option value="' + esc(x.rel) + '"' + (x.rel === shown ? ' selected' : '') +
      '>★ ' + esc(shortName(x.rel)) + '（' + (x.score * 100).toFixed(0) + '%）</option>';
  });
  files.forEach((rel) => {
    if (seen[rel]) return;
    seen[rel] = 1;
    opts += '<option value="' + esc(rel) + '"' + (rel === shown ? ' selected' : '') +
      '>' + esc(rel) + '</option>';
  });
  let badge = '';
  if (st === 'fuzzy') {
    badge = '<span class="badge warn">自动 ' +
      ((slot.score || 0) * 100).toFixed(0) + '%</span>';
  } else if (st === 'manual') {
    badge = '<span class="badge ok">手动</span>';
  } else if (st === 'ambiguous') {
    badge = '<span class="badge err">需要指定</span>';
  } else if (st === 'missing') {
    badge = '<span class="badge err">没找到</span>';
  } else if (cur) {
    badge = '<span class="badge">已改</span>';
  }
  // 候选里最接近的、但不是当前值的那一个，给一句提示
  let hint = '';
  const top = sugg[0];
  if (top && top.rel !== shown) {
    hint = '<span class="hint" style="margin:2px 0 0">最相近：' +
      esc(shortName(top.rel)) + '（' + (top.score * 100).toFixed(0) + '%）</span>';
  }
  return '<div class="field"><label>' + esc(slot.label) + badge + '</label>' +
    '<select data-slot="' + esc(slot.key) + '">' + opts + '</select>' + hint + '</div>';
}

function shortName(rel) {
  const s = String(rel || '');
  const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'));
  return i >= 0 ? s.slice(i + 1) : s;
}

function slotNeedsAttention(x) {
  return (x.status || 'default') !== 'default';
}

function renderFileMap(s) {
  const slots = s.file_slots || [];
  const group = ($('fileGroup') && $('fileGroup').value) || 'all';
  const kw = (($('fileSearch') && $('fileSearch').value) || '').trim().toLowerCase();
  let rows = slots;
  if (group === 'attn') rows = slots.filter(slotNeedsAttention);
  else if (group && group !== 'all') rows = slots.filter((x) => x.kind === group);
  // 关键字实时过滤：同时匹配槽位标签、用途说明、以及当前/默认/候选文件名，
  // 这样输入「A3-5」能直接缩小到那一行，不用在 20 多行里翻。
  if (kw) {
    rows = rows.filter((x) => {
      const hay = [
        x.label, x.group, x.kind, x.rel, x.default, MAP_EDIT[x.key],
      ].concat((x.suggestions || []).map((v) => v.rel)).join(' ').toLowerCase();
      return hay.indexOf(kw) >= 0;
    });
  }
  const groups = {};
  rows.forEach((x) => { (groups[x.group] = groups[x.group] || []).push(x); });
  let html = '';
  Object.keys(groups).forEach((g) => {
    html += '<div class="slotgroup">' + esc(g) + '（' + groups[g].length + '）</div>';
    groups[g].forEach((x) => { html += _slotControl(x); });
  });
  if (!rows.length) {
    html = '<p class="hint">' +
      (kw ? '没有匹配「' + esc(kw) + '」的槽位。'
        : (group === 'attn' ? '没有需要确认的槽位——全部按默认文件名找到了。'
          : '这个分类没有槽位。')) + '</p>';
  }
  const box = $('fileMap');
  box.innerHTML = html;
  box.classList.toggle('collapsed', !!($('fileCompact') && $('fileCompact').checked));
  MAP_BUILT = true;

  // 事件：改动即记进 MAP_EDIT（点「重新计算」才生效，和别的参数一致）
  box.querySelectorAll('select[data-slot]').forEach((sel) => {
    sel.onchange = () => {
      const key = sel.dataset.slot;
      if (sel.value) MAP_EDIT[key] = sel.value;
      else delete MAP_EDIT[key];
      updateFileMapNote();
    };
  });
  updateFileMapNote();
}

function updateFileMapNote() {
  const slots = (STATE && STATE.file_slots) || [];
  const manual = Object.keys(MAP_EDIT).length;
  const auto = slots.filter((x) => x.status === 'fuzzy').length;
  const bad = slots.filter((x) => x.status === 'ambiguous' || x.status === 'missing').length;
  let txt = '共 ' + slots.length + ' 个槽位';
  if (auto) txt += '，其中 ' + auto + ' 个是自动匹配的（请核对）';
  if (manual) txt += '，已手动指定 ' + manual + ' 个';
  if (bad) txt += '，' + bad + ' 个找不到文件';
  if (!auto && !manual && !bad) txt += '，全部按默认文件名找到';
  $('fileMapNote').textContent = txt + '。改完点右上角「重新计算」生效。';
}

async function autoMap() {
  busy(true, '正在按文件名匹配…');
  try {
    // 后端只在 do_POST 里注册了 /api/files/auto（服务端会写映射），
    // 走 GET 会一直是 404 —— 必须显式 POST。
    const r = await api('/api/files/auto', { method: 'POST' });
    if (!r.ok) { toast('匹配失败：' + r.error); return; }
    const n = Object.keys(r.map).length;
    Object.keys(r.map).forEach((k) => { MAP_EDIT[k] = r.map[k]; });
    toast('自动匹配到 ' + n + ' 个文件' +
      (r.unresolved.length ? '，' + r.unresolved.length + ' 个仍需手动指定' : '') +
      '，点「重新计算」生效', 6000);
    await recalc();
  } catch (e) { toast('匹配失败：' + e.message, 5000); }
  finally { busy(false); }
}

async function clearMap() {
  Object.keys(MAP_EDIT).forEach((k) => { delete MAP_EDIT[k]; });
  toast('已恢复全部默认文件名，点「重新计算」生效');
  await recalc();
}

/* ---------------------------------------------------------------- 单文件查看 */
async function pickFile() {
  const cur = $('singlePath').value.trim();
  const dir = cur ? cur.replace(/[\\/][^\\/]*$/, '') : ($('dataDir').value.trim());
  busy(true, '请在弹出的窗口里选择文件…');
  try {
    const r = await api('/api/pickfile?initial=' + encodeURIComponent(dir));
    busy(false);
    if (r.path) {
      $('singlePath').value = r.path;
      await viewSingle();
    } else {
      toast('已取消');
    }
  } catch (e) {
    busy(false);
    toast('打开选择窗口失败：' + e.message, 5000);
  }
}

async function viewSingle(pathArg) {
  const path = pathArg || $('singlePath').value.trim();
  if (!path) { toast('先选一个文件'); return; }
  $('singlePath').value = path;
  $('singleNote').textContent = '读取中…';
  try {
    const info = await api('/api/file/info?path=' + encodeURIComponent(path));
    const i = info.info || {};
    let txt = info.name + '：' + i.n + ' 个数据点，最强点 pixel ' +
      fmt(i.pixel, 0) + '，强度 ' + Number(i.intensity).toPrecision(4);
    if (isFinite(i.lam)) txt += '（按当前标定约 ' + fmt(i.lam, 1) + ' nm）';
    if (info.slot) txt += '；这是槽位「' + info.slot.label + '」用的文件';
    $('singleNote').textContent = txt;
    const q = new URLSearchParams();
    q.set('path', path);
    q.set('cal', $('singleCal').value);
    q.set('smooth', $('singleSmooth').value || 1);
    q.set('t', Date.now());
    $('singleChartBox').style.display = '';
    $('singleChart').src = '/api/preview/single?' + q.toString();
  } catch (e) {
    $('singleNote').textContent = '读取失败：' + e.message;
    $('singleChartBox').style.display = 'none';
    $('singleChart').removeAttribute('src');
  }
}

function fillSingleSelect() {
  const sel = $('singleSelect');
  if (!sel) return;
  const cur = sel.value;
  let html = '<option value="">（从数据目录里挑）</option>';
  FILE_FILES.forEach((rel) => {
    html += '<option value="' + esc(rel) + '"' + (rel === cur ? ' selected' : '') + '>' +
      esc(rel) + '</option>';
  });
  sel.innerHTML = html;
}

async function loadFileList() {
  const dir = $('dataDir').value.trim() || ((STATE && STATE.data_dir) || '');
  try {
    const r = await api('/api/files?dir=' + encodeURIComponent(dir));
    if (!r.ok) return;
    FILE_FILES = r.files || [];
    FILE_AUTO = r.auto || {};
    fillSingleSelect();
  } catch (e) { /* 扫描失败不影响主流程 */ }
  loadFileBrowser(dir);
}

/* ---------------------------------------------------------------- 文件浏览
 * 共享层 web/files.js 提供的 PcalFiles：把 /api/files 的清单渲染成可搜索列表。
 * 槽位匹配仍是 uv.py 那一套（不推翻），这里只多给一个「找文件」的入口：
 * 点一行就把相对路径填进「单文件查看」的路径框，方便换新数据时先看一眼。
 */
let fileBrowser = null;

function ensureFileBrowser() {
  if (fileBrowser) return fileBrowser;
  const host = $('fileBrowser');
  if (!host || !window.PcalFiles) return null;
  fileBrowser = PcalFiles.mount(host, {
    placeholder: '搜索文件名，如 A3 / 氘灯 / 空白',
    exts: ['.txt'],
    onPick: (rel) => {
      const p = $('singlePath');
      if (!p) return;
      p.value = rel;
      toast('已选：' + rel + '，点「查看」画出来', 4000);
      viewSingle(rel);
    },
  });
  return fileBrowser;
}

async function loadFileBrowser(dir) {
  const picker = ensureFileBrowser();
  if (!picker) return;
  try {
    await picker.load(dir);
  } catch (e) { /* 浏览面板失败不影响主流程 */ }
}


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
    conc: 'A3 不同浓度的吸收光谱（原始数据、未扣基线）',
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

/**
 * 弹出系统文件夹选择窗口，把选中的绝对路径填进指定输入框。
 *
 * 后端 /api/pickdir 早就有了（tkinter 子进程），这里只做成通用函数，
 * 数据目录、高斯日志目录共用一套，免得每加一处就抄一遍。
 * onPicked 可选：选完后的附加动作（数据目录要顺带 scanDir）。
 */
async function pickFolderInto(inputId, opts) {
  const o = opts || {};
  const el = $(inputId);
  if (!el) { toast('找不到输入框：' + inputId); return null; }
  const cur = el.value.trim();
  busy(true, o.busyText || '请在弹出的窗口里选择文件夹…');
  try {
    const r = await api('/api/pickdir?initial=' + encodeURIComponent(cur));
    busy(false);
    if (r && r.path) {
      el.value = r.path;
      toast('已选择：' + r.path, 4000);
      if (o.onPicked) await o.onPicked(r.path);
      return r.path;
    }
    toast('已取消');
    return null;
  } catch (e) {
    busy(false);
    toast('打开选择窗口失败：' + e.message, 5000);
    return null;
  }
}

async function pickDir() {
  return pickFolderInto('dataDir', {
    busyText: '请在弹出的窗口里选择数据文件夹…',
    onPicked: () => scanDir(),
  });
}

async function scanDir() {
  const dir = $('dataDir').value.trim();
  try {
    const r = await api('/api/scan?dir=' + encodeURIComponent(dir));
    if (!r.ok) { $('scanInfo').innerHTML = '<span class="err">' + esc(r.error) + '</span>'; return; }
    let html = '找到 ' + r.count + ' 个 txt 文件；需要 ' + r.expected + ' 个。';
    if (r.missing && r.missing.length) {
      html += '<br><span class="err">缺 ' + r.missing.length + ' 个文件</span>';
      html += '<br><span style="font-size:11px">' + r.missing.slice(0, 4).map((m) =>
        esc(m.label) + (m.suggestions.length
          ? ' → 疑似 ' + esc(shortName(m.suggestions[0].rel))
          : '')).join('<br>') + (r.missing.length > 4 ? '<br>…' : '') + '</span>';
      html += '<br><button class="btn" id="btnScanAuto" style="margin-top:6px">' +
        '自动匹配到相近文件</button>';
    } else if (r.fuzzy && r.fuzzy.length) {
      html += '<br><span class="warn">' + r.fuzzy.length +
        ' 个文件按名称自动匹配（见「数据文件映射」）</span>';
      html += '<br><span class="ok">数据齐全，可以计算。</span>';
    } else {
      html += '<br><span class="ok">数据齐全，可以计算。</span>';
    }
    $('scanInfo').innerHTML = html;
    const btn = $('btnScanAuto');
    if (btn) btn.onclick = autoMap;
    // 顺手刷新单文件下拉框，并用最新的槽位状态重画映射卡片
    await loadFileList();
    if (STATE && r.slots) {
      STATE.file_slots = r.slots;
      renderFileMap(STATE);
    }
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
  let html = '<thead><tr><th>分子</th><th>泛函</th><th>计算 λmax / nm</th><th>f</th>' +
             '<th>S1 / nm</th><th>态</th></tr></thead><tbody>';
  mols.forEach((m) => {
    const b = m.bright || {}; const s1 = m.s1 || {};
    html += '<tr data-name="' + esc(m.name) + '" style="cursor:pointer">' +
      '<td>' + esc(m.base || gcalcBase(m.name)) + '</td>' +
      '<td>' + esc(m.functional || '—') + '</td>' +
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
  const nBase = new Set(mols.map((m) => m.base || gcalcBase(m.name))).size;
  $('gcalcNote').textContent = '共 ' + mols.length + ' 条计算结果（' + nBase +
    ' 个分子，目录：' + (res.dir || '') +
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
    // 实际用的目录回填到输入框：留空时后端是"自动找"，如果不回填，
    // 界面上永远看不出到底读了哪个文件夹，出问题无从核对。
    if (r.dir && !dir) {
      $('gcalcLogs').value = r.dir;
      $('gcalcNote').textContent = '已自动找到日志目录并读入；要换目录请点「选择文件夹…」。';
    }
  } catch (e) { toast('读取失败：' + e.message); }
  finally { busy(false); }
}

function pickGcalcLogs() {
  return pickFolderInto('gcalcLogs', {
    busyText: '请选择高斯 TD-DFT 日志所在文件夹…',
  });
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnCalc').onclick = recalc;
  $('btnExport').onclick = doExport;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnScan').onclick = scanDir;
  $('btnBrowse').onclick = pickDir;
  /* ---------------------------------------------------------------- 标定新增 */
let _calFilePicker = null;

async function openCalForm(show) {
  const form = $('calAddForm');
  if (!form) return;
  form.style.display = show ? '' : 'none';
  if (!show) return;
  // 首次展开时才去拉候选光源谱（避免页面加载就多一次请求）
  if (!_calFilePicker && window.PcalFiles) {
    _calFilePicker = PcalFiles.mount($('calNewFilePicker'), {
      placeholder: '搜索光源谱文件名，如 氘灯 / 校准',
      onPick: (rel) => { $('calSaveNote').textContent = '已选：' + rel; },
    });
    try {
      await _calFilePicker.load((STATE && STATE.config && STATE.config.data_dir) || '');
    } catch (e) { /* 目录不可用时不阻塞手填 */ }
  } else if (_calFilePicker) {
    try { await _calFilePicker.refresh(); } catch (e) { /* ignore */ }
  }
  $('calSaveNote').textContent = '';
}

async function saveCal() {
  const note = $('calSaveNote');
  const label = ($('calNewLabel').value || '').trim();
  const short = ($('calNewShort').value || '').trim() || label;
  const rel = _calFilePicker ? _calFilePicker.getValue() : '';
  if (!label) { note.textContent = '请先填名称'; return; }
  if (!rel) { note.textContent = '请先选光源谱文件'; return; }
  const pa = $('calNewPriorA').value;
  const pb = $('calNewPriorB').value;
  // key 从名称派生：英文/数字直接用，中文则用 cal_<序号>，保证能拼进槽位名
  let key = label.replace(/[^\w.\-]+/g, '_').replace(/^_+|_+$/g, '');
  if (!key || /^[\d.\-]+$/.test(key)) {
    const used = {};
    ((STATE && STATE.cal_options) || []).forEach((c) => { used[c.key] = 1; });
    let i = 1;
    while (used['cal_' + i]) i += 1;
    key = 'cal_' + i;
  }
  const entry = { key: key, label: label, short: short, file: rel };
  if (pa !== '' && pb !== '') {
    const fa = Number(pa), fb = Number(pb);
    if (Number.isFinite(fa) && Number.isFinite(fb) && fa !== 0) {
      entry.prior = [fa, fb];
    }
  }
  STATE.custom_cals = (STATE.custom_cals || []).concat([entry]);
  note.textContent = '已添加，正在重新计算…';
  openCalForm(false);
  $('calNewLabel').value = '';
  $('calNewShort').value = '';
  $('calNewPriorA').value = '';
  $('calNewPriorB').value = '';
  if (_calFilePicker) _calFilePicker.setValue('');
  await recalc();
}

$('btnPickLast').onclick = () => {
    document.querySelectorAll('select[data-conc], select[data-mol]').forEach((sel) => {
      sel.selectedIndex = sel.options.length - 1;
    });
    toast('已把每个槽位设为最后一次测量，点「重新计算」生效');
  };
  // ---- 标定：每条曲线选标定 / 增删自定义标定
  $('btnCalReset').onclick = () => {
    document.querySelectorAll('select[data-curve-cal]').forEach((sel) => {
      const def = (STATE && STATE.curve_cal_default || {})[sel.dataset.curveCal];
      if (def) sel.value = def;
    });
    toast('已把每条曲线恢复为默认标定，点「重新计算」生效');
    if (STATE) renderCurveCals(STATE);
  };
  $('btnCalAdd').onclick = () => openCalForm(true);
  $('btnCalCancel').onclick = () => openCalForm(false);
  $('btnCalSave').onclick = saveCal;

  $('chartKind').onchange = drawChart;
  $('btnGcalcPick').onclick = pickGcalcLogs;
  $('btnGcalcOpen').onclick = openGcalc;
  $('btnGcalcRead').onclick = readGcalc;
  // 数据文件映射
  $('btnAutoMap').onclick = autoMap;
  $('btnClearMap').onclick = clearMap;
  $('fileGroup').onchange = () => { if (STATE) renderFileMap(STATE); };
  $('fileCompact').onchange = () => { if (STATE) renderFileMap(STATE); };
  // 查找框：边输边筛（input 事件覆盖键入、粘贴、清空 ×、Esc）
  if ($('fileSearch')) {
    $('fileSearch').oninput = () => { if (STATE) renderFileMap(STATE); };
  }
  // 单文件查看
  $('btnPickFile').onclick = pickFile;
  $('btnSingleView').onclick = () => viewSingle();
  $('singleSelect').onchange = () => {
    const v = $('singleSelect').value;
    if (v) viewSingle(v);
  };
  $('singleCal').onchange = () => { if ($('singlePath').value.trim()) viewSingle(); };
  $('singleSmooth').onchange = () => { if ($('singlePath').value.trim()) viewSingle(); };
  $('singlePath').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); viewSingle(); }
  });
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
}

bindUI();
boot();
