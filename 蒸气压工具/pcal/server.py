# -*- coding: utf-8 -*-
"""液体饱和蒸气压实验报告生成 —— 本地网页服务。"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, 'web')
TEMPLATE = os.path.join(ROOT, 'templates', '蒸气压报告模板2026.docx')
DATA_DIR = os.path.join(ROOT, 'data')
DATA_FILE = os.path.join(DATA_DIR, '蒸气压数据.json')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import plotting, vapor                        # noqa: E402
from pcal import report as rpt                          # noqa: E402
from pcal import profile
from pcal import workspace
from pcal.analysis import (default_config, default_config_with_saved,  # noqa: E402
                           load_data, save_data, PERSIST_KEYS)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'data': None, 'key': None}
LOCK = threading.Lock()


# ---------------------------------------------------------------- 设置
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            return profile.merge_saved(json.load(fh))
    except (OSError, ValueError):
        return profile.merge_saved({})


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


def _coerce(cfg, payload):
    base = default_config()
    for key, value in (payload.get('config') or {}).items():
        if key not in base:
            continue
        ref = base[key]
        if isinstance(ref, bool):
            cfg[key] = bool(value)
        elif isinstance(ref, (int, float)) and not isinstance(ref, bool):
            try:
                cfg[key] = float(value) if value not in (None, '') else ref
            except (TypeError, ValueError):
                cfg[key] = ref
        else:
            cfg[key] = value
    return cfg


def _config_from(payload=None):
    cfg = default_config_with_saved(load_settings())
    if payload:
        cfg = _coerce(cfg, payload)
    return cfg


def _normalize_data(data):
    return vapor.normalize_data(data)


def _current_data():
    if STATE.get('data') is not None:
        return STATE['data']
    if os.path.exists(DATA_FILE):
        try:
            return _normalize_data(load_data(DATA_FILE))
        except (OSError, ValueError):
            pass
    return vapor.sample_data()


def _analysis(cfg, data=None, force=False):
    data = _normalize_data(data if data is not None else _current_data())
    key = json.dumps({'cfg': {k: cfg.get(k) for k in PERSIST_KEYS},
                      'data': data}, sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = vapor.analyze(data, cfg)
        STATE.update(analysis=an, config=cfg, data=data, key=key)
        return an


def _liquid_payload(m):
    f = m.get('fit') or {}
    shift = m.get('shift')
    return dict(
        key=m['key'], name=m['name'], method=m['method'], section=m['section'],
        atm=[[float(r[0]), float(r[1])] for r in m['atm']],
        atm_avg=m.get('atm_avg'),
        series=[[float(r[0]), float(r[1])] for r in m['series']],
        fit=dict(
            A=f.get('A'), sigma_A=f.get('sigma_A'),
            B=f.get('B'), sigma_B=f.get('sigma_B'),
            r2=f.get('r2'), n=f.get('n'),
            tb=f.get('tb'), sigma_tb=f.get('sigma_tb'),
            dh_kJ=f.get('dh_kJ'), sigma_dh_kJ=f.get('sigma_dh_kJ'),
            ds=f.get('ds'), sigma_ds=f.get('sigma_ds')) if f else None,
        points=(f.get('points') if f else None),
        shift=dict(shift=shift['shift'], dh_kJ=shift['fit']['dh_kJ'],
                   sigma_dh_kJ=shift['fit']['sigma_dh_kJ'],
                   A=shift['fit']['A'], sigma_A=shift['fit']['sigma_A'],
                   B=shift['fit']['B'], sigma_B=shift['fit']['sigma_B'])
        if shift else None,
        lit=m.get('lit') or {},
        rel_tb=m.get('rel_tb'), rel_dh=m.get('rel_dh'),
        ds_minus_trouton=m.get('ds_minus_trouton'),
    )


def _summary(an):
    cfg = STATE.get('config') or default_config()
    data = STATE.get('data') or _current_data()
    return {
        'ok': True,
        'config': cfg,
        'defaults': default_config(),
        'has_saved': bool(load_settings()),
        'settings_file': SETTINGS_FILE,
        'data_file': DATA_FILE,
        'data': data,
        'water': _liquid_payload(an['water']),
        'cyclo': _liquid_payload(an['cyclo']),
        'trouton': an['trouton'],
        'p1': an['p1'],
        'warnings': an['warnings'],
        'out_dir': OUT_DIR,
        'template': TEMPLATE,
        'report_name': _report_filename(cfg),
    }


# ---------------------------------------------------------------- 预览
def _preview(kind, cfg, data):
    an = _analysis(cfg, data)
    import matplotlib.pyplot as plt

    def png(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=plotting.DPI_PREVIEW,
                    bbox_inches='tight')
        plt.close(fig)
        return buf.getvalue()

    m = an['water'] if kind.startswith('water') else an['cyclo']
    if not m.get('fit'):
        fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
        ax.text(0.5, 0.5, 'no data', ha='center', va='center')
        ax.axis('off')
        return png(fig)
    if kind.endswith('_curve'):
        return png(plotting.make_curve_figure(m))
    if kind.endswith('_fit'):
        return png(plotting.make_fit_figure(m))
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.text(0.5, 0.5, 'no data', ha='center', va='center')
    ax.axis('off')
    return png(fig)


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-蒸气压.docx' % stem


def _safe_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip() or 'report.docx'


def _locked(path):
    d, f = os.path.dirname(path), os.path.basename(path)
    return os.path.exists(os.path.join(d, '~$' + f))


def _unique_path(path, max_tries=50):
    if not os.path.exists(path) and not _locked(path):
        return path, ''
    base, ext = os.path.splitext(path)
    for i in range(2, max_tries + 2):
        cand = '%s(%d)%s' % (base, i, ext)
        if not os.path.exists(cand) and not _locked(cand):
            return cand, '目标文件被占用或已存在，已改名为 %s' % os.path.basename(cand)
    return path, ''


def _export(cfg, data):
    an = _analysis(cfg, data)
    save_data(DATA_FILE, STATE['data'])
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
        workspace.save(out_dir, {'config': cfg, 'data': data}, cfg,
                       '蒸气压', TEMPLATE)
    except Exception as exc:                         # noqa: BLE001
        logs.append('工作区快照写入失败：%s' % exc)
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- 导入
def _import(kind, payload):
    """kind=file：整个 xlsx/csv 自动分两支；kind=water/cyclo：粘贴的 p,t 文本。"""
    if kind == 'file':
        raw = base64.b64decode(payload.get('b64') or '')
        fname = str(payload.get('name') or '')
        rows = None
        if fname.lower().endswith(('.xlsx', '.xlsm', '.xls')):
            rows = vapor.parse_workbook(io.BytesIO(raw))
        if rows is None:
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('gbk', 'replace')
            rows = vapor.parse_numeric_rows(text)
        if not rows:
            return dict(ok=False, error='没有从文件里读到 (p, t) 数据行')
        water, cyclo = vapor.split_branches(rows)
        return dict(ok=True, kind='file', count=len(rows),
                    water=water, cyclo=cyclo)
    if kind in ('water', 'cyclo'):
        rows = vapor.parse_numeric_rows(payload.get('text') or '')
        return dict(ok=True, kind=kind, rows=rows, count=len(rows))
    return dict(ok=False, error='未知导入类型：%s' % kind)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = 'PChemVapor/1.0'

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
        self._send(code, json.dumps(obj, ensure_ascii=False,
                                    default=_json_default))

    def _error(self, exc):
        self._json({'ok': False, 'error': str(exc),
                    'trace': traceback.format_exc()}, 400)

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
            if path == '/api/sample':
                return self._json({'ok': True, 'data': vapor.sample_data()})
            if path == '/api/preview':
                cfg = STATE.get('config') or _config_from()
                data = STATE.get('data') or _current_data()
                kind = (q.get('kind') or ['water_curve'])[0]
                return self._send(200, _preview(kind, cfg, data), 'image/png')
            return self._json({'ok': False, 'error': 'not found: ' + path}, 404)
        except Exception as exc:                       # noqa: BLE001
            return self._error(exc)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == '/api/calc':
                body = self._body()
                cfg = _config_from(body)
                an = _analysis(cfg, body.get('data'), force=True)
                return self._json(_summary(an))
            if u.path == '/api/export':
                body = self._body()
                cfg = _config_from(body)
                return self._json(_export(cfg, body.get('data')))
            if u.path == '/api/settings':
                cfg = _config_from(self._body())
                data = save_settings(cfg)
                return self._json({'ok': True, 'saved': data,
                                   'config': default_config_with_saved(data),
                                   'has_saved': True})
            if u.path == '/api/data':
                body = self._body()
                data = _normalize_data(body.get('data'))
                save_data(DATA_FILE, data)
                STATE['data'] = data
                return self._json({'ok': True, 'data_file': DATA_FILE})
            if u.path == '/api/import':
                kind = (q.get('kind') or ['file'])[0]
                body = self._body()
                return self._json(_import(kind, body))
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except Exception as exc:                       # noqa: BLE001
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
        except Exception as exc:                       # noqa: BLE001
            return self._error(exc)

    # ---------- 静态文件
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


# ---------------------------------------------------------------- 启动
def _free_port(preferred=8761):
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
    except Exception as exc:                           # noqa: BLE001
        print('⚠ 初次计算失败：%s' % exc)

    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d' % port
    print('液体饱和蒸气压实验报告生成器')
    print('  数据文件：%s' % DATA_FILE)
    print('  输出目录：%s' % OUT_DIR)
    print('  地址：%s   （Ctrl+C 退出）' % url)
    if open_browser:
        threading.Thread(target=lambda: (__import__('time').sleep(0.6),
                                         webbrowser.open(url)), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已退出')
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
