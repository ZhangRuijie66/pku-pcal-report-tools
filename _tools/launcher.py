# -*- coding: utf-8 -*-
"""物化实验报告工具 —— 无黑框启动器。

由 启动.vbs（以及桌面的「物化实验报告工具」快捷方式）调用：

    python _tools\\launcher.py "<某个工具目录>"      后台启动该工具，不弹命令行窗口
    python _tools\\launcher.py --stop                停掉入口页和全部实验模块（不弹框）
    python _tools\\launcher.py --stop --interactive  同上，但停完弹框确认（双击 vbs 用）
    python _tools\\launcher.py --install "<目录>"    在命令行窗口里装依赖，装完再后台启动
    python _tools\\launcher.py --restart             静默重启入口页（更新装完后自己调）
    python _tools\\launcher.py --update [--apply] [--no-restart]
                                                     命令行检查/安装更新

只有两种情况会看到命令行窗口：首次运行需要 pip 装依赖，或者本机没装 Python。
`--restart` 与 `--update` 是自动化路径：**全程不弹消息框**，结果只打进日志和 stdout。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
LAB_DIR = os.path.dirname(TOOLS_DIR)
PORTAL_DIR = os.path.join(LAB_DIR, '物化实验报告工具')
LOG_FILE = os.path.join(TOOLS_DIR, '启动日志.log')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
RESTART_WAIT = 8.0                       # 等入口端口释放的上限（秒）


def _probe_ports(ports, timeout=0.4):
    """并发探测一组端口，返回监听中的那些（**保持原顺序**）。

    `portal.find_portal_port()` 是一个个串行 connect_ex 的：空端口每个都要等满
    0.4 s 超时，30 个就是 12 s。收摊时入口通常根本没在跑，于是 --stop 光"找
    入口"就卡十几秒。改成先并发筛一遍，只有真在监听的那一两个端口才进后面的
    HTTP 校验，语义不变、时间降到一次超时。
    """
    ports = list(ports)
    if not ports:
        return []

    def _one(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return port, s.connect_ex(('127.0.0.1', port)) == 0

    open_ports = set()
    with ThreadPoolExecutor(max_workers=min(32, len(ports))) as pool:
        for port, is_open in pool.map(_one, ports):
            if is_open:
                open_ports.add(port)
    return [p for p in ports if p in open_ports]


def _portal_port():
    """入口页端口；没有在跑就返回 0。

    先并发筛出真正在监听的入口端口，再让 portal 自己按原逻辑确认（它会校验
    /api/modules 返回的 portal_port）。这样"入口没在跑"时不再白等 30×0.4 s。
    """
    portal = _portal_module()
    candidates = []
    env_port = portal._env_port()
    if env_port:
        candidates.append(env_port)
    for port in range(*portal.PORTAL_PORTS):
        if port not in candidates:
            candidates.append(port)
    if not _probe_ports(candidates, timeout=0.25):
        return 0
    return portal.find_portal_port()

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


def _rotate_log(path, max_bytes=4 * 1024 * 1024):
    """日志只追加不轮转会越积越大；超过上限就改名成 .1 再重开（只留一代）。"""
    try:
        if os.path.getsize(path) > max_bytes:
            backup = path + '.1'
            try:
                os.remove(backup)
            except OSError:
                pass
            os.replace(path, backup)
    except OSError:
        pass


def _spawn_hidden(argv, cwd=None):
    """后台启动一个 python 进程：输出写日志文件，不创建任何窗口。"""
    _rotate_log(LOG_FILE)
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
    try:
        return subprocess.Popen(argv, cwd=cwd, stdout=log, stderr=log,
                                stdin=subprocess.DEVNULL, env=env,
                                creationflags=NO_WINDOW)
    finally:
        # 句柄已交给子进程，父进程这份要关掉，否则每起一次就泄漏一个
        if log is not subprocess.DEVNULL:
            try:
                log.close()
            except OSError:
                pass


def _has(exe, module):
    probe = subprocess.run([exe, '-c', 'import %s' % module],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0


#: 依赖探测结果缓存文件：每次启动都开 4~5 个子进程逐个 import，
#: 实测要 1.1~1.3 s，占整个启动链路的四成。缓存到「Python 可执行文件 +
#: 依赖清单」的指纹上，依赖没变就直接读缓存（几十毫秒）。
DEPS_CACHE = os.path.join(TOOLS_DIR, 'deps_cache.json')
#: 缓存多久失效一次（天）。装/卸载依赖不会改变 exe 路径，所以要定期重探。
DEPS_CACHE_DAYS = 7


def _deps_fingerprint(exe, modules):
    """Python 解释器 + 依赖清单的指纹（换 Python 或改清单就重探）。"""
    mtime = ''
    try:
        mtime = str(int(os.path.getmtime(exe)))
    except OSError:
        pass
    return {'exe': os.path.abspath(exe), 'mtime': mtime,
            'modules': sorted(modules)}


def _deps_cache_read(finger):
    try:
        with open(DEPS_CACHE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get('fingerprint') != finger:
        return None
    try:
        age = time.time() - float(data.get('checked', 0))
    except (TypeError, ValueError):
        return None
    if age > DEPS_CACHE_DAYS * 86400:
        return None
    missing = data.get('missing')
    return missing if isinstance(missing, list) else None


def _deps_cache_write(finger, missing):
    try:
        with open(DEPS_CACHE, 'w', encoding='utf-8') as fh:
            json.dump({'fingerprint': finger, 'missing': list(missing),
                       'checked': time.time()}, fh, ensure_ascii=False)
    except OSError:
        pass


def missing_deps(exe, modules):
    """哪些依赖缺失（带缓存）。返回模块名列表，空列表表示都齐了。"""
    modules = list(modules or ())
    finger = _deps_fingerprint(exe, modules)
    cached = _deps_cache_read(finger)
    if cached is not None:
        # 缓存说「缺 X」，但可能刚装好：缺的项再真探一次，别让用户白等安装窗口
        return [m for m in cached if not _has(exe, m)]
    missing = [m for m in modules if not _has(exe, m)]
    _deps_cache_write(finger, missing)
    return missing


def portal_port_hint():
    """启动画面该盯的端口区间 ``(起始端口, 宽度)``。

    入口页从 8700 起往后找空位，落在哪个不确定，所以给的是整个扫描区间；
    启动画面逐个试，任意一个能连上就算就绪。
    """
    try:
        portal = _portal_module()
        low, high = portal.PORTAL_PORTS
        return low, max(1, high - low)
    except Exception:                     # noqa: BLE001
        return 8700, 30


def _spawn_splash(port=0, span=1, timeout=25):
    """拉起启动画面（独立进程，0.3 秒内可见，不等它）。

    入口页从双击到浏览器可用要 2~3 秒，这段时间原来完全没有任何窗口。
    splash 自己轮询端口区间，端口一通就关；失败也不影响主流程。
    """
    try:
        exe = sys.executable or 'python'
        argv = [exe, os.path.join(TOOLS_DIR, 'splash.py'),
                '--port', str(int(port or 0)), '--span', str(int(span or 1)),
                '--timeout', str(int(timeout))]
        subprocess.Popen(argv, cwd=TOOLS_DIR, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


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
        p_port = _portal_port()
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
    missing = missing_deps(exe, DEPS.get(name, DEFAULT_DEPS))
    if missing:
        # 装依赖要看得见进度：开一个命令行窗口跑 --install，本进程退出
        _spawn_console(['--install', tool_dir])
        return 0

    # 启动画面：入口页要 2~3 秒才可用，先给一块可见的反馈，端口一通它自己关。
    # 只在「启动入口页」时显示——单独启动某个模块本来就有浏览器标签页可看。
    if os.path.abspath(tool_dir) == os.path.abspath(PORTAL_DIR):
        try:
            low, span = portal_port_hint()
            _spawn_splash(low, span, timeout=25)
        except Exception:                 # noqa: BLE001
            pass                          # 启动画面失败绝不影响启动

    proc = _spawn_hidden([exe, run_py], cwd=tool_dir)
    # 原来是固定 sleep(1.5) 再看返回码；改成短间隔轮询：进程秒退能立刻报错，
    # 正常启动也不用白等满 1.5 s。
    deadline = time.time() + 3.0
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            if rc == 0:
                return 0
            return _fail(tool_dir, '启动后立即退出（返回码 %s）' % rc)
        time.sleep(0.1)
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


def stop_all(interactive=True):
    """停掉入口页（入口会顺手收掉它拉起的模块），再兜底清理独立启动的模块。

    ``interactive``：停完是否弹消息框告诉用户「已停止」。
    * 双击 `停止服务.vbs` 是人在操作 → 传 True，弹框确认（这是唯一能看到
      「已经停干净了」的反馈，因为后台服务没有命令行窗口）。
    * 脚本/命令行调用（`python _tools\\launcher.py --stop`）→ 传 False，
      **绝不弹框**：`_alert` 用的是 MessageBoxW，没人去点它时永不返回，
      调用方会永久卡在等消息框上（实测 20 秒都不退出）。
    """
    portal = _portal_module()
    stopped = []
    p_port = _portal_port()
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
    if interactive:
        _alert('已停止：\n%s' % text)
    return 0


def now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _say(text=''):
    """命令行输出。

    可能根本没有 stdout（被 wscript/无窗口方式拉起时 sys.stdout 是 None），
    也可能控制台是 GBK（编不出来的字符会抛 UnicodeEncodeError）；
    两种情况都不许让打印本身把流程打断。
    """
    line = '' if text is None else str(text)
    try:
        if sys.stdout is None:
            return
        print(line, flush=True)
    except UnicodeEncodeError:
        try:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            print(line.encode(enc, 'replace').decode(enc, 'replace'), flush=True)
        except Exception:                 # noqa: BLE001
            pass
    except (OSError, ValueError, AttributeError):
        pass


def _log(text):
    """追加到启动日志；日志写不动也不影响主流程。"""
    _rotate_log(LOG_FILE)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as fh:
            fh.write('[%s] %s\n' % (now_str(), text))
    except OSError:
        pass


def _report(text, also_print=True):
    """自动化路径的汇报口径：stdout 一行 + 日志一份（不弹框）。"""
    if also_print:
        _say(text)
    _log(text)


def _http_json(url, payload=None, timeout=3):
    """发一个请求并读 JSON（payload 不为 None 时用 POST）。失败返回 {}。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    try:
        out = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return {}
    return out if isinstance(out, dict) else {}


