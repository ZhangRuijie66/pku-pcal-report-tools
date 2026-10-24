# -*- coding: utf-8 -*-
"""稀溶液法偶极矩实验报告生成 —— 本地网页服务。"""
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
TEMPLATE = os.path.join(ROOT, 'templates', '偶极矩报告模板2026.docx')
DATA_DIR = os.path.join(ROOT, 'data')
DATA_FILE = os.path.join(DATA_DIR, '偶极矩数据.json')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import dipole, plotting                      # noqa: E402
from pcal import report as rpt                         # noqa: E402
from pcal.analysis import (default_config, default_config_with_saved,  # noqa: E402
                           load_data, save_data, PERSIST_KEYS)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'data': None, 'key': None}
LOCK = threading.Lock()


# ---------------------------------------------------------------- 设置
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
    return dipole.normalize_data(data)


def _current_data():
    if STATE.get('data') is not None:
        return STATE['data']
    if os.path.exists(DATA_FILE):
        try:
            return _normalize_data(load_data(DATA_FILE))
        except (OSError, ValueError):
            pass
    return dipole.sample_data()


def _analysis(cfg, data=None, force=False):
    data = _normalize_data(data if data is not None else _current_data())
    key = json.dumps({'cfg': {k: cfg.get(k) for k in PERSIST_KEYS},
                      'data': data}, sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = dipole.analyze(data, cfg)
        STATE.update(analysis=an, config=cfg, data=data, key=key)
        return an


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
        'result': an,
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

    if kind == 'eps_fit':
        return png(plotting.make_eps_figure(an))
    if kind == 'rho_fit':
        return png(plotting.make_rho_figure(an))
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.text(0.5, 0.5, 'no data', ha='center', va='center')
    ax.axis('off')
    return png(fig)


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-偶极矩.docx' % stem


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
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- 导入
def _import(kind, payload):
    """kind=file：读 xlsx/csv 的数据处理表（数据处理.xlsx 布局）；
    kind=weigh：粘贴 m1, m2 两列；kind=cap：粘贴 C'样 一列。"""
    if kind == 'file':
        raw = base64.b64decode(payload.get('b64') or '')
        fname = str(payload.get('name') or '')
        rows = None
        if fname.lower().endswith(('.xlsx', '.xlsm', '.xls')):
            rows = _parse_workbook(io.BytesIO(raw))
        if rows is None:
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('gbk', 'replace')
            rows = _parse_text(text)
        if not rows.get('solutions'):
            return dict(ok=False, error='没有从文件里读到溶液数据行')
        return dict(ok=True, kind='file', rows=rows)
    if kind in ('weigh', 'cap'):
        rows = dipole.parse_numeric_rows(payload.get('text') or '')
        return dict(ok=True, kind=kind, rows=rows, count=len(rows))
    return dict(ok=False, error='未知导入类型：%s' % kind)


def _parse_workbook(fobj):
    import openpyxl
    wb = openpyxl.load_workbook(fobj, data_only=True)
    out = {'solutions': [], 'cyclo': None, 'butanol': None}
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            label = str(row[0]).strip() if row and row[0] is not None else ''
            nums = [v for v in row[1:] if isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if label in ('环己烷', '正丁醇'):
                rec = {'rho': nums[0] if nums else None}
                if len(nums) > 1:
                    rec['c_sample' if label == '环己烷' else 'n'] = (
                        [nums[1]] if label == '环己烷' else nums[1])
                out['cyclo' if label == '环己烷' else 'butanol'] = rec
                continue
            try:
                no = int(float(label))
            except ValueError:
                continue
            if 1 <= no <= 20 and len(nums) >= 4:
                # 数据处理表布局：m1, m2, x(算好), ρ, C'样 —— nums 里第 3 个是 x
                if len(nums) >= 5 and 0.005 < nums[2] < 0.5:
                    out['solutions'].append({'m1': nums[0], 'm2': nums[1],
                                             'rho': nums[3],
                                             'c_sample': [nums[4]]})
                else:
                    out['solutions'].append({'m1': nums[0], 'm2': nums[1],
                                             'rho': nums[2],
                                             'c_sample': [nums[3]]})
    return out


def _parse_text(text):
    """两列/多列文本：m1, m2（称量）或 C'样（电容）。"""
    rows = dipole.parse_numeric_rows(text)
    return {'solutions': [{'m1': r[0], 'm2': r[1]} for r in rows],
            'cyclo': None, 'butanol': None}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = 'PChemDipole/1.0'

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
                return self._json({'ok': True, 'data': dipole.sample_data()})
            if path == '/api/preview':
                cfg = STATE.get('config') or _config_from()
                data = STATE.get('data') or _current_data()
                kind = (q.get('kind') or ['eps_fit'])[0]
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
def _free_port(preferred=8831):
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
    print('稀溶液法偶极矩实验报告生成器')
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
