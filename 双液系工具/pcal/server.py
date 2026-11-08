# -*- coding: utf-8 -*-
"""双液体系沸点-成分图实验报告生成 —— 本地网页服务。"""
from __future__ import annotations

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
TEMPLATE = os.path.join(ROOT, 'templates', '双液系报告模板2026.docx')
DATA_DIR = os.path.join(ROOT, 'data')
DATA_FILE = os.path.join(DATA_DIR, '双液系数据.json')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import phase, plotting                       # noqa: E402
from pcal import report as rpt                         # noqa: E402
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
# 数据本体在 data/双液系数据.json；「数据目录」指从哪里挑**数据快照**来载入。
# 推导顺序见 dataloc：记住的 ＞ 课程原始数据目录（相对套件根）＞ 本工具 data/。
# 最后一档一定存在，换机器解压后不会开天窗。
_COURSE_DIRS = ('物理化学实验/物理化学实验/双液系',)
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
    """GET /api/files：列出数据目录里的文件（相对路径，前端自己过滤）。"""
    with LOCK:
        cfg = STATE.get('config')
    d = _browse_dir(query, cfg)
    if not os.path.isdir(d):
        return {'ok': False, 'dir': d, 'files': [], 'total': 0,
                'error': '目录不存在：%s' % d}
    return filepick.index_payload(d, dataloc.list_data_files(d))


def _load_snapshot(payload):
    """POST /api/load：把数据目录里的一份 .json 快照载入内存。

    **不写盘**（写盘仍只由 /api/data 负责）：载入后用户确认结果再点
    「保存数据」才落盘，避免「点一下就把真实读数换成另一份」那种静默覆盖。
    路径只允许数据目录内部 + .json（dataloc.resolve_rel 拒绝 ../ 穿越）。
    """
    with LOCK:
        cfg = STATE.get('config')
    d = _browse_dir({'dir': [str(payload.get('dir') or '')]}, cfg)
    rel = str(payload.get('rel') or '').strip()
    path = dataloc.resolve_rel(d, rel) if (d and rel) else ''
    if not path or not os.path.isfile(path):
        return {'ok': False, 'error': '找不到文件：%s' % rel}
    if not path.lower().endswith('.json'):
        return {'ok': False, 'error': '只能载入 .json 数据文件：%s' % rel}
    try:
        data = _normalize_data(load_data(path))
    except (OSError, ValueError) as exc:
        return {'ok': False, 'error': '读不出数据文件：%s' % exc}
    with LOCK:
        STATE['data'] = data
        STATE['key'] = None          # 让下一次 _analysis 强制重算
    return {'ok': True, 'name': os.path.basename(path), 'rel': rel,
            'dir': os.path.abspath(d), 'data': data}



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


def _num(v, default=None):
    try:
        return float(v) if v not in (None, '') else default
    except (TypeError, ValueError):
        return default


def _normalize_data(data):
    if not isinstance(data, dict):
        return phase.sample_data()

    def fnum(v):
        v = _num(v)
        return v if v is not None and abs(v) < 1e12 else None

    out = dict(data)
    for key in ('n_cyclohexane', 'n_ethanol'):
        if key in out:
            v = fnum(out[key])
            out[key] = v if v is not None else phase.sample_data()[key]
    curve = []
    for b in out.get('curve') or []:
        m1, m2, n = fnum(b.get('m1')), fnum(b.get('m2')), fnum(b.get('n'))
        if m1 is None and m2 is None:
            continue
        curve.append({'m1': m1, 'm2': m2, 'n': n})
    out['curve'] = curve
    out['curve_exclude'] = [int(i) for i in (out.get('curve_exclude') or [])
                            if str(i).strip() != '']
    boil = []
    for b in out.get('boiling') or []:
        vE, vC = fnum(b.get('v_ethanol')), fnum(b.get('v_cyclohexane'))
        if vE is None or vC is None:
            continue
        ng = [v for v in (fnum(x) for x in (b.get('n_g') or [])) if v is not None]
        nl = [v for v in (fnum(x) for x in (b.get('n_l') or [])) if v is not None]
        boil.append({'v_ethanol': vE, 'v_cyclohexane': vC,
                     'n_g': ng, 'n_l': nl,
                     'T_c': fnum(b.get('T_c')), 'p_kpa': fnum(b.get('p_kpa'))})
    out['boiling'] = boil
    return out


def _current_data():
    if STATE.get('data') is not None:
        return STATE['data']
    if os.path.exists(DATA_FILE):
        try:
            return _normalize_data(load_data(DATA_FILE))
        except (OSError, ValueError):
            pass
    return phase.sample_data()