def _all_tool_names(portal):
    """全部工具目录名（入口登记的 + 额外常驻端口的），只要目录里有 run.py。"""
    names = [mod['tool'] for mod in portal.MODULES if mod.get('tool')]
    names += list(EXTRA_PORTS)
    out = []
    for name in names:
        if name in out:
            continue
        if os.path.exists(os.path.join(LAB_DIR, name, 'run.py')):
            out.append(name)
    return out


def restart_services():
    """静默重启入口页：收摊（POST /api/shutdown → 等端口释放 → kill_tools 兜底）再起。

    这是自动更新装完后的路径，**全程不弹消息框**：结果只进日志和 stdout。
    容忍「入口本来就不在」（用户手动关过）的情况。
    """
    try:
        portal = _portal_module()
    except Exception as exc:              # noqa: BLE001
        _report('[FAIL] 重启失败：读不到入口模块（%s）' % exc)
        return 1

    p_port = 0
    try:
        p_port = _portal_port()
    except Exception as exc:              # noqa: BLE001
        _report('探测入口端口出错（%s），按「入口不在」处理。' % exc)
        p_port = 0

    if p_port:
        _http_json('http://127.0.0.1:%d/api/shutdown' % p_port, payload={})
        _report('已请求入口页（:%d）收摊……' % p_port)
        deadline = time.time() + RESTART_WAIT
        released = False
        while time.time() < deadline:
            try:
                still = _portal_port()
            except Exception:             # noqa: BLE001
                still = 0
            if not still:
                released = True
                break
            time.sleep(0.4)
        if not released:
            _report('入口端口 %d s 内没释放，用 kill_tools 兜底。' % int(RESTART_WAIT))
    else:
        _report('入口页当前没有在运行，直接起一个新的。')

    try:
        killed = portal.kill_tools(_all_tool_names(portal))
    except Exception as exc:              # noqa: BLE001
        killed = []
        _log('kill_tools 出错（忽略）：%s' % exc)
    if killed:
        _report('已回收残留进程：%s' % '、'.join(killed))

    try:
        rc = start(PORTAL_DIR)
    except Exception as exc:              # noqa: BLE001
        _report('[FAIL] 重启失败：拉不起入口页（%s）' % exc)
        return 1
    if rc == 0:
        _report('入口页已重新启动。')
    else:
        _report('[FAIL] 重启失败：入口页启动返回码 %s' % rc)
    return rc


