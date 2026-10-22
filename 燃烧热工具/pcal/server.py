# -*- coding: utf-8 -*-
"""燃烧热实验报告一键生成 —— 本地网页服务。

启动后自动打开浏览器；所有计算在本机完成，不联网、不上传数据。
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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, 'web')
TEMPLATE = os.path.join(ROOT, 'templates', '燃烧热报告模板2026.docx')
if not os.path.exists(TEMPLATE):                       # 兼容旧模板
    TEMPLATE = os.path.join(ROOT, 'templates', '燃烧热报告模板.docx')
ASSETS = os.path.join(ROOT, 'assets')
# 报告统一写到一个**工具目录外面**的共享文件夹里：
#   <工具目录的上一级>\实验报告输出\<学号>-<姓名>-<实验名>\
# 这样一个课程下所有实验的报告都在一处，方便集中管理和整体拷走。
# 想改位置就改这一行（或直接给 OUT_DIR 赋绝对路径）。
OUT_DIR = os.path.join(os.path.dirname(ROOT), '实验报告输出')

sys.path.insert(0, ROOT)

from pcal import combustion as cb          # noqa: E402
from pcal import plotting                  # noqa: E402
from pcal.analysis import (Analysis, SUBSTANCES, PERSIST_KEYS, default_config,
                           default_config_with_saved, default_round)  # noqa: E402
from pcal import report as rpt             # noqa: E402

SETTINGS_FILE = os.path.join(ROOT, 'settings.json')

STATE = {
    'config': None,
    'datasets': {},     # 文件名 -> CombustionData
    'analysis': None,
    'points': {},       # index -> [s1,e1,s2,e2]
}


def load_settings():
    """读取上次记住的封面 / 实验条件。"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(cfg):
    """把要记住的字段写进设置文件（只覆盖这些字段，不动其它）。"""
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
    """rounds_cfg: [{file|text, name, role, substance, params, sample_mass, points}]"""
    datasets = {}
    for i, r in enumerate(rounds_cfg):
        text = r.get('text')
        if not text:
            path = r.get('file')
            if not path or not os.path.exists(path):
                raise ValueError('第 %d 轮的数据文件不存在：%s' % (i + 1, path))
            text = _read_csv_text(path)
        key = r.get('file') or ('round%d' % i)
        datasets[key] = cb.parse_combustion_csv(text, r.get('name') or os.path.basename(key))
    return datasets


def build_state(payload):
    cfg = payload.get('config') or {}
    base = default_config_with_saved(load_settings())     # 先铺上记住的默认值
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


def _round_view(it, an, points):
    d = it['data']
    t = d.t
    y = d.y
    x0 = it['reynolds']['x0']
    return {
        'index': it['index'],
        'name': it['name'],
        'role': it['role'],
        'n': int(len(t)),
        'points': [int(p) for p in points],
        'points_t': [round(float(t[p]), 2) for p in points],
        'is_auto': it['is_auto'],
        'auto_points': [int(p) for p in it['auto_points']],
        'auto_method': it.get('auto_method', ''),
        'auto_warning': it.get('auto_warning', ''),
        'time_end': float(t[-1]),
        'x0': float(x0),
        'T_left': float(it['reynolds']['T_left']),
        'T_right': float(it['reynolds']['T_right']),
        'dT': float(it['dT']),
        'S_left': float(it['reynolds']['S_left']),
        'S_right': float(it['reynolds']['S_right']),
        'k1': it['fit1']['k1'], 'b1': it['fit1']['b1'], 'R2_1': it['fit1']['r_square'],
        'sk1': it['fit1']['stddev_k1'], 'sb1': it['fit1']['stddev_b1'],
        'k2': it['fit2']['k2'], 'b2': it['fit2']['b2'], 'R2_2': it['fit2']['r_square'],
        'sk2': it['fit2']['stddev_k2'], 'sb2': it['fit2']['stddev_b2'],
        'sample_mass': it['sample_mass'],
        'D_Cw': it['D_Cw'],
        'temperature_used_K': it['temperature'],
        'temperature_source': it.get('temperature_source', ''),
        'params': it['params'],
        'chart': _chart(it),
        'results': _results(it, an),
    }


