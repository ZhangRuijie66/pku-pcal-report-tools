# -*- coding: utf-8 -*-
"""溶解热实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算都在本机完成，不联网、不上传数据。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, 'web')
TEMPLATE = os.path.join(ROOT, 'templates', '溶解热报告模板2026.docx')
if not os.path.exists(TEMPLATE):
    TEMPLATE = os.path.join(ROOT, 'templates', '溶解热报告模板.docx')
ASSETS = os.path.join(ROOT, 'assets')
# 报告统一写到一个**工具目录外面**的共享文件夹里：
#   <工具目录的上一级>\实验报告输出\<学号>-<姓名>-<实验名>\
# 这样一个课程下所有实验的报告都在一处，方便集中管理和整体拷走。
# 想改位置就改这一行（或直接给 OUT_DIR 赋绝对路径）。
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import dissolution as ds            # noqa: E402
from pcal.jsonutil import core_json_dumps
from pcal import plotting                     # noqa: E402
from pcal.analysis import (Analysis, SUBSTANCES, PERSIST_KEYS, default_config,
                           default_config_with_saved, default_round)  # noqa: E402
from pcal import report as rpt                # noqa: E402
from pcal import profile
from pcal import workspace
from pcal import dataloc                      # noqa: E402  数据目录可移植定位
from pcal import filepick                     # noqa: E402  系统文件选择窗口
from pcal.atomicio import atomic_write_json   # noqa: E402

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')

STATE = {'config': None, 'datasets': {}, 'analysis': None}
LOCK = threading.Lock()   # STATE 的读写都在它里面
# matplotlib 的 pyplot 不是线程安全的：两个请求同时建图/存图会互相踩坏对方的
# figure（"2 并发就 100% 失败"）。建图到取回 PNG 字节这一段必须串行。
PREVIEW_LOCK = threading.Lock()
EXPORT_LOCK = threading.Lock()    # 导出串行：并发 / 连点两下时不能算出同一个文件名
MAX_BODY_BYTES = 8 * 1024 * 1024  # 请求体上限，超过直接 413，绝不去 rfile.read


class BodyTooLarge(ValueError):
    """Content-Length 非法或超过 MAX_BODY_BYTES。"""



def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return profile.merge_saved(data if isinstance(data, dict) else {})
    except (OSError, ValueError):
        return profile.merge_saved({})


def save_settings(cfg):
    saved = load_settings()
    for k in PERSIST_KEYS:
        if k in cfg:
            saved[k] = cfg[k]
    try:
        # 原子写盘：设置里含姓名/学号，写到一半崩掉会留下半截 JSON。
        atomic_write_json(SETTINGS_FILE, saved, sort_keys=True)
        return True
    except OSError:
        return False


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(repr(o))


# ---------------------------------------------------------------- 数据装载
def _read_csv_text(path):
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as fh:
        return fh.read()


def load_rounds(rounds_cfg):
    datasets = {}
    for i, r in enumerate(rounds_cfg):
        text = r.get('text')
        path = r.get('file')
        if not text:
            if not path or not os.path.exists(path):
                raise ValueError('第 %d 轮的数据文件不存在：%s' % (i + 1, path))
            text = _read_csv_text(path)
        key = path or ('round%d' % i)
        d = ds.parse_dissolution_csv(text, r.get('name') or os.path.basename(key))
        d.path = path          # 报告要用同名 .png（课程软件导出的雷诺校正图）
        datasets[key] = d
    return datasets


def build_state(payload):
    cfg = payload.get('config') or {}
    base = default_config_with_saved(load_settings())
    base.update({k: v for k, v in cfg.items() if k != 'rounds'})
    rounds = []
    for i, r in enumerate(payload.get('rounds') or []):
        d = default_round(i + 1)
        d.update(r)
        rounds.append(d)
    base['rounds'] = rounds
    datasets = load_rounds(rounds)
    an = Analysis(base)
    an.run(datasets)
    return base, datasets, an


def _chart(it):
    """把绘图所需的折线 / 散点降采样后送给前端（手写 SVG 作图）。"""
    d = it['data']
    t, y = d.t, d.y
    n = len(t)
    stride = max(1, n // 3000)
    rd, rh = it['reynolds_diss'], it['reynolds_heat']
    area = {'x': [], 'lin': [], 'curve': []}
    for lo, hi, kk, bb, reyn in (
            (t[it['fit1']['end']], rd['x0'], rd['k1'], rd['b1'], rd),
            (rd['x0'], t[it['fit2']['start']], rd['k2'], rd['b2'], rd),
            (t[it['fit2']['end']], rh['x0'], rh['k1'], rh['b1'], rh),
            (rh['x0'], t[it['fit3']['start']], rh['k2'], rh['b2'], rh)):
        if hi <= lo:
            continue
        m = max(2, int((hi - lo) / 0.5))
        xx = np.linspace(lo, hi, m)
        area['x'].append(xx.tolist())
        area['lin'].append((kk * xx + bb).tolist())
        area['curve'].append(reyn['smooth'](xx).tolist())
    xd, xh = rd['x_smooth'], rh['x_smooth']
    return {
        't': t[::stride].tolist(),
        'y': y[::stride].tolist(),
        'curve1_t': xd.tolist(), 'curve1_y': rd['smooth'](xd).tolist(),
        'curve2_t': xh.tolist(), 'curve2_y': rh['smooth'](xh).tolist(),
        'fit1': [float(it['fit1']['k']), float(it['fit1']['b'])],
        'fit2': [float(it['fit2']['k']), float(it['fit2']['b'])],
        'fit3': [float(it['fit3']['k']), float(it['fit3']['b'])],
        'fit_lines_t': [float(min(xd.min(), xh.min())), float(max(xd.max(), xh.max()))],
        'area': area,
        'endpoints': [
            {'t': float(t[it['fit1']['start']]), 'y': float(y[it['fit1']['start']]), 'c': 1},
            {'t': float(t[it['fit1']['end']]), 'y': float(y[it['fit1']['end']]), 'c': 1},
            {'t': float(t[it['fit2']['start']]), 'y': float(y[it['fit2']['start']]), 'c': 2},
            {'t': float(t[it['fit2']['end']]), 'y': float(y[it['fit2']['end']]), 'c': 2},
            {'t': float(t[it['fit3']['start']]), 'y': float(y[it['fit3']['start']]), 'c': 3},
            {'t': float(t[it['fit3']['end']]), 'y': float(y[it['fit3']['end']]), 'c': 3},
        ],
        'x1': float(rd['x0']), 'x2': float(rh['x0']),
        'T1_left': float(rd['T_left']), 'T1_right': float(rd['T_right']),
        'T2_left': float(rh['T_left']), 'T2_right': float(rh['T_right']),
    }


def _round_view(it, an):
    d = it['data']
    t = d.t
    return {
        'index': it['index'],
        'name': it['name'],
        'n': int(len(t)),
        'points': [int(p) for p in it['points']],
        'points_t': [round(float(t[p]), 2) for p in it['points']],
        'is_auto': it['is_auto'],
        'auto_points': [int(p) for p in (it['auto_points'] or it['points'])],
        'auto_note': it['auto_note'],
        'time_end': float(t[-1]),
        'x1': float(it['reynolds_diss']['x0']),
        'x2': float(it['reynolds_heat']['x0']),
        'T1_left': float(it['reynolds_diss']['T_left']),
        'T1_right': float(it['reynolds_diss']['T_right']),
        'T2_left': float(it['reynolds_heat']['T_left']),
        'T2_right': float(it['reynolds_heat']['T_right']),
        'dT_diss': float(it['dT_diss']),
        'dT_heat': float(it['dT_heat']),
        'Q_elec': float(it['Q_elec']),
        'Q': float(it['Q']),
        'sigma_Q': float(it['sigma_Q']),
        'sigma_Q_rel': float(it['sigma_Q_rel']),
        'R_heat': float(it['R_heat']),
        't_heat': float(it['t_heat']),
        'current': float(it['current']),
        'solute_mass': float(it['solute_mass']),
        'Mr': float(it['Mr']),
        'water_volume': float(it['water_volume']),
        'temperature_used_K': float(it['temperature']),
        'temperature_source': it['temperature_source'],
        'water_density': float(it['water_density']),
        'water_capacity': float(it['water_capacity']),
        'cum_m2': float(it['cum_m2']),
        'cum_Q': float(it['cum_Q']),
        'sum_n2': float(it['sum_n2']),
        'n0': float(it['n0']),
        'Qs': float(it['Qs']),
        'sigma_Qs': float(it['sigma_Qs']),
        'sigma_n0': float(it['sigma_n0']),
        'fit1': _fit_view(it['fit1']), 'fit2': _fit_view(it['fit2']),
        'fit3': _fit_view(it['fit3']),
        'params': it['params'],
        'software_Q_kJ': it.get('software_Q_kJ'),
        'chart': _chart(it),
    }


def _fit_view(f):
    return {'k': f['k'], 'b': f['b'], 'sk': f['stddev_k'], 'sb': f['stddev_b'],
            'R2': f['r_square'], 'start': f['start'], 'end': f['end']}


def _fit_payload(an):
    fit, diff = an.fit, an.diff
    return {
        'Qs0': fit['Qs0'], 'a': fit['a'],
        'sigma_Qs0': fit['sigma_Qs0'], 'sigma_a': fit['sigma_a'],
        'r_square': fit['r_square'], 'n1': fit['n1'],
        'n_half': an.half_concentration(),
        'n0': fit['n0'].tolist(), 'Qs': fit['Qs'].tolist(),
        'marks': {'n0': diff['n0'].tolist(), 'Qs': diff['Qs'].tolist(),
                  'Qs_n2': diff['Qs_n2'].tolist(), 'Qs_n0': diff['Qs_n0'].tolist(),
                  'Qd': diff['Qd'].tolist()},
    }


# ---------------------------------------------------------------- HTTP
def pick_folder(initial=None, title=None):
    """弹出系统「选择文件夹」窗口，返回绝对路径；取消时返回 ''。

    实现统一走共享层 ``pcal/filepick.py``：窗口由独立子进程（tkinter）打开，
    不阻塞服务进程；``PCAL_PICK_AUTO`` 环境变量可直接返回指定目录
    （自动化测试用），口径与其它 10 个模块完全一致。
    """
    return filepick.pick_folder(initial, title or '选择数据文件夹')


def pick_file(initial=None, exts=None, title=None):
    """弹出系统「选择文件」窗口，返回绝对路径；取消或后缀不符返回 ''。"""
    return filepick.pick_file(initial, exts, title or '选择数据文件')


class Handler(BaseHTTPRequestHandler):
    # 单次 socket 读写超时：半截请求最多占住线程这么久就断开。
    timeout = 30
    server_version = 'PChemDissolution/1.0'

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
        # 用 core_json_dumps：json.dumps 默认把 nan/inf 写成裸 NaN/Infinity，
        # 那不是合法 JSON，浏览器 res.json() 直接抛语法错 → 整页「初始化失败」。
        # 这里统一把非有限值转成 null（前端显示「—」），并禁用 allow_nan。
        self._send(code, core_json_dumps(obj))

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
        try:
            if path in ('/', '/index.html'):
                return self._file(os.path.join(WEB_DIR, 'index.html'),
                                  'text/html; charset=utf-8')
            if path.startswith('/static/'):
                return self._static(path[len('/static/'):])
            if path == '/api/state':
                return self._json(self._state_payload())
            if path == '/api/settings':
                return self._json({'ok': True,
                                   'config': default_config_with_saved(load_settings()),
                                   'defaults': default_config(),
                                   'settings_file': SETTINGS_FILE,
                                   'has_saved': bool(load_settings())})
            if path == '/api/scan':
                q = urllib.parse.parse_qs(u.query)
                d = (q.get('dir') or [''])[0]
                return self._json({'ok': True, 'files': _scan_dir(d),
                                   'software': _software_summary(d)})
            if path == '/api/pickdir':
                q = urllib.parse.parse_qs(u.query)
                initial = (q.get('initial') or [''])[0]
                return self._json({'ok': True, 'path': pick_folder(initial)})
            if path == '/api/pickfile':
                q = urllib.parse.parse_qs(u.query)
                initial = (q.get('initial') or [''])[0]
                exts = (q.get('exts') or [''])[0]
                return self._json({'ok': True,
                                   'path': pick_file(initial, exts or None)})
            if path == '/api/files':
                # 数据目录的文件清单（相对路径 + 总数），前端 PcalFiles 自己过滤。
                # 只读：不给绝对路径、不写盘。
                q = urllib.parse.parse_qs(u.query)
                d = (q.get('dir') or [''])[0]
                return self._json(_files_index(d))

            if path == '/api/fitplot':
                return self._fitplot()
            return self._json({'ok': False, 'error': 'not found: ' + path}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == '/api/calc':
                return self._calc(self._body())
            if u.path == '/api/export':
                return self._export(self._body())
            if u.path == '/api/settings':
                return self._save_settings(self._body())
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
        if not target.startswith(os.path.normpath(WEB_DIR)):
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

    # ---------- api
    def _state_payload(self):
        T = 298.15
        return {
            'ok': True,
            'config': default_config_with_saved(load_settings()),
            'defaults': default_config(),
            'settings_file': SETTINGS_FILE,
            'has_saved': bool(load_settings()),
            'substances': SUBSTANCES,
            'default_dir': _default_data_dir(),
            'output_dir': OUT_DIR,
            'template': TEMPLATE,
            'template_exists': os.path.exists(TEMPLATE),
            'assets': {'apparatus': os.path.exists(os.path.join(ASSETS, '装置图.png')),
                       'principle': os.path.exists(os.path.join(ASSETS, 'Qs-n0图.png'))},
            'water': {'density': ds.wp.water_density(T), 'capacity': ds.wp.water_capacity(T)},
            'constants': {'M_H2O': ds.M_H2O,
                          'sigma_current': ds.SIGMA_CURRENT,
                          'sigma_resistance': ds.SIGMA_RESISTANCE,
                          'sigma_time': ds.SIGMA_TIME,
                          'sigma_dt': ds.SIGMA_DT,
                          'e_balance': ds.E_BALANCE,
                          'e_volume': ds.E_VOLUME},
            'python': sys.version,
        }

    def _save_settings(self, payload):
        cfg = payload.get('config') or payload or {}
        ok = save_settings(cfg)
        return self._json({'ok': bool(ok),
                           'error': None if ok else '无法写入设置文件：' + SETTINGS_FILE,
                           'settings_file': SETTINGS_FILE,
                           'saved': {k: cfg.get(k) for k in PERSIST_KEYS if k in cfg}})

    def _fitplot(self):
        an = STATE.get('analysis')
        if an is None or an.fit is None:
            return self._json({'ok': False, 'error': '尚未计算'}, 400)
        # 建图 + savefig + 取回 bytes 必须整段串行：pyplot 是进程级单例，
        # 并发会互相 close/覆盖对方的 figure。
        with PREVIEW_LOCK:
            fig = plotting.make_fit_figure(an.fit, an.diff)
            png = plotting.figure_png(fig)
        return self._send(200, png, 'image/png')

    def _calc(self, payload):
        base, datasets, an = build_state(payload)
        # 三项必须一起更新：并发请求（页面同时触发 calc 与 export）时
        # 否则可能读到「新 config + 旧 analysis」的混合态。
        with LOCK:
            STATE['config'] = base
            STATE['datasets'] = datasets
            STATE['analysis'] = an
        rounds = [_round_view(it, an) for it in an.rounds]
        return self._json({
            'ok': True,
            'rounds': rounds,
            'fit': _fit_payload(an),
            'sigma_dT': an.sigma_dT,
            'sigma_m': an.sigma_m_single,
        })

    def _export(self, payload):
        """导出报告。整段串行：并发 / 连点两下时不能算出同一个文件名。"""
        with EXPORT_LOCK:
            return self._export_locked(payload)

    def _export_locked(self, payload):
        base, datasets, an = build_state(payload)
        # 三项必须一起更新：并发请求（页面同时触发 calc 与 export）时
        # 否则可能读到「新 config + 旧 analysis」的混合态。
        with LOCK:
            STATE['config'] = base
            STATE['datasets'] = datasets
            STATE['analysis'] = an
        stamp = time.strftime('%Y%m%d-%H%M%S')
        name = payload.get('filename') or _report_filename(base, stamp)
        name = _safe_filename(name)
        if not name.lower().endswith('.docx'):
            name += '.docx'
        # 每份报告单独占一个输出文件夹：报告与它用到的插图放在一起，方便整体拷走
        stem = os.path.splitext(name)[0]
        out_dir = os.path.join(OUT_DIR, stem)
        out = os.path.join(out_dir, name)
        out, note = _unique_path(out)
        plots = os.path.join(out_dir, 'figures')
        messages = []
        if note:
            messages.append(note)

        def progress(msg):
            messages.append(msg)

        try:
            # matplotlib 的 mathtext 解析器是进程级全局状态：预览与导出同时建图会互相踩
            # （实测 4 导出 + 12 预览 → 全报 ParseException）。这里也拿 PREVIEW_LOCK，
            # 让「建图 + savefig」全局串行。锁序 EXPORT_LOCK -> PREVIEW_LOCK，
            # 与只拿 PREVIEW_LOCK 的预览路径不冲突，不成环。
            with PREVIEW_LOCK:
                rpt.build_report(an, base, out, plots, TEMPLATE, progress=progress)
        except PermissionError:
            return self._json({'ok': False,
                               'error': '无法写入 %s（文件被占用），请关闭正在打开该文档的 '
                                        'Word 后重试。' % out}, 400)
        try:
            workspace.save(out_dir, payload, base, '溶解热', TEMPLATE,
                           extra={'datasets': sorted(datasets)})
        except Exception as exc:                     # noqa: BLE001
            messages.append('工作区快照写入失败：%s' % exc)
        return self._json({'ok': True, 'path': out, 'filename': os.path.basename(out),
                           'dir': os.path.dirname(out), 'messages': messages})


# ---------------------------------------------------------------- 工具
def _report_filename(cfg, stamp=None):
    parts = []
    sid = str(cfg.get('student_id') or '').strip()
    name = str(cfg.get('student_name') or '').strip()
    if sid:
        parts.append(sid)
    if name:
        parts.append(name)
    parts.append('溶解热')
    base = '-'.join(parts)
    if not sid and not name and stamp:
        base += '-' + stamp
    return base + '.docx'


def _safe_filename(name):
    bad = '<>:"/\\|?*'
    out = ''.join('_' if c in bad else c for c in str(name)).strip().strip('.')
    return out or '溶解热.docx'


def _unique_path(path, max_tries=50):
    """目标文件被 Word 占用时自动换名。"""
    d = os.path.dirname(path) or '.'
    base = os.path.basename(path)

    def locked(p):
        if os.path.exists(os.path.join(d, '~$' + os.path.basename(p))):
            return True
        if not os.path.exists(p):
            return False
        try:
            with open(p, 'a+b'):
                return False
        except OSError:
            return True

    if not os.path.exists(path) and not locked(path):
        return path, ''
    root, ext = os.path.splitext(path)
    for i in range(2, max_tries + 1):
        cand = '%s (%d)%s' % (root, i, ext)
        # 已存在也要换名：否则「连点两下生成报告」会静默覆盖上一份
        # （原来只查 Word 占用，文件存在但没打开时直接返回原路径）。
        if not os.path.exists(cand) and not locked(cand):
            if locked(path):
                why = ('原文件「%s」正被其它程序占用（可能开在 Word 里），'
                       '本次改为写入「%s」。' % (base, os.path.basename(cand)))
            else:
                why = ('目标文件「%s」已存在，本次改为写入「%s」。'
                       % (base, os.path.basename(cand)))
            return cand, why
    cand = '%s-%s%s' % (root, time.strftime('%H%M%S'), ext)
    return cand, ('原文件「%s」正被其它程序占用，本次改为写入「%s」。'
                  % (base, os.path.basename(cand)))


def _default_data_dir():
    """
    数据文件夹的默认值：优先用上次记住的那个（换目录/换机器后也能接着用），
    再按共享层 ``pcal/dataloc.find_data_dir`` 的优先级推一个**一定存在**的目录：
    套件根下的「数据」→ 课程原始数据目录「2 溶解热」（相对套件根，跟着包走）
    → 本工具目录里的「样例数据」→ 本工具目录本身。

    **不写死任何一台机器上的绝对路径**：可移植包解压到别人电脑上以后，
    这里推出的目录一定存在（最后一档是本工具目录），不会抛 FileNotFoundError。
    """
    saved = (load_settings().get('data_dir') or '').strip()
    return dataloc.find_data_dir(ROOT, saved,
                                 extra=('2 溶解热',),
                                 tool_subdirs=('样例数据',))


def _files_index(d):
    """``/api/files``：数据目录里的数据文件清单（相对路径，给前端搜索用）。

    只读端点。目录为空时退回默认数据目录，换机器打开也不会一片空白。
    """
    data_dir = (d or '').strip() or _default_data_dir()
    return filepick.index_payload(data_dir)


def _scan_dir(d):
    if not d or not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if not (os.path.isfile(p) and fn.lower().endswith('.csv')):
            continue
        try:
            with open(p, 'r', encoding='utf-8-sig', errors='replace') as fh:
                head = fh.read(600)
        except OSError:
            continue
        flat = head.replace(' ', '')
        if 'time(s)' not in flat or 'Delta_T' not in flat:
            continue
        if 'solute_mass(g)' not in flat or 'current(A)' not in flat:
            continue                                  # 不是溶解热数据
        out.append({'name': fn, 'path': p, 'size': os.path.getsize(p)})
    return out


def _software_summary(d):
    """读同目录下课程软件导出的 dissolution.csv（用户当时选定的取点与结果）。"""
    if not d:
        return {}
    p = os.path.join(d, 'dissolution.csv')
    if not os.path.exists(p):
        return {}
    try:
        return ds.load_summary_csv(p)
    except (OSError, ValueError):
        return {}


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


def _free_port(preferred=8741):
    for port in range(preferred, preferred + 40):
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
    os.makedirs(OUT_DIR, exist_ok=True)
    url = 'http://127.0.0.1:%d' % port
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print('=' * 56)
    print('  溶解热实验报告一键生成')
    print('  请在浏览器打开：%s' % url)
    print('  关闭本窗口即可停止服务。')
    print('=' * 56)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
