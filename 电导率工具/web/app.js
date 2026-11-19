/* 电导率实验报告生成器 —— 前端逻辑（无第三方依赖） */
'use strict';

const $ = (id) => document.getElementById(id);
const COVER_FIELDS = ['student_name', 'student_id', 'group', 'group_no', 'date',
  'room_temp', 'pressure'];
const DATA_FIELDS = ['cell_constant_label', 'cell_constant', 'kcl_label_uS',
  'kcl_theory_uS', 'kcl_after_uS', 'kappa_w_uS', 'temp_c', 'compensation'];
const SOLUTIONS = [
  ['NaCl', 'NaCl'], ['NaAc', 'NaAc'], ['HCl', 'HCl'], ['HAc', 'HAc'],
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
    const label = { NaCl: 'NaCl', NaAc: 'NaAc', HCl: 'HCl', HAc: 'HAc' }[r.key];
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
  renderSharedFromState(s.shared);
  $('savedInfo').textContent = s.has_saved ? '已保存封面默认设置（settings.json）'
                                           : '尚未保存封面默认设置';
  drawChart();
  loadFileList(s.data_dir);
}

/* 页面刚打开（或刷新后）时，共享数据的状态在服务端 STATE 里。
 * 这里只回显"读过没、认领到谁"，不重拉整份组内统计——那份体积大，
 * 用户点「重新读取」时再取。 */
function renderSharedFromState(sh) {
  if (!sh || !sh.loaded) { return; }
  if (SHARED && SHARED.ok) { return; }     // 已经有完整数据，别覆盖
  const info = $('sharedInfo');
  const match = sh.match || {};
  if (match.index != null) {
    info.innerHTML = '已读取 <b>' + sh.n + '</b> 位同学的数据，' +
      (match.auto ? '按姓名自动认领：<b>' : '手动指定：<b>') +
      esc(match.name || '') + '</b>。点「重新读取」可看详细统计。';
  } else if (match.student_name) {
    info.innerHTML = '已读取 <b>' + sh.n + '</b> 位同学的数据，但表里找不到「' +
      esc(match.student_name) + '」。点「重新读取」后可手动选择你的数据。';
  }
}

/* ---------------------------------------------------------------- 数据文件列表
 * 数据文件名是固定的（电导率数据.json），但一个学期的实验目录里往往还堆着
 * 别的实验的文件；用共享组件 PcalFiles 挂一个可搜索的清单，方便确认
 * 「我现在到底在读哪一份」。
 */
let PICKER = null;
let PICKER_DIR = null;

async function loadFileList(dir) {
  const box = $('filePicker');
  if (!box) return;
  if (!dir) { box.innerHTML = '<div class="pcal-files-empty">还没有设置数据目录。</div>'; return; }
  if (!window.PcalFiles) {
    box.innerHTML = '<div class="pcal-files-empty">文件选择组件没加载（/static/files.js）。</div>';
    return;
  }
  // 每次重算都重拉一遍清单太浪费（学期目录可能有几百个文件）：目录没变就跳过
  if (PICKER && PICKER_DIR === dir) return;
  try {
    if (!PICKER) {
      PICKER = PcalFiles.mount(box, {
        placeholder: '搜索文件名，如 电导率 / json',
        exts: ['.json'],
        onPick: (rel) => {
          const name = rel.split('/').pop();
          if (name === '电导率数据.json') {
            toast('就是当前在用的数据文件：' + rel, 4000);
          } else {
            toast('这份不是本实验的数据文件（当前固定读 电导率数据.json）：' + rel, 6000);
          }
        },
        // 选了数据目录外面的文件：本实验不按单文件工作，只提示，不改目录
        onPickFile: (abs) => {
          toast('本实验固定读取数据目录里的 电导率数据.json，选中的是目录外的文件：' + abs, 7000);
        },
      });
    }
    const j = await PICKER.load(dir);
    PICKER_DIR = dir;
    const meta = $('filesMeta');
    if (meta) {
      meta.textContent = j && j.ok
        ? '共 ' + j.total + ' 个文件' + (j.target_exists ? '，数据文件已在' : '，数据文件还没有生成')
        : ((j && j.error) || '读取失败');
    }
    if (j && j.target_rel) PICKER.setValue(j.target_rel);
  } catch (e) {
    box.innerHTML = '<div class="pcal-files-empty">读取文件列表失败：' + esc(e.message) + '</div>';
  }
}


