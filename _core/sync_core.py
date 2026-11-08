# -*- coding: utf-8 -*-
"""把 _core 里的 canonical 核心件与版本号同步到 11 个实验工具。

保留每个工具目录可独立拷走的设计：运行时仍然是各工具自己的 pcal/omml.py
与 pcal/docxkit.py，只是内容由这里统一维护。

除了排版件，还同步两件与版本号有关的东西：

* `_core/version.py`（唯一真源）→ 各工具的 `pcal/version.py`；
* 各工具 `pcal/__init__.py` 的 `__version__` 统一改成
  `from .version import APP_VERSION as __version__`，
  这样版本号只有一处真源，工具里不再硬编码。

    python _core/sync_core.py --check     # 只检查，不写文件
    python _core/sync_core.py --apply     # 同步（默认先备份旧文件）

比较时忽略 CRLF/LF 差异；写入时保留目标文件原来的行尾风格，避免整文件
因为换行符变化而出现在 git diff 里。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CORE_DIR.parent
CORE_VERSION = '1.0.0'

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)

VERSION_SOURCE = 'version.py'
INIT_FILE = Path('pcal') / '__init__.py'
VERSION_IMPORT = 'from .version import APP_VERSION as __version__'

FILES = (
    (VERSION_SOURCE, Path('pcal') / 'version.py'),
    ('omml.py', Path('pcal') / 'omml.py'),
    ('docxkit.py', Path('pcal') / 'docxkit.py'),
    ('sigfig.py', Path('pcal') / 'sigfig.py'),
    ('workspace.py', Path('pcal') / 'workspace.py'),
    ('profile.py', Path('pcal') / 'profile.py'),
    ('atomicio.py', Path('pcal') / 'atomicio.py'),
    # 可移植定位 + 文件选择与模糊匹配（2026-11-08）：11 个模块共用一份，
    # 保证「换机器/换文件名」的行为在所有实验里一致。
    ('dataloc.py', Path('pcal') / 'dataloc.py'),
    ('filepick.py', Path('pcal') / 'filepick.py'),
)

# 需要前端草稿的 6 个手工录入模块；draft.js 由 _core/web_draft.js 同步。
WEB_TOOLS = ('化学动力学工具', '蒸气压工具', '双液系工具',
             '偶极矩工具', '表面吸附工具', '磁化率工具')
WEB_FILES = (('web_draft.js', Path('web') / 'draft.js'),)

# 全部 11 个模块都要的文件选择/搜索前端组件（/static/files.js）。
# 启动过渡页 web_boot.html 只给入口页用，不进各模块的 web/。
WEB_FILES_ALL = (('web_files.js', Path('web') / 'files.js'),)

_ASSIGN_VERSION_RE = re.compile(r'^[ \t]*__version__[ \t]*=')
_IMPORT_VERSION_RE = re.compile(
    r'^[ \t]*from[ \t]+\.version[ \t]+import[ \t]+APP_VERSION[ \t]+as[ \t]+__version__[ \t]*$')


def files_for(tool):
    return FILES + (WEB_FILES if tool in WEB_TOOLS else ()) + WEB_FILES_ALL


def normalized_bytes(data: bytes) -> bytes:
    return data.replace(b'\r\n', b'\n')


def digest(path: Path) -> str:
    return hashlib.sha256(normalized_bytes(path.read_bytes())).hexdigest()


def canonical_digest(name: str) -> str:
    return digest(CORE_DIR / name)


def target_path(tool: str, rel: Path) -> Path:
    return REPO_ROOT / tool / rel


def canonical_app_version() -> str:
    """从 `_core/version.py` 文本里读 APP_VERSION（用正则，不 import）。"""
    try:
        text = (CORE_DIR / VERSION_SOURCE).read_text(encoding='utf-8')
    except OSError:
        return ''
    match = re.search(r"^[ \t]*APP_VERSION[ \t]*=[ \t]*['\"]([^'\"]+)['\"]",
                      text, re.M)
    return match.group(1).strip() if match else ''


# ---------------------------------------------------------------- pcal/__init__.py
def init_version_state(dst: Path):
    """各工具 `pcal/__init__.py` 里 __version__ 的状态。

    返回 `(state, 说明)`，state 取值：

    * ``OK``      —— 已经是 `from .version import APP_VERSION as __version__`；
    * ``MISSING`` —— 没有 __init__.py，或里面根本没有 __version__；
    * ``DIFF``    —— 有 __version__，但不是引用真源（硬编码或引用错东西）。
    """
    if not dst.is_file():
        return 'MISSING', '没有 pcal/__init__.py'
    try:
        text = dst.read_text(encoding='utf-8')
    except OSError as exc:
        return 'MISSING', '读不出 pcal/__init__.py：%s' % exc
    lines = text.replace('\r\n', '\n').split('\n')
    want = canonical_app_version()
    for line in lines:
        if _IMPORT_VERSION_RE.match(line):
            return 'OK', ''
    for line in lines:
        if _ASSIGN_VERSION_RE.match(line):
            value = line.split('=', 1)[1].strip().strip('\'"').strip()
            if value == want:
                return 'DIFF', '硬编码 %s，应改为 %s' % (value, VERSION_IMPORT)
            return 'DIFF', '硬编码 %r 与真源 %s 不同' % (value or '（空）', want)
    return 'MISSING', '缺少 __version__'


def _docstring_end(lines):
    """模块 docstring 结束处的 0-based 行号；没有 docstring 返回 None。"""
    try:
        tree = ast.parse('\n'.join(lines))
    except SyntaxError:
        return None
    if not tree.body:
        return None
    first = tree.body[0]
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return max(0, int(getattr(first, 'end_lineno', 1)) - 1)
    return None


def rewrite_init_text(text: str) -> str:
    """把 `pcal/__init__.py` 的 __version__ 改写成引用真源，保留 docstring 与 __all__。"""
    text = text.replace('\r\n', '\n')
    lines = text.split('\n')
    for line in lines:                      # 已经是引用形式：一个字都不动
        if _IMPORT_VERSION_RE.match(line):
            return '\n'.join(lines)
    for index, line in enumerate(lines):    # 原来是赋值：原位替换那一行
        if _ASSIGN_VERSION_RE.match(line):
            lines[index] = VERSION_IMPORT
            return '\n'.join(lines)
    # 完全没有 __version__：插在模块 docstring（或开头注释）之后
    end = _docstring_end(lines)
    if end is None:
        end = -1
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('#') or not stripped:
                end = index
                continue
            break
    insert_at = end + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines[insert_at:insert_at] = [VERSION_IMPORT, '']
    return '\n'.join(lines)


def write_text_with_same_newline(dst: Path, text: str):
    """按目标文件原有的行尾风格写回（新文件用 LF）。"""
    old = dst.read_bytes() if dst.exists() else b''
    newline = '\r\n' if b'\r\n' in old else '\n'
    dst.write_bytes(text.replace('\r\n', '\n').replace('\n', newline).encode('utf-8'))


def write_with_same_newline(dst: Path, src: Path):
    write_text_with_same_newline(dst, src.read_text(encoding='utf-8'))


def apply_init(tool: str, backup_dir: Path, backup: bool) -> bool:
    """把某个工具的 pcal/__init__.py 改写成引用真源；返回是否改动。"""
    dst = target_path(tool, INIT_FILE)
    state, _why = init_version_state(dst)
    if state == 'OK':
        return False
    old_text = dst.read_text(encoding='utf-8') if dst.is_file() else ''
    new_text = rewrite_init_text(old_text)
    if dst.is_file() and normalized_bytes(new_text.encode('utf-8')) == \
            normalized_bytes(old_text.encode('utf-8')):
        return False
    if backup and dst.is_file():
        bdst = backup_dir / tool / INIT_FILE.name
        bdst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, bdst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    write_text_with_same_newline(dst, new_text)
    return True


# ---------------------------------------------------------------- 检查 / 同步
def check_tool(tool: str):
    rows = []
    for name, rel in files_for(tool):
        dst = target_path(tool, rel)
        if not dst.exists():
            rows.append((name, 'MISSING', ''))
            continue
        want, got = canonical_digest(name), digest(dst)
        rows.append((name, 'OK' if want == got else 'DIFF', got[:12]))
    state, why = init_version_state(target_path(tool, INIT_FILE))
    rows.append((INIT_FILE.name, state, why))
    return rows


def apply_tool(tool: str, backup_dir: Path, backup: bool):
    changed = []
    for name, rel in files_for(tool):
        src = CORE_DIR / name
        dst = target_path(tool, rel)
        if dst.exists() and digest(src) == digest(dst):
            continue
        if backup and dst.exists():
            bdst = backup_dir / tool / name
            bdst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bdst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        write_with_same_newline(dst, src)
        changed.append(name)
    if apply_init(tool, backup_dir, backup):
        changed.append(INIT_FILE.name)
    return changed


def write_manifest():
    data = {
        'version': CORE_VERSION,
        'files': {name: canonical_digest(name) for name, _ in FILES},
        'web_files': {name: canonical_digest(name) for name, _ in WEB_FILES},
        'web_files_all': {name: canonical_digest(name) for name, _ in WEB_FILES_ALL},
        'tools': list(TOOLS),
        'web_tools': list(WEB_TOOLS),
        'init_import': VERSION_IMPORT,
        'note': 'canonical 源在 _core/；各工具 pcal/ 是 vendored 副本；'
                'pcal/__init__.py 的 __version__ 引用 pcal/version.py。',
    }
    path = CORE_DIR / 'core_manifest.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description='同步/检查 pcal 核心件与版本号')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='只检查（默认）')
    group.add_argument('--apply', action='store_true', help='写入各工具')
    parser.add_argument('--tool', help='只处理某一个工具目录')
    parser.add_argument('--no-backup', action='store_true', help='不备份旧文件')
    args = parser.parse_args(argv)

    tools = [args.tool] if args.tool else list(TOOLS)
    missing = [t for t in tools if not (REPO_ROOT / t).is_dir()]
    if missing:
        print('工具目录不存在：%s' % '、'.join(missing))
        return 2

    if args.apply:
        stamp = time.strftime('%Y%m%d-%H%M%S')
        backup_dir = CORE_DIR / 'backups' / stamp
        total = 0
        for tool in tools:
            changed = apply_tool(tool, backup_dir, not args.no_backup)
            if changed:
                print('  [SYNC] %-10s %s' % (tool, '、'.join(changed)))
                total += len(changed)
            else:
                print('  [ OK ] %-10s' % tool)
        path = write_manifest()
        print('\n同步完成：%d 个文件；清单 %s' % (total, path))
        if total and not args.no_backup:
            print('旧文件备份：%s' % backup_dir)

        bad = []
        for tool in tools:
            for name, state, _ in check_tool(tool):
                if state != 'OK':
                    bad.append('%s/%s=%s' % (tool, name, state))
        if bad:
            print('同步后校验失败：%s' % '、'.join(bad))
            return 1
        return 0

    bad = 0
    for tool in tools:
        for name, state, why in check_tool(tool):
            if state == 'OK':
                print('  [ OK ] %-10s %s' % (tool, name))
            else:
                print('  [%s] %-10s %s %s'
                      % (state, tool, name, ('（%s）' % why) if why else ''))
                bad += 1
    if bad:
        print('\n有 %d 处与 canonical 不一致（含 pcal/__init__.py 的 __version__）；'
              '运行 --apply 同步。' % bad)
        return 1
    print('\n全部 %d 个工具与 canonical 一致。' % len(tools))
    return 0


if __name__ == '__main__':
    sys.exit(main())
