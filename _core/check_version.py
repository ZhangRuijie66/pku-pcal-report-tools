# -*- coding: utf-8 -*-
"""版本号一致性自检 —— `python _core/check_version.py`。

口径见 `_tmp_update/CONTRACT.md` 的 B 节：整套工具一个版本号，真源
`_core/version.py`；每版一份 `更新日志/CHANGELOG_v<X>_<Y>_<Z>.md`；
11 个工具的 `pcal/version.py` 是同步副本、`pcal/__init__.py` 的
`__version__` 引用 `pcal/version.py`。这里把「版本号有没有漏改/回退」全部查一遍。

输出约定（控制台可能是 GBK，GBK 里没有 ✓/⚠/✗）：

* 先探测 stdout 编码，能编码才用 ✓/⚠/✗，否则退回 `[OK]`/`[WARN]`/`[FAIL]`；
* 有任何 fail → 退出码 1；只有 ok/warn → 退出码 0。

对外接口（`tests/test_version.py` 复用）：

    CHECKS: list[callable]                     # 每个 check 接受 root，返回 (level, title, detail)
    run_checks(root=None) -> list[tuple[str, str, str]]   # level ∈ 'ok'|'warn'|'fail'
    main(argv=None) -> int                     # 打印结果，有 fail 返回 1
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_FALLBACK = os.path.dirname(HERE)

CHANGELOG_DIR = '更新日志'
VERSION_SOURCE = 'version.py'
INIT_NAME = '__init__.py'
# 契约里列举的「不许残留旧版本号」的文件（相对安装根）
SCAN_TARGETS = (
    '物化实验报告工具/portal.py',
    '_tools/launcher.py',
    'README.md',
    'make_portable.py',
)

# 本地兜底的工具清单（与 _core/sync_core.py 的 TOOLS 一致；优先用后者）
TOOLS_FALLBACK = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)

_APP_VERSION_RE = re.compile(r"^[ \t]*APP_VERSION[ \t]*=[ \t]*['\"]([^'\"]*)['\"]", re.M)
_RELEASE_DATE_RE = re.compile(r"^[ \t]*RELEASE_DATE[ \t]*=[ \t]*['\"]([^'\"]*)['\"]", re.M)
_SEMVER_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
_DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
_CHANGELOG_NAME_RE = re.compile(r'^CHANGELOG_v(\d+)_(\d+)_(\d+)\.md$')
_CHANGELOG_HEAD_RE = re.compile(r'^#\s*[vV]\s*(\d+)\.(\d+)\.(\d+)\s*$')
_ANY_SEMVER_RE = re.compile(r'(?<![\d.])(\d+)\.(\d+)\.(\d+)(?![\d.])')
# CHANGELOG 里的「类型」一行可能写成 `- **类型**：功能`（Markdown 加粗）
_CHANGELOG_TYPE_RE = re.compile(r'类型\s*[*_`]*\s*[:：]')
_VERSION_IMPORT_RE = re.compile(
    r'^[ \t]*from[ \t]+\.version[ \t]+import[ \t]+APP_VERSION[ \t]+as[ \t]+__version__'
    r'[ \t]*$', re.M)

_SYNC_CORE_CACHE = {}


# ---------------------------------------------------------------- 基础工具
def _root_of(root):
    return os.path.abspath(root or ROOT_FALLBACK)


def normalized_bytes(data):
    """忽略 CRLF/LF 差异后的字节（与 sync_core.digest 的归一化一致）。"""
    return data.replace(b'\r\n', b'\n')


def digest_of(path):
    """文件内容的 sha256（忽略 CRLF/LF）；读不到返回 None。"""
    try:
        with open(path, 'rb') as fh:
            return hashlib.sha256(normalized_bytes(fh.read())).hexdigest()
    except OSError:
        return None


def read_text(path):
    """按 UTF-8 读文本（坏字节替换），读不到返回 None。"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def _load_sync_core(root):
    """载入 `<root>/_core/sync_core.py` 以复用它的 TOOLS；失败返回 None。"""
    root = _root_of(root)
    if root in _SYNC_CORE_CACHE:
        return _SYNC_CORE_CACHE[root]
    path = os.path.join(root, '_core', 'sync_core.py')
    module = None
    if os.path.isfile(path):
        name = '_cv_sync_core_%s' % hashlib.md5(root.encode('utf-8')).hexdigest()[:10]
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
        except Exception:                        # noqa: BLE001  自检不许因载入失败中断
            module = None
    _SYNC_CORE_CACHE[root] = module
    return module


