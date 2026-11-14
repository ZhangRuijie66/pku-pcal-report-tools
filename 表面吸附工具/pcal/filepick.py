# -*- coding: utf-8 -*-
"""系统文件/文件夹选择窗口（tkinter 子进程），以及数据目录的 HTTP 端点辅助。

为什么单独开子进程：各模块的 HTTP 服务跑在主线程的事件循环里，
直接在服务进程里 ``tkinter.Tk()`` 会把整个服务卡住（窗口关掉前一律无响应）。
子进程 + ``subprocess.run`` 只阻塞那一个请求线程，别的请求照常处理。

Windows 上子进程开窗之前**必须先声明 DPI 感知**（见 ``_DPI_PRELUDE``），
否则 200% 缩放的机器上系统对话框按 96 DPI 排版再被拉伸 2 倍，又小又糊。

自动化测试用环境变量接管，不要弹真窗口：

    PCAL_PICK_AUTO=<目录>        → 「选择文件夹」直接返回它
    PCAL_PICK_FILE_AUTO=<文件>   → 「选择文件」直接返回它

各模块的 ``server.py`` 只需把端点接到 ``pick_folder`` / ``pick_file``。
"""
from __future__ import annotations

import os
import subprocess
import sys

#: 单次选择最多等多久（秒）。用户慢慢翻目录也不会超时。
PICK_TIMEOUT = 900


