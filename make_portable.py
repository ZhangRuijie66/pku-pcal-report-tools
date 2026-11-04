# -*- coding: utf-8 -*-
"""打可移植版 zip：把 11 个工具 + 入口 + 核心件 + 启动器打成一个绿色包。

    python make_portable.py                # 输出到 发布/物化实验报告工具-可移植版.zip
    python make_portable.py --out D:/x.zip
    python make_portable.py --no-zip       # 只准备 staging 目录，方便先检查

包内结构（解压到任意位置，双击根目录 启动入口.cmd 即可）：

    启动入口.cmd / 停止服务.cmd / 安装依赖.cmd
    _tools/      无黑框启动器（hidden-launch.vbs + launcher.py + 图标）
    _core/       canonical 核心件（各工具 pcal/ 里已有副本，这里只是留档）
    requirements.txt
    物化实验报告工具/  ← 入口页（按哪个子目录有 portal.py 来定位）
    燃烧热工具/ … 紫外光谱工具/   ← 11 个模块

不进包：settings.json（使用者个人信息）、profile.json、data/*.json（本机数据）、
__pycache__、输出目录、发布目录、实验报告输出、原始数据目录、高斯计算工具
（它是另一个仓库、依赖 rdkit/paramiko 体积很大，单独发）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / '发布'
DEFAULT_OUT = DIST / '物化实验报告工具-可移植版.zip'

# 11 个实验模块（顺序 = 讲义实验顺序，与 portal.MODULES 一致）
TOOLS = (
    '燃烧热工具', '溶解热工具', '蒸气压工具', '双液系工具', '化学动力学工具',
    '表面吸附工具', '电导率工具', '电化学工具', '偶极矩工具', '磁化率工具',
    '紫外光谱工具',
)
PORTAL = '物化实验报告工具'

# 打包时排除的文件/目录名（任意层级）
EXCLUDE_NAMES = {
    '__pycache__', '.pytest_cache', 'settings.json', 'profile.json',
    '输出', '_test_out', '发布', '实验报告输出', '.git', '.vscode',
    '高斯计算工具', 'backups',
}
EXCLUDE_SUFFIX = {'.pyc', '.pyo', '.bak', '.zip', '.log'}
# 本机录入数据：各工具的 data/ 目录整个不进包
EXCLUDE_REL = {'data'}

# 根目录要带上的文件
ROOT_FILES = (
    ('启动入口.cmd', '启动入口.cmd'),
    ('启动入口.vbs', '启动入口.vbs'),
    ('停止服务.vbs', '停止服务.vbs'),
    ('安装依赖.cmd', '安装依赖.cmd'),
    ('requirements.txt', 'requirements.txt'),
    ('README.md', '使用说明.md'),
    ('LICENSE', 'LICENSE'),
)
ROOT_DIRS = ('_core', '_tools')


def skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    # 文件名或任意一级目录名命中排除表
    if any(part in EXCLUDE_NAMES for part in rel.parts):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIX:
        return True
    # 任意层级的 data/ 目录（本机录入数据）
    if any(part in EXCLUDE_REL for part in rel.parts[:-1]):
        return True
    return False


def copy_tree(src: Path, dst: Path, root: Path) -> int:
    n = 0
    for item in src.rglob('*'):
        if item.is_dir():
            continue
        if skip(item, root):
            continue
        target = dst / item.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        n += 1
    return n


def _rmtree(path: Path) -> None:
    """清空 staging 目录；个别文件被占用（资源管理器预览/杀软扫描）时重试几次。"""
    if not path.exists():
        return

    def onerror(func, p, exc_info):
        for _ in range(5):
            time.sleep(0.4)
            try:
                os.chmod(p, 0o666)
                func(p)
                return
            except OSError:
                continue
        raise exc_info[1]

    shutil.rmtree(path, onerror=onerror)


def stage(target: Path) -> int:
    _rmtree(target)
    target.mkdir(parents=True)

    count = 0
    # 1) 11 个模块 + 入口
    for name in TOOLS + (PORTAL,):
        src = ROOT / name
        if not src.is_dir():
            raise SystemExit('缺少模块目录：%s' % src)
        count += copy_tree(src, target / name, src)
        print('  %-14s %d 个文件' % (name, sum(1 for _ in (target / name).rglob('*')
                                             if _.is_file())))

    # 2) 核心件与启动器（canonical 留档，模块里已有副本）
    for name in ROOT_DIRS:
        src = ROOT / name
        if not src.is_dir():
            continue
        n = copy_tree(src, target / name, src)
        count += n
        print('  %-14s %d 个文件' % (name, n))

    # 3) 根目录文件
    for src_name, dst_name in ROOT_FILES:
        src = ROOT / src_name
        if src.exists():
            shutil.copy2(src, target / dst_name)
            count += 1
    print('  根目录文件     %d 个' % sum(1 for s, _ in ROOT_FILES if (ROOT / s).exists()))

    # 4) 追加一节「可移植版说明」
    usage = target / '使用说明.md'
    if usage.exists():
        with open(usage, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\n\n---\n\n## 可移植版说明\n\n'
                     '本包由 `make_portable.py` 生成于 %s。\n\n'
                     '- 解压到**任意位置**，双击根目录的 `启动入口.cmd` 即可；\n'
                     '- 首次运行会自动装依赖（`安装依赖.cmd`，走清华源）；\n'
                     '- 停止：双击 `停止服务.vbs`，或在入口页点「停止全部服务」；\n'
                     '- 报告输出在 `实验报告输出/<学号>-<姓名>-<实验名>/`；\n'
                     '- 各工具的 `data/`、`settings.json`、`profile.json` '
                     '**没有打进包**（那是使用者自己的数据），首次打开会重新生成。\n'
                     % time.strftime('%Y-%m-%d %H:%M'))
    return count


def make_zip(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in sorted(src.rglob('*')):
            if item.is_file():
                z.write(item, item.relative_to(src).as_posix())
    print('\n已打包：%s（%.1f MB，%d 个文件）'
          % (out, out.stat().st_size / 1e6,
             sum(1 for _ in src.rglob('*') if _.is_file())))


def main(argv=None):
    ap = argparse.ArgumentParser(description='打物化实验报告工具的可移植版 zip')
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='输出 zip 路径')
    ap.add_argument('--stage', default=str(DIST / '_stage_portable'),
                    help='staging 目录（会被清空重建）')
    ap.add_argument('--no-zip', action='store_true', help='只准备 staging，不打 zip')
    args = ap.parse_args(argv)

    stage_dir = Path(args.stage)
    print('准备 staging：%s' % stage_dir)
    n = stage(stage_dir)
    print('  共 %d 个文件' % n)

    if not args.no_zip:
        make_zip(stage_dir, Path(args.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
