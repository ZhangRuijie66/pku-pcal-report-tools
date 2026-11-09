/* 物化实验报告工具 —— 通用「文件选择 + 搜索」前端组件
 *
 * 解决的问题：
 *   1. 数据文件名带时间戳，换一天/换个人就全变（写死文件名撑不过一次重测）；
 *   2. 一个学期的数据可能有几百个文件，下拉框根本翻不完，要能按关键字过滤；
 *   3. 各模块原来各写各的「选择文件夹」按钮，行为不一致。
 *
 * 用法（在 index.html 里 <script src="/static/files.js"></script>，
 * 放在 app.js 之前）：
 *
 *   // 选目录（弹系统窗口）
 *   const dir = await PcalFiles.pickFolder(currentDir);
 *
 *   // 选单个文件
 *   const f = await PcalFiles.pickFile(currentDir, ['.csv', '.txt']);
 *
 *   // 把「可搜索的文件选择器」挂到某个容器上
 *   const picker = PcalFiles.mount(el, {
 *     onPick: (rel, info) => { ... },     // 用户选定后回调（rel 是相对路径）
 *     placeholder: '搜索文件名，如 苯甲酸 / A3-5',
 *   });
 *   await picker.load(dir);               // 拉 /api/files 填充
 *   picker.setValue('a/b.csv');           // 程序化选中
 *
 * 依赖后端端点（各模块 server.py 里接，见 _core/filepick.py）：
 *   GET /api/files             → {ok, dir, files:[相对路径], total}
 *   GET /api/pickdir?initial=  → {ok, path}
 *   GET /api/pickfile?initial=&exts= → {ok, path}
 */
