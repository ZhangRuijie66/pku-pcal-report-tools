# -*- coding: utf-8 -*-
"""物化实验报告工具 —— 无黑框启动器。

由 启动.vbs（以及桌面的「物化实验报告工具」快捷方式）调用：

    python _tools\\launcher.py "<某个工具目录>"      后台启动该工具，不弹命令行窗口
    python _tools\\launcher.py --stop                停掉入口页和全部实验模块
    python _tools\\launcher.py --install "<目录>"    在命令行窗口里装依赖，装完再后台启动

只有两种情况会看到命令行窗口：首次运行需要 pip 装依赖，或者本机没装 Python。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
LAB_DIR = os.path.dirname(TOOLS_DIR)
PORTAL_DIR = os.path.join(LAB_DIR, '物化实验报告工具')
LOG_FILE = os.path.join(TOOLS_DIR, '启动日志.log')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# 每个工具额外需要的第三方库（缺了就开个窗口 pip 安装）
DEPS = {
    '化学动力学工具': ['numpy', 'scipy', 'matplotlib', 'docx', 'openpyxl'],
    '蒸气压工具': ['numpy', 'scipy', 'matplotlib', 'docx', 'openpyxl'],
    '偶极矩工具': ['numpy', 'scipy', 'matplotlib', 'docx', 'openpyxl'],
    '高斯计算工具': ['rdkit', 'paramiko'],
}
DEFAULT_DEPS = ['numpy', 'scipy', 'matplotlib', 'docx']

# 入口页没登记、但同样在后台常驻端口上的工具
EXTRA_PORTS = {'高斯计算工具': 8795}


def _portal_module():
    sys.path.insert(0, PORTAL_DIR)
    import portal  # noqa: F401  复用它的端口表与停服函数
    return portal


def _spawn_hidden(argv, cwd=None):
    """后台启动一个 python 进程：输出写日志文件，不创建任何窗口。"""
    try:
        log = open(LOG_FILE, 'a', encoding='utf-8')
        log.write('\n===== %s\n    %s\n' %
                  (time.strftime('%Y-%m-%d %H:%M:%S'), ' '.join(argv)))
        log.flush()
    except OSError:
        log = subprocess.DEVNULL
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'      # 日志要实时，不能等进程退出才刷出来
    return subprocess.Popen(argv, cwd=cwd, stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, env=env,
                            creationflags=NO_WINDOW)


def _has(exe, module):
    probe = subprocess.run([exe, '-c', 'import %s' % module],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0


def _alert(text):
    """没有控制台时，用消息框把错误告诉用户。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, '物化实验报告工具', 0x10)
    except Exception:  # noqa: BLE001
        pass


def _fail(tool_dir, msg):
    text = '%s：%s' % (os.path.basename(tool_dir), msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as fh:
            fh.write('\n[FAIL] ' + text + '\n')
    except OSError:
        pass
    _alert(text + '\n\n详细输出见：\n%s' % LOG_FILE)
    return 1


def _running_port(tool_dir):
    """这个模块是不是已经在跑了（入口页拉起 / 别处单独启动）。"""
    portal = _portal_module()
    name = os.path.basename(tool_dir.rstrip('\\/'))
    extra = EXTRA_PORTS.get(name)
    if extra and portal._healthy(extra, 0.6):
        return extra
    for mod in portal.MODULES:
        if mod.get('tool') != name:
            continue
        if portal._healthy(mod['port'], 0.6):
            return mod['port']
        p_port = portal.find_portal_port()
        if not p_port:
            return 0
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/api/modules' % p_port,
                                        timeout=2) as r:
                data = json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError):
            return 0
        for m in data.get('modules', []):
            if m.get('title') == mod['title'] and m.get('running'):
                return m.get('port') or 0
    return 0


def start(tool_dir):
    tool_dir = os.path.abspath(tool_dir)
    run_py = os.path.join(tool_dir, 'run.py')
    if not os.path.exists(run_py):
        return _fail(tool_dir, '找不到启动脚本 run.py')

    busy = _running_port(tool_dir)
    if busy:
        # 后台已经有这个模块了：只把页面打开，不再重复起一份
        import webbrowser
        webbrowser.open('http://127.0.0.1:%d' % busy)
        return 0

    exe = sys.executable or 'python'
    name = os.path.basename(tool_dir.rstrip('\\/'))
    missing = [m for m in DEPS.get(name, DEFAULT_DEPS) if not _has(exe, m)]
    if missing:
        # 装依赖要看得见进度：开一个命令行窗口跑 --install，本进程退出
        _spawn_console(['--install', tool_dir])
        return 0

    proc = _spawn_hidden([exe, run_py], cwd=tool_dir)
    time.sleep(1.5)
    rc = proc.poll()
    if rc not in (None, 0):
        return _fail(tool_dir, '启动后立即退出（返回码 %s）' % rc)
    return 0


def _spawn_console(extra):
    exe = sys.executable or 'python'
    subprocess.Popen('start "" "%s" "%s" %s' % (
        exe, os.path.abspath(__file__),
        ' '.join('"%s"' % a for a in extra)), shell=True)


def install_and_start(tool_dir):
    """在可见的命令行窗口里装依赖，装好后转后台启动。"""
    exe = sys.executable or 'python'
    req = os.path.join(LAB_DIR, 'requirements.txt')
    name = os.path.basename(tool_dir.rstrip('\\/'))
    print('首次运行：正在安装 %s 需要的依赖……' % name)
    if name == '高斯计算工具':
        cmd = [exe, '-m', 'pip', 'install', 'rdkit', 'paramiko']
    elif os.path.exists(req):
        cmd = [exe, '-m', 'pip', 'install', '-r', req]
    else:
        cmd = [exe, '-m', 'pip', 'install'] + DEPS.get(name, DEFAULT_DEPS)
    cmd += ['-i', 'https://pypi.tuna.tsinghua.edu.cn/simple']
    rc = subprocess.call(cmd)
    if rc:
        print('\n[ERROR] 依赖安装失败（返回码 %s），请检查网络后重试。' % rc)
    else:
        print('\n依赖已就绪，正在后台启动 %s …' % name)
        start(tool_dir)
        print('已在后台启动，稍后浏览器会自动打开这个工具的页面。')
    print('\n本窗口 6 秒后自动关闭。')
    time.sleep(6)
    return rc


def stop_all():
    """停掉入口页（入口会顺手收掉它拉起的模块），再兜底清理独立启动的模块。"""
    portal = _portal_module()
    stopped = []
    p_port = portal.find_portal_port()
    if p_port:
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/api/shutdown' % p_port,
                                        timeout=3) as r:
                r.read()
        except OSError:
            pass
        stopped.append('入口页 :%d' % p_port)
        time.sleep(1.2)
    names = [mod['tool'] for mod in portal.MODULES if mod.get('tool')]
    names += list(EXTRA_PORTS)
    names = [n for n in names if os.path.exists(os.path.join(LAB_DIR, n, 'run.py'))]
    for name in portal.kill_tools(names):
        stopped.append('%s（后台进程）' % name)
    text = '、'.join(stopped) if stopped else '没有正在运行的服务'
    print('已停止：%s' % text)
    _alert('已停止：\n%s' % text)
    return 0


def main(argv):
    argv = list(argv)
    if not argv:
        return start(PORTAL_DIR)
    if argv[0] == '--stop':
        return stop_all()
    if argv[0] == '--install':
        return install_and_start(argv[1])
    return start(argv[0])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
