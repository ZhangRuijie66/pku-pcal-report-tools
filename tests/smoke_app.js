/**
 * 用最小 DOM 桩真跑 web/app.js，抓 `cfg is not defined` 这类运行时错误。
 *
 * 为什么需要这个：`node --check` 只做语法检查，ReferenceError 是运行时才
 * 暴露的——2026-11-14 我在 fillConfig 里把参数名 c 写成 cfg，语法完全合法，
 * 但页面一加载就整页卡在「初始化失败 cfg is not defined」。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const argv = process.argv.slice(2);
const APP = argv[0];
const STATE_FILE = argv[1];
if (!APP) {
  console.error('用法: node smoke_app.js <app.js> [state.json]');
  process.exit(2);
}

// ---------------- 极简 DOM ----------------
class El {
  constructor(id, tag = 'div') {
    this.id = id;
    this.tagName = tag.toUpperCase();
    this.textContent = '';
    this.innerHTML = '';
    this.type = 'text';
    this.checked = false;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.className = '';
    this._attrs = {};
    this.classList = {
      _s: new Set(),
      add: (...c) => c.forEach((x) => this.classList._s.add(x)),
      remove: (...c) => c.forEach((x) => this.classList._s.delete(x)),
      toggle: (c) => (this.classList._s.has(c) ? this.classList._s.delete(c)
                                                : this.classList._s.add(c)),
      contains: (c) => this.classList._s.has(c),
    };
  }
  getAttribute(k) { return this._attrs[k] === undefined ? null : this._attrs[k]; }
  setAttribute(k, v) { this._attrs[k] = v; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener() {}
  removeEventListener() {}
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  scrollIntoView() {}
  focus() {}
  blur() {}
  click() {}
  insertAdjacentHTML() {}
  insertAdjacentElement(pos, el) { this.children.push(el); return el; }
  set value(v) { this._value = (v === null || v === undefined) ? '' : String(v); }
  get value() { return this._value === undefined ? '' : this._value; }
  insertBefore(el) { this.children.unshift(el); return el; }
  replaceChild(a, b) { return b; }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 100, bottom: 20, width: 100, height: 20, x: 0, y: 0 };
  }
  get parentNode() { return null; }
  get parentElement() { return null; }
  get nextSibling() { return null; }
  get previousSibling() { return null; }
  get classList_str() { return ''; }
  setProperty(k, v) { this.style[k] = v; }
  contains() { return false; }
  get offsetWidth() { return 100; }
  get offsetHeight() { return 20; }
}

// 收集 HTML 里所有 id，保证 $('xxx') 都能拿到元素（而不是 null 判定分支）
const html = fs.readFileSync(path.join(path.dirname(APP), 'index.html'), 'utf8');
const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
const store = new Map();
for (const id of ids) {
  const tag = /<select[^>]*id="'?/.test(html) ? 'select' : 'div';
  const el = new El(id, tag);
  // 让 <select> 有可用的 options/value
  if (new RegExp('<select[^>]*id="' + id + '"').test(html)) {
    el.tagName = 'SELECT';
    el.options = [];
    el.value = '';
  }
  store.set(id, el);
}

const document = {
  getElementById: (id) => store.get(id) || null,
  querySelector: (sel) => {
    if (sel.startsWith('#')) return store.get(sel.slice(1)) || null;
    return null;
  },
  querySelectorAll: () => [],
  createElement: (t) => new El('', t),
  addEventListener() {},
  removeEventListener() {},
  body: new El('body'),
  documentElement: new El('html'),
  readyState: 'loading',
  cookie: '',
  get title() { return ''; },
  set title(v) {},
};

const noop = () => {};
const localStorage = {
  _m: new Map(),
  getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
  setItem(k, v) { this._m.set(k, String(v)); },
  removeItem(k) { this._m.delete(k); },
  clear() { this._m.clear(); },
};

// fetch 桩：返回一份像样的 /api/state，让 boot() 走正常路径
// 用模块真实的 /api/state 响应（tests/fixtures/web_state/<工具>.json）。
// 手写假数据一旦字段对不上，就会报「Cannot read properties of undefined」，
// 那是假数据的错，会淹没真正的前端 bug。
let API_STATE = {};
if (STATE_FILE && fs.existsSync(STATE_FILE)) {
  API_STATE = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
}

// 不同端点返回不同形状——不能所有 URL 都回 state，否则前端在
// /api/scan 上读 files.files 就炸（2026-11-14 冒烟脚本第一版就是这个错）。
function responseFor(url) {
  const u = String(url || '');
  if (u.indexOf('/api/scan') >= 0 || u.indexOf('/api/files') >= 0) {
    return { ok: true, files: [], dir: '', output_dir: '.' };
  }
  if (u.indexOf('/api/preview') >= 0) {
    return { ok: true, svg: '<svg/>', png: '', curves: [] };
  }
  if (u.indexOf('/api/state') >= 0) return API_STATE;
  return Object.assign({ ok: true }, API_STATE);
}

const fetchStub = async (url) => {
  const body = responseFor(url);
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
};

const errors = [];
const listeners = {};
const addListener = (type, fn) => {
  (listeners[type] = listeners[type] || []).push(fn);
};
const sandbox = {
  document,
  window: {},
  navigator: { clipboard: { writeText: async () => {} }, userAgent: 'node' },
  localStorage,
  sessionStorage: localStorage,
  fetch: fetchStub,
  console: {
    log: (...a) => console.log('[log]', ...a),
    warn: (...a) => console.log('[warn]', ...a),
    error: (...a) => errors.push('console.error: ' + a.join(' ')),
    info: noop, debug: noop,
  },
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: (f) => setTimeout(f, 0),
  alert: noop, confirm: () => true, prompt: () => '',
  URL: { createObjectURL: () => 'blob:', revokeObjectURL: noop },
  Blob: function () {}, File: function () {}, FileReader: function () {
    this.readAsText = noop; this.readAsArrayBuffer = noop;
  },
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  Event: function () {}, CustomEvent: function () {},
  addEventListener: addListener,
  removeEventListener: noop,
  Math, JSON, Date, Number, String, Boolean, Array, Object, RegExp, Error,
  isNaN, isFinite, parseFloat, parseInt, encodeURIComponent, decodeURIComponent,
  location: { search: '', href: 'http://127.0.0.1/', reload: noop },
  history: { replaceState: noop, pushState: noop },
  matchMedia: () => ({ matches: false, addEventListener: noop }),
  URLSearchParams,
  TextEncoder, TextDecoder,
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

const src = fs.readFileSync(APP, 'utf8');
const context = vm.createContext(sandbox);

try {
  vm.runInContext(src, context, { filename: 'app.js' });
} catch (e) {
  errors.push('加载期异常: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e));
}

// 触发 boot（app.js 末尾通常是 boot(); 或 DOMContentLoaded）
(async () => {
  // 先按浏览器的方式触发 DOMContentLoaded（很多模块在这里启动）
  for (const fn of (listeners.DOMContentLoaded || [])) {
    try { await fn(); } catch (e) {
      errors.push('DOMContentLoaded 异常: ' + (e && e.message ? e.message : e));
    }
  }
  await new Promise((r) => setTimeout(r, 600));
  for (const fn of ['boot', 'init', 'main']) {
    if (typeof context[fn] === 'function') {
      try { await context[fn](); } catch (e) {
        errors.push(fn + '() 异常: ' + (e && e.message ? e.message : e));
      }
    }
  }
  await new Promise((r) => setTimeout(r, 400));

  // boot() 里 try/catch 会把异常吞进 setStatus，所以必须再看状态栏
  const st = store.get('status');
  const stText = st ? String(st.textContent || '') : '';
  if (/失败|is not defined|undefined/.test(stText)) {
    errors.push('状态栏显示失败: ' + stText);
  }

  if (errors.length) {
    console.log('发现 ' + errors.length + ' 个问题：');
    for (const e of errors) console.log('  - ' + e);
    process.exit(1);
  }
  console.log('未捕获到运行时错误');
  process.exit(0);
})();