(function (global) {
  'use strict';

  const MAX_RENDER = 300;   // 一次最多渲染多少行（再多用户也不会手翻）

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function getJSON(url) {
    const r = await fetch(url);
    let j;
    try { j = await r.json(); } catch (e) { j = { ok: false, error: 'HTTP ' + r.status }; }
    return j;
  }

  /* ---------------------------------------------------------------- 端点 */

  async function pickFolder(initial) {
    const j = await getJSON('/api/pickdir?initial=' + encodeURIComponent(initial || ''));
    return (j && j.ok && j.path) ? j.path : '';
  }

  async function pickFile(initial, exts) {
    const q = '/api/pickfile?initial=' + encodeURIComponent(initial || '')
            + '&exts=' + encodeURIComponent((exts || []).join(';'));
    const j = await getJSON(q);
    return (j && j.ok && j.path) ? j.path : '';
  }

  async function index(dir) {
    const j = await getJSON('/api/files?dir=' + encodeURIComponent(dir || ''));
    if (!j || !j.ok) return { dir: '', files: [], total: 0, error: (j && j.error) || '读取失败' };
    return j;
  }

  /* ---------------------------------------------------------------- 搜索
   * 与后端 dataloc.search_files 同口径（子串 > 子序列 > 模糊），
   * 但纯前端跑，输入即时响应。
   */
  function plain(s) {
    return String(s || '').toLowerCase().replace(/[^0-9a-z\u4e00-\u9fff]+/g, '');
  }

  function isSubsequence(q, hay) {
    let i = 0;
    for (let k = 0; k < hay.length && i < q.length; k += 1) {
      if (hay[k] === q[i]) i += 1;
    }
    return i === q.length;
  }

  function ratio(a, b) {
    // 简化版相似度：公共前缀/后缀 + 长度比，够用来排「明显相关」
    if (!a || !b) return 0;
    let same = 0;
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i += 1) { if (a[i] === b[i]) same += 1; else break; }
    return (2 * same) / (a.length + b.length);
  }

  function search(files, query, limit) {
    files = files || [];
    limit = limit || MAX_RENDER;
    const q = plain(query);
    if (!q) return files.slice(0, limit);

    const exact = [];
    const subseq = [];
    const fuzzy = [];
    for (let i = 0; i < files.length; i += 1) {
      const rel = files[i];
      const hay = plain(rel);
      if (hay.indexOf(q) >= 0) { exact.push([hay.length, rel]); continue; }
      if (isSubsequence(q, hay)) { subseq.push([hay.length, rel]); continue; }
      const r = ratio(q, hay);
      if (r >= 0.5) fuzzy.push([-r, rel]);
    }
    exact.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
    subseq.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
    fuzzy.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
    const out = [];
    const push = (arr) => { for (let i = 0; i < arr.length && out.length < limit; i += 1) out.push(arr[i][1]); };
    push(exact); push(subseq); push(fuzzy);
    return out;
  }

  /* ---------------------------------------------------------------- 选择器 */

  let uid = 0;

  /** 文件名是否在该组允许的后缀里（``opts.exts`` 为空 = 不限制）。 */
  function _allowed(rel, exts) {
    if (!exts || !exts.length) return true;
    const low = String(rel || '').toLowerCase();
    for (let i = 0; i < exts.length; i += 1) {
      let e = String(exts[i] || '').toLowerCase();
      if (!e) continue;
      if (e[0] !== '.') e = '.' + e;
      if (low.slice(-e.length) === e) return true;
    }
    return false;
  }

  function mount(el, opts) {
    if (!el) throw new Error('PcalFiles.mount: 容器不存在');
    opts = opts || {};
    const id = 'pcalFiles' + (uid += 1);
    const files = [];
    let dir = '';
    let value = '';
    let filtered = [];
    // 目录里所有文件（未过滤）— 只为了在提示里说清「有几个不支持的文件」，
    // 不然用户会以为工具没扫到它们。
    let rawCount = 0;

    el.innerHTML =
      '<div class="pcal-files">' +
      '  <div class="pcal-files-bar">' +
      '    <input type="search" class="pcal-files-search" id="' + id + 'q" ' +
      '           placeholder="' + esc(opts.placeholder || '搜索文件名…') + '" ' +
      '           autocomplete="off" spellcheck="false">' +
      '    <button type="button" class="pcal-files-btn" id="' + id + 'pick">选择文件…</button>' +
      '  </div>' +
      '  <div class="pcal-files-meta" id="' + id + 'meta"></div>' +
      '  <div class="pcal-files-list" id="' + id + 'list" role="listbox"></div>' +
      '</div>';

    const q = el.querySelector('#' + id + 'q');
    const list = el.querySelector('#' + id + 'list');
    const meta = el.querySelector('#' + id + 'meta');
    const btn = el.querySelector('#' + id + 'pick');

    function paint() {
      filtered = search(files, q.value, MAX_RENDER);
      if (!files.length) {
        // 空列表分四种情况，给的下一步不一样：
        //   没设目录 / 目录不存在 → 去选；目录有文件但后缀都不支持 → 说清要哪种格式；
        //   目录存在但没数据文件 → 说清要放什么进去。
        let msg;
        if (!dir) {
          msg = '还没有选择数据文件夹。点上面的「选择文件…」，或先选好数据文件夹。';
        } else if (rawCount && opts.exts && opts.exts.length) {
          msg = '这个文件夹里有 ' + rawCount + ' 个文件，但没有 ' +
                esc(opts.exts.join(' / ')) + ' 格式的数据文件（' + esc(dir) +
                '）。本实验只读这几种格式，其它文件不会列出来。';
        } else if (opts.emptyHint) {
          msg = opts.emptyHint;
        } else {
          msg = '这个文件夹里没有找到数据文件（' + esc(dir) +
                '）。把课程软件导出的数据文件放进这个文件夹，再点「刷新」。';
        }
        list.innerHTML = '<div class="pcal-files-empty">' + msg + '</div>';
        // 别把 meta 清空：用户要知道「是空的」还是「没扫到」
        meta.textContent = rawCount
          ? '共 ' + rawCount + ' 个文件，其中 0 个可用'
          : '目录里没有文件';
        return;
      }
      const shown = filtered.length;
      // 被后缀过滤掉的文件数：主动说出来，别让人以为工具漏扫了
      const skipped = rawCount - files.length;
      const skipNote = skipped > 0
        ? '（另有 ' + skipped + ' 个非 ' + (opts.exts || []).join('/') + ' 文件未列出）'
        : '';
      meta.textContent = q.value
        ? '匹配 ' + shown + ' / 共 ' + files.length + ' 个文件' + skipNote
        : '共 ' + files.length + ' 个文件' + skipNote +
          (files.length > MAX_RENDER ? '（列出前 ' + Math.min(files.length, MAX_RENDER) + ' 个，输入关键字可缩小范围）' : '');
      if (!shown) {
        list.innerHTML = '<div class="pcal-files-empty">没有匹配的文件，换个关键字试试。</div>';
        return;
      }
      list.innerHTML = filtered.map((rel) => {
        const base = rel.split('/').pop();
        const dirPart = rel.slice(0, rel.length - base.length).replace(/\/$/, '');
        const on = rel === value ? ' on' : '';
        return '<button type="button" class="pcal-files-row' + on + '" data-rel="' +
          esc(rel) + '" title="' + esc(rel) + '">' +
          '<span class="pcal-files-name">' + esc(base) + '</span>' +
          (dirPart ? '<span class="pcal-files-dir">' + esc(dirPart) + '</span>' : '') +
          '</button>';
      }).join('');
    }

    list.addEventListener('click', (ev) => {
      const row = ev.target.closest ? ev.target.closest('[data-rel]') : null;
      if (!row) return;
      value = row.getAttribute('data-rel');
      paint();
      if (opts.onPick) opts.onPick(value, { dir: dir });
    });

    q.addEventListener('input', paint);
    q.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        if (filtered.length) {
          value = filtered[0];
          paint();
          if (opts.onPick) opts.onPick(value, { dir: dir });
        }
      } else if (ev.key === 'Escape') {
        q.value = '';
        paint();
      }
    });

    btn.addEventListener('click', async () => {
      const picked = await pickFile(dir, opts.exts);
      if (!picked) return;
      // 选的是绝对路径：若在数据目录内就转成相对路径并选中；否则交给回调
      const norm = picked.replace(/\\/g, '/');
      const base = (dir || '').replace(/\\/g, '/').replace(/\/$/, '');
      if (base && norm.indexOf(base + '/') === 0) {
        value = norm.slice(base.length + 1);
        // 用户主动从系统对话框选的，一定收进来（对话框本身已按 opts.exts 过滤过）
        if (files.indexOf(value) < 0) { files.push(value); rawCount += 1; }
        paint();
        if (opts.onPick) opts.onPick(value, { dir: dir });
      } else if (opts.onPickFile) {
        opts.onPickFile(picked);
      } else if (opts.onPick) {
        opts.onPick(picked, { dir: dir, absolute: true });
      }
    });

    async function reload(newDir) {
      dir = newDir || '';
      const j = await index(dir);
      const all = j.files || [];
      rawCount = all.length;
      files.length = 0;
      // 只列出本模块真能读的后缀。
      // ⚠️ 2026-11-09 修：以前 opts.exts 只用于「选择文件…」系统对话框的过滤，
      // 列表本身按后端 DATA_EXTS（csv/txt/xlsx/xls/json/dat/tsv）全列出来。
      // 于是表面吸附工具会把 数据处理.xlsx 也列出来，点一下却报
      // 「导入失败：不是 CSV/TXT 文件」——列表里出现了点不动的文件。
      // 双液系工具同理（列 3 个，其中 2 个 xlsx 用不上）。
      all.forEach((f) => { if (_allowed(f, opts.exts)) files.push(f); });
      if (j.dir) dir = j.dir;
      if (j.error && opts.onError) opts.onError(j.error);
      paint();
      return j;
    }

    return {
      load: reload,
      /** 重新读一遍当前目录（用户往文件夹里放了新文件之后用）。 */
      async refresh() { return reload(dir); },
      setValue(rel) { value = rel || ''; paint(); },
      getValue() { return value; },
      search(query) { return search(files, query, MAX_RENDER); },
      get files() { return files.slice(); },
      get dir() { return dir; },
    };
  }

  global.PcalFiles = {
    pickFolder: pickFolder,
    pickFile: pickFile,
    index: index,
    search: search,
    mount: mount,
  };
}(window));
