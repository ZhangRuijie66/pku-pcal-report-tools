/**
 * 抓取每个模块真实的 /api/state，存成 tests/fixtures，供 smoke_app.js 使用。
 *
 * 为什么必须用真实响应：前端 boot() 直接消费这个结构，我手写的假数据
 * 一旦字段对不上，冒烟脚本就会报「Cannot read properties of undefined」——
 * 那是**假数据的错**，不是前端的错，会淹没真正的问题。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2];
const OUT = process.argv[3];
const mods = JSON.parse(process.argv[4] || '[]');

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function fetchState(port) {
  for (let i = 0; i < 80; i++) {
    await sleep(400);
    try {
      const r = await fetch('http://127.0.0.1:' + port + '/api/state');
      if (r.ok) return await r.json();
    } catch (e) { /* 还没起来 */ }
  }
  return null;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  let port = 8910;
  for (const tool of mods) {
    const dir = path.join(ROOT, tool);
    const p = port++;
    const child = spawn(process.env.PYTHON_EXE || 'python',
      ['run.py', '--port', String(p), '--no-browser'],
      { cwd: dir, stdio: 'ignore',
        env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' }) });
    try {
      const state = await fetchState(p);
      if (!state) {
        console.log('  [FAIL] ' + tool + ' 没起来');
        continue;
      }
      const file = path.join(OUT, tool + '.json');
      fs.writeFileSync(file, JSON.stringify(state, null, 1), 'utf8');
      console.log('  [ OK ] ' + tool + ' (' + fs.statSync(file).size + ' bytes)');
    } finally {
      child.kill();
      await sleep(300);
    }
  }
})();