def _chart(it):
    """把绘图所需的折线/散点降采样后送给前端（SVG 交互作图）。"""
    d = it['data']
    t, y = d.t, d.y
    n = len(t)
    stride = max(1, n // 3000)
    reyn = it['reynolds']
    xs = reyn['x_smooth']
    sy = reyn['smooth'](xs)
    x0 = reyn['x0']
    area = {'x': [], 'lin': [], 'curve': []}
    for lo, hi, kk, bb in ((t[it['fit1']['end']], x0, reyn['k1'], reyn['b1']),
                           (x0, t[it['fit2']['start']], reyn['k2'], reyn['b2'])):
        m = max(2, int((hi - lo) / 0.5))
        xx = np.linspace(lo, hi, m)
        area['x'].append(xx.tolist())
        area['lin'].append((kk * xx + bb).tolist())
        area['curve'].append(reyn['smooth'](xx).tolist())
    return {
        't': t[::stride].tolist(),
        'y': y[::stride].tolist(),
        'curve_t': xs.tolist(),
        'curve_y': sy.tolist(),
        'fit1': [float(reyn['k1']), float(reyn['b1'])],
        'fit2': [float(reyn['k2']), float(reyn['b2'])],
        'fit_lines_t': [float(xs.min()), float(xs.max())],
        'area': area,
        'endpoints': [
            {'t': float(t[it['fit1']['start']]), 'y': float(y[it['fit1']['start']]), 'c': 1},
            {'t': float(t[it['fit1']['end']]), 'y': float(y[it['fit1']['end']]), 'c': 1},
            {'t': float(t[it['fit2']['start']]), 'y': float(y[it['fit2']['start']]), 'c': 2},
            {'t': float(t[it['fit2']['end']]), 'y': float(y[it['fit2']['end']]), 'c': 2},
        ],
        'T_left': float(reyn['T_left']),
        'T_right': float(reyn['T_right']),
        'x0': float(x0),
    }


def _results(it, an):
    r = {
        'dT': it['dT'],
        'sum_q': it['sum_q'],
        'Q_cotton': it['Q_cotton'],
        'Q_nickel': it['Q_nickel'],
        'D_Cw': it['D_Cw'],
        'Qv_per_gram': it.get('Qv_per_gram'),
        'sigma_Qv_per_gram': it.get('sigma_Qv_per_gram'),
        'sample_mass': it['sample_mass'],
    }
    if it['role'] == 'standard':
        r['Qv_benzoic'] = it.get('Qv_benzoic')
        r['W'] = it.get('W')
        r['sigma_W'] = it.get('sigma_W')
    mol = an.molar(it)
    if mol:
        r['molar'] = mol
    return r


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
    server_version = 'PChemReport/1.0'

    def log_message(self, fmt, *args):
        if os.environ.get('PCAL_DEBUG'):
            sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    # ---------- helpers
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
        self._json({'ok': False, 'error': str(exc),
                    'trace': traceback.format_exc()}, 400)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode('utf-8'))

    # ---------- routes
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        try:
            if path in ('/', '/index.html'):
                return self._file(os.path.join(WEB_DIR, 'index.html'), 'text/html; charset=utf-8')
            if path.startswith('/static/'):
                rel = path[len('/static/'):]
                return self._static(rel)
            if path == '/api/state':
                return self._json(self._state_payload())
            if path == '/api/settings':
                return self._json({'ok': True, 'config': default_config_with_saved(load_settings()),
                                   'defaults': default_config(),
                                   'settings_file': SETTINGS_FILE,
                                   'has_saved': bool(load_settings())})
            if path == '/api/file':
                q = urllib.parse.parse_qs(u.query)
                p = (q.get('path') or [''])[0]
                if not p or not os.path.exists(p):
                    return self._json({'ok': False, 'error': '文件不存在'}, 404)
                return self._json({'ok': True, 'text': _read_csv_text(p)})
            if path == '/api/plot':
                q = urllib.parse.parse_qs(u.query)
                key = (q.get('key') or [''])[0]
                return self._plot(key)
            if path == '/api/scan':
                q = urllib.parse.parse_qs(u.query)
                d = (q.get('dir') or [''])[0]
                return self._json({'ok': True, 'files': _scan_dir(d)})
            if path == '/api/pickdir':
                q = urllib.parse.parse_qs(u.query)
                initial = (q.get('initial') or [''])[0]
                return self._json({'ok': True, 'path': pick_folder(initial)})

            if path == '/api/results':
                return self._json(self._results_payload())
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
                                   'defaults': default_config(),
                                   'has_saved': False})
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
        ctype = {'.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
                 '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'}.get(
            ext, 'application/octet-stream')
        return self._file(target, ctype)

    def _file(self, path, ctype):
        if not os.path.exists(path):
            return self._json({'ok': False, 'error': 'missing ' + path}, 404)
        with open(path, 'rb') as fh:
            data = fh.read()
        self._send(200, data, ctype)

    # ---------- api
    def _state_payload(self):
        # 注意：这里返回“出厂默认值 + 已保存的默认值”，不是上一次提交的参数。
        # 否则每新开一个页面都会继承上次会话的选择，看起来像默认值自己变了。
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
            'python': sys.version,
        }

    def _save_settings(self, payload):
        """把当前封面 / 实验条件存为默认值。"""
        cfg = payload.get('config') or payload or {}
        ok = save_settings(cfg)
        return self._json({'ok': bool(ok),
                           'error': None if ok else '无法写入设置文件：' + SETTINGS_FILE,
                           'settings_file': SETTINGS_FILE,
                           'saved': {k: cfg.get(k) for k in PERSIST_KEYS if k in cfg}})

    def _plot(self, key):
        """按轮次序号生成课程软件样式的 PNG（用于前端预览）。"""
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
        fig = plotting.make_figure(it['data'], it['fit1'], it['fit2'], it['reynolds'])
        png = plotting.figure_png(fig)
        return self._send(200, png, 'image/png')

    def _calc(self, payload):
        base, datasets, an = build_state(payload)
        STATE['config'] = base
        STATE['datasets'] = datasets
        STATE['analysis'] = an
        rounds = [_round_view(it, an, it['points']) for it in an.rounds]
        std = next((r for r in rounds if r['role'] == 'standard'), None)
        return self._json({
            'ok': True,
            'rounds': rounds,
            'standard': std,
            'W': an.W,
            'sigma_W': an.sigma_W,
            'sigma_dT': an.sigma_dT,
            'sigma_sumq': an.sigma_sumq,
            'sigma_msam': an.sigma_m_diff,
            'Qv_benzoic': an.Qv_benzoic,
        })

    def _results_payload(self):
        an = STATE.get('analysis')
        if an is None:
            return {'ok': False, 'error': '尚未计算'}
        rounds = [_round_view(it, an, it['points']) for it in an.rounds]
        return {'ok': True, 'rounds': rounds, 'W': an.W, 'sigma_W': an.sigma_W}

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
    """报告文件名：“学号-姓名-燃烧热”，缺项自动跳过。"""
    parts = []
    sid = str(cfg.get('student_id') or '').strip()
    name = str(cfg.get('student_name') or '').strip()
    if sid:
        parts.append(sid)
    if name:
        parts.append(name)
    parts.append('燃烧热')
    base = '-'.join(parts)
    if not sid and not name and stamp:
        base += '-' + stamp
    return base + '.docx'


