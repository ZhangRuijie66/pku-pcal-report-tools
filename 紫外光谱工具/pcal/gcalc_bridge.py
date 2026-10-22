# -*- coding: utf-8 -*-
"""连接「高斯计算工具」：读取 TD-DFT 结果、画计算谱、并在报告里引用。

高斯计算工具与本工具同级目录（..\\高斯计算工具），里面已经有解析好的
glog / plotting 模块，这里直接复用，避免两套解析逻辑。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GCALC_DIR = os.path.normpath(os.path.join(_HERE, '..', '高斯计算工具'))


def gcalc_dir(cfg=None):
    d = (cfg or {}).get('gcalc_dir') or DEFAULT_GCALC_DIR
    return os.path.abspath(d)


def _modules(cfg=None):
    """把高斯计算工具加入 sys.path 并导入它的 glog / plotting。"""
    d = gcalc_dir(cfg)
    if not os.path.isdir(d):
        raise RuntimeError('找不到高斯计算工具目录：%s（可在设置里改 gcalc_dir）' % d)
    if d not in sys.path:
        sys.path.insert(0, d)
    from gcalc import glog, plotting  # noqa: WPS433
    return glog, plotting


def logs_dir(cfg=None):
    """默认日志目录：<数据目录>\\..\\calculation\\gjf\\logs。"""
    cfg = cfg or {}
    d = (cfg.get('gcalc_logs_dir') or '').strip()
    if d:
        return os.path.abspath(d)
    data = (cfg.get('data_dir') or '').strip()
    if data:
        base = os.path.dirname(os.path.abspath(data))
        return os.path.join(base, 'calculation', 'gjf', 'logs')
    return ''


def read_results(cfg=None):
    """读日志目录里所有 TD-DFT 日志，返回每个分子的 S1 / 最强跃迁。"""
    cfg = cfg or {}
    glog, _ = _modules(cfg)
    folder = logs_dir(cfg)
    if not folder or not os.path.isdir(folder):
        return dict(ok=False, error='日志目录不存在：%s' % (folder or '(未设置)'),
                    dir=folder, molecules=[])
    out = []
    for fn in sorted(os.listdir(folder)):
        low = fn.lower()
        if not low.endswith('.log') or '_td' not in low:
            continue
        try:
            res = glog.parse_log(os.path.join(folder, fn))
        except Exception as exc:  # noqa: BLE001
            out.append(dict(name=os.path.splitext(fn)[0], error=str(exc)))
            continue
        ex = res.get('excitations') or []
        if not ex:
            continue
        s1 = next((e for e in ex if e['state'] == 1), ex[0])
        bright = max(ex, key=lambda e: e['f'])
        out.append(dict(
            name=res.get('name') or os.path.splitext(fn)[0],
            file=os.path.join(folder, fn),
            status=res.get('status'),
            energy=res.get('energy'),
            n_states=len(ex),
            s1=dict(wavelength_nm=s1['wavelength_nm'], f=s1['f'],
                    energy_ev=s1['energy_ev']),
            bright=dict(state=bright['state'], wavelength_nm=bright['wavelength_nm'],
                        f=bright['f'], energy_ev=bright['energy_ev']),
            excitations=[dict(state=e['state'], wavelength_nm=e['wavelength_nm'],
                              f=e['f'], energy_ev=e['energy_ev']) for e in ex],
        ))
    out.sort(key=lambda m: m.get('name', ''))
    return dict(ok=True, dir=folder, molecules=out)


def find_molecule(results, name):
    for m in results.get('molecules') or []:
        if m.get('name') == name:
            return m
    return None


def make_figure(mol, path, sigma_ev=0.3):
    """用高斯计算工具的 plotting 画这个分子的计算 UV-Vis 谱。"""
    _, plotting = _modules(None)
    ex = [dict(state=e['state'], wavelength_nm=e['wavelength_nm'],
               f=e['f'], energy_ev=e['energy_ev']) for e in (mol.get('excitations') or [])]
    if not ex:
        return None
    return plotting.save_uvvis(ex, path, title='%s  TD-DFT' % mol.get('name', ''),
                               sigma_ev=sigma_ev)


def comparison_rows(results):
    """报告用：分子 | 计算 λmax | f | 实验 λmax（实验值由调用方合并）。"""
    rows = []
    for m in results.get('molecules') or []:
        b = m.get('bright') or {}
        rows.append((m.get('name'), b.get('wavelength_nm'), b.get('f'),
                     b.get('state'), m.get('s1', {}).get('wavelength_nm')))
    return rows
