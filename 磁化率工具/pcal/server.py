# -*- coding: utf-8 -*-
"""磁化率测定实验报告生成 —— 本地网页服务。"""
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
TEMPLATE = os.path.join(ROOT, 'templates', '磁化率报告模板2026.docx')
DATA_DIR = os.path.join(ROOT, 'data')
DATA_FILE = os.path.join(DATA_DIR, '磁化率数据.json')
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import magnetic, plotting
from pcal import report as rpt
from pcal import profile
from pcal import workspace
from pcal.analysis import run_analysis, format_results

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
STATE = {'analysis': None, 'config': None, 'data': None, 'key': None}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()          # matplotlib 不是线程安全的，预览图串行生成

PERSIST_KEYS = ['student_name', 'student_id', 'group', 'group_no',
                'date', 'room_temp', 'pressure']


def default_config():
    return {
        'student_name': '',
        'student_id': '',
        'group': '',
        'group_no': '',
        'date': '',
        'room_temp': None,
        'pressure': None,
        'data_dir': '',
    }


def default_config_with_saved(saved):
    cfg = default_config()
    for key in PERSIST_KEYS:
        if key in saved and saved[key] not in (None, ''):
            cfg[key] = saved[key]
    return cfg


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


def load_data(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_data(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _current_data():
    if STATE.get('data') is not None:
        return STATE['data']
    if os.path.exists(DATA_FILE):
        try:
            return load_data(DATA_FILE)
        except (OSError, ValueError):
            pass
    return magnetic.sample_data()


def _analysis(cfg, data=None, force=False):
    data = data if data is not None else _current_data()
    key = json.dumps({'cfg': {k: cfg.get(k) for k in PERSIST_KEYS},
                      'data': data}, sort_keys=True, default=str)
    with LOCK:
        if not force and STATE['key'] == key and STATE['analysis'] is not None:
            return STATE['analysis']
        an = run_analysis(data)
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
        'temperature_C': an['temperature_C'],
        'temperature_K': an['temperature_K'],
        'chi_std': an['chi_std'],
        'samples': an['samples'],
        'formatted': format_results(an),
    }


def _export(cfg, data, progress=None):
    an = _analysis(cfg, data, force=True)

    # 文件名：空姓名/学号要有兜底，非法字符要清洗——否则会建出
    # 「--磁化率」「2400011877-None-磁化率」这种目录，姓名带 / 或 : 时直接 500。
    stem = _safe_filename(
        '%s-%s-磁化率' % (cfg.get('student_id') or '未署名',
                          cfg.get('student_name') or '未署名'))
    out_dir = os.path.join(OUT_DIR, stem)
    os.makedirs(out_dir, exist_ok=True)
    # 同名报告已存在（或正被 Word 占用）时自动加序号，别静默覆盖上次那份。
    out_path, note = _unique_path(os.path.join(out_dir, stem + '.docx'))
    plots_dir = os.path.join(out_dir, 'figures')
    os.makedirs(plots_dir, exist_ok=True)

    if not os.path.exists(TEMPLATE):
        if progress:
            progress('警告：模板文件不存在，将使用空白模板：%s' % TEMPLATE)
        template_path = None
    else:
        template_path = TEMPLATE

    rpt.build_report(an, cfg, out_path, plots_dir, template_path,
                     progress=progress, cover_tail_blanks=0)
    try:
        workspace.save(os.path.dirname(out_path), {'config': cfg, 'data': data},
                       cfg, '磁化率', template_path)
    except Exception as exc:                         # noqa: BLE001
        if progress:
            progress('工作区快照写入失败：%s' % exc)
    if note and progress:
        progress(note)

    return out_path, an


# ---------------------------------------------------------------- 文件名
def _safe_filename(name):
    """把 Windows 不允许的字符换成下划线；空名给兜底。"""
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip() or 'report.docx'


def _locked(path):
    """Word 打开文件时会建一个 ~$ 属主文件。"""
    d, f = os.path.dirname(path), os.path.basename(path)
    return os.path.exists(os.path.join(d, '~$' + f))


def _unique_path(path, max_tries=50):
    """目标已存在或被 Word 占用时加序号，返回 (路径, 提示)。"""
    if not os.path.exists(path) and not _locked(path):
        return path, ''
    base, ext = os.path.splitext(path)
    for i in range(2, max_tries + 2):
        cand = '%s(%d)%s' % (base, i, ext)
        if not os.path.exists(cand) and not _locked(cand):
            return cand, '目标文件被占用或已存在，已改名为 %s' % os.path.basename(cand)
    return path, ''


# ---------------------------------------------------------------- 绘图预览
def _placeholder_png():
    fig, ax = plotting.plt.subplots(figsize=(5, 3), dpi=100)
    ax.text(0.5, 0.5, '暂无可绘制的数据', ha='center', va='center',
            fontsize=14, color='#98a2b3')
    ax.axis('off')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    plotting.plt.close(fig)
    return buf.getvalue()


def _preview_png(kind, chart):
    if not chart:
        return _placeholder_png()
    buf = io.BytesIO()
    if kind == 'mu':
        plotting.plot_magnetic_moment(chart, buf, dpi=plotting.DPI_PREVIEW)
    elif kind == 'n':
        plotting.plot_unpaired_electrons(chart, buf, dpi=plotting.DPI_PREVIEW)
    elif kind == 'chi_m':
        plotting.plot_molar_susceptibility(chart, buf, dpi=plotting.DPI_PREVIEW)
    else:
        return _placeholder_png()
    return buf.getvalue() or _placeholder_png()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path):
        # 只允许读 web/ 目录里的文件：不做 normpath 校验的话
        # /static/../pcal/server.py、/static/../../profile.json 都能读到。
        rel = path.replace('\\', '/').lstrip('/')
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.normpath(WEB_DIR)):
            self.send_error(403)
            return
        if not os.path.exists(full):
            self.send_error(404)
            return
        ctype = 'text/html; charset=utf-8'
        if full.endswith('.js'):
            ctype = 'application/javascript; charset=utf-8'
        elif full.endswith('.css'):
            ctype = 'text/css; charset=utf-8'
        elif full.endswith('.png'):
            ctype = 'image/png'
        with open(full, 'rb') as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _png(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self._html('index.html')
        elif path == '/api/state':
            cfg = default_config_with_saved(load_settings())
            an = _analysis(cfg)
            self._json(_summary(an))
        elif path == '/api/preview':
            cfg = default_config_with_saved(load_settings())
            an = _analysis(cfg)
            kind = (query.get('kind') or ['chi_m'])[0]
            with PREVIEW_LOCK:
                png = _preview_png(kind, an.get('chart') or [])
            self._png(png)
        elif path.startswith('/static/'):
            self._html(path[len('/static/'):])
        elif path.startswith('/web/'):
            self._html(path[1:])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else '{}'

        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}

        if path == '/api/config':
            cfg = default_config_with_saved(load_settings())
            for key, value in payload.items():
                if key in cfg:
                    cfg[key] = value
            save_settings(cfg)
            self._json({'ok': True, 'config': cfg})
        elif path == '/api/sample':
            data = magnetic.sample_data()
            save_data(DATA_FILE, data)
            cfg = default_config_with_saved(load_settings())
            an = _analysis(cfg, data, force=True)
            self._json(_summary(an))
        elif path == '/api/data':
            try:
                data = payload.get('data', magnetic.sample_data())
                save_data(DATA_FILE, data)
                cfg = default_config_with_saved(load_settings())
                an = _analysis(cfg, data, force=True)
                self._json(_summary(an))
            except Exception as exc:                 # noqa: BLE001
                self._json({'ok': False, 'error': '数据无法计算：%s' % exc}, 400)
        elif path == '/api/export':
            cfg = default_config_with_saved(load_settings())
            for key, value in payload.get('config', {}).items():
                if key in cfg:
                    cfg[key] = value
            data = payload.get('data', _current_data())
            try:
                out_path, an = _export(cfg, data, progress=lambda msg: print(msg))
                self._json({'ok': True, 'path': out_path})
            except Exception as e:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(e)}, 500)
        else:
            self.send_error(404)


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


def _free_port(preferred=8781):
    for port in range(preferred, preferred + 60):
        if not _port_busy(port):
            return port
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description='磁化率测定实验报告生成工具')
    parser.add_argument('--port', type=int, default=0, help='服务端口')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    parser.add_argument('--test', action='store_true', help='无界面自检')
    args = parser.parse_args()

    if args.test:
        print('=== 磁化率测定工具自检 ===')
        cfg = default_config()
        data = magnetic.sample_data()
        out_path, an = _export(cfg, data, progress=lambda msg: print(msg))
        print('报告已生成：%s' % out_path)
        print('=== 自检完成 ===')
        return

    port = args.port or _free_port()
    if not port:
        print('错误：无法找到可用端口')
        sys.exit(1)

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d' % port
    print('磁化率测定实验报告生成工具')
    print('服务地址：%s' % url)
    print('按 Ctrl+C 停止服务')

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止服务...')
        httpd.shutdown()
        httpd.server_close()
        print('服务已停止')


if __name__ == '__main__':
    main()