def _safe_filename(name):
    """去掉 Windows 文件名不允许的字符。"""
    bad = '<>:"/\\|?*'
    out = ''.join('_' if c in bad else c for c in str(name)).strip().strip('.')
    return out or '燃烧热.docx'


def _unique_path(path, max_tries=50):
    """
    若 path 已被占用（最常见：报告正开在 Word 里），返回一个带序号的新路径，
    并说明原因；否则原样返回。

    Word 打开文档时会创建隐藏的属主文件 `~$名字.docx`，Windows 上也允许别人
    再用追加方式打开原文件，所以两种迹象都要查。
    """
    d = os.path.dirname(path) or '.'
    base = os.path.basename(path)

    def locked(p):
        if os.path.exists(os.path.join(d, '~$' + os.path.basename(p))):
            return True                      # Word 属主文件存在 → 正被打开
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
    stamp = time.strftime('%H%M%S')
    cand = '%s-%s%s' % (root, stamp, ext)
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
        r'D:\北大\课程\26秋大三上\物理化学实验\1 燃烧热',
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
        if os.path.isfile(p) and fn.lower().endswith('.csv'):
            try:
                with open(p, 'r', encoding='utf-8-sig', errors='replace') as fh:
                    head = fh.read(400)
                if 'time(s)' in head.replace(' ', '') or 'Delta_T' in head:
                    out.append({'name': fn, 'path': p, 'size': os.path.getsize(p)})
            except OSError:
                pass
    return out


def _free_port(preferred=8731):
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 0


def main():
    # 支持 --port N / --no-browser：统一入口（物化实验报告工具）用它拉起本模块
    argv = list(sys.argv[1:])
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
    print('  燃烧热实验报告一键生成')
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
