# -*- coding: utf-8 -*-
"""溶解热实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算都在本机完成，不联网、不上传数据。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
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
from pcal import plotting                     # noqa: E402
from pcal.analysis import (Analysis, SUBSTANCES, PERSIST_KEYS, default_config,
                           default_config_with_saved, default_round)  # noqa: E402
from pcal import report as rpt                # noqa: E402

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')

STATE = {'config': None, 'datasets': {}, 'analysis': None}


def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(cfg):
    saved = load_settings()
    for k in PERSIST_KEYS:
        if k in cfg:
            saved[k] = cfg[k]
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as fh:
            json.dump(saved, fh, ensure_ascii=False, indent=2, sort_keys=True)
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
def pick_folder(initial=None):
    """弹出系统「选择文件夹」窗口，返回绝对路径；取消时返回 ''。

    窗口由独立子进程（tkinter）打开，不阻塞服务进程。
    设置环境变量 PCAL_PICK_AUTO 可直接返回指定目录（自动化测试用）。
    """
    auto = os.environ.get('PCAL_PICK_AUTO')
    if auto:
        return os.path.normpath(auto) if os.path.isdir(auto) else ''
    code = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "try:\n"
        "    root.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "root.update()\n"
        "kwargs = dict(parent=root, title='选择数据文件夹')\n"
        "init = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if init:\n"
        "    kwargs['initialdir'] = init\n"
        "p = filedialog.askdirectory(**kwargs)\n"
        "root.destroy()\n"
        "sys.stdout.write(p or '')\n"
    )
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        out = subprocess.run([sys.executable, '-c', code, initial or ''],
                             capture_output=True, timeout=900, env=env)
    except (OSError, subprocess.SubprocessError):
        return ''
    txt = out.stdout.decode('utf-8', 'replace').strip()
    if not txt:
        return ''
    return os.path.normpath(txt) if os.path.isdir(txt) else ''


class Handler(BaseHTTPRequestHandler):
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
        self._send(code, json.dumps(obj, ensure_ascii=False, default=_json_default))

    def _error(self, exc):
        self._json({'ok': False, 'error': str(exc), 'trace': traceback.format_exc()}, 400)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
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

            if path == '/api/plot':
                q = urllib.parse.parse_qs(u.query)
                return self._plot((q.get('key') or ['0'])[0])
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

    def _plot(self, key):
        an = STATE.get('analysis')
        if an is None:
            return self._json({'ok': False, 'error': '尚未计算'}, 400)
        try:
            idx = int(key or 0)
        except ValueError:
            idx = 0
        it = next((r for r in an.rounds if r['index'] == idx), None)
        if it is None:
            return self._json({'ok': False, 'error': '没有第 %s 轮' % key}, 404)
        fig = plotting.make_figure(it['data'], it['reynolds_diss'], it['reynolds_heat'],
                                   it['fit1'], it['fit2'], it['fit3'])
        return self._send(200, plotting.figure_png(fig), 'image/png')

    def _fitplot(self):
        an = STATE.get('analysis')
        if an is None or an.fit is None:
            return self._json({'ok': False, 'error': '尚未计算'}, 400)
        fig = plotting.make_fit_figure(an.fit, an.diff)
        return self._send(200, plotting.figure_png(fig), 'image/png')

    def _calc(self, payload):
        base, datasets, an = build_state(payload)
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
        base, datasets, an = build_state(payload)
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
            rpt.build_report(an, base, out, plots, TEMPLATE, progress=progress)
        except PermissionError:
            return self._json({'ok': False,
                               'error': '无法写入 %s（文件被占用），请关闭正在打开该文档的 '
                                        'Word 后重试。' % out}, 400)
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

    if not locked(path):
        return path, ''
    root, ext = os.path.splitext(path)
    for i in range(2, max_tries + 1):
        cand = '%s (%d)%s' % (root, i, ext)
        if not locked(cand):
            return cand, ('原文件「%s」正被其它程序占用（可能开在 Word 里），'
                          '本次改为写入「%s」。' % (base, os.path.basename(cand)))
    cand = '%s-%s%s' % (root, time.strftime('%H%M%S'), ext)
    return cand, ('原文件「%s」正被其它程序占用，本次改为写入「%s」。'
                  % (base, os.path.basename(cand)))


def _default_data_dir():
    """
    数据文件夹的默认值：优先用上次记住的那个（换目录/换机器后也能接着用），
    再试开发机上的原始数据目录，最后退回本工具目录。
    """
    saved = (load_settings().get('data_dir') or '').strip()
    if saved and os.path.isdir(saved):
        return saved
    cands = [
        r'D:\北大\课程\26秋大三上\物理化学实验\2 溶解热',
        os.path.join(os.path.dirname(ROOT), '数据'),      # 可移植包：同级放个「数据」文件夹
        os.path.join(ROOT, '样例数据'),
    ]
    for c in cands:
        if os.path.isdir(c):
            return c
    return ROOT


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


def _free_port(preferred=8741):
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
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
