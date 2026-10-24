# -*- coding: utf-8 -*-
"""把 _core 里的 canonical 排版件同步到 11 个实验工具。

保留每个工具目录可独立拷走的设计：运行时仍然是各工具自己的 pcal/omml.py
与 pcal/docxkit.py，只是内容由这里统一维护。

    python _core/sync_core.py --check     # 只检查，不写文件
    python _core/sync_core.py --apply     # 同步（默认先备份旧文件）

比较时忽略 CRLF/LF 差异；写入时保留目标文件原来的行尾风格，避免整文件
因为换行符变化而出现在 git diff 里。
"""
from __future__ import annotations

import argparse
import hashlib
import json
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

FILES = (
    ('omml.py', Path('pcal') / 'omml.py'),
    ('docxkit.py', Path('pcal') / 'docxkit.py'),
    ('workspace.py', Path('pcal') / 'workspace.py'),
    ('profile.py', Path('pcal') / 'profile.py'),
)

# 需要前端草稿的 6 个手工录入模块；draft.js 由 _core/web_draft.js 同步。
WEB_TOOLS = ('化学动力学工具', '蒸气压工具', '双液系工具',
             '偶极矩工具', '表面吸附工具', '磁化率工具')
WEB_FILES = (('web_draft.js', Path('web') / 'draft.js'),)


def files_for(tool):
    return FILES + (WEB_FILES if tool in WEB_TOOLS else ())


def normalized_bytes(data: bytes) -> bytes:
    return data.replace(b'\r\n', b'\n')


def digest(path: Path) -> str:
    return hashlib.sha256(normalized_bytes(path.read_bytes())).hexdigest()


def canonical_digest(name: str) -> str:
    return digest(CORE_DIR / name)


def target_path(tool: str, rel: Path) -> Path:
    return REPO_ROOT / tool / rel


def check_tool(tool: str):
    rows = []
    for name, rel in files_for(tool):
        dst = target_path(tool, rel)
        if not dst.exists():
            rows.append((name, 'MISSING', ''))
            continue
        want, got = canonical_digest(name), digest(dst)
        rows.append((name, 'OK' if want == got else 'DIFF', got[:12]))
    return rows


def write_with_same_newline(dst: Path, src: Path):
    text = src.read_text(encoding='utf-8').replace('\r\n', '\n')
    old = dst.read_bytes() if dst.exists() else b''
    newline = '\r\n' if b'\r\n' in old else '\n'
    dst.write_bytes(text.replace('\n', newline).encode('utf-8'))


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
    return changed


def write_manifest():
    data = {
        'version': CORE_VERSION,
        'files': {name: canonical_digest(name) for name, _ in FILES},
        'web_files': {name: canonical_digest(name) for name, _ in WEB_FILES},
        'tools': list(TOOLS),
        'web_tools': list(WEB_TOOLS),
        'note': 'canonical 源在 _core/；各工具 pcal/ 是 vendored 副本。',
    }
    path = CORE_DIR / 'core_manifest.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description='同步/检查 pcal 核心排版件')
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
        for name, state, _ in check_tool(tool):
            if state == 'OK':
                print('  [ OK ] %-10s %s' % (tool, name))
            else:
                print('  [%s] %-10s %s' % (state, tool, name))
                bad += 1
    if bad:
        print('\n有 %d 个副本与 canonical 不一致；运行 --apply 同步。' % bad)
        return 1
    print('\n全部 %d 个工具与 canonical 一致。' % len(tools))
    return 0


if __name__ == '__main__':
    sys.exit(main())