def tools_for(root):
    """11 个工具目录名：优先取 `_core/sync_core.py` 的 TOOLS。"""
    module = _load_sync_core(root)
    tools = getattr(module, 'TOOLS', None) if module is not None else None
    if isinstance(tools, (list, tuple)) and tools:
        return tuple(str(t) for t in tools)
    return TOOLS_FALLBACK


def _fmt(parts):
    return '%d.%d.%d' % tuple(parts)


def changelog_relpath(parts):
    major, minor, patch = tuple(parts)
    return '%s/CHANGELOG_v%d_%d_%d.md' % (CHANGELOG_DIR, major, minor, patch)


def read_declared_version(root=None):
    """从 `<root>/_core/version.py` 文本解析 APP_VERSION 与 RELEASE_DATE（不 import）。"""
    root = _root_of(root)
    path = os.path.join(root, '_core', VERSION_SOURCE)
    text = read_text(path)
    if text is None:
        return {'text': None, 'version': '', 'date': '', 'path': path}
    mv = _APP_VERSION_RE.search(text)
    md = _RELEASE_DATE_RE.search(text)
    return {
        'text': text,
        'version': mv.group(1).strip() if mv else '',
        'date': md.group(1).strip() if md else '',
        'path': path,
    }


def current_version(root=None):
    """当前 APP_VERSION 的三段式元组；解析不了返回 None。"""
    match = _SEMVER_RE.match(read_declared_version(root)['version'] or '')
    return tuple(int(g) for g in match.groups()) if match else None


def published_versions(root=None):
    """`更新日志/` 里出现过的版本号：{'X.Y.Z': [来源, …]}（文件名或首行都算）。"""
    base = os.path.join(_root_of(root), CHANGELOG_DIR)
    out = {}
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        path = os.path.join(base, name)
        if not os.path.isfile(path):
            continue
        match = _CHANGELOG_NAME_RE.match(name)
        if match:
            out.setdefault(_fmt(int(g) for g in match.groups()), []).append(name)
        text = read_text(path) or ''
        for line in text.splitlines():
            if not line.strip():
                continue
            head = _CHANGELOG_HEAD_RE.match(line.strip())
            if head:
                version = _fmt(int(g) for g in head.groups())
                sources = out.setdefault(version, [])
                if name not in sources:          # 文件名与首行同源时只记一次
                    sources.append(name + ' 首行')
            break                                # 只看第一行非空内容
    return out


def init_version_state(path):
    """读 `pcal/__init__.py` 的 `__version__`（AST 解析赋值/导入）。

    返回 `(形式, 值, 说明)`：形式 ∈ {'import', 'literal', 'expression', None}。
    `import` 表示 `from .version import APP_VERSION as __version__`，
    真正的值要到同目录的 version.py 里取，由调用方补。
    """
    text = read_text(path)
    if text is None:
        return None, '', '读不出 pcal/__init__.py'
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return None, '', 'pcal/__init__.py 语法错误：%s' % exc
    for node in tree.body:
        value_node = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == '__version__'
                   for t in node.targets):
                value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == '__version__':
                value_node = node.value
        elif isinstance(node, ast.ImportFrom):
            if (node.level or 0) >= 1 and (node.module or '') in ('version',):
                for alias in node.names:
                    if alias.asname == '__version__':
                        return 'import', alias.name, ''
            continue
        if value_node is None:
            continue
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            return 'literal', value_node.value, ''
        try:
            shown = ast.unparse(value_node)
        except (AttributeError, ValueError):
            shown = type(value_node).__name__
        return 'expression', shown, ''
    if _VERSION_IMPORT_RE.search(text.replace('\r\n', '\n')):
        return 'import', 'APP_VERSION', ''
    return None, '', '没有 __version__'


def tool_declared_version(root, tool):
    """某个工具 `pcal/version.py` 里的 APP_VERSION（正则，不 import）。"""
    path = os.path.join(_root_of(root), tool, 'pcal', VERSION_SOURCE)
    text = read_text(path)
    if text is None:
        return ''
    match = _APP_VERSION_RE.search(text)
    return match.group(1).strip() if match else ''


