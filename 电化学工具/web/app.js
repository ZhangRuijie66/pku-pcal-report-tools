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
// 槽位键 -> 状态徽标的文案与配色（与服务端 analysis.SLOT_STATUS 对应）
const SLOT_BADGE = {
  default: ['默认', ''],
  manual: ['手动', 'ok'],
  fuzzy: ['自动', 'warn'],
  ambiguous: ['需要指定', 'err'],
  missing: ['没找到', 'err'],
};

let STATE = null;
let SLOT_INFO = {};   // 槽位键 -> /api/files 返回的匹配信息（score / suggestions / status）
let FILE_FILES = [];  // 当前数据目录里的 txt 清单（相对路径）

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
  // 槽位下拉框由 renderFileMap 渲染（它的值来自 STATE.config，不在这里灌）
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
  // 槽位：读 DOM 里当前选中的值（用户可能刚改过还没重新计算）
  FILE_KEYS.forEach(([key]) => {
    const sel = document.querySelector('select[data-slot="' + key + '"]');
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

/* ---------------------------------------------------------------- 数据文件映射
 * 7 个槽位 -> 实际的 CHI txt 文件。
 *
 * CHI 工作站导出的文件名每年都不同，靠用户肉眼在下拉框里认是撑不住的：
 * 服务端对每个槽位做文件名模糊匹配（pcal/dataloc.py，权重 0.74 语义后缀 +
 * 0.20 整名 + 0.04 同目录 + 0.02 同时间戳），
 *   · ≥0.80 → 自动采用，界面上标「自动 NN%」（橙色，提醒核对）
 *   · ≥0.45 → 进候选下拉框（★ 前缀）
 * 用户改过的值仍走原来的持久化（settings.json + profile.json 合并），没变。
 */
function slotsByKey() {
  const out = {};
  (SLOT_INFO.slots || []).forEach((x) => { out[x.key] = x; });
  return out;
}

function shortName(rel) {
  const s = String(rel || '');
  const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'));
  return i >= 0 ? s.slice(i + 1) : s;
}

function slotControl(info, cur) {
  let st = info.status || 'missing';
  // 用户刚在下拉框里改过、还没点「重新计算」时，服务端的 status 仍是旧的。
  // 先在本地说「已手动指定」，否则会一直挂着「默认」徽标，让人以为没改成功。
  if (cur && info.default && cur !== info.default && st === 'default') st = 'manual';
  const badge = SLOT_BADGE[st] || SLOT_BADGE.missing;
  const score = info.score;
  const badgeText = st === 'fuzzy'
    ? badge[0] + ' ' + ((score || 0) * 100).toFixed(0) + '%' : badge[0];
  const shown = cur || info.rel || '';
  // 下拉框的选项：候选（带匹配度）在前，然后是目录里全部 txt
  const seen = {};
  let opts = '<option value="">（默认：' + esc(shortName(info.default || '')) + '）</option>';
  (info.suggestions || []).forEach((x) => {
    if (seen[x.rel]) return;
    seen[x.rel] = 1;
    opts += '<option value="' + esc(x.rel) + '"' + (x.rel === shown ? ' selected' : '') +
      '>★ ' + esc(shortName(x.rel)) + '（' + ((x.score || 0) * 100).toFixed(0) + '%）</option>';
  });
  const files = FILE_FILES.slice();
  if (shown && files.indexOf(shown) < 0) files.unshift(shown);   // 当前值不在清单里也要显示
  files.forEach((rel) => {
    if (seen[rel]) return;
    seen[rel] = 1;
    opts += '<option value="' + esc(rel) + '"' + (rel === shown ? ' selected' : '') +
      '>' + esc(rel) + '</option>';
  });
  // 候选里最接近的、但不是当前值的那一个，给一句提示
  let hint = '';
  const top = (info.suggestions || [])[0];
  if (st === 'fuzzy') {
    hint = '原文件名 <code>' + esc(shortName(info.requested || '')) + '</code> 不在了，' +
      '按文件名自动改用 <code>' + esc(shortName(info.rel || '')) + '</code>' +
      (info.reason ? '（' + esc(info.reason) + '）' : '');
  } else if (st === 'ambiguous' || st === 'missing') {
    hint = st === 'ambiguous'
      ? '找不到 <code>' + esc(shortName(info.requested || '')) + '</code>；' +
        '下面有 ' + (info.suggestions || []).length + ' 个相近的，请挑一个'
      : '找不到 <code>' + esc(shortName(info.requested || '')) + '</code>，也没有相近的文件名';
  } else if (top && top.rel !== shown) {
    hint = '最相近：<code>' + esc(shortName(top.rel)) + '</code>（' +
      ((top.score || 0) * 100).toFixed(0) + '%）';
  }
  return '<div class="field" data-slot-row="' + esc(info.key) + '">' +
    '<label class="slot-head"><span>' + esc(info.label) + '</span>' +
    '<span class="badge ' + badge[1] + '">' + badgeText + '</span></label>' +
    '<select data-slot="' + esc(info.key) + '">' + opts + '</select>' +
    (hint ? '<p class="slot-why">' + hint + '</p>' : '') +
    '</div>';
}

function renderFileMap(s) {
  const box = $('fileMap');
  // 每次重渲染都重建：目录/映射/自动匹配结果都可能变，缓存 HTML 会显示旧状态
  const cfg = (STATE && STATE.config) || {};
  const info = slotsByKey();
  const kw = (($('fileSearch') && $('fileSearch').value) || '').trim().toLowerCase();
  let rows = FILE_KEYS.map(([key, label]) => {
    const it = info[key] || { key: key, label: label, status: 'missing',
                              default: '', requested: '', suggestions: [] };
    return Object.assign({}, it, { label: label });
  });
  if (kw) {
    // 关键字实时过滤：同时匹配槽位标签、当前值、默认值与候选文件名，
    // 这样输入「O2_slow」能直接缩小到那一行。
    rows = rows.filter((x) => {
      const hay = [x.label, x.rel, x.default, x.requested]
        .concat((x.suggestions || []).map((v) => v.rel))
        .concat([cfg[x.key] || '']).join(' ').toLowerCase();
      return hay.indexOf(kw) >= 0;
    });
  }
  if (!rows.length) {
    box.innerHTML = '<p class="hint">没有匹配「' + esc(kw) + '」的槽位。</p>';
    return;
  }
  box.innerHTML = rows.map((x) => slotControl(x, cfg[x.key] || '')).join('');
  const attn = FILE_KEYS.filter(([k]) => {
    const st = (info[k] || {}).status;
    return st && st !== 'default' && st !== 'manual';
  }).length;
  const total = FILE_KEYS.length;
  $('mapInfo').innerHTML = attn
    ? '<span class="warn">' + attn + ' / ' + total +
      ' 个槽位不是按默认文件名读到的，请核对上面橙色/红色几行。</span>'
    : '<span class="ok">' + total + ' 个槽位都按预期文件读到了。</span>';
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
  loadFiles(s.data_dir);
}

/* ---------------------------------------------------------------- 文件清单
 * /api/files 给的是「目录里有哪些 txt + 每个槽位的候选与匹配度」。
 * 槽位映射（renderFileMap）和目录浏览（PcalFiles 组件）都靠它。
 */
let PICKER = null;
let FILES_DIR = null;

async function loadFiles(dir) {
  if (!dir) return;
  const changed = FILES_DIR !== dir;
  try {
    const r = await api('/api/files?dir=' + encodeURIComponent(dir));
    SLOT_INFO = { slots: r.slots || [] };
    FILE_FILES = r.files || [];
    FILES_DIR = dir;
    // 目录变了才重挂组件（几百个文件时每次重算都重建会很卡）
    const box = $('filePicker');
    if (box && window.PcalFiles && (changed || !PICKER)) {
      if (!PICKER) {
        PICKER = PcalFiles.mount(box, {
          placeholder: '搜索文件名，如 N2 / O2_slow / 甲醇',
          exts: ['.txt'],
          // 选中一个文件：填给「最接近」的那个槽位（按当前匹配度挑），
          // 这样用户不必先猜该改哪一行。
          onPick: (rel) => assignToSlot(rel),
          onPickFile: (abs) => {
            toast('选的文件不在当前数据目录里：' + abs + '。请先把数据目录设为它所在的文件夹。', 7000);
          },
        });
      }
      const j = await PICKER.load(dir);
      const meta = $('filesMeta');
      if (meta) {
        meta.textContent = (j && j.ok)
          ? '共 ' + j.total + ' 个 txt 文件'
          : ((j && j.error) || '读取失败');
      }
    }
    renderFileMap(STATE);
  } catch (e) {
    const meta = $('filesMeta');
    if (meta) meta.textContent = '读取文件列表失败：' + e.message;
  }
}

/** 把一个文件名填给最接近的槽位（用户从文件清单里点了一行）。
 *
 * ⚠️ 2026-11-09 修 bug：以前是纯前端评分，只在每个槽位的 `suggestions` 里找
 * 这个文件。但 `suggestions` 只在「登记的文件名找不到」时才由服务端填
 * （见 analysis.resolve_slots ② 分支）——七个槽位全都 `status='default'` 时
 * 人人都是空数组 → 所有候选同分 0 → `sc > bestScore` 一次都不成立，
 * `bestKey` 停在遍历的第一个槽位 = file_n2_blank。
 * 用户看到的症状就是：「点击之后只会把数据派给 N₂ 空白」。
 *
 * 现在改成**问后端**（POST /api/files/assign），后端用与「一键自动匹配」
 * 完全同一套规则（slot_tail + dataloc.match_score）正向打分，口径一致。
 * 分数不够就弹候选让用户自己挑，绝不静默塞进某一格。
 */
async function assignToSlot(rel) {
  let r;
  try {
    r = await api('/api/files/assign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel: rel }),
    });
  } catch (e) {
    toast('没算出该填给哪个槽位：' + e.message, 6000);
    return;
  }
  const best = r.best;
  const cands = r.candidates || [];
  if (!best) {
    // 分都不够：把最像的几个列出来让用户点，不替他决定
    const top = cands.slice(0, 3).map((x) =>
      x.label + '（' + Math.round((x.score || 0) * 100) + '%）').join('、');
    toast('“' + rel + '”和哪个槽位都不太像' + (top ? '，最接近的是：' + top : '') +
          '。请在「数据文件映射」里手动挑一格。', 8000);
    return;
  }
  const sel = document.querySelector('select[data-slot="' + best.key + '"]');
  if (!sel) { toast('槽位下拉框还没渲染好，稍后再试', 5000); return; }
  if (sel.querySelector('option[value="' + CSS.escape(rel) + '"]') === null) {
    const o = document.createElement('option');
    o.value = rel;
    o.textContent = rel;
    sel.appendChild(o);
  }
  const before = sel.value;
  sel.value = rel;
  // 同步进 STATE.config 再重渲染：renderFileMap 只读 STATE.config，
  // 不先写进去的话重渲染会把刚填的值弹回去（下拉框闪一下又变回原值）。
  if (STATE && STATE.config) STATE.config[best.key] = rel;
  const pct = Math.round((best.score || 0) * 100);
  let msg = '已把 ' + rel + ' 填给「' + best.label + '」（匹配 ' + pct + '%）';
  if (before && before !== rel) msg += '，原来是 ' + before;
  // 分不高就提醒核对：0.80 是自动采用门槛，低于它说明是猜的
  if ((best.score || 0) < 0.8) {
    msg += '。这个匹配度不高，请核对是不是填对了格子';
  }
  toast(msg + '，记得点「重新计算」', 7000);
  // 填完刷新那一行，让用户看到「手动」徽标
  if (STATE) renderFileMap(STATE);
}

async function autoMap() {
  busy(true, '正在按文件名自动匹配…');
  try {
    const dir = ($('dataDir').value || '').trim();
    const r = await api('/api/files/auto' + (dir ? '?dir=' + encodeURIComponent(dir) : ''),
                        { method: 'POST' });
    busy(false);
    const n = Object.keys(r.map || {}).length;
    FILES_DIR = null;
    if (r.state) renderState(r.state);
    else await recalc();
    if (n) {
      toast('自动匹配到 ' + n + ' 个文件并已保存映射', 6000);
    } else {
      toast('没有分数够 80% 的候选，请在下拉框里手动挑（红色/橙色那几行）', 7000);
    }
    if ((r.unresolved || []).length) {
      const names = r.unresolved.map((x) => x.label).join('、');
      setTimeout(() => alert('这些槽位仍需手动指定：\n' + names), 200);
    }
  } catch (e) {
    busy(false);
    toast('自动匹配失败：' + e.message, 6000);
  }
}

async function resetMap() {
  // 恢复默认 = 把 7 个槽位清空后存盘（清空即回落到 echem.DEFAULT_FILES）
  busy(true, '正在恢复默认映射…');
  try {
    const cfg = readConfig();
    FILE_KEYS.forEach(([key]) => { cfg[key] = ''; });
    const s = await api('/api/calc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: cfg }),
    });
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: cfg }),
    });
    busy(false);
    FILES_DIR = null;
    renderState(s);
    toast('已恢复默认文件名', 5000);
  } catch (e) {
    busy(false);
    toast('恢复失败：' + e.message, 6000);
  }
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
    // 用共享组件（PcalFiles.pickFolder → /api/pickdir），没加载时退回原来那条路径
    const path = window.PcalFiles ? await PcalFiles.pickFolder(cur)
                                  : (await api('/api/pickdir?initial=' +
                                      encodeURIComponent(cur))).path;
    busy(false);
    if (path) {
      $('dataDir').value = path;
      toast('已选择：' + path, 4000);
      FILES_DIR = null;
      PICKER = null;
      await scanDir();
      await recalc();
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
      html += '<br>（在「数据文件映射」里手动指定，或点「一键自动匹配」）';
    } else {
      html += '<br><span class="ok">数据齐全，可以计算。</span>';
    }
    // 扫描与计算走同一套槽位解析，所以这里能说清「哪几个是自动匹配来的」
    const fuzzy = r.fuzzy || [];
    if (fuzzy.length) {
      html += '<br><span class="warn">' + fuzzy.length + ' 个是自动匹配（请核对）：</span>' +
        fuzzy.map((x) => '<br>· ' + esc(x.requested) + ' → <code>' + esc(x.rel) +
                         '</code>（' + ((x.score || 0) * 100).toFixed(0) + '%）').join('');
    }
    $('scanInfo').innerHTML = html;
    FILES_DIR = null;
    loadFiles(dir);
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
  if ($('btnAutoMap')) $('btnAutoMap').onclick = autoMap;
  if ($('btnResetMap')) $('btnResetMap').onclick = resetMap;
  if ($('fileSearch')) $('fileSearch').oninput = () => renderFileMap(STATE);
  $('chartKind').onchange = drawChart;
  document.querySelectorAll('.field input, .field select').forEach((el) => {
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') recalc(); });
  });
  // 槽位下拉框是动态渲染的：用事件委托，别在每次渲染后重绑
  document.addEventListener('change', (e) => {
    const sel = e.target.closest && e.target.closest('select[data-slot]');
    if (!sel) return;
    setStatus('映射已改，点「重新计算」生效：' + sel.getAttribute('data-slot'));
  });
}

bindUI();
boot();