# ---------------------------------------------------------------- 命令行更新
def _updater_module():
    """导入 _core.updater，返回 (模块, 中文错误原因)。"""
    if LAB_DIR not in sys.path:
        sys.path.insert(0, LAB_DIR)
    try:
        from _core import updater
        return updater, ''
    except Exception as exc:              # noqa: BLE001
        return None, ('读不到更新模块（_core/updater.py 缺失或损坏，'
                      '也可能本机 Python 版本过低）：%s' % exc)


def _version_module(updater):
    """_core.version；拿不到就退回 updater 内部那份。"""
    try:
        from _core import version
        return version
    except Exception:                     # noqa: BLE001
        return getattr(updater, '_version', None)


def update_cli(apply=False, no_restart=False):
    """--update：只检查；--update --apply：检查并安装。返回 0 成功 / 1 失败。"""
    updater, why = _updater_module()
    if updater is None:
        _report('[ERROR] %s' % why)
        return 1
    version = _version_module(updater)
    if version is None:
        _report('[ERROR] 读不到版本真源（_core/version.py 缺失或损坏）。')
        return 1

    # 用磁盘上的版本（安装/回滚刚写完文件时，模块里的常量还是旧值）
    try:
        current = updater.installed_version()
    except Exception:                     # noqa: BLE001
        current = str(getattr(version, 'APP_VERSION', '') or '')
    release = str(getattr(version, 'RELEASE_DATE', '') or '')
    _report('当前版本 v%s（%s）' % (current or '未知', release or '未知日期'))

    try:
        remote = updater.latest_remote_tag()
    except getattr(updater, 'NoReleaseTag', ()):
        # 远端一个 tag 都没有：不是故障，是「作者还没发版」（新克隆的仓库就是这样）
        _report('远端仓库还没有 vX.Y.Z 发版 tag —— 当前是开发版，等作者发版后再检查。')
        return 0
    except updater.UpdateError as exc:
        _report('[ERROR] 检查更新失败：%s' % exc)
        return 1
    except Exception as exc:              # noqa: BLE001
        _report('[ERROR] 检查更新失败：%s' % exc)
        return 1

    latest = str(remote.get('version') or '')
    tag = str(remote.get('tag') or '')
    available = bool(version.is_newer(latest, current))
    _report('最新版本 v%s' % (latest or '未知'))
    _report('可更新：%s' % ('是' if available else '否'))
    if available:
        try:
            link = updater.notes_url(tag, latest)
        except Exception:                 # noqa: BLE001
            link = ''
        _report('更新说明：%s' % (link or '（仓库里还没有这一版的更新日志）'))

    if not apply:
        return 0
    if not available:
        _report('已经是最新版本，无需安装。')
        return 0

    _report('开始下载并安装 v%s ……' % latest)
    try:
        result = updater.update_now(tag=tag or None, restart=False)
    except updater.UpdateError as exc:
        _report('[ERROR] 安装更新失败：%s' % exc)
        return 1
    except Exception as exc:              # noqa: BLE001
        _report('[ERROR] 安装更新失败：%s' % exc)
        return 1

    result = result or {}
    to_version = str(result.get('to') or latest)
    _report('已更新到 v%s（覆盖 %s 个文件、新增 %s 个文件）'
            % (to_version, result.get('updated', '?'), result.get('added', '?')))
    backup = str(result.get('backup_dir') or '')
    _report('备份路径：%s' % (backup or '（无）'))

    if no_restart:
        _report('已按要求跳过重启（--no-restart）；请手动重启入口页让新版本生效。')
        return 0

    _report('正在重启入口页……')
    return restart_services()


def main(argv):
    argv = list(argv)
    if not argv:
        return start(PORTAL_DIR)
    if argv[0] == '--stop':
        # 只有双击 停止服务.vbs 时会带 --interactive（弹框确认「已停止」）；
        # 命令行/脚本来调不弹框，否则无交互环境下会永久卡在消息框上。
        return stop_all(interactive=('--interactive' in argv[1:]))
    if argv[0] == '--install':
        return install_and_start(argv[1])
    if argv[0] == '--restart':
        return restart_services()
    if argv[0] == '--update':
        return update_cli(apply='--apply' in argv[1:],
                          no_restart='--no-restart' in argv[1:])
    if argv[0] in ('-h', '--help'):
        _say(__doc__)
        return 0
    return start(argv[0])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
