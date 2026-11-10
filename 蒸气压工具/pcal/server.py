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
from pcal.jsonutil import core_json_dumps
from pcal import report as rpt                          # noqa: E402
from pcal import dataloc, filepick
from pcal import profile
from pcal import workspace
from pcal.atomicio import atomic_write_json
from pcal.analysis import (default_config, default_config_with_saved,  # noqa: E402
                           load_data, save_data, PERSIST_KEYS)

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'data': None, 'key': None}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()   # matplotlib 不是线程安全的
EXPORT_LOCK = threading.Lock()    # 导出串行：并发 / 连点两下时不能算出同一个文件名
MAX_BODY_BYTES = 8 * 1024 * 1024  # 请求体上限，超过直接 413，绝不去 rfile.read


class BodyTooLarge(ValueError):
    """Content-Length 非法或超过 MAX_BODY_BYTES。"""


# ---------------------------------------------------------------- 数据目录
# 这四个「手工录入 + 导入文件」型模块的数据本体在 data/蒸气压数据.json；
# 「数据目录」指的是**从哪里翻文件来导入**。推导顺序（见 dataloc）：
#   记住的 data_dir ＞ 课程原始数据目录（相对套件根，跟着包走）
#   ＞ 本工具的 data/。最后一档一定存在，换机器解压后不会开天窗。
_COURSE_DIRS = ('物理化学实验/物理化学实验/蒸气压',)
_LOCAL_DATA = os.path.join(ROOT, 'data')


def default_data_dir(saved=''):
    """推一个**一定存在**的数据目录，绝不写死任何一台机器的绝对路径。"""
    return dataloc.find_data_dir(ROOT, saved,
                                 extra=_COURSE_DIRS + (_LOCAL_DATA,))


def _browse_dir(query=None, cfg=None):
    """当前浏览目录：请求参数 ＞ config ＞ settings.json ＞ 推导默认。"""
    asked = str(((query or {}).get('dir') or [''])[0] or '').strip()
    if asked:
        return asked
    saved = str((cfg or {}).get('data_dir') or '').strip()
    if not saved:
        saved = str(load_settings().get('data_dir') or '')
    return default_data_dir(saved)


def _files_payload(query):
    """GET /api/files：列出可导入的数据文件（相对路径，前端自己过滤）。"""
    with LOCK:
        cfg = STATE.get('config')
    d = _browse_dir(query, cfg)
    if not os.path.isdir(d):
        return {'ok': False, 'dir': d, 'files': [], 'total': 0,
                'error': '目录不存在：%s' % d}
    return filepick.index_payload(d, dataloc.list_data_files(d))


def _file_b64(query):
    """GET /api/fileb64：把浏览目录里的数据文件读成 base64。

    只读端点，且**只允许浏览目录内部 + 白名单后缀 + 体积上限**：
    路径先过 dataloc.resolve_rel（拒绝 ../ 穿越），不提供「按绝对路径读
    任意本地文件」的能力（那正是燃烧热工具下线 /api/file 的原因）。
    """
    with LOCK:
        cfg = STATE.get('config')
    d = _browse_dir(query, cfg)
    rel = str((query.get('rel') or [''])[0] or '').strip()
    path = dataloc.resolve_rel(d, rel) if (d and rel) else ''
    if not path or not os.path.isfile(path):
        return {'ok': False, 'error': '找不到文件：%s' % rel}
    if not path.lower().endswith(tuple(e.lower() for e in dataloc.DATA_EXTS)):
        return {'ok': False, 'error': '不是数据文件：%s' % rel}
    size = os.path.getsize(path)
    if size > MAX_BODY_BYTES:
        return {'ok': False,
                'error': '文件太大（%.1f MB）：%s' % (size / 1048576.0, rel)}
    with open(path, 'rb') as fh:
        raw = fh.read()
    return {'ok': True, 'name': os.path.basename(path),
            'dir': os.path.abspath(d), 'rel': rel, 'size': size,
            'b64': base64.b64encode(raw).decode('ascii')}



# ---------------------------------------------------------------- 设置
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
    # 快照必须在锁里取：否则并发 /api/data 与 /api/calc 时可能读到
    # 「新 config + 旧 data」的混合态，并把它渲染出去、再拿去导出。
    with LOCK:
        cfg = STATE.get('config')
        data = STATE.get('data')
    if cfg is None:
        cfg = default_config()
    if data is None:
        data = _current_data()
    return {
        'ok': True,
        'config': cfg,
        'defaults': default_config(),
        'has_saved': bool(load_settings()),
        'settings_file': SETTINGS_FILE,
        'data_file': DATA_FILE,
        'data_dir': default_data_dir(str((cfg or {}).get('data_dir') or '')),
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
    """导出报告。整段串行：并发 / 连点两下时不能算出同一个文件名。"""
    with EXPORT_LOCK:
        return _export_locked(cfg, data)


def _export_locked(cfg, data):
    an = _analysis(cfg, data)
    # 导出报告**不写数据文件**：保存由 /api/data 负责。原来这里会
    # save_data(DATA_FILE, STATE['data'])，于是「载入示例 → 计算 → 一键生成报告」
    # 会把用户真实的实验读数整个替换成示例数据，前端却只提示"报告已生成"。
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
    # 单次 socket 读写超时：半截请求最多占住线程这么久就断开。
    timeout = 30
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
                with PREVIEW_LOCK:
                    png = _preview(kind, cfg, data)
                return self._send(200, png, 'image/png')
            if path == '/api/files':
                return self._json(_files_payload(q))
            if path == '/api/fileb64':
                return self._json(_file_b64(q))
            if path == '/api/pickdir':
                initial = (q.get('initial') or [''])[0] or _browse_dir(q)
                return self._json({'ok': True,
                                   'path': filepick.pick_folder(initial)})
            if path == '/api/pickfile':
                initial = (q.get('initial') or [''])[0] or _browse_dir(q)
                exts = [e for e in (q.get('exts') or [''])[0].split(';') if e]
                return self._json({'ok': True, 'path': filepick.pick_file(
                    initial, exts or dataloc.DATA_EXTS)})
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
                # 写盘与 STATE 更新放同一把锁：原来 STATE['data'] 在锁外写，
                # 会与 _analysis() 里的 STATE.update 交叉，读到混合态。
                with LOCK:
                    save_data(DATA_FILE, data)
                    STATE['data'] = data
                return self._json({'ok': True, 'data_file': DATA_FILE})
            if u.path == '/api/import':
                kind = (q.get('kind') or ['file'])[0]
                body = self._body()
                return self._json(_import(kind, body))
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except BodyTooLarge as exc:
            return self._json({'ok': False, 'error': str(exc)}, 413)
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


def _free_port(preferred=8761):
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
