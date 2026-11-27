# -*- coding: utf-8 -*-
"""11 个实验模块的基准数据与报告生成入口。

每个 case 都尽量走服务器真实的装载路径：
  · 自带示例数据的模块直接用 kernel.sample_data()
  · 有默认数据目录的模块用 default_config()（电导率/电化学/紫外）
  · 燃烧热/溶解热按服务器的方式解析 CSV，并保留 .path（报告要找课程软件 PNG）
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from support import FIXTURES, REPO_ROOT, load_module

PROFILE = {
    'student_name': '测试同学',
    'student_id': '2300000000',
    'group': '3',
    'group_no': '8',
    'date': '2026-10-24',
    'room_temp': 22.0,
    'pressure': 101.3,
}


@dataclass
class ModuleCase:
    label: str
    tool: str
    an: object
    cfg: dict


def template_for(tool):
    candidates = [
        p for p in glob.glob(str(REPO_ROOT / tool / 'templates' / '*.docx'))
        if '2026' in os.path.basename(p) and '未裁剪' not in p
    ]
    if not candidates:
        raise FileNotFoundError('%s/templates 下没有 2026 模板' % tool)
    return sorted(candidates)[0]


def _cfg(tool):
    cfg = load_module(tool, 'analysis').default_config()
    cfg.update(PROFILE)
    return cfg


def _sample(tool, kernel):
    cfg = _cfg(tool)
    an = load_module(tool, kernel).analyze(
        load_module(tool, kernel).sample_data(), cfg)
    return ModuleCase(tool.replace('工具', ''), tool, an, cfg)


def _magnetic():
    tool = '磁化率工具'
    cfg = dict(PROFILE, room_temp=22.5)
    an = load_module(tool, 'analysis').run_analysis(
        load_module(tool, 'magnetic').sample_data())
    return ModuleCase('磁化率', tool, an, cfg)


def _conductivity():
    tool = '电导率工具'
    cfg = _cfg(tool)
    # 数据目录指向随仓库走的 fixtures（7 号仪器的真实读数），
    # 不再依赖仓库外那份手记数据 —— 否则新 clone 上数值基准会静默降级。
    cfg['data_dir'] = str(FIXTURES / '电导率')
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('电导率', tool, an, cfg)


def _echem():
    tool = '电化学工具'
    cfg = _cfg(tool)
    # 同 _uv：数据目录指向 fixtures，别依赖仓库外的 `物理化学实验/…/电化学/`。
    cfg['data_dir'] = str(FIXTURES / '电化学')
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('电化学', tool, an, cfg)


def _uv():
    tool = '紫外光谱工具'
    cfg = _cfg(tool)
    # 数据目录指向随仓库走的 fixtures，不再依赖仓库外的原始数据目录。
    # 槽位是按文件名匹配的，fixtures 里保留了 `1/ 2/ 3/ 4/` 子目录原名。
    cfg['data_dir'] = str(FIXTURES / '紫外光谱')
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('紫外', tool, an, cfg)


def _combustion():
    tool = '燃烧热工具'
    cb = load_module(tool, 'combustion')
    analysis = load_module(tool, 'analysis')
    cfg = analysis.default_config()
    cfg.update(PROFILE, pressure_kPa=101.3, temperature_C=27.1,
               water_volume_mL=3000)
    base = FIXTURES / '燃烧热'
    cfg['rounds'] = [
        {'role': 'standard', 'name': '苯甲酸', 'substance': 'benzoic',
         'file': str(base / '苯甲酸.csv')},
        {'role': 'sample', 'name': '方糖', 'substance': 'sucrose',
         'file': str(base / '方糖.csv')},
    ]
    datasets = {}
    for r in cfg['rounds']:
        with open(r['file'], encoding='utf-8-sig', errors='replace') as fh:
            datasets[r['file']] = cb.parse_combustion_csv(fh.read(), r['name'])
    an = analysis.Analysis(cfg)
    an.run(datasets)
    return ModuleCase('燃烧热', tool, an, cfg)


def _dissolution():
    tool = '溶解热工具'
    ds = load_module(tool, 'dissolution')
    analysis = load_module(tool, 'analysis')
    cfg = analysis.default_config()
    cfg.update(PROFILE, pressure_kPa=101.3, water_volume_mL=500,
               solute='kno3')
    base = FIXTURES / '溶解热'
    files = sorted(str(p) for p in base.glob('*dissolutiondata-*.csv'))
    cfg['rounds'] = [{'file': f, 'name': os.path.basename(f)} for f in files]
    loaders = {}
    for f in files:
        with open(f, encoding='utf-8-sig', errors='replace') as fh:
            data = ds.parse_dissolution_csv(fh.read(), os.path.basename(f))
        data.path = f          # 服务器 load_rounds 会设置，报告靠它找课程软件 PNG
        loaders[f] = data
    an = analysis.Analysis(cfg)
    an.run(loaders)
    return ModuleCase('溶解热', tool, an, cfg)


BUILDERS = (
    ('化学动力学', lambda: _sample('化学动力学工具', 'kinetics')),
    ('蒸气压', lambda: _sample('蒸气压工具', 'vapor')),
    ('双液系', lambda: _sample('双液系工具', 'phase')),
    ('偶极矩', lambda: _sample('偶极矩工具', 'dipole')),
    ('表面吸附', lambda: _sample('表面吸附工具', 'adsorption')),
    ('磁化率', _magnetic),
    ('电导率', _conductivity),
    ('电化学', _echem),
    ('紫外', _uv),
    ('燃烧热', _combustion),
    ('溶解热', _dissolution),
)


def build_cases():
    cases, errors = {}, {}
    for label, build in BUILDERS:
        try:
            case = build()
            cases[case.label] = case
        except Exception as exc:                     # noqa: BLE001
            errors[label] = exc
    return cases, errors


def _report_cache_key(case):
    """报告产物的**内容寻址**键：任何会影响 docx 的东西变了，键就变。

    为什么需要：`test_modules`（结构审计）与 `test_italic`（正斜体检查）
    都要把 11 份报告完整生成一遍，合计重复 27 s（实测单份约 2.5 s × 22 份）。
    在 8 并发下这 27 s 是实打实的 CPU 争用，直接体现在墙钟上。

    ⚠ 缓存**必须**是内容寻址的，不能用「上次生成过就复用」这种时间戳方案。
    这个项目有过两次「检查器假绿」的教训（check_italic v1、check_source_symbols
    第一版），缓存一旦过期就会让改了代码却仍拿旧产物去审计，是同一类错误的
    放大版。所以这里把**所有输入**都并进键里：

      · 该工具 pcal/ 下全部 .py（report.py 改了 → 键变）
      · 模板 .docx 的字节（模板改了 → 键变）
      · tests/fixtures/ 全部文件（数据改了 → 键变）
      · 该 case 的 cfg（姓名/温度/组别等进了封面的项）
      · Python 版本（不同解释器下 docx 序列化可能有差异）

    fixtures 是全量并入的，比「只并入本工具用到的那几个」保守——极端情况下
    会多算几次缓存，但绝不会漏掉影响产物的输入。宁可慢，不可假绿。
    """
    import hashlib

    h = hashlib.sha256()
    h.update(case.tool.encode('utf-8'))
    h.update(case.cfg.__repr__().encode('utf-8'))
    h.update(sys.version.encode('utf-8'))

    pkg = REPO_ROOT / case.tool / 'pcal'
    for p in sorted(pkg.glob('*.py')):
        h.update(p.name.encode('utf-8'))
        h.update(p.read_bytes())
    # 同包的子目录（部分模块有 pcal/assets 之类）也一并纳入
    for p in sorted(pkg.rglob('*')):
        if p.is_file() and p.suffix != '.pyc':
            h.update(str(p.relative_to(pkg)).encode('utf-8'))
            h.update(p.read_bytes())

    h.update(Path(template_for(case.tool)).read_bytes())

    for p in sorted(FIXTURES.rglob('*')):
        if p.is_file():
            h.update(str(p.relative_to(FIXTURES)).encode('utf-8'))
            h.update(p.read_bytes())

    return h.hexdigest()[:20]


def _cache_root():
    """缓存目录：系统临时目录下，跨进程可见（`test_modules` 与 `test_italic`
    是两个进程，所以不能放在进程内字典里）。

    ``PCAL_TEST_NOCACHE=1`` 可关闭（排查缓存本身的问题时用）。
    """
    import tempfile
    root = Path(tempfile.gettempdir()) / 'pcal-test-reports'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _prune_cache(root, keep=40):
    """只保留最近用过的若干份，避免缓存目录无限膨胀。

    ⚠ 三条必须遵守（都是并发下的真实风险）：

    1. **不能删 ``build_*`` 临时目录** —— 那是别的进程正在构建的工作区，
       删了会让它 rename 失败。
    2. **不能删当前进程刚用的那份** —— 它可能正被 audit 打开着。
    3. 按内容寻址的目录天然可以随时删：删了只是下次重算，不会出错。
    """
    try:
        entries = [p for p in root.iterdir()
                   if p.is_dir() and not p.name.startswith('build_')]
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in entries[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def generate_report(case, out_dir=None):
    """生成（或复用内容缓存里的）报告 docx，返回其路径。

    ⚠ 返回的路径**不一定**在 ``out_dir`` 下（缓存命中时在临时目录里）。
    调用方只应该拿它去 audit / check 读，不要假设它位于某个具体目录。

    ``PCAL_TEST_NOCACHE=1`` 关闭缓存（排查缓存本身的问题时用）。

    ## 并发安全的两次踩坑（都写在这里，别再犯）

    **坑 1：临时目录名不能用缓存键。** 一开始写成 ``root/<key>.tmp``，
    于是「两个进程同时要同一份报告」会**共用同一个临时目录**：A 写
    report.docx、B 也在写，B 还在往 ``figures/`` 里画图时 A 已经在 rename，
    拿到的 docx 里图片路径指向已被移走的目录 → 报告里图号从 1 跳到 3
    （实测：磁化率报告的 ``caption.gap 图编号不连续：1 → 3``，且文件只有
    464 KB 而非 529 KB）。现在每次构建都用 ``mkdtemp`` 的**唯一**目录。

    **坑 2：最后一步 rename 必须容忍「别人先建好了」。** 两个进程都算完并
    各自 rename 时，后一个的 ``os.replace`` 会覆盖前一个——两份内容相同，
    覆盖本身无害，但若前一个刚被另一个进程打开读取就会失败。这里改成
    「已存在就丢弃自己的」，谁先落地用谁的。
    """
    if os.environ.get('PCAL_TEST_NOCACHE') == '1':
        return _build_into(case, out_dir or tempfile.mkdtemp(prefix='pcalrpt_'))

    root = _cache_root()
    key = _report_cache_key(case)
    target = root / key
    cached = target / 'report.docx'
    if cached.is_file() and cached.stat().st_size > 0:
        try:
            os.utime(cached, None)      # 触碰 mtime，prune 才知道它在用
        except OSError:
            pass
        return cached

    # 唯一临时目录：绝不与别的进程共用（坑 1）
    tmp = Path(tempfile.mkdtemp(prefix='build_', dir=str(root)))
    try:
        _build_into(case, tmp)
        if target.exists():
            # 别人先建好了（内容相同，因为键一样）——用它的，丢掉自己的（坑 2）
            return target / 'report.docx'
        try:
            os.replace(str(tmp), str(target))
        except OSError:
            # rename 失败（Windows 上目标已存在、或被占用）：退回用自己这份
            if (target / 'report.docx').is_file():
                return target / 'report.docx'
            raise
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    _prune_cache(root)
    return target / 'report.docx'


def _build_into(case, out_dir):
    """真正调 build_report 的那一层（不含缓存逻辑）。"""
    rpt = load_module(case.tool, 'report')
    out = Path(out_dir) / 'report.docx'
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rpt.build_report(case.an, case.cfg, str(out),
                     str(Path(out_dir) / 'figures'), template_for(case.tool))
    return out