# ---------------------------------------------------------------- 各检查项
def check_version_source(root=None):
    """1. 能从 _core/version.py 文本解析出三段式 APP_VERSION 与 YYYY-MM-DD 的 RELEASE_DATE。"""
    info = read_declared_version(root)
    if info['text'] is None:
        return 'fail', '版本真源', '读不出 _core/version.py（%s）' % info['path']
    problems = []
    version = info['version']
    if not version:
        problems.append('缺少 APP_VERSION')
    elif not _SEMVER_RE.match(version):
        problems.append('APP_VERSION %r 不是三段式 X.Y.Z' % version)
    date = info['date']
    date_match = _DATE_RE.match(date or '')
    if not date:
        problems.append('缺少 RELEASE_DATE')
    elif not date_match:
        problems.append('RELEASE_DATE %r 不是 YYYY-MM-DD' % date)
    else:
        month, day = int(date_match.group(2)), int(date_match.group(3))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            problems.append('RELEASE_DATE %r 不是合法日期' % date)
    if problems:
        return 'fail', '版本真源', '；'.join(problems)
    return 'ok', '版本真源', 'v%s（%s），来自 _core/%s' % (
        version, date, VERSION_SOURCE)


def check_changelog_exists(root=None):
    """2. 更新日志/CHANGELOG_v<X>_<Y>_<Z>.md 必须存在。"""
    parts = current_version(root)
    if parts is None:
        return 'fail', '更新日志存在性', 'APP_VERSION 不可用，无法定位更新日志'
    rel = changelog_relpath(parts)
    path = os.path.join(_root_of(root), *rel.split('/'))
    if not os.path.isfile(path):
        return 'fail', '更新日志存在性', '缺少 %s（v%s 的发版说明）' % (rel, _fmt(parts))
    return 'ok', '更新日志存在性', '有 %s' % rel


def check_no_future_changelog(root=None):
    """3. 更新日志目录里不许有比当前 APP_VERSION 更高的版本（版本回退/漏改检测）。"""
    cur = current_version(root)
    if cur is None:
        return 'fail', '版本回退检测', 'APP_VERSION 不可用，无法比较版本高低'
    versions = published_versions(root)
    if not versions:
        return 'warn', '版本回退检测', '更新日志目录里没有可识别的版本号'
    higher = []
    for text, sources in versions.items():
        match = _SEMVER_RE.match(text)
        if not match:
            continue
        if tuple(int(g) for g in match.groups()) > cur:
            higher.append('v%s（%s）' % (text, '、'.join(sorted(set(sources)))))
    if higher:
        return 'fail', '版本回退检测', '更新日志里有比当前 v%s 更高的版本：%s' % (
            _fmt(cur), '、'.join(higher))
    return 'ok', '版本回退检测', '%d 份更新日志都不高于 v%s' % (len(versions), _fmt(cur))


def check_tool_version_copies(root=None):
    """4. 11 个工具的 pcal/version.py 必须与 _core/version.py 逐字节一致（忽略 CRLF）。"""
    root = _root_of(root)
    want = digest_of(os.path.join(root, '_core', VERSION_SOURCE))
    if want is None:
        return 'fail', '工具版本副本', '读不出 _core/version.py，无法比对'
    bad = []
    for tool in tools_for(root):
        got = digest_of(os.path.join(root, tool, 'pcal', VERSION_SOURCE))
        if got is None:
            bad.append('%s 缺少 pcal/%s' % (tool, VERSION_SOURCE))
        elif got != want:
            bad.append('%s/pcal/%s 与真源不同' % (tool, VERSION_SOURCE))
    if bad:
        return 'fail', '工具版本副本', (
            '%d 个工具不同步：%s（运行 `python _core/sync_core.py --apply` 同步）'
            % (len(bad), '；'.join(bad)))
    return 'ok', '工具版本副本', '%d 个工具的 pcal/%s 与真源一致' % (
        len(tools_for(root)), VERSION_SOURCE)


def check_tool_init_version(root=None):
    """5. 11 个工具的 pcal/__init__.py 必须有 __version__ 且等于 APP_VERSION。"""
    root = _root_of(root)
    app_version = read_declared_version(root)['version'].strip()
    if not app_version:
        return 'fail', '工具 __version__', 'APP_VERSION 不可用，无法比对'
    tools = tools_for(root)
    bad = []
    for tool in tools:
        form, value, why = init_version_state(
            os.path.join(root, tool, 'pcal', INIT_NAME))
        if form is None:
            bad.append('%s：%s' % (tool, why or '没有 __version__'))
        elif form == 'import':
            effective = tool_declared_version(root, tool)
            if not effective:
                bad.append('%s：__version__ 引用 pcal/version.py，'
                           '但那里读不到 APP_VERSION' % tool)
            elif effective != app_version:
                bad.append('%s：经 version.py 得到 %s，真源是 %s'
                           % (tool, effective, app_version))
        elif form == 'expression':
            bad.append('%s：__version__ 是表达式 %r，不是字面值或真源引用'
                       % (tool, value))
        elif value != app_version:
            bad.append('%s：__version__ = %r，真源是 %s' % (tool, value, app_version))
    if bad:
        return 'fail', '工具 __version__', '%d 个工具不对：%s' % (
            len(bad), '；'.join(bad))
    return 'ok', '工具 __version__', '%d 个工具的 __version__ 都等于 %s' % (
        len(tools), app_version)


