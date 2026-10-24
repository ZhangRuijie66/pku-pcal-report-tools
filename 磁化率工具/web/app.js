/* 磁化率的测定 —— 前端逻辑（与其它实验模块同一套模板） */
'use strict';

const $ = (id) => document.getElementById(id);
const state = { config: null, defaults: null, data: null, result: null };

function toast(msg, ms = 3000) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), ms);
}
function busy(on, text) {
  $('overlay').classList.toggle('show', !!on);
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
function sup(n) {
  const map = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
                '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
  return String(n).split('').map(c => map[c] || c).join('');
}
function sci(x, n = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  if (x === 0) return '0';
  const e = Math.floor(Math.log10(Math.abs(x)));
  return (x / Math.pow(10, e)).toFixed(n) + '×10' + sup(e);
}
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function num(id) {
  const v = $(id).value.trim();
  return v === '' ? null : Number(v);
}

const CONFIG_TEXT = ['student_name', 'student_id', 'group', 'group_no', 'date'];
const CONFIG_NUM = ['room_temp', 'pressure'];

function readConfig() {
  const cfg = { data_dir: (state.config && state.config.data_dir) || '' };
  CONFIG_TEXT.forEach(k => { cfg[k] = $(k).value.trim(); });
  CONFIG_NUM.forEach(k => { cfg[k] = num(k); });
  return cfg;
}
function fillConfig(c) {
  c = c || {};
  CONFIG_TEXT.forEach(k => { $(k).value = c[k] === null || c[k] === undefined ? '' : c[k]; });
  CONFIG_NUM.forEach(k => {
    $(k).value = c[k] === null || c[k] === undefined ? '' : c[k];
  });
}

function renderSummary(s) {
  const samples = Object.keys(s.samples || {}).length;
  const t = s.temperature_C === null || s.temperature_C === undefined
    ? '—' : fmt(s.temperature_C, 1) + ' ℃';
  const tk = s.temperature_K === null || s.temperature_K === undefined
    ? '—' : fmt(s.temperature_K, 2) + ' K';
  $('summary').innerHTML =
    `<div class="stat"><div class="k">实验温度</div><div class="v">${t}</div><div class="hint">${tk}</div></div>
     <div class="stat"><div class="k">莫尔盐比磁化率 χ<sub>标</sub></div><div class="v">${sci(s.chi_std, 3)}</div><div class="hint">m³·kg⁻¹</div></div>
     <div class="stat"><div class="k">样品数</div><div class="v">${samples}</div><div class="hint">含标样外的待测样品</div></div>`;
}

function renderTable(s) {
  const rows = Object.entries(s.samples || {});
  if (!rows.length) {
    $('dataTable').innerHTML = '<tr><td class="muted">还没有数据</td></tr>';
    return;
  }
  const head = `<thead><tr>
    <th>样品</th><th>m<sub>0</sub> / g</th><th>m<sub>H</sub> / g</th><th>Δm / g</th>
    <th>χ /(m³·kg⁻¹)</th><th>χ<sub>m</sub> /(m³·mol⁻¹)</th>
    <th>μ / μ<sub>B</sub></th><th>n</th></tr></thead>`;
  const body = rows.map(([name, v]) => {
    const m0 = v.m_zero === undefined ? v.m_sample : v.m_zero;
    const mu = v.mu === null || v.mu === undefined ? '—' : fmt(v.mu, 3);
    let n = v.n === null || v.n === undefined ? '—' : fmt(v.n, 2);
    if ((v.n === null || v.n === undefined) && v.chi_m !== null && v.chi_m < 0) {
      n = '0（反磁性）';
    }
    return `<tr>
      <td>${esc(name)}</td>
      <td>${fmt(m0, 4)}</td>
      <td>${fmt(v.m_field, 4)}</td>
      <td>${fmt(v.delta_m, 4)}</td>
      <td>${sci(v.chi_mass, 3)}</td>
      <td>${sci(v.chi_m, 3)}</td>
      <td>${mu}</td>
      <td>${n}</td>
    </tr>`;
  }).join('');
  $('dataTable').innerHTML = head + '<tbody>' + body + '</tbody>';
}

const CHART_HINT = {
  chi_m: '各样品摩尔磁化率，单位 10⁻⁶ m³·mol⁻¹',
  mu: '只画有永久磁矩的样品；反磁性样品不出现在图中',
  n: '由 μ 反推的未成对电子数；反磁性样品不出现',
};
function drawChart() {
  const kind = $('chartKind').value;
  $('chartHint').textContent = CHART_HINT[kind] || '';
  $('chart').src = '/api/preview?kind=' + encodeURIComponent(kind) + '&t=' + Date.now();
}

function renderState(s, fill = true) {
  state.config = s.config || state.config || {};
  state.defaults = s.defaults || state.defaults;
  state.data = s.data;
  state.result = s;
  if (fill) fillConfig(state.config);
  $('dataFile').textContent = s.data_file || '—';
  renderSummary(s);
  renderTable(s);
  $('formatted').textContent = s.formatted || '—';
  drawChart();
}

async function postData(data) {
  const s = await api('/api/data', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data }),
  });
  renderState(s, false);
  setStatus('数据已更新 · ' + new Date().toLocaleTimeString());
  return s;
}