function drawChart() {
  const kind = $('chartKind').value;
  $('chart').src = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
  const hints = {
    kappa_c: '三溶液的 κ校–c 曲线（黑方 NaCl / 红圆 HCl / 蓝三角 HAc）',
    'fit:NaCl': 'Λm–√c 拟合，截距即 Λm∞',
    'fit:NaAc': 'Λm–√c 拟合，截距即 Λm∞',
    'fit:HCl': 'Λm–√c 拟合，截距即 Λm∞',
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

// 只重拉 /api/state（不提交表单）：共享数据的「我的数据」改动后用它刷新，
// 不必把整个表单再 POST 一遍（那会顺带把界面上的临时改动一起保存）。
async function reloadState() {
  try {
    const s = await api('/api/state');
    renderState(s);
  } catch (e) {
    toast('刷新状态失败：' + e.message, 5000);
  }
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
    // 用共享组件（PcalFiles.pickFolder → /api/pickdir），没加载时退回原来那条路径
    const path = window.PcalFiles ? await PcalFiles.pickFolder(cur)
                                  : (await api('/api/pickdir?initial=' +
                                      encodeURIComponent(cur))).path;
    busy(false);
    if (path) {
      $('dataDir').value = path;
      toast('已选择：' + path, 4000);
      PICKER = null;            // 换目录了，重建清单
      PICKER_DIR = null;
      await recalc(true);
    } else {
      toast('已取消');
    }
  } catch (e) {
    busy(false);
    toast('打开选择窗口失败：' + e.message, 5000);
  }
}

/* ---------------------------------------------------------------- 共享数据 */
/*
 * 交互约定（2026-11-20 与用户确认）：
 *   · 能按姓名匹配就**自动认领**「我的数据」，不打扰用户；
 *   · 匹配不上（表里没这个人，或用的是别人的名字合作做的这一台）就把
 *     该表里填了姓名的成员列出来让他手选——**绝不猜**，猜错了整份报告的
 *     数据就是别人的；
 *   · 选完把选择发回服务端重算，组内统计与报告的 4.2 节都跟着更新。
 */
let SHARED = null;           // 最近一次 /api/shared 的返回值
let SHARED_FILE = null;      // 浏览器里选过的那份文件（供「重新读取」用）
let SHARED_PATH = '';        // 若通过服务端选择窗口选的，记住路径

function fmtNum(v, n) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(n == null ? 5 : n);
}
function sciShort(v) {
  if (v == null || isNaN(v)) return '—';
  const x = Number(v);
  if (x === 0) return '0';
  const e = Math.floor(Math.log10(Math.abs(x)));
  return (x / Math.pow(10, e)).toFixed(2) + '×10' + supStr(e);
}
function supStr(e) {
  const map = { '-': '⁻', 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴',
                5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' };
  return String(e).split('').map((c) => map[c] || c).join('');
}

function renderShared(res) {
  SHARED = res || null;
  const info = $('sharedInfo');
  const box = $('sharedMeBox');
  const warns = $('sharedWarns');
  const tables = $('sharedTables');
  if (!res || !res.ok) {
    info.textContent = '尚未读取共享数据表。';
    box.style.display = 'none';
    warns.innerHTML = '';
    tables.innerHTML = '';
    return;
  }
  const match = res.match || {};
  const n = res.n || 0;
  const rows = (res.members || []);
  const me = (match.index != null && rows[match.index]) ? rows[match.index] : null;

  if (me) {
    info.innerHTML = '已读取 <b>' + n + '</b> 位同学的数据，' +
      (match.auto ? '按姓名自动认领：<b>' + esc(me.name) + '</b>'
                  : '手动指定：<b>' + esc(me.name) + '</b>') + '。';
    box.style.display = 'none';
  } else {
    const who = match.student_name ? '「' + esc(match.student_name) + '」' : '你的姓名';
    info.innerHTML = '已读取 <b>' + n + '</b> 位同学的数据，但表里找不到 ' +
      who + '。请手动选择你的数据。';
    // 需要手选时才显示选择框
    box.style.display = '';
    const sel = $('sharedMe');
    sel.innerHTML = rows.map((m, i) =>
      '<option value="' + i + '">' + (m.no != null ? m.no + ' 号 · ' : '') +
      esc(m.name) + '</option>').join('');
    $('sharedMeHint').textContent = match.auto === false
      ? '共享表里填的姓名与个人档案不一致时会出现这种情况（例如两人合做一台）。'
      : '';
  }

  // 纠错与可疑点：必须让用户看见，这是"我们替你改了什么"的交代
  const msgs = [];
  (res.fixes || []).forEach((f) => {
    msgs.push({ cls: 'warn', text:
      '已按量级自动改正：' + f.name + ' 的 ' + f.species + ' 第 ' +
      (f.index + 1) + ' 点 ' + f.old + ' → ' + f.new + '（' + f.reason + '）' });
  });
  (res.suspects || []).forEach((s) => {
    msgs.push({ cls: 'warn', text:
      '可疑读数（未改动，请自行核对）：' + s.name + ' 的 ' + s.species +
      ' 第 ' + (s.index + 1) + ' 点 = ' + s.value + '；' + s.why });
  });
  (res.meta && res.meta.skipped && res.meta.skipped.length)
    ? msgs.push({ cls: 'sub', text: '空白仪器块（未填数据，已跳过）：' +
        res.meta.skipped.join('、') + ' 号' }) : null;
  warns.innerHTML = msgs.length
    ? msgs.map((m) => '<div class="msg">' + esc(m.text) + '</div>').join('')
    : '';

  const g = res.group || {};
  if (!g.species) { tables.innerHTML = ''; return; }
  const SPEC = ['NaCl', 'NaAc', 'HCl'];
  let html = '<div class="field"><label><b>组内一致性（n = ' + n +
    '）</b></label><table><tr><th>物种</th><th>组内平均 Λm∞</th>' +
    '<th>s</th><th>RSD</th><th>Grubbs G</th><th>判定</th></tr>';
  SPEC.forEach((k) => {
    const node = g.species[k];
    if (!node) return;
    const d = node.lam_inf || {};
    const gb = node.grubbs || {};
    let verdict = '正常';
    if (gb.is_outlier && gb.outlier_index != null && rows[gb.outlier_index])
      verdict = '异常（' + esc(rows[gb.outlier_index].name) + '）';
    html += '<tr><td>' + k + '</td><td>' +
      '(' + fmtNum(d.mean) + ' ± ' + fmtNum(d.sd) + ')</td><td>' +
      sciShort(d.sd) + '</td><td>' + fmtNum(d.rsd, 2) + '%</td><td>' +
      fmtNum(gb.g, 2) + '</td><td>' + verdict + '</td></tr>';
  });
  html += '</table></div>';

  // 本人 vs 组内
  if (g.me && g.tests && Object.keys(g.tests).length) {
    html += '<div class="field"><label><b>本人 vs 组内（t 检验 / F 检验）' +
      '</b></label><table><tr><th>物种</th><th>本人值</th><th>组内均值</th>' +
      '<th>t</th><th>p</th><th>F</th><th>p(F)</th></tr>';
    ['NaCl', 'NaAc', 'HCl', 'HAc'].forEach((k) => {
      const t = g.tests[k];
      if (!t) return;
      const tt = t.t || {};
      const ff = t.F || {};
      html += '<tr><td>' + k + '</td><td>' +
        fmtNum(tt.diff + tt.others_mean) + '</td><td>' +
        fmtNum(tt.others_mean) + '</td><td>' + fmtNum(tt.t, 2) +
        '</td><td>' + fmtNum(tt.p, 3) + '</td><td>' +
        (ff.F != null ? fmtNum(ff.F, 2) : '—') + '</td><td>' +
        (ff.p != null ? fmtNum(ff.p, 3) : '—') + '</td></tr>';
    });
    html += '</table></div>';
  }

  // 两法 K°
  const km = g.k_methods;
  if (km && km.paired) {
    const p = km.paired;
    html += '<div class="field"><label><b>两法 K° 组内比较</b></label>' +
      '<table><tr><th>方法</th><th>组内平均 K°</th><th>RSD</th></tr>' +
      '<tr><td>求平均法</td><td>' + sciShort(km.mean.mean) + '</td><td>' +
      fmtNum(km.mean.rsd, 2) + '%</td></tr>' +
      '<tr><td>拟合直线法</td><td>' + sciShort(km.fit.mean) + '</td><td>' +
      fmtNum(km.fit.rsd, 2) + '%</td></tr></table>' +
      '<p class="hint">配对 t 检验：平均差 ' + sciShort(p.mean_diff) +
      '，t = ' + fmtNum(p.t, 2) + '，p = ' + fmtNum(p.p, 3) +
      (p.significant ? '（差异显著）' : '（无显著差异）') + '</p></div>';
  }
  tables.innerHTML = html;
}

async function loadShared(file) {
  try {
    busy(true, '正在解析共享数据表…');
    const body = {};
    if (file) {
      body.file_b64 = await fileToB64(file);
      SHARED_FILE = file;
    } else if (SHARED_PATH) {
      body.path = SHARED_PATH;
    } else if (SHARED && SHARED.path) {
      body.path = SHARED.path;
    } else {
      busy(false);
      toast('请先选择共享数据表');
      return;
    }
    const res = await api('/api/shared', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    busy(false);
    renderShared(res);
    if (res.match && res.match.index != null) {
      toast('共享数据已读取：' + res.n + ' 位同学', 3500);
    } else if (res.match && res.match.candidates &&
               res.match.candidates.length) {
      toast('共享数据已读取，但未匹配到你的姓名，请手动选择', 5200);
    }
    return res;
  } catch (e) {
    busy(false);
    toast('读取共享数据失败：' + e.message, 6000);
    throw e;
  }
}

/* 「选择共享数据表」：走浏览器原生文件选择。
 *
 * 为什么不用服务端的 tkinter 选择窗：xlsx 要按**字节**读（文本端点解不了），
 * 而原生 <input type=file> 直接给 File 对象，读成 base64 交给
 * /api/shared 即可，跨平台行为一致，也不会因为 Windows 的 DPI/焦点问题
 * 卡住。服务端路径入口（/api/pickfile）保留给"文件已在磁盘上"的场景。 */
function pickShared() {
  if (!SHARED_FILE && $('sharedInput')) {
    $('sharedInput').click();
    return;
  }
  loadShared(SHARED_FILE);
}

async function useSharedMe() {
  if (!SHARED) { toast('请先读取共享数据表'); return; }
  const idx = Number($('sharedMe').value);
  try {
    busy(true, '正在重算组内统计…');
    const body = { me_index: idx };
    if (SHARED_FILE) {
      body.file_b64 = await fileToB64(SHARED_FILE);
    } else if (SHARED_PATH || (SHARED && SHARED.path)) {
      body.path = SHARED_PATH || SHARED.path;
    }
    const res = await api('/api/shared', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    busy(false);
    renderShared(res);
    // 认领变了 → 报告 4.2 节的「本人」也跟着变，刷新一次 state
    await reloadState();
    toast('已设定我的数据，报告 4.2 节会按这份更新', 4200);
  } catch (e) {
    busy(false);
    toast('设置失败：' + e.message, 6000);
  }
}

function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error('读取文件失败'));
    fr.onload = () => {
      const s = String(fr.result || '');
      const i = s.indexOf(',');
      resolve(i >= 0 ? s.slice(i + 1) : s);
    };
    fr.readAsDataURL(file);
  });
}