def check_no_stale_version_strings(root=None):
    """6. portal.py / launcher.py / README.md / make_portable.py 不许残留旧的已发布版本号。"""
    root = _root_of(root)
    cur = current_version(root)
    if cur is None:
        return 'fail', '旧版本号残留', 'APP_VERSION 不可用，无法判断哪个版本是旧的'
    current = _fmt(cur)
    published = set(published_versions(root))
    stale, missing = [], []
    checked = 0
    for rel in SCAN_TARGETS:
        text = read_text(os.path.join(root, *rel.split('/')))
        if text is None:
            missing.append(rel)
            continue
        checked += 1
        for match in _ANY_SEMVER_RE.finditer(text):
            version = _fmt(int(g) for g in match.groups())
            if version == current or version not in published:
                continue                       # 1.1 版本库号、3.10 python 版本之类
            line_no = text.count('\n', 0, match.start()) + 1
            stale.append('%s:%d 出现 v%s' % (rel, line_no, version))
    if stale:
        return 'fail', '旧版本号残留', '%d 处：%s' % (len(stale), '；'.join(stale))
    if not checked:
        return 'fail', '旧版本号残留', '待扫描文件都不存在：%s' % '、'.join(missing)
    if missing:
        return 'warn', '旧版本号残留', '%d 个文件里没有旧版本号；但缺少文件：%s' % (
            checked, '、'.join(missing))
    return 'ok', '旧版本号残留', '%d 个文件里没有旧版本号' % checked


def check_changelog_content(root=None):
    """7. 当前 CHANGELOG 首行必须是 `# v<cur>`，正文必须有「类型：」字样。"""
    parts = current_version(root)
    if parts is None:
        return 'fail', '更新日志内容', 'APP_VERSION 不可用，无法定位更新日志'
    version = _fmt(parts)
    rel = changelog_relpath(parts)
    text = read_text(os.path.join(_root_of(root), *rel.split('/')))
    if text is None:
        return 'fail', '更新日志内容', '缺少 %s' % rel
    first = ''
    for line in text.splitlines():
        if line.strip():
            first = line.strip()
            break
    problems = []
    head = _CHANGELOG_HEAD_RE.match(first)
    if not head:
        problems.append('首行不是「# vX.Y.Z」形式：%r'
                        % (first[:60] or '（空文件）'))
    elif _fmt(int(g) for g in head.groups()) != version:
        problems.append('首行写的是 v%s，与 APP_VERSION v%s 不同'
                        % (_fmt(int(g) for g in head.groups()), version))
    if not _CHANGELOG_TYPE_RE.search(text):
        problems.append('正文缺少「类型：」一行')
    if problems:
        return 'fail', '更新日志内容', '%s：%s' % (rel, '；'.join(problems))
    return 'ok', '更新日志内容', '%s 的首行与「类型」都在' % rel


def check_manifest(root=None):
    """8. _core/core_manifest.json 的 files 必须含 version.py 且哈希与 canonical 一致。"""
    root = _root_of(root)
    text = read_text(os.path.join(root, '_core', 'core_manifest.json'))
    if text is None:
        return 'fail', '核心清单', '读不出 _core/core_manifest.json'
    try:
        data = json.loads(text)
    except ValueError as exc:
        return 'fail', '核心清单', 'core_manifest.json 不是合法 JSON：%s' % exc
    if not isinstance(data, dict):
        return 'fail', '核心清单', 'core_manifest.json 顶层不是对象'
    files = data.get('files')
    if not isinstance(files, dict) or not files:
        return 'fail', '核心清单', 'files 为空，未记录 canonical 哈希'
    if VERSION_SOURCE not in files:
        return 'fail', '核心清单', ('files 里没有 %s（运行 `python '
                                  '_core/sync_core.py --apply` 重建清单）'
                                  % VERSION_SOURCE)
    got = digest_of(os.path.join(root, '_core', VERSION_SOURCE))
    if got is None:
        return 'fail', '核心清单', '读不出 _core/%s，无法核对哈希' % VERSION_SOURCE
    if str(files.get(VERSION_SOURCE)).strip().lower() != got:
        return 'fail', '核心清单', '%s 的哈希与清单不一致（清单 %s…，实际 %s…）' % (
            VERSION_SOURCE, str(files.get(VERSION_SOURCE))[:12], got[:12])
    mismatched, unchecked = [], []
    for name in sorted(str(k) for k in files):
        if name == VERSION_SOURCE:
            continue
        other = digest_of(os.path.join(root, '_core', name))
        if other is None:
            unchecked.append(name)
        elif str(files.get(name)).strip().lower() != other:
            mismatched.append(name)
    if mismatched:
        return 'fail', '核心清单', '这些文件的哈希与清单不一致：%s' % '、'.join(mismatched)
    detail = '%s 的哈希与清单一致（共 %d 项）' % (VERSION_SOURCE, len(files))
    if unchecked:
        return 'warn', '核心清单', detail + '；_core 里找不到：%s' % '、'.join(unchecked)
    return 'ok', '核心清单', detail


