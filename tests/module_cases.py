# -*- coding: utf-8 -*-
"""11 个实验模块的基准数据与报告生成入口。

每个 case 都尽量走服务器真实的装载路径：
  · 自带示例数据的模块直接用 kernel.sample_data()
  · 有默认数据目录的模块用 default_config()（电导率/电化学/紫外）
  · 燃烧热/溶解热按服务器的方式解析 CSV，并保留 .path（报告要找课程软件 PNG）
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from pathlib import Path

from support import REPO_ROOT, load_module

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
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('电导率', tool, an, cfg)


def _echem():
    tool = '电化学工具'
    cfg = _cfg(tool)
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('电化学', tool, an, cfg)


def _uv():
    tool = '紫外光谱工具'
    cfg = _cfg(tool)
    an = load_module(tool, 'analysis').Analysis(cfg).run()
    return ModuleCase('紫外', tool, an, cfg)


def _combustion():
    tool = '燃烧热工具'
    cb = load_module(tool, 'combustion')
    analysis = load_module(tool, 'analysis')
    cfg = analysis.default_config()
    cfg.update(PROFILE, pressure_kPa=101.3, temperature_C=27.1,
               water_volume_mL=3000)
    base = REPO_ROOT / '1 燃烧热'
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
    base = REPO_ROOT / '2 溶解热'
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


def generate_report(case, out_dir):
    rpt = load_module(case.tool, 'report')
    out = Path(out_dir) / 'report.docx'
    rpt.build_report(case.an, case.cfg, str(out),
                     str(Path(out_dir) / 'figures'), template_for(case.tool))
    return out