/* ---------------------------------------------------------------- 绑定 */
function bindUI() {
  $('btnExport').onclick = doExport;
  $('btnSaveData').onclick = saveData;
  $('btnSaveData2').onclick = saveData;
  $('btnSaveDefault').onclick = saveDefault;
  $('btnBrowse').onclick = pickDir;
  $('chartKind').onchange = drawChart;
  if ($('btnSharedPick')) $('btnSharedPick').onclick = pickShared;
  if ($('btnSharedUseMe')) $('btnSharedUseMe').onclick = useSharedMe;
  if ($('btnSharedReload')) {
    $('btnSharedReload').onclick = () => {
      if (!SHARED_FILE && !SHARED_PATH && !(SHARED && SHARED.ok)) {
        pickShared();           // 还没读过 → 直接让他选文件
      } else {
        loadShared(null);
      }
    };
  }
  if ($('sharedInput')) {
    $('sharedInput').onchange = (e) => {
      const f = e.target.files && e.target.files[0];
      if (f) loadShared(f);          // 选了文件就直接读，不再多点一次
      e.target.value = '';           // 允许重复选同一个文件
    };
  }
  document.querySelectorAll('.field input').forEach((el) => {
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      // 手改数据目录后要重建文件清单（renderState 只在目录变了时才重拉）
      if (el.id === 'dataDir') { PICKER = null; PICKER_DIR = null; }
      recalc(true);
    });
  });
}

bindUI();
boot();