def _analysis(cfg, data=None, force=False):
    data = _normalize_data(data if data is not None else _current_data())
    key = json.dumps({'cfg': {k: cfg.get(k) for k in PERSIST_KEYS},
                      'data': data}, sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = phase.analyze(data, cfg)
        STATE.update(analysis=an, config=cfg, data=data, key=key)
        return an


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
    curve = dict(an['curve'])
    azeo = {k: v for k, v in an['azeotrope'].items()
            if k not in ('vapor_curve', 'liquid_curve')}
    return {
        'ok': True, 'config': cfg, 'defaults': default_config(),
        'has_saved': bool(load_settings()), 'settings_file': SETTINGS_FILE,
        'data_file': DATA_FILE,
        'data_dir': default_data_dir(str((cfg or {}).get('data_dir') or '')),
        'data': data,
        'curve': curve, 'rows': an['rows'], 'azeotrope': azeo,
        'sigma_n': an['sigma_n'], 'sigma_parts': an['sigma_parts'],
        'lit_w': an['lit_w'], 'lit_x': an['lit_x'], 'lit_T_K': an['lit_T_K'],
        'deviation': an['deviation'], 'x_label': an['x_label'],
        'mode': an['mode'], 'warnings': an['warnings'],
        'out_dir': OUT_DIR, 'template': TEMPLATE,
        'report_name': _report_filename(cfg),
    }


# ---------------------------------------------------------------- 预览
def _preview(kind, cfg, data, query):
    an = _analysis(cfg, data)
    import matplotlib.pyplot as plt

    def png(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=plotting.DPI_PREVIEW,
                    bbox_inches='tight')
        plt.close(fig)
        return buf.getvalue()

    if kind == 'curve':
        has_removed = bool(an['curve']['removed'])
        return png(plotting.make_curve_figure(
            an['curve'], 'fit_all' if has_removed else 'fit'))
    if kind == 'curve_refit' and an['curve']['removed']:
        return png(plotting.make_curve_figure(an['curve'], 'fit'))
    if kind == 'phase':
        return png(plotting.make_phase_figure(an['rows'], an['azeotrope'],
                                              an['mode']))
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.text(0.5, 0.5, 'no data', ha='center', va='center')
    ax.axis('off')
    return png(fig)


# ---------------------------------------------------------------- 导出
def _report_filename(cfg):
    name = str(cfg.get('student_name') or '').strip()
    sid = str(cfg.get('student_id') or '').strip()
    stem = '-'.join([p for p in (sid, name) if p]) or '未命名'
    return '%s-双液系.docx' % stem


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
                       '双液系', TEMPLATE)
    except Exception as exc:                         # noqa: BLE001
        logs.append('工作区快照写入失败：%s' % exc)
    return dict(ok=True, path=out, note=note, logs=logs, figures=plots)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    # 单次 socket 读写超时：半截请求最多占住线程这么久就断开。
    timeout = 30
    server_version = 'PChemPhase/1.0'

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
                return self._json(_summary(_analysis(cfg)))
            if path == '/api/settings':
                return self._json({'ok': True,
                                   'config': default_config_with_saved(load_settings()),
                                   'defaults': default_config(),
                                   'settings_file': SETTINGS_FILE,
                                   'has_saved': bool(load_settings())})
            if path == '/api/sample':
                return self._json({'ok': True, 'data': phase.sample_data()})
            if path == '/api/preview':
                cfg = STATE.get('config') or _config_from()
                data = STATE.get('data') or _current_data()
                kind = (q.get('kind') or ['curve'])[0]
                with PREVIEW_LOCK:
                    png = _preview(kind, cfg, data, q)
                return self._send(200, png, 'image/png')
            if path == '/api/files':
                return self._json(_files_payload(q))
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
        except Exception as exc:                        # noqa: BLE001
            return self._error(exc)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == '/api/calc':
                body = self._body()
                cfg = _config_from(body)
                return self._json(_summary(_analysis(cfg, body.get('data'), force=True)))
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
            if u.path == '/api/load':
                return self._json(_load_snapshot(self._body()))
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except BodyTooLarge as exc:
            return self._json({'ok': False, 'error': str(exc)}, 413)
        except Exception as exc:                        # noqa: BLE001
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
        except Exception as exc:                        # noqa: BLE001
            return self._error(exc)

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


def _free_port(preferred=8821):
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
    print('双液体系沸点-成分图实验报告生成器')
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
