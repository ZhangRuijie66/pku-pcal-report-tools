# -*- coding: utf-8 -*-
"""电导率实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算都在本机完成，不联网、不上传数据。
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
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
TEMPLATE = os.path.join(ROOT, 'templates', '电导率报告模板2026.docx')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import conduct                         # noqa: E402
from pcal import plotting                        # noqa: E402
from pcal import report as rpt                   # noqa: E402
from pcal import profile
from pcal import workspace
from pcal.atomicio import atomic_write_json
from pcal.analysis import (Analysis, PERSIST_KEYS, default_config,  # noqa: E402
                           default_config_with_saved)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'key': None}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()   # matplotlib 不是线程安全的


# ---------------------------------------------------------------- 选择文件夹
def pick_folder(initial=None):
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
        "kwargs = dict(parent=root, title='选择数据文件夹（电导率数据.json 所在目录）')\n"
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
            return profile.merge_saved(json.load(fh))
    except (OSError, ValueError):
        return profile.merge_saved({})


def save_settings(cfg):
    data = {k: cfg.get(k) for k in PERSIST_KEYS if k in cfg}
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
def _config_from(payload=None):
    cfg = default_config_with_saved(load_settings())
    if payload:
        for key, value in (payload.get('config') or {}).items():
            if key not in cfg:
                continue
            ref = cfg[key]
            if isinstance(ref, (int, float)) and not isinstance(ref, bool):
                try:
                    value = float(value) if value not in (None, '') else ref
                except (TypeError, ValueError):
                    value = ref
            cfg[key] = value
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
    fits = an.fits

    def fit_dict(f):
        return dict(lam_inf=f['lam_inf'], sigma_inf=f['sigma_inf'],
                    k=f['k'], sigma_k=f['sigma_k'], r=f['r'],
                    x=f['x'], y=f['y'])

    def table_dict(rows):
        return [dict(c=r['c'], kappa=r['kappa'], kappa_corr=r['kappa_corr'],
                     lam=r['lam'], sigma_kappa=r['sigma_kappa']) for r in rows]

    km, kf = an.kmean, an.kfit
    return {
        'ok': True,
        'config': cfg,
        'defaults': default_config(),
        'has_saved': bool(load_settings()),
        'settings_file': SETTINGS_FILE,
        'data': an.data,
        'data_path': an.data_path,
        'ctx': {k: an.ctx.get(k) for k in
                ('kappa_w_us', 'kcl_label', 'kcl_theory', 'kcl_after',
                 'cell_label', 'cell', 'temp', 'compensation')},
        'tables': {k: table_dict(v) for k, v in an.tables.items()},
        'fits': {k: fit_dict(v) for k, v in fits.items()},
        'lam_hac': an.esa.get('lam_inf'),
        'sigma_hac': an.esa.get('sigma'),
        'lit_table': an.lit_table,
        'kmean': dict(mean=km['mean'], sigma=km['sigma'],
                      bottles=[dict(k=b['k'], alpha=b['alpha'],
                                    sigma_k=b['sigma_k'],
                                    sigma_kappa=b['sigma_kappa'])
                               for b in km['bottles']]),
        'kfit': dict(K=kf['K'], sigma_K=kf['sigma_K'], k=kf['k'],
                     sigma_k=kf['sigma_k'], b=kf['b'], sigma_b=kf['sigma_b'],
                     r=kf['r'], x=kf['x'], y=kf['y']),
        'warnings': an.warnings,
        'out_dir': OUT_DIR,
        'data_dir': cfg.get('data_dir'),
        'template': TEMPLATE,
        'report_name': _report_filename(cfg),
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

    if kind.startswith('fit:'):
        return png(plotting.make_kohlrausch_figure(an, kind.split(':', 1)[1]))
    if kind == 'kfit':
        if an.kfit:
            return png(plotting.make_kfit_figure(an))
    if kind == 'kappa_c':
        return png(plotting.make_kappa_c_figure(an))
    fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
    ax.text(0.5, 0.5, 'no such preview', ha='center', va='center')
    ax.axis('off')
    return png(fig)


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-电导率.docx' % stem


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
    try:
        workspace.save(out_dir, {'config': cfg}, cfg, '电导率', TEMPLATE,
                       extra={'data_file': getattr(an, 'data_path', None)})
    except Exception as exc:                         # noqa: BLE001
        logs.append('工作区快照写入失败：%s' % exc)
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = 'PChemCond/1.0'

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
                kind = (q.get('kind') or ['kappa_c'])[0]
                with PREVIEW_LOCK:
                    png = _preview(kind, cfg, q)
                return self._send(200, png, 'image/png')
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
                return self._json(_export(cfg))
            if u.path == '/api/settings':
                cfg = _config_from(self._body())
                data = save_settings(cfg)
                return self._json({'ok': True, 'saved': data,
                                   'config': default_config_with_saved(data),
                                   'has_saved': True})
            if u.path == '/api/data':
                # 请求体只能读一次：Content-Length 的字节读走就没了，
                # 再调一次 _body() 会一直阻塞到客户端超时（请求线程永久挂死）。
                body = self._body()
                cfg = _config_from(body)
                payload = body.get('data') or {}
                # 用 load_data_ex 拿告警：坏文件已被改名留证时**不要再写回去**，
                # 否则默认参照数据会把用户（可能还能救回来的）读数顶掉。
                data, _path, data_warnings = conduct.load_data_ex(cfg.get('data_dir'))
                # 紧接着取留证路径：load_data_ex 每次调用都会重置这个状态，
                # 而下面 _analysis() 内部还会再读一次数据文件，晚取就丢了。
                corrupt_path = conduct.last_corrupt_path()
                for key in ('temp_c', 'kcl_label_uS', 'kcl_theory_uS',
                            'cell_constant_label', 'cell_constant',
                            'kcl_after_uS', 'kappa_w_uS', 'compensation'):
                    if key in payload:
                        data[key] = payload[key]
                if isinstance(payload.get('solutions'), dict):
                    for sk, sv in payload['solutions'].items():
                        if sk in data['solutions'] and isinstance(sv, dict):
                            data['solutions'][sk].update(sv)
                path = conduct.save_data(cfg.get('data_dir'), data)
                an = _analysis(cfg, force=True)
                s = _summary(an)
                s['saved_path'] = path
                if data_warnings:
                    s['corrupt_warnings'] = data_warnings
                if corrupt_path:
                    # 保存成功了，但这份数据是从"原文件已坏、已备份"的状态长出来的。
                    # 明确告诉用户原读数在哪，别让他以为坏文件被悄无声息地覆盖了。
                    s['corrupt_backup'] = corrupt_path
                    s['corrupt_notice'] = (
                        '原数据文件无法读取，已被完整备份为 %s（未删除）。'
                        '本次已按当前界面内容保存新文件；如需找回原读数，'
                        '把该备份文件改回 %s 即可。'
                        % (os.path.basename(corrupt_path), conduct.DATA_FILENAME))
                return self._json(s)
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


def _free_port(preferred=8751):
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
    print('电导率实验报告生成器')
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