async function boot() {
  setStatus('正在初始化…');
  try {
    const s = await api('/api/state');
    renderState(s);
    const q = new URLSearchParams(location.search);
    if (q.get('home')) {
      $('btnHome').href = q.get('home');
      $('btnHome').style.display = '';
    }
    setStatus('就绪');
    if (window.PcalDraft) {
      await PcalDraft.init({
        key: 'pcal-draft-magnetic-v1',
        read: () => ({ config: readConfig(), data: state.data }),
        apply: async (d) => {
          fillConfig(d.config || {});
          if (d.data) await postData(d.data);
          else await recalc();
        },
      });
    }
  } catch (e) {
    setStatus('初始化失败：' + e.message);
    toast('初始化失败：' + e.message, 6000);
  }
}

async function recalc() {
  try {
    const s = await api('/api/state');
    renderState(s, false);
    setStatus('已重新计算 · ' + new Date().toLocaleTimeString());
    toast('计算完成');
  } catch (e) {
    setStatus('计算失败：' + e.message);
    toast('计算失败：' + e.message, 6000);
  }
}

async function loadSample() {
  busy(true, '正在载入示例数据…');
  try {
    const s = await api('/api/sample', { method: 'POST' });
    renderState(s, false);
    if (window.PcalDraft) PcalDraft.save();
    setStatus('已载入示例数据');
    toast('已载入示例数据');
  } catch (e) {
    toast('载入失败：' + e.message, 6000);
  } finally {
    busy(false);
  }
}

async function saveData() {
  try {
    await postData(state.data);
    if (window.PcalDraft) PcalDraft.save();
    toast('数据已保存到 data/磁化率数据.json');
  } catch (e) {
    toast('保存失败：' + e.message, 6000);
  }
}

async function importData(file) {
  if (!file) return;
  busy(true, '正在导入数据…');
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('JSON 顶层必须是一个对象');
    }
    await postData(data);
    if (window.PcalDraft) PcalDraft.save();
    toast('已导入：' + file.name);
  } catch (e) {
    toast('导入失败：' + e.message, 7000);
  } finally {
    busy(false);
    $('fileInput').value = '';
  }
}

async function saveDefault() {
  try {
    const s = await api('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(readConfig()),
    });
    state.config = s.config || readConfig();
    if (window.PcalDraft) PcalDraft.save();
    toast('已存为默认，下次打开自动填回');
  } catch (e) {
    toast('保存失败：' + e.message, 6000);
  }
}

async function exportReport() {
  busy(true, '正在排版 Word 文档…');
  try {
    const r = await api('/api/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readConfig(), data: state.data }),
    });
    busy(false);
    if (window.PcalDraft) PcalDraft.clear();
    toast('已生成：' + r.path, 7000);
    setStatus('报告已生成：' + r.path);
    alert('报告已生成：\n' + r.path);
  } catch (e) {
    busy(false);
    toast('生成失败：' + e.message, 7000);
  }
}

function bindUI() {
  $('btnSample').addEventListener('click', loadSample);
  $('btnSaveData').addEventListener('click', saveData);
  $('fileInput').addEventListener('change', (e) => importData(e.target.files[0]));
  $('btnSaveDefault').addEventListener('click', saveDefault);
  $('btnRecalc').addEventListener('click', recalc);
  $('btnExport').addEventListener('click', exportReport);
  $('chartKind').addEventListener('change', drawChart);
}

window.addEventListener('DOMContentLoaded', () => {
  bindUI();
  boot();
});