def _run_dialog(code, argv, timeout=PICK_TIMEOUT):
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    # 子进程不该继承「自动选择」以外的特殊情况；这里只是显式声明编码
    try:
        out = subprocess.run([sys.executable, '-c', code] + list(argv),
                             capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return ''
    txt = out.stdout.decode('utf-8', 'replace').strip()
    return txt


def _norm_dir(path):
    path = (path or '').strip().strip('"')
    if not path:
        return ''
    path = os.path.normpath(path)
    return path if os.path.isdir(path) else ''


def _norm_file(path, exts=None):
    path = (path or '').strip().strip('"')
    if not path:
        return ''
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return ''
    if exts:
        exts = tuple(e.lower() for e in exts)
        if not path.lower().endswith(exts):
            return ''
    return path


_DPI_PRELUDE = r"""
def _pcal_enable_dpi_awareness():
    '''让本进程按显示器的真实 DPI 渲染。

    Windows 默认把「不声明 DPI 感知」的进程当作 96 DPI，再把整窗位图放大到
    200%（用户机器 devicePixelRatio=2）。后果是系统文件对话框按 96 DPI 排版、
    再被拉伸 2 倍 —— 又小又糊。真实备上量到：不声明时窗口 dpi=96、
    720x501 设备像素；声明后 dpi=192、1440x1002，文字按原生分辨率绘制。

    必须在创建任何窗口（含 tk.Tk()）之前调用。只在子进程里做，
    不动服务主进程（那里没有窗口，提前改感知模式反而会干扰日志/预览）。
    '''
    try:
        import ctypes
    except Exception:
        return 'none'
    try:
        # Win10 1703+：每显示器感知 v2（跨显示器缩放切换也正确）
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return 'permonitor_v2'
    except Exception:
        pass
    try:
        # Win8.1+：每显示器感知
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return 'permonitor'
    except Exception:
        pass
    try:
        # Vista+：系统级感知（低版本 Windows 的兜底，仍然比不声明清晰）
        ctypes.windll.user32.SetProcessDPIAware()
        return 'system'
    except Exception:
        pass
    return 'none'


_PCAL_DPI = _pcal_enable_dpi_awareness()
if __import__('os').environ.get('PCAL_PICK_DPI_DEBUG'):
    __import__('sys').stderr.write('dpi=' + _PCAL_DPI + '\n')
"""


def dpi_awareness_prelude():
    """子进程里「开启 DPI 感知」的前置代码。

    单独暴露出来是为了让测试跑同一份字符串，而不是另抄一份逻辑——
    抄一份的话改了这里、测试仍然绿，这个坑就是这么漏掉的。
    """
    return _DPI_PRELUDE


_DIR_CODE = _DPI_PRELUDE + r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw()
try:
    root.attributes('-topmost', True)
except Exception:
    pass
root.update()
kwargs = {'parent': root, 'title': sys.argv[2] if len(sys.argv) > 2 else '\u9009\u62e9\u6570\u636e\u6587\u4ef6\u5939'}
if len(sys.argv) > 1 and sys.argv[1] and __import__('os').path.isdir(sys.argv[1]):
    kwargs['initialdir'] = sys.argv[1]
p = filedialog.askdirectory(**kwargs)
root.destroy()
sys.stdout.write(p or '')
"""

_FILE_CODE = _DPI_PRELUDE + r"""
import sys, os, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw()
try:
    root.attributes('-topmost', True)
except Exception:
    pass
root.update()
kwargs = {'parent': root, 'title': sys.argv[3] if len(sys.argv) > 3 else '\u9009\u62e9\u6570\u636e\u6587\u4ef6'}
init = sys.argv[1] if len(sys.argv) > 1 else ''
exts = sys.argv[2] if len(sys.argv) > 2 else ''
if init and os.path.isdir(init):
    kwargs['initialdir'] = init
elif init and os.path.isdir(os.path.dirname(init)):
    kwargs['initialdir'] = os.path.dirname(init)
if exts:
    pats = []
    for e in exts.split(';'):
        e = e.strip()
        if e:
            pats.append('*' + (e if e.startswith('.') else '.' + e))
            pats.append('*' + (e if e.startswith('.') else '.' + e) + '.*')
    if pats:
        kwargs['filetypes'] = [('\u6570\u636e\u6587\u4ef6', ' '.join(pats)), ('\u6240\u6709\u6587\u4ef6', '*.*')]
p = filedialog.askopenfilename(**kwargs)
root.destroy()
sys.stdout.write(p or '')
"""


def pick_folder(initial=None, title=None):
    """弹「选择文件夹」，返回绝对路径；取消返回 ``''``。"""
    auto = os.environ.get('PCAL_PICK_AUTO')
    if auto:
        return _norm_dir(auto)
    return _norm_dir(_run_dialog(_DIR_CODE, [initial or '', title or ''])[:4096])


def pick_file(initial=None, exts=None, title=None):
    """弹「选择文件」，返回绝对路径；取消或后缀不符返回 ``''``。

    ``exts`` 可以是 ``('.csv', '.txt')`` 或 ``'.csv;.txt'``。
    """
    auto = os.environ.get('PCAL_PICK_FILE_AUTO')
    if exts:
        exts_norm = tuple(e.lower() for e in (
            exts.split(';') if isinstance(exts, str) else exts))
    else:
        exts_norm = None
    if auto:
        return _norm_file(auto, exts_norm)
    spec = ';'.join(exts_norm) if exts_norm else ''
    return _norm_file(_run_dialog(_FILE_CODE, [initial or '', spec, title or ''])[:4096],
                      exts_norm)


# ---------------------------------------------------------------- 端点负载
def index_payload(data_dir, files=None):
    """``/api/files`` 的返回体：目录 + 文件清单，够前端自己过滤。"""
    from . import dataloc
    index = dataloc.dump_index(data_dir, files)
    index['ok'] = True
    return index


def auto_match_payload(defaults, data_dir, files=None):
    """给一组「默认文件名」自动匹配（``/api/files/auto``）。

    ``defaults`` 形如 ``{'苯甲酸.csv': '…真实相对路径' or None, …}``；
    返回每项的 ``status`` ∈ ``default / fuzzy / missing`` 与候选。
    """
    from . import dataloc
    files = list(dataloc.list_data_files(data_dir)) if files is None else list(files)
    out = {}
    for key, default in (defaults or {}).items():
        default = str(default or '')
        cands = dataloc.rank_candidates(default, files, top=6)
        picked = dataloc.auto_match(default, files)
        if picked:
            status = 'default' if os.path.basename(picked) == os.path.basename(default) \
                and os.path.dirname(picked) == os.path.dirname(default) else 'fuzzy'
        else:
            status = 'missing'
        out[key] = {
            'default': default,
            'picked': picked or '',
            'status': status,
            'candidates': cands,
        }
    return {'ok': True, 'dir': os.path.abspath(data_dir) if data_dir else '',
            'files': len(files), 'slots': out}
