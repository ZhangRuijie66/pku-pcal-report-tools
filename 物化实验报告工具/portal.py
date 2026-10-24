# -*- coding: utf-8 -*-
"""物化实验报告工具 —— 统一入口。

一次启动本机全部实验模块（燃烧热、溶解热……），并在浏览器里给出一个
卡片式入口页：点哪张卡片就进哪个实验的交互界面。

设计要点
--------
· 只监听 127.0.0.1，不联网、不上传任何数据；
· 每个实验模块都是独立目录、独立进程（各自的 pcal 包互不干扰），
  入口只负责挑端口、拉起子进程、做健康检查、退出时收摊；
· 全部在后台运行（没有命令行窗口），停止走入口页的「停止全部服务」
  或根目录的 停止服务.vbs；
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
LOG_PATH = os.path.join(LAB_DIR, '_tools', '启动日志.log')
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
PORTAL_PORTS = (8700, 8730)              # 入口页优先用 8700，被占了往后找

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
        'key': 'conductivity', 'title': '电解质溶液电导率的测定', 'tool': '电导率工具',
        'port': 8751,
        'desc': 'KCl 标定后测 NaNO₃/NaAc/HNO₃/HAc 各 5 个浓度的电导率；'
                'Kohlrausch 拟合外推 Λm∞，离子独立运动定律得 Λm∞(HAc)，'
                '求平均法与拟合直线法两种方法求 HAc 的标准电离平衡常数。',
        'tags': ['电导率', 'Kohlrausch 拟合', 'K° 两种方法'], 'sample': None,
    },
    {
        'key': 'vapor', 'title': '液体饱和蒸气压的测定', 'tool': '蒸气压工具',
        'port': 8761,
        'desc': '动态法测水、静态法测环己烷的沸点–压力数据；克拉贝龙-克劳修斯'
                '拟合求常压沸点、摩尔蒸发焓、摩尔蒸发熵，并与楚顿规则比较。',
        'tags': ['饱和蒸气压', '克拉贝龙-克劳修斯', '楚顿规则'], 'sample': None,
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
        'key': 'electro', 'title': '电化学（循环伏安法）', 'tool': '电化学工具',
        'port': 8801,
        'desc': 'CHI 工作站测 N₂/甲醇体系的 CV 曲线：铂电极电化学活性面积、'
                'ORR/MOR 起始电位，并由扣空白的 ORR+MOR 曲线得到 DMFC 单池的'
                '极化曲线与最大输出功率。',
        'tags': ['循环伏安', 'ORR / MOR', 'DMFC 极化曲线'], 'sample': None,
    },
    {
        'key': 'kinetics', 'title': '化学反应动力学探究', 'tool': '化学动力学工具',
        'port': 8811,
        'desc': '数智旋光仪监测蔗糖水解；积分法判定反应级数，求速率常数、半衰期，'
                '并由 k₁–c(H⁺) 关系确定氢离子反应级数。',
        'tags': ['蔗糖水解', '一级反应', 'k₁ / t₁/₂'],
        'sample': None,
    },
    {
        'key': 'phase', 'title': '双液体系沸点-成分图的绘制', 'tool': '双液系工具',
        'port': 8821,
        'desc': '环己烷-乙醇体系：称量法建折射率-组成工作曲线（二次拟合 + 离群点剔除），'
                '回流冷凝法测沸点与气、液两相组成，绘制沸点-成分图并定位最低恒沸点。',
        'tags': ['环己烷-乙醇', '折射率工作曲线', '最低恒沸点'],
        'sample': None,
    },
    {
        'key': 'dipole', 'title': '稀溶液法测定极性分子的偶极矩', 'tool': '偶极矩工具',
        'port': 8831,
        'desc': '桥法测正丁醇/环己烷溶液的电容与密度，Hedestrand 外推求总摩尔'
                '极化度，结合摩尔折射度得偶极矩 μ。',
        'tags': ['偶极矩', '摩尔极化度', 'Hedestrand'],
        'sample': None,
    },
]

STATE = {
    'portal_port': 0,
    'httpd': None,
    'modules': {},          # key -> {'proc':Popen, 'port':int, 'ok':bool, 'error':str}
    'lock': threading.Lock(),
}


# ---------------------------------------------------------------- 小工具
def _log_handle():
    """后台运行时看不到 stdout，把各模块的输出汇到一个日志里。"""
    try:
        fh = open(LOG_PATH, 'a', encoding='utf-8')
        fh.write('\n===== %s\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
        fh.flush()
        return fh
    except OSError:
        return subprocess.DEVNULL
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


def find_portal_port():
    """已经有一个入口页在跑就复用它（重复点快捷方式只会开一个新标签页）。"""
    for port in range(*PORTAL_PORTS):
        if not _port_open(port):
            continue
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/api/modules' % port,
                                        timeout=1.0) as r:
                data = json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if data.get('portal_port') == port:
            return port
    return 0


def _run_cli(args):
    """取命令输出：中文 Windows 的控制台输出不是 UTF-8，按字节读再宽容解码。"""
    try:
        out = subprocess.check_output(args, stderr=subprocess.DEVNULL,
                                      creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ''
    return out.decode('utf-8-sig', errors='ignore') if isinstance(out, bytes) else str(out)


def _python_processes():
    """[(pid, 命令行), …] 本机所有 python/pythonw 进程。

    PowerShell 往管道里写的是本机 ANSI/OEM 编码，中文路径会解错，
    所以显式让它输出 UTF-8，再按 utf-8-sig 解码。
    """
    script = ('[Console]::OutputEncoding=[Text.Encoding]::UTF8; '
              "Get-CimInstance Win32_Process -Filter \"name='python.exe' or "
              "name='pythonw.exe'\" | ForEach-Object "
              '{ "$($_.ProcessId)|$($_.CommandLine)" }')
    raw = _run_cli(['powershell', '-NoProfile', '-Command', script])
    procs = []
    for line in raw.splitlines():
        pid, sep, cmd = line.partition('|')
        if sep and pid.strip().isdigit():
            procs.append((pid.strip(), cmd))
    return procs


def kill_tools(tool_names):
    """按命令行精确回收这些工具自己的服务进程：只杀命令行里带
       <工具目录>\run.py 的 python，不看端口号（各模块端口区间会互相重叠），
       也绝不碰入口进程本身。返回被杀掉的工具名列表。"""
    needles = {n: (os.sep + n + os.sep + 'run.py').lower() for n in set(tool_names) if n}
    if not needles:
        return []
    killed = set()
    for pid, cmd in _python_processes():
        if pid == str(os.getpid()):
            continue
        low = cmd.lower()
        for name, needle in needles.items():
            if needle not in low:
                continue
            try:
                subprocess.call(['taskkill', '/PID', pid, '/F'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW)
                killed.add(name)
            except OSError:
                pass
    return sorted(killed)


def kill_tool(tool_name):
    return bool(kill_tools([tool_name]))


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
        creationflags = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) |
                         CREATE_NO_WINDOW)
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'      # 输出要实时进日志，不然攒到退出才写
    try:
        proc = subprocess.Popen(
            [PYTHON, os.path.join(d, 'run.py'), '--port', str(port), '--no-browser'],
            cwd=d, env=env, creationflags=creationflags,
            stdin=subprocess.DEVNULL, stdout=_log_handle(), stderr=subprocess.STDOUT)
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


def _stop_all(kill_external=False):
    with STATE['lock']:
        mine = list(STATE['modules'].items())
        external = [mod for mod in MODULES
                    if _installed(mod) and
                    (STATE['modules'].get(mod['key']) or {}).get('external')]
    for key, st in mine:
        proc = st.get('proc')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
    time.sleep(0.4)
    for key, st in mine:
        proc = st.get('proc')
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        with STATE['lock']:
            STATE['modules'].pop(key, None)
    if kill_external and external:
        kill_tools([mod['tool'] for mod in external])


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
            if u.path == '/api/shutdown':
                return self._shutdown()
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
        external_tool = None
        if st and st.get('proc') and st['proc'].poll() is None:
            try:
                st['proc'].terminate()
            except OSError:
                pass
        elif st and st.get('external'):
            # 用户单独用 启动.vbs 起的模块：按命令行找回它自己的 python 进程
            mod = next((m for m in MODULES if m['key'] == key), None)
            if mod and mod.get('tool'):
                external_tool = mod['tool']
        with STATE['lock']:
            STATE['modules'].pop(key, None)
        if external_tool:
            kill_tool(external_tool)
        if quiet:
            return {'ok': True}
        return self._json({'ok': True, 'modules': _module_payload()})

    def _shutdown(self):
        """后台运行没有窗口可关，停止服务走这里。"""
        resp = self._json({'ok': True, 'bye': True})

        def worker():
            time.sleep(0.3)
            _stop_all(kill_external=True)
            httpd = STATE.get('httpd')
            if httpd:
                threading.Thread(target=httpd.shutdown, daemon=True).start()
            time.sleep(0.5)
            os._exit(0)

        threading.Thread(target=worker, daemon=True).start()
        return resp


# ---------------------------------------------------------------- 主流程
def main():
    argv = list(sys.argv[1:])
    open_browser = True
    if '--no-browser' in argv:
        open_browser = False
    existing = find_portal_port()
    if existing:
        # 已经开着了：再点一次快捷方式只是把入口页重新打开，不再起一套服务
        url = 'http://127.0.0.1:%d' % existing
        print('入口页已经在运行：%s' % url)
        if open_browser:
            webbrowser.open(url)
        return 0
    port = _free_port(PORTAL_PORTS[0])
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
    STATE['httpd'] = httpd
    url = 'http://127.0.0.1:%d' % port
    print('  请在浏览器打开：%s' % url)
    print('  停止服务：入口页点「停止全部服务」，或双击 停止服务.vbs。')
    print('  运行日志：%s' % LOG_PATH)
    print('=' * 60)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止各模块…')
    finally:
        httpd.server_close()
        _stop_all(kill_external=True)
        print('已停止。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
