# -*- coding: utf-8 -*-
"""电化学（循环伏安法）实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算都在本机完成，不联网、不上传数据。
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, 'web')
TEMPLATE = os.path.join(ROOT, 'templates', '电化学报告模板2026.docx')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import echem                           # noqa: E402
from pcal import dataloc                         # noqa: E402
from pcal import filepick                        # noqa: E402
from pcal import plotting                        # noqa: E402
from pcal import report as rpt                   # noqa: E402
from pcal import profile
from pcal import workspace
from pcal.atomicio import atomic_write_json
from pcal.analysis import (Analysis, DATA_DIR_CANDIDATES, FILE_SLOTS,  # noqa: E402
                           PERSIST_KEYS, default_config,
                           default_config_with_saved, resolve_slots)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'key': None}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()   # matplotlib 不是线程安全的
EXPORT_LOCK = threading.Lock()    # 导出串行：并发 / 连点两下时不能算出同一个文件名
MAX_BODY_BYTES = 8 * 1024 * 1024  # 请求体上限，超过直接 413，绝不去 rfile.read


class BodyTooLarge(ValueError):
    """Content-Length 非法或超过 MAX_BODY_BYTES。"""



# ---------------------------------------------------------------- 选择文件夹
def pick_folder(initial=None):
    """弹出系统「选择文件夹」窗口，返回绝对路径；取消时返回 ''。

    实现已收进共享层 ``pcal/filepick.py``（tkinter 子进程，不阻塞服务线程，
    自动化测试用 ``PCAL_PICK_AUTO`` 接管）。这里只保留同签名入口。
    """
    return filepick.pick_folder(initial, title='选择数据文件夹（CHI 导出的 txt 所在目录）')


def pick_file(initial=None, exts=None):
    """弹出系统「选择文件」窗口，返回绝对路径；取消时返回 ''。"""
    return filepick.pick_file(initial, exts or ('.txt',),
                              title='选择 CHI 导出的 CV 数据文件（txt）')


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
        if isinstance(ref, (int, float)) and not isinstance(ref, bool):
            try:
                value = float(value) if value not in (None, '') else ref
            except (TypeError, ValueError):
                value = ref
            if isinstance(ref, int) and not isinstance(ref, bool):
                value = int(round(value))
        cfg[key] = value
    return cfg


def _config_from(payload=None):
    cfg = default_config_with_saved(load_settings())
    if payload:
        cfg = _coerce(cfg, payload)
    return cfg


def _analysis(cfg, force=False):
    key = json.dumps({k: cfg.get(k) for k in PERSIST_KEYS},
                     sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = Analysis(cfg).run()
        STATE.update(analysis=an, config=cfg, key=key)
        return an


def _summary(an):
    cfg = an.cfg
    esa = an.esa
    orr = an.orr
    mor = an.mor
    d = an.dmfc or {}
    return {
        'ok': True,
        'config': cfg,
        'defaults': default_config(),
        'has_saved': bool(load_settings()),
        'settings_file': SETTINGS_FILE,
        'table1': an.table1,
        'esa': {k: esa.get(k) for k in
                ('A', 'Q', 'baseline', 'lo', 'hi', 'area_cm2', 'area_mm2', 'v')},
        'orr': {k: orr.get(k) for k in ('onset_red', 'onset_ox', 'threshold')},
        'mor': {k: mor.get(k) for k in ('onset', 'threshold')},
        'dmfc': {k: d.get(k) for k in
                 ('E_intersect', 'I_intersect', 'P_max', 'E_at_Pmax',
                  'I_at_Pmax', 'I_max')},
        'warnings': an.warnings,
        'out_dir': OUT_DIR,
        'data_dir': cfg.get('data_dir'),
        'template': TEMPLATE,
        'report_name': _report_filename(cfg),
        'files_found': sorted(an.files.keys()),
        'txt_files': echem.scan_directory(cfg.get('data_dir')),
        # 槽位解析结果（含自动匹配的匹配度）：界面据此标「自动 NN%」
        'file_slots': _slot_payload(an),
    }


def _slot_payload(an):
    """把槽位解析结果转成前端要的形状（列表，顺序与 FILE_SLOTS 一致）。"""
    detail = getattr(an, 'slots', None) or {}
    out = []
    for key, label, why in FILE_SLOTS:
        entry = dict(detail.get(key) or {})
        out.append({
            'key': key,
            'label': label,
            'why': why,
            'requested': entry.get('requested') or '',
            'default': entry.get('default') or '',
            'rel': entry.get('rel') or '',
            'score': entry.get('score'),
            'status': entry.get('status') or 'missing',
            'reason': entry.get('why') or '',
            'suggestions': entry.get('suggestions') or [],
            'found': entry.get('status') in ('default', 'manual', 'fuzzy'),
        })
    return out


# ---------------------------------------------------------------- 数据文件
def _data_dir(query=None):
    """当前要用的数据目录：``?dir=`` 覆盖 > 已算过的 cfg > 默认推导。

    优先级与 ``dataloc.find_data_dir`` 一致（记住的目录存在就沿用），
    但这里不允许返回空串——空串会让 ``list_data_files`` 直接返回 []。
    """
    query = query or {}
    cfg = STATE.get('config') or _config_from()
    data_dir = (query.get('dir') or [''])[0] or cfg.get('data_dir') or ''
    if not data_dir:
        data_dir = dataloc.find_data_dir(ROOT, extra=DATA_DIR_CANDIDATES,
                                         tool_subdirs=('样例数据',))
    return data_dir


def _files(query):
    """``GET /api/files``：数据目录里的数据文件清单 + 每个槽位的候选与匹配度。

    这是电化学「数据文件映射」升级的核心：CHI 工作站导出的文件名每年不同，
    原来的下拉框只能列目录里已有的文件、靠用户肉眼认。现在每个槽位都给出

    * ``status``：``default``（用户没改过，且文件在）/ ``manual``（用户指定）/
      ``fuzzy``（原文件名不在，按模糊匹配自动采用）/ ``ambiguous`` /
      ``missing``；
    * ``score``：匹配度 0~1（界面显示成「自动 NN%」）；
    * ``suggestions``：≥0.45 的候选，按分数降序，可一键采用。

    ``?dir=`` 覆盖数据目录；``?slot=`` 只算某个槽位（刷新单个下拉框时用）。
    """
    data_dir = _data_dir(query)
    if not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'files': []}
    files = dataloc.list_data_files(data_dir, exts=('.txt',))
    cfg = STATE.get('config') or _config_from()
    detail = resolve_slots(data_dir, cfg, files)
    want = (query.get('slot') or [''])[0]
    slots = []
    for key, label, why in FILE_SLOTS:
        if want and key != want:
            continue
        entry = dict(detail.get(key) or {})
        slots.append({
            'key': key,
            'label': label,
            'why': why,
            'requested': entry.get('requested') or '',
            'default': entry.get('default') or '',
            'rel': entry.get('rel') or '',
            'score': entry.get('score'),
            'status': entry.get('status') or 'missing',
            'reason': entry.get('why') or '',
            'suggestions': entry.get('suggestions') or [],
        })
    payload = filepick.index_payload(data_dir, files)
    payload.update({'slots': slots,
                    'accept': dataloc.FUZZY_ACCEPT,
                    'suggest': dataloc.FUZZY_SUGGEST})
    return payload


def _auto_map(query):
    """``POST /api/files/auto``：把高置信度（≥0.80）的自动匹配写进映射并保存。

    只写**分数够**的槽位；分数不够的一个都不动，把候选回给前端让用户自己挑。
    这样「一键自动匹配」永远不会把一份错的文件悄悄塞进报告。
    """
    data_dir = _data_dir(query)
    if not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'map': {}}
    files = dataloc.list_data_files(data_dir, exts=('.txt',))
    cfg = _config_from()
    detail = resolve_slots(data_dir, cfg, files)
    out, low = {}, []
    for key, label, _why in FILE_SLOTS:
        entry = dict(detail.get(key) or {})
        if entry.get('status') == 'fuzzy':
            out[key] = entry['rel']
        elif entry.get('status') in ('ambiguous', 'missing'):
            low.append({'key': key, 'label': label,
                        'requested': entry.get('requested') or '',
                        'score': entry.get('score'),
                        'reason': entry.get('why') or '',
                        'suggestions': entry.get('suggestions') or []})
    if out:
        # 沿用原有持久化机制（settings.json + profile.json 合并），不另开一套
        merged = _config_from({'config': out})
        save_settings(merged)
        an = _analysis(merged, force=True)
        return {'ok': True, 'data_dir': data_dir, 'map': out, 'unresolved': low,
                'saved': True, 'state': _summary(an)}
    return {'ok': True, 'data_dir': data_dir, 'map': {}, 'unresolved': low,
            'saved': False}


def _assign(query, body):
    """``POST /api/files/assign``：用户从文件清单里点了一行，该填给哪个槽位。

    请求体 ``{"rel": "N2_2.txt"}``；``?dir=`` 覆盖数据目录。

    返回 ``{'ok', 'rel', 'best', 'candidates': [...]}``：

    * ``best``：分最高的槽位 ``{'key','label','score','why','current'}``，
      分数够高时前端直接填进下拉框；
    * ``candidates``：全部槽位按分数降序（含 ``best``），供前端在分数不够
      （或用户想改派）时让他自己挑——**不替用户静默决定**。

    **写盘端点必须是 POST**（项目审计结论：GET 被地址栏/书签/`<img src>`
    误触时不能有副作用）。这里只算不写，映射仍由用户点「重新计算」时随
    ``config`` 提交。
    """
    from pcal.analysis import ASSIGN_MIN_SCORE, rank_slots_for_file
    data_dir = _data_dir(query)
    rel = str((body or {}).get('rel') or '').strip().replace('\\', '/')
    if not rel:
        return {'ok': False, 'error': '缺少文件名 rel'}
    cfg = _config_from()
    files = dataloc.list_data_files(data_dir, exts=('.txt',)) \
        if data_dir and os.path.isdir(data_dir) else []
    if files and rel not in files:
        # 允许点目录外的绝对路径，但要说清它不在当前数据目录里
        return {'ok': False, 'error': '这个文件不在当前数据目录里：%s' % rel,
                'rel': rel, 'candidates': []}
    detail = resolve_slots(data_dir, cfg, files) if files else {}
    ranked = rank_slots_for_file(rel, cfg, detail)
    best = ranked[0] if ranked and ranked[0]['score'] >= ASSIGN_MIN_SCORE else None
    return {'ok': True, 'rel': rel, 'best': best, 'candidates': ranked[:7],
            'min_score': ASSIGN_MIN_SCORE}



# ---------------------------------------------------------------- 预览图
def _preview(kind, cfg, query):
    an = _analysis(cfg)
    import matplotlib.pyplot as plt

    def png(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
        plt.close(fig)
        return buf.getvalue()

    makers = {
        'n2': plotting.make_n2_series_figure,
        'esa': plotting.make_esa_figure,
        'o2': plotting.make_o2_series_figure,
        'orr': plotting.make_orr_overlay_figure,
        'meoh': plotting.make_meoh_figure,
        'mor': plotting.make_mor_overlay_figure,
        'curves': plotting.make_orr_mor_figure,
        'polarization': plotting.make_dmfc_polarization_figure,
        'power': plotting.make_dmfc_power_figure,
    }
    maker = makers.get(kind)
    if maker is None:
        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
        ax.text(0.5, 0.5, 'no such preview', ha='center', va='center')
        ax.axis('off')
        return png(fig)
    return png(maker(an))


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-电化学.docx' % stem


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
    try:
        workspace.save(out_dir, {'config': cfg}, cfg, '电化学', TEMPLATE,
                       extra={'files': getattr(an, 'files', {})})
    except Exception as exc:                         # noqa: BLE001
        logs.append('工作区快照写入失败：%s' % exc)
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    # 单次 socket 读写超时：半截请求最多占住线程这么久就断开。
    timeout = 30
    server_version = 'PChemEchem/1.0'

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
                kind = (q.get('kind') or ['n2'])[0]
                with PREVIEW_LOCK:
                    png = _preview(kind, cfg, q)
                return self._send(200, png, 'image/png')
            if path == '/api/scan':
                d = (q.get('dir') or [''])[0]
                return self._json(_scan(d))
            if path == '/api/pickdir':
                initial = (q.get('initial') or [''])[0]
                return self._json({'ok': True, 'path': pick_folder(initial)})
            if path == '/api/pickfile':
                initial = (q.get('initial') or [''])[0]
                exts = [e for e in (q.get('exts') or [''])[0].split(';') if e]
                return self._json({'ok': True,
                                   'path': pick_file(initial, exts or None)})
            if path == '/api/files':
                return self._json(_files(q))
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
                return self._json(_export(cfg))
            if u.path == '/api/files/auto':
                return self._json(_auto_map(urllib.parse.parse_qs(u.query)))
            if u.path == '/api/files/assign':
                body = self._body()          # 只能读一次（见审计结论 §24.4）
                return self._json(_assign(urllib.parse.parse_qs(u.query), body))
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
    """``GET /api/scan?dir=``：「扫描」按钮用，报数据齐不齐。

    与 ``Analysis.run()`` 走**同一套**槽位解析（``resolve_slots``），
    否则会出现「扫描说缺少 N2_1.txt，但计算其实已经自动匹配上了」的自相矛盾。
    ``dir`` 省略时回落到当前数据目录（与 /api/files 一致）。
    """
    if not data_dir:
        data_dir = _data_dir()
    if not data_dir or not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'files': []}
    files = echem.scan_directory(data_dir)
    cfg = STATE.get('config') or _config_from()
    detail = resolve_slots(data_dir, cfg, dataloc.list_data_files(
        data_dir, exts=('.txt',)))
    need = [v['key'] for v in
            (detail.get('file_' + k) or {} for k in
             ('n2_blank', 'n2_02', 'n2_05', 'o2_fast', 'o2_slow', 'o2_still',
              'meoh'))]
    missing, fuzzy = [], []
    for key in need:
        entry = detail.get(key) or {}
        status = entry.get('status')
        if status == 'fuzzy':
            fuzzy.append({'key': key, 'requested': entry.get('requested'),
                          'rel': entry.get('rel'), 'score': entry.get('score')})
        elif status not in ('default', 'manual'):
            missing.append(entry.get('requested') or key)
    return {'ok': True, 'data_dir': data_dir, 'count': len(files),
            'files': files[:200],
            'missing': missing, 'expected': len(need),
            'fuzzy': fuzzy,
            'ready': not missing}


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


def _free_port(preferred=8801):
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
    print('电化学（循环伏安法）实验报告生成器')
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
