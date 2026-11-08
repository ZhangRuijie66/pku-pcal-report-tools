# -*- coding: utf-8 -*-
"""紫外光谱实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算都在本机完成，不联网、不上传数据。
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, 'web')
TEMPLATE = os.path.join(ROOT, 'templates', '紫外光谱报告模板2026.docx')
ASSETS = os.path.join(ROOT, 'assets')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import gcalc_bridge                    # noqa: E402
from pcal import plotting                        # noqa: E402
from pcal import uv                              # noqa: E402
from pcal import report as rpt                   # noqa: E402
from pcal import profile
from pcal import workspace
from pcal import dataloc                         # noqa: E402  数据目录可移植定位
from pcal import filepick                        # noqa: E402  系统文件选择窗口
from pcal.atomicio import atomic_write_json
from pcal.analysis import (Analysis, PERSIST_KEYS, default_config,  # noqa: E402
                           default_config_with_saved)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'key': None, 'gcalc': None}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()   # matplotlib 不是线程安全的
SINGLE_LOCK = threading.Lock()    # 单文件查看的谱缓存（按路径 + 大小 + mtime）
EXPORT_LOCK = threading.Lock()    # 导出串行：并发 / 连点两下时不能算出同一个文件名
MAX_BODY_BYTES = 8 * 1024 * 1024  # 请求体上限，超过直接 413，绝不去 rfile.read


class BodyTooLarge(ValueError):
    """Content-Length 非法或超过 MAX_BODY_BYTES。"""

SINGLE_CACHE = {}


# ---------------------------------------------------------------- 选择文件
def pick_file(initial=None, exts=None, title=None):
    """弹出系统「选择文件」窗口，返回绝对路径；取消时返回 ''。

    窗口实现统一走共享层 ``pcal/filepick.py``（子进程 tkinter，不阻塞服务，
    ``PCAL_PICK_FILE_AUTO`` 可指定返回值）。光谱数据默认只列 txt。
    """
    return filepick.pick_file(initial, exts or ('.txt',),
                              title or '选择光谱数据文件（txt）')


# ---------------------------------------------------------------- 选择文件夹
def pick_folder(initial=None, title=None):
    """弹出系统「选择文件夹」窗口，返回绝对路径；取消时返回 ''。

    窗口实现统一走共享层 ``pcal/filepick.py``（子进程 tkinter，不阻塞服务，
    ``PCAL_PICK_AUTO`` 可指定返回值），与其它 10 个模块口径一致。
    """
    return filepick.pick_folder(initial, title or '选择数据文件夹（光谱仪导出的 txt 所在目录）')


# ---------------------------------------------------------------- 设置文件
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            return profile.merge_saved(json.load(fh))
    except (OSError, ValueError):
        return profile.merge_saved({})


def save_settings(cfg):
    data = {k: cfg.get(k) for k in PERSIST_KEYS if k in cfg}
    # 原子写盘：设置里含姓名/学号，写到一半崩掉会留下半截 JSON。
    atomic_write_json(SETTINGS_FILE, data)
    return data


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ---------------------------------------------------------------- 计算
def _coerce(cfg, payload):
    base = default_config()
    for key, value in (payload.get('config') or {}).items():
        if key not in base:
            continue
        ref = base[key]
        if isinstance(ref, list):
            # calibrations 是列表：只接受能清洗成合法条目的（key 要能拼进
            # 槽位名 cal:<key> 与图文件名 calib_<key>.png）。
            if key == 'calibrations':
                cfg[key] = uv.clean_calibrations(value)
            elif isinstance(value, list):
                cfg[key] = value
            continue
        if isinstance(ref, dict):
            # file_map / molecule_default / conc_pick 这类字典：
            # 以前整块被覆盖，于是前端没传的键会被清空；
            # 现在按「传了就覆盖、没传保留」合并，并做一次白名单清洗。
            if not isinstance(value, dict):
                continue
            if key == 'file_map':
                cfg[key] = uv.clean_file_map(value)
            else:
                merged = dict(cfg.get(key) or {})
                merged.update({k: v for k, v in value.items() if v not in (None, '')})
                cfg[key] = merged
            continue
        if isinstance(ref, (int, float)) and not isinstance(ref, bool):
            try:
                value = float(value) if value not in (None, '') else ref
            except (TypeError, ValueError):
                value = ref
            if isinstance(ref, int):
                value = int(round(value))
        cfg[key] = value
    return cfg


def _config_from(payload=None):
    cfg = default_config_with_saved(load_settings())
    if payload:
        cfg = _coerce(cfg, payload)
    return cfg


def _analysis(cfg, force=False):
    # 缓存键必须覆盖**影响计算结果的所有配置**。以前漏了标定相关项：
    # 于是「改某条曲线的标定」后点了重新计算也拿回旧结果，界面上看不出异常。
    key = json.dumps({k: cfg.get(k) for k in ('data_dir', 'file_map', 'smooth_window',
                                              'stray_mode', 'stray',
                                              'stray_a3', 'path_cm',
                                              'anchor_pad', 'beer_keys',
                                              'calibrations', 'curve_cal',
                                              'molecule_default', 'conc_pick',
                                              'voigt_peaks')},
                     sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = Analysis(cfg).run()
        STATE.update(analysis=an, config=cfg, key=key)
        return an


def _summary(an):
    cfg = an.cfg
    samples = []
    for s in uv.SAMPLES:
        it = an.samples.get(s['key'])
        if not it:
            continue
        samples.append(dict(
            key=s['key'], mol=s['mol'], kind=s.get('kind'), day=s.get('day'),
            conc=it['conc'], source=it['source'], band=list(it['band']),
            stray=it['stray'],
            lmax_obs=it['peak_obs']['lam'], A_obs=it['peak_obs']['A'],
            lmax=it['peak']['lam'], A=it['peak']['A'], eps=it['eps'],
            cal=it['cal_label'],
            sample_file=it.get('sample_file'), blank_file=it.get('blank_file'),
            sample_path=it.get('sample_path'), blank_path=it.get('blank_path')))
    return {
        'ok': True,
        'config': cfg,
        'defaults': default_config(),
        'has_saved': bool(load_settings()),
        'settings_file': SETTINGS_FILE,
        'cals': [dict(key=c['key'], label=c['label'], short=c['short'],
                      a=c['a'], sigma_a=c['sigma_a'], b=c['b'],
                      sigma_b=c['sigma_b'], r2=c['r2'],
                      lam_lo=c['lam_lo'], lam_hi=c['lam_hi'],
                      points=c['points'], fallback=c.get('fallback', False),
                      file_name=c.get('file_name'), path=c.get('path'))
                 for c in an.cals.values()],
        'samples': samples,
        'molecules': an.molecule_table,
        'beer': an.beer,
        'box': an.box,
        'warnings': an.warnings,
        'out_dir': OUT_DIR,
        'data_dir': cfg.get('data_dir'),
        'template': TEMPLATE,
        'report_name': _report_filename(cfg),
        'molecule_codes': ['A1', 'A2', 'A3', 'A4', 'B1', 'B2'],
        'choices': uv.pick_choices(),
        'conc_values': list(uv.CONC_VALUES),
        'conc_items': [dict(key=it['key'], conc=it['conc'],
                            lmax=it['peak']['lam'], A=it['peak']['A'])
                       for it in getattr(an, 'conc_items', [])],
        # 数据文件槽位：每个槽位解析到哪个文件、是否模糊匹配来的、还有哪些候选
        'file_slots': _slot_view(an),
        'file_summary': _file_summary(an),
        # 标定：可选清单（供「每条曲线用哪条」下拉）、自定义条目、逐曲线选择
        'cal_options': [dict(key=c['key'], label=c['label'], short=c['short'],
                             custom=bool(c.get('custom')), file=c.get('file'))
                        for c in (getattr(an, 'cal_list', None) or [])],
        'custom_cals': list(cfg.get('calibrations') or []),
        'curve_cal': dict(getattr(an, 'curve_cal', {}) or {}),
        'curve_cal_default': dict(uv.CURVE_CAL_DEFAULT),
        # 每条曲线（样品）供界面列出的标签
        'curve_rows': [dict(key=s['key'], mol=s['mol'], kind=s.get('kind'),
                            day=s.get('day'), conc=s.get('conc'),
                            cal_key=(getattr(an, 'curve_cal', {}) or {}).get(s['key']),
                            cal_short=((an.samples.get(s['key']) or {})
                                       .get('cal_label') or ''))
                       for s in uv.SAMPLES],
        'default_cal_key': uv.DEFAULT_CAL_KEY,
    }


def _cal_options(query):
    """新增标定时的候选光源谱文件（GET /api/cals/options）。

    返回数据目录里的光谱 txt（相对路径 + 已被哪条标定占用），
    前端据此做可搜索的下拉。只读，不写盘。
    """
    cfg = STATE.get('config') or _config_from()
    data_dir = (query.get('dir') or [''])[0] or cfg.get('data_dir') or ''
    if not os.path.isdir(data_dir):
        return {'ok': False,
                'error': '数据目录不存在：%s' % (data_dir or '（未设置）'),
                'files': [], 'dir': data_dir}
    files = dataloc.list_data_files(data_dir, exts=('.txt',))
    used = {}
    for c in uv.effective_calibrations(cfg.get('calibrations')):
        used[uv._norm_key(c.get('file') or '')] = c['key']
    rows = [dict(rel=rel, used_by=used.get(uv._norm_key(rel)) or '')
            for rel in files]
    return {'ok': True, 'dir': os.path.abspath(data_dir),
            'files': rows, 'total': len(rows),
            'default_key': uv.DEFAULT_CAL_KEY,
            'existing': [dict(key=c['key'], label=c['label'],
                              short=c['short'], file=c.get('file'),
                              custom=bool(c.get('custom')))
                         for c in uv.effective_calibrations(
                             cfg.get('calibrations'))]}


def _slot_view(an):
    """槽位列表 + 解析状态，给前端「数据文件映射」卡片用。

    只列报告真正会读的那几条：同一浓度测了两次也只占一行
    （用哪一次由「测量选择」决定）。
    """
    slots = uv.file_slots(getattr(an, 'picks_mol', None),
                          getattr(an, 'picks_conc', None))
    rows = []
    for slot in slots:
        entry = dict((getattr(an, 'slots', {}) or {}).get(slot['key']) or {})
        rows.append(dict(
            key=slot['key'], kind=slot['kind'], group=slot['group'],
            label=slot['label'], note=slot.get('note', ''),
            default=slot['default'],
            rel=entry.get('rel') or slot['default'],
            path=entry.get('path') or '',
            status=entry.get('status') or 'default',
            score=entry.get('score'),
            overridden=bool(entry.get('overridden')),
            suggestions=[dict(rel=x['rel'], score=x['score'], path=x['path'])
                         for x in (entry.get('suggestions') or [])][:6],
        ))
    return rows


def _file_summary(an):
    """给状态栏/卡片用的一句话统计 + 有多少槽位是自动匹配来的。"""
    slots = getattr(an, 'slots', {}) or {}
    counts = {'default': 0, 'manual': 0, 'fuzzy': 0}
    for entry in slots.values():
        counts[entry.get('status', 'default')] = \
            counts.get(entry.get('status', 'default'), 0) + 1
    fuzzy = [dict(key=k, label=v['label'], rel=v.get('rel'),
                  score=v.get('score'), default=v['default'])
             for k, v in slots.items() if v.get('status') == 'fuzzy']
    return dict(total=len(slots), default=counts.get('default', 0),
                manual=counts.get('manual', 0), fuzzy=counts.get('fuzzy', 0),
                fuzzy_items=fuzzy)


# ---------------------------------------------------------------- 预览图
def _mol_items(an, codes):
    """按分子编号取当前选中的测量（不写死 sample key，换测量时图也跟着走）。"""
    picks = getattr(an, 'picks_mol', {}) or {}
    items, labels = [], []
    for code in codes:
        key = picks.get(code) or uv.MOLECULE_DEFAULT.get(code)
        it = an.samples.get(key)
        if it is not None:
            items.append(it)
            labels.append(code)
    return items, labels


def _preview(kind, cfg, query):
    an = _analysis(cfg)
    import matplotlib.pyplot as plt

    def png(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
        plt.close(fig)
        return buf.getvalue()

    if kind == 'cal':
        key = (query.get('key') or ['d1_long'])[0]
        cal = an.cals.get(key) or an.cals['d1_long']
        return png(plotting.make_calibration_figure(cal))
    if kind == 'conc':
        return png(plotting.make_concentration_figure(an.conc_items))
    if kind == 'beer':
        if an.beer and an.beer.get('fit'):
            return png(plotting.make_beer_figure(an.beer))
    if kind == 'spectra':
        group = (query.get('group') or ['long'])[0]
        codes = ('A1', 'B1', 'B2') if group == 'short' else ('A2', 'A3', 'A4')
        items, labels = _mol_items(an, codes)
        xlim = (250, 620) if group == 'short' else (450, 880)
        return png(plotting.make_spectra_figure(items, labels=labels, xlim=xlim))
    if kind == 'voigt':
        a3k = (getattr(an, 'picks_mol', {}) or {}).get('A3') or 'A3c5b'
        it = an.samples.get(a3k)
        if it:
            fig = plotting.make_voigt_figure(it)
            if fig is not None:
                return png(fig)
    if kind == 'source':
        src = [an.samples[k] for k in uv.SOURCE_SAMPLE_KEYS if k in an.samples]
        if len(src) == 2:
            return png(plotting.make_source_figure(src[0], src[1]))
    # 空图
    fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
    ax.text(0.5, 0.5, 'no data', ha='center', va='center')
    ax.axis('off')
    return png(fig)


# ---------------------------------------------------------------- 单个文件
def _single_spec(path):
    """读一个 txt（带缓存：同一路径 + 大小 + 修改时间不变就不重读）。"""
    if not os.path.isfile(path):
        raise ValueError('文件不存在：%s' % path)
    try:
        st = os.stat(path)
        stamp = (st.st_size, int(st.st_mtime))
    except OSError as exc:
        raise ValueError('读不到文件信息：%s' % exc)
    real = os.path.abspath(path)
    with SINGLE_LOCK:
        hit = SINGLE_CACHE.get(real)
        if hit and hit[0] == stamp:
            return hit[1]
    spec = uv.read_single(path)
    with SINGLE_LOCK:
        if len(SINGLE_CACHE) > 24:            # 看过的文件不无限积攒
            SINGLE_CACHE.clear()
        SINGLE_CACHE[real] = (stamp, spec)
    return spec


def _single_info(path, cfg=None):
    """单个文件的概要：点数、最强 pixel/波长/强度、以及它对应哪个槽位。"""
    spec = _single_spec(path)
    cfg = cfg or STATE.get('config') or _config_from()
    cal = None
    if STATE.get('analysis') is not None:
        # 用当前标定把 pixel 翻成波长；标定本身不可靠就算了，只报 pixel
        day2 = STATE['analysis'].cals.get('d2_long')
        cal = day2
    info = uv.single_peak_info(spec, cal=cal)
    rel = None
    try:
        rel = os.path.relpath(path, cfg.get('data_dir') or '')
        if rel.startswith('..'):
            rel = None
    except ValueError:
        rel = None
    slot = None
    for row in _slot_view(STATE['analysis']) if STATE.get('analysis') else []:
        if os.path.normcase(os.path.normpath(row['path'])) == \
                os.path.normcase(os.path.normpath(path)):
            slot = dict(key=row['key'], label=row['label'], status=row['status'])
            break
    return dict(ok=True, path=os.path.abspath(path), name=os.path.basename(path),
                rel=rel, slot=slot, cal=info.get('lam'),
                info=info, data_dir=cfg.get('data_dir'))


def _single_preview(path, cal='auto', smooth=1):
    """单文件预览图：原始谱（上）+ 若给了标定则换算成波长（下）。"""
    import matplotlib.pyplot as plt
    spec = _single_spec(path)
    y = np.asarray(spec['difference'], float)
    idx = np.asarray(spec['index'], float)
    ys = uv.smooth(y, int(smooth or 1))

    cal_info = None
    if cal and cal != 'off' and STATE.get('analysis') is not None:
        key = cal if cal != 'auto' else 'd2_long'
        cal_info = STATE['analysis'].cals.get(key)
    if cal_info:
        fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6), dpi=120)
        ax = axes[0]
        ax.plot(idx, y, color='0.72', linewidth=0.6, label='原始')
        if int(smooth or 1) > 1:
            ax.plot(idx, ys, color='black', linewidth=0.9, label='平滑 %d 点' % int(smooth))
        ax.set_xlabel('pixel')
        ax.set_ylabel('光强（difference）')
        ax.set_xlim(0, float(np.max(idx)) if len(idx) else 1)
        ax.legend(fontsize=8)
        _style_dark(ax)
        ax = axes[1]
        lam = cal_info['a'] * idx + cal_info['b']
        ax.plot(lam, y, color='0.72', linewidth=0.6, label='原始')
        if int(smooth or 1) > 1:
            ax.plot(lam, ys, color='black', linewidth=0.9, label='平滑 %d 点' % int(smooth))
        ax.set_xlabel('波长 / nm')
        ax.set_ylabel('光强（difference）')
        ax.set_xlim(float(np.min(lam)), float(np.max(lam)))
        ax.legend(fontsize=8)
        _style_dark(ax)
        fig.tight_layout()
        return fig
    fig, ax = plt.subplots(figsize=(7.4, 3.6), dpi=120)
    ax.plot(idx, y, color='0.72', linewidth=0.6, label='原始')
    if int(smooth or 1) > 1:
        ax.plot(idx, ys, color='black', linewidth=0.9, label='平滑 %d 点' % int(smooth))
    ax.set_xlabel('pixel')
    ax.set_ylabel('光强（difference）')
    ax.set_xlim(0, float(np.max(idx)) if len(idx) else 1)
    ax.legend(fontsize=8)
    _style_dark(ax)
    fig.tight_layout()
    return fig


def _style_dark(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)


# ---------------------------------------------------------------- 数据文件映射
def _picks_from_cfg(cfg):
    """从配置里解析「测量选择」，用来决定哪些槽位需要文件。"""
    pm = dict(uv.MOLECULE_DEFAULT)
    for code, key in (cfg.get('molecule_default') or {}).items():
        if key in uv.MOLECULE_CANDIDATES.get(code, []):
            pm[code] = key
    pc = dict(uv.CONC_PICK_DEFAULT)
    for slot, key in (cfg.get('conc_pick') or {}).items():
        if key in uv.CONC_CANDIDATES.get(slot, []):
            pc[slot] = key
    return pm, pc


def _files(query):
    """数据目录里的 txt 清单（相对路径），以及每个槽位的模糊匹配候选。

    ?dir=  覆盖数据目录（切换目录时前端先探一遍）
    ?slot=（可选）只算这个槽位的候选
    ?q=    （可选）按关键字过滤清单（共享层 dataloc.search_files 同口径）

    只算「当前测量选择下真正要用的」槽位——同一浓度测了两次时只算选中的那条。
    返回体同时给两套字段名：
      · ``files`` / ``count`` / ``data_dir`` / ``auto`` —— 本模块前端一直在用；
      · ``total`` / ``dir`` —— 共享层 ``/api/files`` 约定（web/files.js 用）。
    两套都给是为了「不推翻已跑通的槽位匹配」，同时让 PcalFiles 能直接挂上去。
    """
    cfg = STATE.get('config') or _config_from()
    data_dir = (query.get('dir') or [''])[0] or cfg.get('data_dir') or ''
    if not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir,
                'files': [], 'total': 0, 'dir': data_dir}
    files = uv._index_files(data_dir)
    pm, pc = _picks_from_cfg(cfg)
    slot_key = (query.get('slot') or [''])[0]
    slots = [s for s in uv.file_slots(pm, pc) if not slot_key or s['key'] == slot_key]
    auto = {}
    for slot in slots:
        target = slot['default']
        best_rel, best_score = uv.fuzzy_match(target, data_dir, files)
        auto[slot['key']] = dict(
            default=target, match=best_rel, score=round(best_score, 4),
            auto=bool(best_rel and best_score >= uv.FUZZY_ACCEPT),
            suggestions=[dict(rel=rel, score=s)
                         for s, rel in uv.suggest_files(target, files, top=6)])
    out = dict(ok=True, data_dir=data_dir, count=len(files),
               files=files, auto=auto, accept=uv.FUZZY_ACCEPT)
    # 共享层 /api/files 约定的两个字段（web/files.js 的 PcalFiles 直接读它们）。
    # 只加不改：本模块前端用的 files/count/data_dir 保持原样，槽位匹配结果不变。
    out['dir'] = os.path.abspath(data_dir)
    out['exists'] = True
    out['total'] = len(files)
    return out


def _auto_map(query):
    """一键自动匹配：给当前用到的每个槽位生成 {槽位: rel} 映射（只收高置信度的）。"""
    cfg = STATE.get('config') or _config_from()
    data_dir = (query.get('dir') or [''])[0] or cfg.get('data_dir') or ''
    if not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'map': {}}
    files = uv._index_files(data_dir)
    pm, pc = _picks_from_cfg(cfg)
    out, low = {}, []
    taken = {}
    for slot in uv.file_slots(pm, pc):
        best_rel, score = uv.fuzzy_match(slot['default'], data_dir, files)
        if best_rel and score >= uv.FUZZY_ACCEPT:
            # 同一份文件被两个槽位抢：只留给分最高的那个
            if best_rel in taken and taken[best_rel][1] >= score:
                low.append(dict(key=slot['key'], label=slot['label'],
                                reason='候选文件已被「%s」占用' % taken[best_rel][0]))
                continue
            taken[best_rel] = (slot['label'], score)
            out[slot['key']] = best_rel
        else:
            low.append(dict(key=slot['key'], label=slot['label'],
                            best=best_rel, score=round(score, 4),
                            suggestions=[dict(rel=rel, score=s)
                                         for s, rel in uv.suggest_files(
                                             slot['default'], files, top=4)]))
    return dict(ok=True, data_dir=data_dir, map=out, unresolved=low,
                accept=uv.FUZZY_ACCEPT)


def _file_info(query):
    path = (query.get('path') or [''])[0]
    if not path:
        return {'ok': False, 'error': '缺少 path 参数'}
    cfg = STATE.get('config') or _config_from()
    if not os.path.isabs(path):
        path = os.path.join(cfg.get('data_dir') or '', path)
    return _single_info(path, cfg)


def _preview_single(query):
    path = (query.get('path') or [''])[0]
    if not path:
        raise ValueError('缺少 path 参数')
    cfg = STATE.get('config') or _config_from()
    if not os.path.isabs(path):
        path = os.path.join(cfg.get('data_dir') or '', path)
    cal = (query.get('cal') or ['auto'])[0]
    try:
        smooth = int((query.get('smooth') or ['1'])[0] or 1)
    except ValueError:
        smooth = 1
    fig = _single_preview(path, cal=cal, smooth=smooth)
    return plotting.figure_png(fig, dpi=110)


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-紫外光谱.docx' % stem


def _safe_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip() or 'report.docx'


def _unique_path(path, max_tries=50):
    if not os.path.exists(path) and not _locked(path):
        return path, ''
    base, ext = os.path.splitext(path)
    for i in range(2, max_tries + 2):
        cand = '%s(%d)%s' % (base, i, ext)
        if not os.path.exists(cand) and not _locked(cand):
            return cand, '目标文件被占用或已存在，已改名为 %s' % os.path.basename(cand)
    return path, ''


def _locked(path):
    d, f = os.path.dirname(path), os.path.basename(path)
    return os.path.exists(os.path.join(d, '~$' + f))


def _gcalc_read(d=''):
    """读取高斯计算工具的 TD-DFT 日志（可选指定目录）。"""
    cfg = _config_from()
    if d:
        cfg['gcalc_logs_dir'] = d
    try:
        res = gcalc_bridge.read_results(cfg)
    except Exception as exc:  # noqa: BLE001
        return dict(ok=False, error=str(exc), dir=d, molecules=[])
    with LOCK:
        STATE['gcalc'] = res
    return res


def _gcalc_open(payload=None):
    """确保高斯计算工具在运行，返回它的地址。"""
    gdir = gcalc_bridge.gcalc_dir()
    url = 'http://127.0.0.1:8795/'
    if _http_alive(url):
        return dict(ok=True, url=url, started=False)
    if not os.path.isfile(os.path.join(gdir, 'run.py')):
        return dict(ok=False, error='找不到高斯计算工具目录：%s' % gdir)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.Popen([sys.executable, 'run.py', '--port', '8795', '--no-browser'],
                     cwd=gdir, creationflags=flags)
    for _ in range(30):
        time.sleep(0.5)
        if _http_alive(url):
            return dict(ok=True, url=url, started=True)
    return dict(ok=False, error='高斯计算工具启动超时，请手动双击它的 启动.cmd')


def _http_alive(url):
    try:
        with urllib.request.urlopen(url + 'api/state', timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _export(cfg):
    """导出报告。整段串行：并发 / 连点两下时不能算出同一个文件名。"""
    with EXPORT_LOCK:
        return _export_locked(cfg)


def _export_locked(cfg):
    an = _analysis(cfg)
    name = _safe_filename(_report_filename(cfg))
    stem = os.path.splitext(name)[0]
    out_dir = os.path.join(OUT_DIR, stem)
    os.makedirs(out_dir, exist_ok=True)
    out, note = _unique_path(os.path.join(out_dir, name))
    plots = os.path.join(out_dir, 'figures')
    logs = []
    # matplotlib 的 mathtext 解析器是进程级全局状态：预览与导出同时建图会互相踩
    # （实测 4 导出 + 12 预览 → 全报 ParseException）。这里也拿 PREVIEW_LOCK，
    # 让「建图 + savefig」全局串行。锁序 EXPORT_LOCK -> PREVIEW_LOCK，
    # 与只拿 PREVIEW_LOCK 的预览路径不冲突，不成环。
    with PREVIEW_LOCK:
        rpt.build_report(an, cfg, out, plots, TEMPLATE,
                         progress=lambda m: logs.append(m))
    # 报告里实际用了哪个文件必须留下来：模糊匹配会挑替身，
    # workspace.json 里的绝对路径 + 哈希是唯一的事后追溯依据。
    used = dict((getattr(an, 'paths', {}) or {}))
    fuzzy = [dict(key=k, label=v['label'], rel=v.get('rel'),
                  score=v.get('score'), default=v['default'])
             for k, v in (getattr(an, 'slots', {}) or {}).items()
             if v.get('status') == 'fuzzy']
    try:
        workspace.save(out_dir,
                       {'config': cfg, 'file_slots': used, 'fuzzy': fuzzy},
                       cfg, '紫外', TEMPLATE,
                       extra={'spectra': sorted(getattr(an, 'spectra', {}) or {}),
                              'file_slots': used, 'fuzzy_matched': fuzzy})
    except Exception as exc:                         # noqa: BLE001
        logs.append('工作区快照写入失败：%s' % exc)
    if fuzzy:
        logs.append('%d 个文件是按文件名自动匹配的，详见 workspace.json 的 fuzzy_matched'
                    % len(fuzzy))
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots,
                fuzzy=fuzzy, file_slots=used)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    # 单次 socket 读写超时：半截请求最多占住线程这么久就断开。
    timeout = 30
    server_version = 'PChemUV/1.0'

    def log_message(self, fmt, *args):
        if os.environ.get('PCAL_DEBUG'):
            sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=_json_default))

    def _error(self, exc):
        """把异常回给前端。traceback 只在本机调试（PCAL_DEBUG=1）时附带——
        原来无条件回 trace，等于把内部路径结构和异常栈都吐给调用方。"""
        payload = {'ok': False, 'error': str(exc)}
        if os.environ.get('PCAL_DEBUG'):
            payload['trace'] = traceback.format_exc()
        self._json(payload, 400)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        # Content-Length 为负时 rfile.read(-1) 会一直读到连接关闭；超过上限同理——
        # 一个声明 1 GB 的慢速请求能长期占住一个线程（实测 30 个悬挂 = 30 个线程）。
        if n < 0 or n > MAX_BODY_BYTES:
            raise BodyTooLarge('请求体 %s 字节，超过上限 %d 字节'
                               % (n, MAX_BODY_BYTES))
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode('utf-8'))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        q = urllib.parse.parse_qs(u.query)
        try:
            if path in ('/', '/index.html'):
                return self._file(os.path.join(WEB_DIR, 'index.html'),
                                  'text/html; charset=utf-8')
            if path.startswith('/static/'):
                return self._static(path[len('/static/'):])
            if path == '/api/state':
                cfg = _config_from()
                an = _analysis(cfg)
                return self._json(_summary(an))
            if path == '/api/settings':
                return self._json({'ok': True,
                                   'config': default_config_with_saved(load_settings()),
                                   'defaults': default_config(),
                                   'settings_file': SETTINGS_FILE,
                                   'has_saved': bool(load_settings())})
            if path == '/api/preview':
                cfg = STATE.get('config') or _config_from()
                kind = (q.get('kind') or ['conc'])[0]
                with PREVIEW_LOCK:
                    png = _preview(kind, cfg, q)
                return self._send(200, png, 'image/png')
            if path == '/api/cals/options':
                # 新增标定用：数据目录里可作为「光源谱」的文件 + 现有标定清单
                return self._json(_cal_options(q))
            if path == '/api/scan':
                d = (q.get('dir') or [''])[0]
                return self._json(_scan(d))
            if path == '/api/gcalc/read':
                d = (q.get('dir') or [''])[0]
                return self._json(_gcalc_read(d))
            if path == '/api/gcalc/figure':
                return self._gcalc_figure(q)
            if path == '/api/pickdir':
                initial = (q.get('initial') or [''])[0]
                return self._json({'ok': True, 'path': pick_folder(initial)})
            if path == '/api/pickfile':
                initial = (q.get('initial') or [''])[0]
                exts = (q.get('exts') or [''])[0]
                return self._json({'ok': True,
                                   'path': pick_file(initial, exts or None)})
            if path == '/api/files':
                return self._json(_files(q))
            if path == '/api/file/info':
                return self._json(_file_info(q))
            if path == '/api/preview/single':
                with PREVIEW_LOCK:
                    png = _preview_single(q)
                return self._send(200, png, 'image/png')
            return self._json({'ok': False, 'error': 'not found: ' + path}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == '/api/calc':
                cfg = _config_from(self._body())
                an = _analysis(cfg, force=True)
                return self._json(_summary(an))
            if u.path == '/api/export':
                cfg = _config_from(self._body())
                with LOCK:                       # STATE['gcalc'] 的写入也在锁内
                    gcalc = STATE.get('gcalc')
                cfg['gcalc'] = gcalc or {}
                return self._json(_export(cfg))
            if u.path == '/api/gcalc/open':
                return self._json(_gcalc_open(self._body()))
            if u.path == '/api/files/auto':
                return self._json(_auto_map(
                    urllib.parse.parse_qs(u.query)))
            if u.path == '/api/settings':
                cfg = _config_from(self._body())
                data = save_settings(cfg)
                return self._json({'ok': True, 'saved': data,
                                   'config': default_config_with_saved(data),
                                   'has_saved': True})
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except BodyTooLarge as exc:
            return self._json({'ok': False, 'error': str(exc)}, 413)
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def _gcalc_figure(self, q):
        name = (q.get('name') or [''])[0]
        sigma = float((q.get('sigma') or ['0.3'])[0] or 0.3)
        res = STATE.get('gcalc') or _gcalc_read()
        mol = gcalc_bridge.find_molecule(res, name)
        if not mol:
            return self._send(404, b'molecule not found', 'text/plain; charset=utf-8')
        tmp = os.path.join(tempfile.gettempdir(), 'uv_gcalc_%s.png' % name)
        try:
            path = gcalc_bridge.make_figure(mol, tmp, sigma_ev=sigma)
        except Exception as exc:  # noqa: BLE001
            return self._send(500, str(exc).encode('utf-8'), 'text/plain; charset=utf-8')
        if not path:
            return self._send(404, b'no excitations', 'text/plain; charset=utf-8')
        with open(path, 'rb') as fh:
            return self._send(200, fh.read(), 'image/png')

    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == '/api/settings':
                try:
                    os.remove(SETTINGS_FILE)
                except FileNotFoundError:
                    pass
                return self._json({'ok': True, 'config': default_config(),
                                   'defaults': default_config(), 'has_saved': False})
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    # ---------- static
    def _static(self, rel):
        rel = rel.replace('\\', '/').lstrip('/')
        target = os.path.normpath(os.path.join(WEB_DIR, rel))
        # 补 os.sep：原来只比前缀，同级的 web2/ 兄弟目录也能通过
        # （/static/../web2/secret.txt 会 200）。
        root = os.path.normpath(WEB_DIR) + os.sep
        if not (target + os.sep).startswith(root):
            return self._json({'ok': False, 'error': 'forbidden'}, 403)
        ext = os.path.splitext(target)[1].lower()
        ctype = {'.css': 'text/css; charset=utf-8',
                 '.js': 'application/javascript; charset=utf-8',
                 '.svg': 'image/svg+xml', '.png': 'image/png',
                 '.json': 'application/json'}.get(ext, 'application/octet-stream')
        return self._file(target, ctype)

    def _file(self, path, ctype):
        if not os.path.exists(path):
            return self._json({'ok': False, 'error': 'missing ' + path}, 404)
        with open(path, 'rb') as fh:
            data = fh.read()
        self._send(200, data, ctype)


# ---------------------------------------------------------------- 扫描数据目录
def _scan(data_dir):
    """扫描：当前要用的文件齐不齐、哪些能模糊匹配上。

    返回的 ``ready`` 只在「当前测量选择下全部槽位都能解析」时为真；
    ``fuzzy`` 是被自动匹配的槽位（换了一批改名数据时该确认的地方）。
    ``slots`` 与 /api/state 里的 file_slots 同形，前端直接拿去重画映射卡片。
    """
    if not data_dir or not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'files': []}
    cfg = STATE.get('config') or _config_from()
    files = uv.spectrum_files(data_dir)
    # 换目录时映射还是旧的，按「新目录 + 当前映射」重新解析
    pm, pc = _picks_from_cfg(cfg)
    paths, missing, detail = uv.resolve_slots(cfg.get('file_map'), data_dir,
                                              picks_mol=pm, picks_conc=pc)
    fuzzy = [dict(key=k, label=v['label'], rel=v['rel'],
                  score=round(v['score'] or 0, 4))
             for k, v in detail.items() if v.get('status') == 'fuzzy']
    rows = []
    for slot in uv.file_slots(pm, pc):
        entry = detail.get(slot['key']) or {}
        rows.append(dict(
            key=slot['key'], kind=slot['kind'], group=slot['group'],
            label=slot['label'], note=slot.get('note', ''),
            default=slot['default'],
            rel=entry.get('rel') or slot['default'],
            path=entry.get('path') or '',
            status=entry.get('status') or 'default',
            score=entry.get('score'),
            overridden=bool(entry.get('overridden')),
            suggestions=[dict(rel=x['rel'], score=x['score'], path=x['path'])
                         for x in (entry.get('suggestions') or [])][:6],
        ))
    return dict(ok=True, data_dir=data_dir, count=len(files),
                files=[os.path.relpath(p, data_dir) for p in files[:200]],
                expected=len(detail), ready=not missing,
                slots=rows, fuzzy=fuzzy, auto=uv.FUZZY_ACCEPT,
                missing=[dict(key=m['key'], label=m['label'],
                              requested=m.get('requested'),
                              suggestions=[dict(rel=x['rel'], score=x['score'])
                                           for x in (m.get('suggestions') or [])[:4]])
                         for m in missing])


# ---------------------------------------------------------------- 启动
def _port_busy(port):
    """端口上是否已有服务在监听。

    不能只用 bind 探测：ThreadingHTTPServer 默认 allow_reuse_address=True，
    两边都带 SO_REUSEADDR 时 Windows 允许同端口重复 bind，探测会误判成空闲，
    于是新实例起在同一端口、请求却被旧实例吞掉（"时好时坏"的由来）。
    这里先 connect_ex 复核，再不带 SO_REUSEADDR 地 bind。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            return True
    return False


def _free_port(preferred=8791):
    for port in range(preferred, preferred + 60):
        if not _port_busy(port):
            return port
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = 0
    open_browser = True
    for i, a in enumerate(argv):
        if a == '--port' and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif a == '--no-browser':
            open_browser = False
    if not port:
        port = _free_port()
    if not port:
        raise SystemExit('没有可用端口')

    cfg = _config_from()
    try:
        _analysis(cfg, force=True)
    except Exception as exc:  # noqa: BLE001
        print('⚠ 初次计算失败：%s' % exc)
        print('  请检查数据目录：%s' % cfg.get('data_dir'))

    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d' % port
    print('紫外光谱实验报告生成器')
    print('  数据目录：%s' % cfg.get('data_dir'))
    print('  输出目录：%s' % OUT_DIR)
    print('  地址：%s   （Ctrl+C 退出）' % url)
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)),
                         daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已退出')
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
