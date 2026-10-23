# -*- coding: utf-8 -*-
"""连接「高斯计算工具」：读取 TD-DFT 结果、画计算谱、并在报告里引用。

高斯计算工具与本工具同级目录（..\\高斯计算工具），里面已经有解析好的
glog / plotting 模块，这里直接复用，避免两套解析逻辑。

同一分子可能有多个泛函、多个几何（base / v2）、带不带溶剂的多份日志，
所以每条结果除了旧的 name/file/status/... 字段外，还带上
base / functional / has_solvent / geometry / route / mtime，
并用 group_results() 按分子归并、pick_best() 挑代表条目。
"""
from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GCALC_DIR = os.path.normpath(os.path.join(_HERE, '..', '高斯计算工具'))

# 文件名末尾常见的附加标记：解析分子名时反复剥掉（大小写不敏感，_ 或 - 分隔）。
# 例：A2_td_m062x_16c → A2，A2_cam → A2，A3_v2_td → A3，benzene_td → benzene。
_BASE_TOKENS = ('td', 'gs', 'fc', 'freq', 'opt', 'v2', 'pcm', '16c', '32c', '8c',
                'cam', 'm062x', 'm06-2x', 'lcwpbe', 'lc-wpbe', 'pbe0', 'pbe1pbe',
                'b3lyp', 'wb97xd', 'b97d')
_BASE_SUFFIX_RX = re.compile(
    r'[_-](?:%s)$' % '|'.join(re.escape(t) for t in _BASE_TOKENS), re.I)

# route 第一段（泛函）→ 报告里显示的写法
_FUNC_NAMES = {
    'pbe1pbe': 'PBE0',
    'm062x': 'M06-2X',
    'cam-b3lyp': 'CAM-B3LYP',
    'lc-wpbe': 'LC-wPBE',
    'b3lyp': 'B3LYP',
}

_SOLVENT_TAGS = ('scrf', 'iefpcm', 'smd', 'pcm')


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


# ---------------------------------------------------------------- 名字解析
def base_name(name):
    """把日志名还原成分子名：A2_td_m062x_16c → A2，A2_cam → A2。

    只剥末尾能识别的标记；如果剥到空（名字本身就叫 td 之类）就保留原名。
    """
    n = str(name or '').strip()
    while True:
        m = _BASE_SUFFIX_RX.search(n)
        if not m:
            break
        n = n[:m.start()]
    return n or str(name or '')


def functional_of(route):
    """route 第一段映射成报告用的泛函名：PBE1PBE→PBE0，M062X→M06-2X…

    没见过的泛函原样返回；route 为空就返回空串。
    """
    first = str(route or '').split('/')[0].strip()
    first = re.sub(r'^#\s*[pP]?\s*', '', first).strip()
    return _FUNC_NAMES.get(first.lower(), first)


def has_solvent_model(route):
    """route 里出现 SCRF/IEFPCM/SMD/PCM 就当作用了隐式溶剂模型。"""
    r = str(route or '').lower()
    return any(tag in r for tag in _SOLVENT_TAGS)


def _full_route(path):
    """读日志里完整的 route：Gaussian 会把长 route 折成多行，glog 只抓到第一行。"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
    except OSError:
        return ''
    for i, line in enumerate(lines):
        text = line.strip()
        if not text.startswith('#') or text.startswith('#!'):
            continue
        # 去掉开头的「#p」，只留下真正的 route，报告里直接展示
        parts = [re.sub(r'^#\s*[pP]?\s*', '', text).strip()]
        for nxt in lines[i + 1:i + 8]:
            t = nxt.strip()
            if not t or set(t) <= {'-'}:
                break
            parts.append(t)
        # Gaussian 的折行是纯粹的字符续行，直接拼回去（不能插空格，
        # 否则 SCRF=(I / EFPCM 这类被拆开的词会拼错）
        return ''.join(parts)
    return ''


def _mtime(path):
    try:
        return float(os.path.getmtime(path))
    except OSError:
        return 0.0


def read_results(cfg=None):
    """读日志目录里所有含激发态的 .log，返回每条 TD-DFT 结果。"""
    cfg = cfg or {}
    glog, _ = _modules(cfg)
    folder = logs_dir(cfg)
    if not folder or not os.path.isdir(folder):
        return dict(ok=False, error='日志目录不存在：%s' % (folder or '(未设置)'),
                    dir=folder, molecules=[])
    out = []
    for fn in sorted(os.listdir(folder)):
        # 不再只筛 *_td：A2_cam、A4_cam 这类名字里没有 _td，但确实有激发态
        if not fn.lower().endswith('.log'):
            continue
        path = os.path.join(folder, fn)
        stem = os.path.splitext(fn)[0]
        try:
            res = glog.parse_log(path)
        except Exception as exc:  # noqa: BLE001
            out.append(dict(name=stem, file=path, base=base_name(stem),
                            functional='', has_solvent=False,
                            geometry='v2' if 'v2' in stem.lower() else 'base',
                            route='', mtime=_mtime(path), error=str(exc)))
            continue
        ex = res.get('excitations') or []
        if not ex:
            continue
        route = _full_route(path) or (res.get('route') or '')
        name = res.get('name') or stem
        s1 = next((e for e in ex if e['state'] == 1), ex[0])
        bright = max(ex, key=lambda e: e['f'])
        out.append(dict(
            name=name,
            file=path,
            base=base_name(name),
            functional=functional_of(route),
            has_solvent=has_solvent_model(route),
            geometry='v2' if 'v2' in stem.lower() else 'base',
            route=route,
            mtime=_mtime(path),
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
    # 同一分子的各泛函/各几何排在一起，报告里按这个顺序取组
    out.sort(key=lambda m: (m.get('base') or '', m.get('name') or ''))
    return dict(ok=True, dir=folder, molecules=out)


def group_results(results):
    """按 base 归并：{分子名: [该分子的所有条目]}。

    results 既可以是 read_results() 的返回值，也可以直接是 molecules 列表。
    """
    mols = results.get('molecules') if isinstance(results, dict) else results
    groups = {}
    for m in mols or []:
        key = m.get('base') or m.get('name')
        if not key:
            continue
        groups.setdefault(key, []).append(m)
    return groups


def pick_best(entries):
    """从同一分子/同一泛函的多条结果里挑一条代表：带溶剂 > v2 > mtime 新。"""
    entries = list(entries or [])
    if not entries:
        return None

    def _key(m):
        name = str(m.get('name') or '').lower()
        is_v2 = m.get('geometry') == 'v2' or 'v2' in name
        return (1 if m.get('has_solvent') else 0, 1 if is_v2 else 0,
                float(m.get('mtime') or 0.0))

    return max(entries, key=_key)


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
