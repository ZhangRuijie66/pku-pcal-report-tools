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
from pcal.analysis import (Analysis, PERSIST_KEYS, default_config,  # noqa: E402
                           default_config_with_saved)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'key': None, 'gcalc': None}
LOCK = threading.Lock()


# ---------------------------------------------------------------- 选择文件夹
def pick_folder(initial=None):
    """弹出系统「选择文件夹」窗口，返回绝对路径；取消时返回 ''。

    窗口由独立的子进程（tkinter）打开，避免阻塞服务进程；
    设置环境变量 PCAL_PICK_AUTO 可以直接返回指定目录（自动化测试用）。
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
        "kwargs = dict(parent=root, title='选择数据文件夹（光谱仪导出的 txt 所在目录）')\n"
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


# ---------------------------------------------------------------- 设置文件
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(cfg):
    data = {k: cfg.get(k) for k in PERSIST_KEYS if k in cfg}
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
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
    key = json.dumps({k: cfg.get(k) for k in ('data_dir', 'smooth_window', 'stray_mode',
                                              'stray', 'stray_a3', 'path_cm',
                                              'anchor_pad', 'beer_keys')},
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
            cal=it['cal_label']))
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
                      points=c['points'], fallback=c.get('fallback', False))
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
    }


# ---------------------------------------------------------------- 预览图
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
        if group == 'short':
            items = [an.samples[k] for k in ('A1', 'B1c', 'B2') if k in an.samples]
            labels = ['A1', 'B1', 'B2']
            xlim = (250, 620)
        else:
            items = [an.samples[k] for k in ('A2', 'A3c5', 'A4') if k in an.samples]
            labels = ['A2', 'A3', 'A4']
            xlim = (450, 880)
        return png(plotting.make_spectra_figure(items, labels=labels, xlim=xlim))
    if kind == 'voigt':
        a3k = (getattr(an, 'picks_mol', {}) or {}).get('A3') or 'A3c5b'
        it = an.samples.get(a3k)
        if it:
            fig = plotting.make_voigt_figure(it)
            if fig is not None:
                return png(fig)
    if kind == 'source':
        return png(plotting.make_source_figure(an.samples['A3c5'],
                                               an.samples['A3_DW']))
    # 空图
    fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
    ax.text(0.5, 0.5, 'no data', ha='center', va='center')
    ax.axis('off')
    return png(fig)


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
    an = _analysis(cfg)
    name = _safe_filename(_report_filename(cfg))
    stem = os.path.splitext(name)[0]
    out_dir = os.path.join(OUT_DIR, stem)
    os.makedirs(out_dir, exist_ok=True)
    out, note = _unique_path(os.path.join(out_dir, name))
    plots = os.path.join(out_dir, 'figures')
    logs = []
    rpt.build_report(an, cfg, out, plots, TEMPLATE,
                     progress=lambda m: logs.append(m))
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
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
        self._json({'ok': False, 'error': str(exc), 'trace': traceback.format_exc()}, 400)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
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
                return self._send(200, _preview(kind, cfg, q), 'image/png')
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
                cfg['gcalc'] = STATE.get('gcalc') or {}
                return self._json(_export(cfg))
            if u.path == '/api/gcalc/open':
                return self._json(_gcalc_open(self._body()))
            if u.path == '/api/settings':
                cfg = _config_from(self._body())
                data = save_settings(cfg)
                return self._json({'ok': True, 'saved': data,
                                   'config': default_config_with_saved(data),
                                   'has_saved': True})
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
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


# ---------------------------------------------------------------- 扫描数据目录
def _scan(data_dir):
    if not data_dir or not os.path.isdir(data_dir):
        return {'ok': False, 'error': '目录不存在：%s' % data_dir, 'files': []}
    files = uv.spectrum_files(data_dir)
    need = set()
    for c in uv.CALIBRATIONS:
        need.add(c['file'])
    for s in uv.SAMPLES:
        need.add(s['sample'])
        need.add(s['blank'])
    missing = [n for n in sorted(need)
               if not os.path.exists(os.path.join(data_dir, n))]
    return {'ok': True, 'data_dir': data_dir, 'count': len(files),
            'files': [os.path.relpath(p, data_dir) for p in files[:200]],
            'missing': missing, 'expected': len(need),
            'ready': not missing}


# ---------------------------------------------------------------- 启动
def _free_port(preferred=8791):
    for port in range(preferred, preferred + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
