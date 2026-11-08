# -*- coding: utf-8 -*-
"""启动画面（splash）：双击快捷方式后 0.3 秒内给出可见反馈。

## 为什么需要

无黑框启动以后，双击快捷方式到浏览器出现入口页之间有约 2~3 秒**完全没有任何
窗口**（进程在导入 numpy/scipy/matplotlib、探测依赖、等端口）。用户看到的是
「点了没反应」，容易重复双击。本模块补上这段反馈。

## 为什么不是简单的「等 2 秒再关」

splash 自己轮询入口端口，**端口一能响应就关**，所以：

* 慢机器（首次启动、杀毒软件扫描）会多显示一会儿，但用户知道在加载；
* 快机器（热缓存）几乎一闪而过，不会拖慢启动——它跑在独立进程里，
  和 launcher 的启动流程并行，不占主链路时间。

实测：从子进程启动到窗口可见约 0.28 s，远快于主体启动的 2~3 s。

## 用法

    python _tools/splash.py --port 8700 [--timeout 25]

由 `_tools/launcher.py` 在启动入口页之前拉起，不需要调用方等待。
"""
from __future__ import annotations

import socket
import sys
import time

TITLE = '物化实验报告工具'
SUBTITLE = '正在启动，稍后会自动打开浏览器…'

# 视觉参数
W, H = 440, 150
BG = '#ffffff'
FG = '#1f2937'
MUTED = '#6b7280'
ACCENT = '#4f46e5'
TRACK = '#eef2ff'


def _port_ready(port, timeout=0.15):
    """端口是否已经能接受连接。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except OSError:
        return False


def _any_ready(ports, timeout=0.12):
    """端口区间里任意一个能连上就算就绪。

    入口页从 8700 起往后找空位，落在哪个不确定；逐个试一遍很快
    （127.0.0.1 上没监听是立刻 refused，不用等超时）。
    """
    for port in ports:
        if _port_ready(port, timeout):
            return True
    return False


def _parse(argv):
    ports = []
    timeout = 25.0
    span = 1
    for i, arg in enumerate(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else ''
        if arg == '--port':
            try:
                ports.append(int(nxt))
            except ValueError:
                pass
        elif arg == '--span':
            try:
                span = max(1, int(nxt))
            except ValueError:
                span = 1
        elif arg == '--timeout':
            try:
                timeout = float(nxt)
            except ValueError:
                timeout = 25.0
    ports_out = []
    for base in ports:
        ports_out.extend(range(base, base + span))
    return ports_out, max(3.0, timeout)


def run(ports=(), timeout=25.0):
    """显示启动画面，直到端口就绪或超时。返回 0。"""
    ports = list(ports or ())
    try:
        import tkinter as tk
    except Exception:                       # noqa: BLE001
        return 0                            # 没有 tkinter 就静默跳过，不能因此起不来

    root = tk.Tk()
    root.title(TITLE)
    root.overrideredirect(True)             # 无标题栏的小卡片
    try:
        root.attributes('-topmost', True)
    except Exception:                       # noqa: BLE001
        pass

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(0, (screen_w - W) // 2)
    y = max(0, int(screen_h * 0.28))
    root.geometry('%dx%d+%d+%d' % (W, H, x, y))
    root.configure(bg=BG)

    # 细边框：overrideredirect 之后没有系统边框，自己画一圈
    frame = tk.Frame(root, bg='#e5e7eb')
    frame.place(x=0, y=0, width=W, height=H)
    inner = tk.Frame(frame, bg=BG)
    inner.place(x=1, y=1, width=W - 2, height=H - 2)

    tk.Label(inner, text=TITLE, bg=BG, fg=FG,
             font=('Microsoft YaHei UI', 15, 'bold')).pack(pady=(30, 6))
    tk.Label(inner, text=SUBTITLE, bg=BG, fg=MUTED,
             font=('Microsoft YaHei UI', 9)).pack()

    # 不确定进度条：来回流动的色块
    canvas = tk.Canvas(inner, width=W - 90, height=4, bg=BG,
                       highlightthickness=0, bd=0)
    canvas.pack(pady=(22, 0))
    canvas.create_rectangle(0, 0, W - 90, 4, fill=TRACK, width=0)
    bar = canvas.create_rectangle(0, 0, 0, 4, fill=ACCENT, width=0)

    deadline = time.time() + max(3.0, timeout)
    state = {'pos': 0.0, 'dir': 1}

    def tick():
        if ports and _any_ready(ports):
            root.destroy()
            return
        if time.time() > deadline:
            root.destroy()                  # 超时也要关，别把窗口留在屏幕上
            return
        # 让色块在轨道里来回跑
        span = W - 90
        state['pos'] += state['dir'] * 7.0
        if state['pos'] > span - 110:
            state['pos'] = span - 110
            state['dir'] = -1
        elif state['pos'] < 0:
            state['pos'] = 0
            state['dir'] = 1
        canvas.coords(bar, state['pos'], 0, state['pos'] + 110, 4)
        root.after(30, tick)

    root.update()                           # 先画出来，再开始轮询
    root.after(30, tick)
    try:
        root.mainloop()
    except Exception:                       # noqa: BLE001
        pass
    return 0


def main(argv=None):
    ports, timeout = _parse(list(argv if argv is not None else sys.argv[1:]))
    try:
        return run(ports, timeout)
    except Exception:                       # noqa: BLE001
        return 0                            # 启动画面失败绝不影响主流程


if __name__ == '__main__':
    sys.exit(main())
