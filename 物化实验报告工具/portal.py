# -*- coding: utf-8 -*-
"""物化实验报告工具 —— 统一入口。

一次启动本机全部实验模块（燃烧热、溶解热……），并在浏览器里给出一个
卡片式入口页：点哪张卡片就进哪个实验的交互界面。

设计要点
--------
· 只监听 127.0.0.1，不联网、不上传任何数据；
· 每个实验模块都是独立目录、独立进程（各自的 pcal 包互不干扰），
  入口只负责挑端口、拉起子进程、做健康检查、退出时收摊；
· 新增实验只要在 MODULES 里加一条，并把该模块的 server.main() 支持
  --port / --no-browser 即可（两个已有模块都已支持）。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, 'web')
LAB_DIR = os.path.dirname(HERE)          # …\物理化学实验
PYTHON = sys.executable or 'python'

# ---------------------------------------------------------------- 实验模块登记表
# ok=True 的模块会随入口一起启动；其余在入口页上显示为「即将支持」。
MODULES = [
    {
        'key': 'combustion', 'title': '燃烧热的测定', 'tool': '燃烧热工具',
        'port': 8731,
        'desc': '氧弹式量热计；苯甲酸标定量热计常数 W，雷诺校正后求蔗糖等的恒容/恒压燃烧热。',
        'tags': ['氧弹量热计', '雷诺校正', 'Q_p / Q_V'],
        'sample': '1 燃烧热',
    },
    {
        'key': 'dissolution', 'title': '溶解热的测定', 'tool': '溶解热工具',
        'port': 8741,
        'desc': '保温瓶式量热计、电热补偿法；累加法测 KNO₃ 的积分溶解热，'
                '拟合经验方程并求微分溶解热 / 微分冲淡热。',
        'tags': ['电热补偿法', '积分溶解热', 'Q_s–n_0 拟合'],
        'sample': '2 溶解热',
    },
    {
        'key': 'conductivity', 'title': '电导率的测定', 'tool': None, 'port': 8751,
        'desc': '电导率仪测弱电解质电导率，求电离度与电离平衡常数。',
        'tags': ['电导率', '电离度'], 'sample': None,
    },
    {
        'key': 'vapor', 'title': '液体饱和蒸气压的测定', 'tool': None, 'port': 8761,
        'desc': '等压法测不同温度下的饱和蒸气压，求摩尔汽化焓。',
        'tags': ['饱和蒸气压', '汽化焓'], 'sample': None,
    },
    {
        'key': 'adsorption', 'title': '溶液表面吸附的测定', 'tool': '表面吸附工具',
        'port': 8771,
        'desc': '最大气泡压力法与吊片法测正丁醇溶液的表面张力；'
                '由 γ–lg c（或 γ–ln c）线性区斜率求饱和吸附量 Γ∞、分子面积 q 与浓度修正 q_c。',
        'tags': ['表面张力', 'Gibbs 吸附', 'Γ∞ / q_c'],
        'sample': None,
    },
    {
        'key': 'magnetic', 'title': '磁化率的测定', 'tool': None, 'port': 8781,
        'desc': '古埃磁天平测磁化率，推算未成对电子数。',
        'tags': ['磁化率'], 'sample': None,
    },
    {
        'key': 'uv', 'title': '紫外可见吸收光谱仪搭建', 'tool': '紫外光谱工具', 'port': 8791,
        'desc': '自建紫外可见光谱仪：氘灯标定 pixel–波长，测 6 种共轭分子的吸收光谱，'
                '求 λmax 与摩尔消光系数，并用一维势箱模型验证。',
        'tags': ['光谱搭建', '朗伯-比尔定律', '一维势箱'],
        'sample': '3 紫外光谱搭建',
    },
    {
        'key': 'electro', 'title': '电化学实验', 'tool': None, 'port': 8801,
        'desc': '电动势的测定与电极电势。', 'tags': ['电动势'], 'sample': None,
    },
    {
        'key': 'kinetics', 'title': '化学反应动力学探究', 'tool': '化学动力学工具',
        'port': 8811,
        'desc': '数智旋光仪监测蔗糖水解；积分法判定反应级数，求速率常数、半衰期，'
                '并由 k₁–c(H⁺) 关系确定氢离子反应级数。',
        'tags': ['蔗糖水解', '一级反应', 'k₁ / t₁/₂'],
        'sample': None,
    },
]

STATE = {
    'portal_port': 0,
    'modules': {},          # key -> {'proc':Popen, 'port':int, 'ok':bool, 'error':str}
    'lock': threading.Lock(),
}


# ---------------------------------------------------------------- 小工具
def _free_port(preferred):
    for port in range(preferred, preferred + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 0


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _healthy(port, timeout=1.0):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/state' % port,
                                    timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _module_dir(mod):
    return os.path.join(LAB_DIR, mod['tool']) if mod['tool'] else None


def _installed(mod):
    d = _module_dir(mod)
    return bool(d) and os.path.exists(os.path.join(d, 'run.py'))


def _start_module(mod, force_new_port=False):
    """拉起一个模块的子进程，返回状态字典。"""
    d = _module_dir(mod)
    if not _installed(mod):
        return {'ok': False, 'installed': False, 'port': None, 'error': '模块尚未安装'}

    key = mod['key']
    with STATE['lock']:
        st = STATE['modules'].get(key)
        # 已经由本入口拉起来且进程还活着 → 直接用
        if st and st.get('proc') and st['proc'].poll() is None and not force_new_port:
            if _healthy(st['port']):
                return st
        # 端口上已经有别的服务（比如用户自己双击了该模块的 启动.cmd）→ 直接复用
        if not force_new_port and _port_open(mod['port']) and _healthy(mod['port']):
            st = {'ok': True, 'installed': True, 'port': mod['port'], 'proc': None,
                  'external': True, 'error': ''}
            STATE['modules'][key] = st
            return st

        port = _free_port(mod['port']) if not force_new_port else _free_port(mod['port'])
        if not port:
            return {'ok': False, 'installed': True, 'port': None,
                    'error': '找不到空闲端口'}

    creationflags = 0
    if os.name == 'nt':
        creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        proc = subprocess.Popen(
            [PYTHON, os.path.join(d, 'run.py'), '--port', str(port), '--no-browser'],
            cwd=d, env=env, creationflags=creationflags)
    except OSError as exc:
        return {'ok': False, 'installed': True, 'port': None, 'error': str(exc)}

    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            return {'ok': False, 'installed': True, 'port': port,
                    'error': '模块进程启动后立即退出（返回码 %s）' % proc.returncode}
        if _healthy(port, 0.6):
            st = {'ok': True, 'installed': True, 'port': port, 'proc': proc,
                  'external': False, 'error': ''}
            with STATE['lock']:
                STATE['modules'][key] = st
            print('  [OK]   %-12s %s' % (mod['title'], 'http://127.0.0.1:%d' % port))
            return st
        time.sleep(0.35)
    return {'ok': False, 'installed': True, 'port': port, 'proc': proc,
            'error': '启动超时（40 s 内没有响应）'}


def _stop_all():
    with STATE['lock']:
        for st in STATE['modules'].values():
            proc = st.get('proc')
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
    time.sleep(0.4)
    with STATE['lock']:
        for st in STATE['modules'].values():
            proc = st.get('proc')
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass


def _module_payload():
    out = []
    for mod in MODULES:
        key = mod['key']
        st = STATE['modules'].get(key, {})
        installed = _installed(mod)
        port = st.get('port')
        running = bool(st.get('ok')) and bool(port) and _healthy(port, 0.5)
        out.append({
            'key': key, 'title': mod['title'], 'desc': mod['desc'],
            'tags': mod['tags'], 'installed': installed, 'ok': bool(st.get('ok')),
            'running': running, 'port': port, 'external': bool(st.get('external')),
            'error': st.get('error', ''),
            'url': ('http://127.0.0.1:%d/?home=http://127.0.0.1:%d'
                    % (port, STATE['portal_port'])) if running else None,
            'raw_url': ('http://127.0.0.1:%d/' % port) if running else None,
            'sample': mod.get('sample'),
        })
    return out


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = 'PChemPortal/1.0'

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
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path in ('/', '/index.html'):
                with open(os.path.join(WEB_DIR, 'index.html'), 'r', encoding='utf-8') as fh:
                    return self._send(200, fh.read(), 'text/html; charset=utf-8')
            if u.path == '/api/modules':
                return self._json({'ok': True, 'portal_port': STATE['portal_port'],
                                   'lab_dir': LAB_DIR,
                                   'output_dir': os.path.join(LAB_DIR, '实验报告输出'),
                                   'modules': _module_payload()})
            if u.path == '/api/start':
                q = urllib.parse.parse_qs(u.query)
                key = (q.get('key') or [''])[0]
                return self._start(key, (q.get('force') or ['0'])[0] == '1')
            if u.path == '/api/stop':
                q = urllib.parse.parse_qs(u.query)
                key = (q.get('key') or [''])[0]
                return self._stop(key)
            return self._json({'ok': False, 'error': 'not found: ' + u.path}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._json({'ok': False, 'error': str(exc)}, 400)

    def do_POST(self):
        return self.do_GET()

    def _start(self, key, force):
        mod = next((m for m in MODULES if m['key'] == key), None)
        if mod is None:
            return self._json({'ok': False, 'error': '未知的实验模块：' + key}, 404)
        if force:
            self._stop(key, quiet=True)
        st = _start_module(mod, force_new_port=force)
        return self._json({'ok': bool(st.get('ok')), 'error': st.get('error', ''),
                           'modules': _module_payload()})

    def _stop(self, key, quiet=False):
        with STATE['lock']:
            st = STATE['modules'].get(key)
        if st and st.get('proc') and st['proc'].poll() is None:
            try:
                st['proc'].terminate()
            except OSError:
                pass
        with STATE['lock']:
            STATE['modules'].pop(key, None)
        if quiet:
            return {'ok': True}
        return self._json({'ok': True, 'modules': _module_payload()})


# ---------------------------------------------------------------- 主流程
def main():
    argv = list(sys.argv[1:])
    open_browser = True
    if '--no-browser' in argv:
        open_browser = False
    port = _free_port(8700)
    if not port:
        print('找不到空闲端口，退出。')
        return 1
    STATE['portal_port'] = port

    print('=' * 60)
    print('  物化实验报告工具 —— 统一入口')
    print('  入口页：http://127.0.0.1:%d' % port)
    print('  正在启动各实验模块（首次启动约需几秒）…')
    print('-' * 60)
    for mod in MODULES:
        if _installed(mod):
            _start_module(mod)
    print('-' * 60)

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d' % port
    print('  请在浏览器打开：%s' % url)
    print('  关闭本窗口即可停止全部服务。')
    print('=' * 60)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止各模块…')
    finally:
        httpd.server_close()
        _stop_all()
        print('已停止。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
