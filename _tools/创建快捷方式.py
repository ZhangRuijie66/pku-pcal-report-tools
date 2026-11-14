# -*- coding: utf-8 -*-
"""创建/修复桌面快捷方式：指向本套件的 启动入口.vbs，带锥形瓶图标。

以前这一步只写在技能文档里（手工敲一段 PowerShell），换台电脑就得重来，
而且很容易漏掉 ``IconLocation`` —— 那样会退回 pythonw.exe 的默认蓝图标，
虽然有功能但一看就不像正经程序。现在做成脚本，任何机器上都能一条命令重建：

    python _tools/创建快捷方式.py              # 建到桌面
    python _tools/创建快捷方式.py --all-user   # 建到「所有用户」桌面（需权限）
    python _tools/创建快捷方式.py --target D:\\某处\\x.lnk
    python _tools/创建快捷方式.py --remove     # 删掉快捷方式

也可以用 ``python _tools/创建快捷方式.py --check`` 只回读现有快捷方式做核对。

⚠️ 路径一律从 ``__file__`` 推导：换机器、换目录、便携版解压到 D: 或 E:
都不用改脚本。这也正是 ``tests/test_portable.py`` 要求的行为。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS_DIR)                     # 套件根目录
VBS = os.path.join(ROOT, '启动入口.vbs')
ICON = os.path.join(TOOLS_DIR, 'pcal.ico')
STOP_VBS = os.path.join(ROOT, '停止服务.vbs')
LINK_NAME = '物化实验报告工具'

#: wscript.exe 的固定位置（用来无黑框跑 .vbs）。用户级安装的 Windows 也在这里。
WSCRIPT = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                       'System32', 'wscript.exe')

DESCRIPTION = '一键启动物化实验报告工具（后台运行，没有命令行窗口）'


def _run_ps(script):
    """跑一段 PowerShell，返回 (rc, stdout, stderr)（都按 UTF-8 解）。

    不能用 ``text=True``：中文 Windows 上 PowerShell 往管道里写的是本机
    GBK，直接按 utf-8 解会 UnicodeDecodeError。必须先取 bytes 再解。
    """
    exe = 'powershell'
    r = subprocess.run([exe, '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True)
    out = (r.stdout or b'').decode('utf-8-sig', 'replace')
    err = (r.stderr or b'').decode('utf-8-sig', 'replace')
    return r.returncode, out, err


def default_link_path(all_user=False):
    if all_user:
        base = os.path.join(os.environ.get('PUBLIC', r'C:\Users\Public'), 'Desktop')
    else:
        base = os.path.join(os.path.expanduser('~'), 'Desktop')
    return os.path.join(base, LINK_NAME + '.lnk')


def check_prerequisites():
    """返回缺失项的说明列表（空列表 = 都齐）。"""
    problems = []
    if not os.path.isfile(VBS):
        problems.append('缺少启动脚本：%s' % VBS)
    if not os.path.isfile(WSCRIPT):
        problems.append('找不到 wscript.exe：%s' % WSCRIPT)
    if not os.path.isfile(ICON):
        # 图标缺失不致命：快捷方式还是能用，只是回到默认图标
        problems.append('（非致命）缺少图标：%s' % ICON)
    return problems


def create(link_path, all_user=False):
    """创建（或就地更新）快捷方式，返回 (ok, message)。"""
    fatal = [p for p in check_prerequisites() if not p.startswith('（非致命）')]
    if fatal:
        return False, '无法创建快捷方式：\n  ' + '\n  '.join(fatal)

    # 用 PowerShell 的 WScript.Shell 建 .lnk（纯 Python 没有标准库支持）
    ps = r'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$sh = New-Object -ComObject WScript.Shell
$link = $sh.CreateShortcut($env:PCAL_LNK)
$link.TargetPath       = $env:PCAL_WSCRIPT
$link.Arguments        = '"' + $env:PCAL_VBS + '"'
$link.WorkingDirectory = $env:PCAL_ROOT
# 图标必须显式给，否则会退回 pythonw.exe 的默认蓝图标
if ($env:PCAL_ICON -and (Test-Path $env:PCAL_ICON)) {
    $link.IconLocation = $env:PCAL_ICON + ',0'
}
$link.Description      = $env:PCAL_DESC
$link.Save()
Write-Output 'SAVED'
'''
    env_backup = dict(os.environ)
    os.environ.update({
        'PCAL_LNK': link_path,
        'PCAL_WSCRIPT': WSCRIPT,
        'PCAL_VBS': VBS,
        'PCAL_ROOT': ROOT,
        'PCAL_ICON': ICON,
        'PCAL_DESC': DESCRIPTION,
    })
    try:
        rc, out, err = _run_ps(ps)
    finally:
        os.environ.clear()
        os.environ.update(env_backup)

    if rc != 0 or 'SAVED' not in out:
        detail = (err or out).strip().splitlines()
        tail = '\n  '.join(detail[-4:]) if detail else '（无输出）'
        return False, 'PowerShell 创建快捷方式失败（返回码 %s）：\n  %s' % (rc, tail)

    ok, info = read(link_path)
    if not ok:
        return False, '文件似乎写出来了但回读失败：%s' % info
    if os.path.normcase(info.get('Target', '')) != os.path.normcase(WSCRIPT):
        return False, '回读校验失败：Target 是 %r，应为 %r' % (
            info.get('Target'), WSCRIPT)
    return True, info


def read(link_path):
    """回读快捷方式属性，返回 (ok, dict|error_message)。"""
    if not os.path.isfile(link_path):
        return False, '文件不存在：%s' % link_path
    # 文件必须是 .lnk / .url：WScript.Shell.CreateShortcut 对别的后缀会抛
    # COMException，而 PowerShell 对这类错误**不会**自动变成非零退出码。
    # 必须 try/catch 把错误显式打到 stdout 里，否则调用方只看到
    # "Target=null" 这种空属性，误以为读到了。
    ps = r'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
try {
    $sh = New-Object -ComObject WScript.Shell
    $l = $sh.CreateShortcut($env:PCAL_LNK)
    $o = @{ Target=$l.TargetPath; Args=$l.Arguments; WorkDir=$l.WorkingDirectory;
            Icon=$l.IconLocation; Desc=$l.Description }
    Write-Output ('OK ' + ($o | ConvertTo-Json -Compress))
} catch {
    Write-Output ('ERR ' + $_.Exception.Message)
    exit 1
}
'''
    env_backup = dict(os.environ)
    os.environ['PCAL_LNK'] = link_path
    try:
        rc, out, err = _run_ps(ps)
    finally:
        os.environ.clear()
        os.environ.update(env_backup)

    body = (out or '').strip().splitlines()
    last = body[-1] if body else ''
    if last.startswith('ERR '):
        return False, last[4:].strip()
    if rc != 0:
        return False, (err or out).strip() or 'PowerShell 返回码 %s' % rc
    if not last.startswith('OK '):
        return False, '读不出快捷方式属性：%r' % out[:200]
    try:
        return True, json.loads(last[3:])
    except ValueError:
        return False, '快捷方式属性不是合法 JSON：%r' % last[3:][:200]


def remove(link_path):
    if not os.path.isfile(link_path):
        return True, '本来就不存在：%s' % link_path
    try:
        os.remove(link_path)
    except OSError as exc:
        return False, '删除失败（可能被资源管理器占用）：%s' % exc
    return True, '已删除：%s' % link_path


def refresh_icon_cache():
    """通知资源管理器刷新图标缓存（失败无所谓，只是显示延迟）。"""
    exe = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                       'System32', 'ie4uinit.exe')
    if not os.path.isfile(exe):
        return
    try:
        subprocess.run([exe, '-show'], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def main(argv):
    ap = argparse.ArgumentParser(
        description='创建/修复「物化实验报告工具」桌面快捷方式')
    ap.add_argument('--target', help='快捷方式输出路径（默认桌面同名 .lnk）')
    ap.add_argument('--all-user', action='store_true',
                    help='建到「所有用户」桌面（需要管理员权限）')
    ap.add_argument('--remove', action='store_true', help='删除快捷方式')
    ap.add_argument('--check', action='store_true',
                    help='只回读现有快捷方式，不修改')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出结果')
    args = ap.parse_args(argv)

    link = args.target or default_link_path(args.all_user)

    if args.check:
        ok, info = read(link)
        if args.json:
            print(json.dumps({'ok': ok, 'path': link, 'info': info},
                             ensure_ascii=False))
        elif ok:
            print('快捷方式：%s' % link)
            print('  目标    %s' % info.get('Target'))
            print('  参数    %s' % info.get('Args'))
            print('  工作目录 %s' % info.get('WorkDir'))
            print('  图标    %s' % info.get('Icon'))
            ok_icon = os.path.normcase(
                str(info.get('Icon', '')).split(',')[0]) == os.path.normcase(ICON)
            print('  图标是否正确：%s' % ('是' if ok_icon else '否（会显示默认蓝图标）'))
        else:
            print('读不到快捷方式：%s' % info)
        return 0 if ok else 1

    if args.remove:
        ok, msg = remove(link)
        print(msg)
        return 0 if ok else 1

    problems = check_prerequisites()
    for p in problems:
        print(('[WARN] ' if p.startswith('（非致命）') else '[ERROR] ') + p)

    ok, result = create(link, args.all_user)
    if not ok:
        print(result)
        print('\n提示：本脚本依赖 Windows 自带的 PowerShell 与 WScript.Shell。'
              '在非 Windows 系统上无法创建 .lnk。')
        return 1

    if args.json:
        print(json.dumps({'ok': True, 'path': link, 'info': result},
                         ensure_ascii=False))
        return 0

    print('已创建快捷方式：%s' % link)
    print('  目标    %s' % result.get('Target'))
    print('  参数    %s' % result.get('Args'))
    print('  工作目录 %s' % result.get('WorkDir'))
    print('  图标    %s' % result.get('Icon'))
    refresh_icon_cache()
    print('\n桌面双击即可启动（后台运行，不弹命令行窗口）。')
    if os.path.isfile(STOP_VBS):
        print('收摊：双击桌面/文件夹里的「停止服务.vbs」，'
              '或在入口页点「停止全部服务」。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