CHECKS = [
    check_version_source,
    check_changelog_exists,
    check_no_future_changelog,
    check_tool_version_copies,
    check_tool_init_version,
    check_no_stale_version_strings,
    check_changelog_content,
    check_manifest,
]


# ---------------------------------------------------------------- 运行
def _short_title(check):
    doc = (getattr(check, '__doc__', '') or '').strip().splitlines()
    return (doc[0] if doc else getattr(check, '__name__', '检查')).strip()


def run_checks(root=None):
    """跑全部检查，返回 [(level, title, detail), …]；单条检查炸了也不中断。"""
    root = _root_of(root)
    results = []
    for check in CHECKS:
        try:
            result = check(root)
        except Exception as exc:                 # noqa: BLE001  自检不许因单项异常中断
            results.append(('fail', _short_title(check), '检查时抛异常：%s' % exc))
            continue
        if (not isinstance(result, (tuple, list))) or len(result) != 3:
            results.append(('fail', _short_title(check), '返回值格式不对：%r' % (result,)))
            continue
        level, title, detail = (str(x) for x in result)
        if level not in ('ok', 'warn', 'fail'):
            level = 'fail'
        results.append((level, title, detail))
    return results


_SYMBOLS = {'ok': '✓', 'warn': '⚠', 'fail': '✗'}
_FALLBACK = {'ok': '[OK]', 'warn': '[WARN]', 'fail': '[FAIL]'}


def console_glyphs():
    """控制台能编码 ✓/⚠/✗ 就用它们，否则退回 [OK]/[WARN]/[FAIL]（GBK 兜底）。"""
    stream = sys.stdout
    encoding = getattr(stream, 'encoding', None) or ''
    if not encoding:
        return dict(_FALLBACK)
    try:
        ''.join(_SYMBOLS.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return dict(_FALLBACK)
    return dict(_SYMBOLS)


def _emit(text=''):
    """打印一行；遇到编码不下的字符就地替换，绝不因编码异常中断。"""
    stream = sys.stdout
    try:
        stream.write(text + '\n')
    except UnicodeEncodeError:
        encoding = getattr(stream, 'encoding', None) or 'utf-8'
        stream.write(text.encode(encoding, 'replace').decode(encoding, 'replace') + '\n')
    except (ValueError, OSError):                 # 控制台被关掉等情形
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description='版本号一致性检查')
    parser.add_argument('--root', help='安装根目录（默认由本文件位置推出）')
    args = parser.parse_args(argv)
    root = _root_of(args.root)

    info = read_declared_version(root)
    symbols = console_glyphs()
    _emit('版本号一致性检查：%s' % root)
    _emit('真源版本：v%s（%s）'
          % (info['version'] or '（读不出）', info['date'] or '（无日期）'))
    _emit('')
    results = run_checks(root)
    counts = {'ok': 0, 'warn': 0, 'fail': 0}
    for level, title, detail in results:
        counts[level] = counts.get(level, 0) + 1
        head = '%s %s' % (symbols.get(level, level), title)
        _emit('%s：%s' % (head, detail) if detail else head)
    _emit('')
    _emit('合计 %d 项：%d OK / %d WARN / %d FAIL'
          % (len(results), counts['ok'], counts['warn'], counts['fail']))
    if counts['fail']:
        _emit('有 %d 项不合格，请按上面的提示修正。' % counts['fail'])
        return 1
    _emit('版本号一致。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
