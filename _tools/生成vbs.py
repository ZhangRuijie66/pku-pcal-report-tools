# -*- coding: utf-8 -*-
"""重新生成物化实验报告工具的各个 .vbs 无黑框启动器（UTF-16，WSH 原生编码）。

    python 生成vbs.py

改启动逻辑优先改 launcher.py；这里的 vbs 只负责「找到 python.exe + 隐藏窗口」。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHARED = r'''Option Explicit
' 物化实验报告工具 —— 统一的无黑框启动逻辑。
' 用法：wscript //nologo hidden-launch.vbs [<工具目录> | --stop]
' 这里只负责找到 python.exe；装依赖、起服务、停服务都在同目录的 launcher.py 里。
Dim sh, fso, launcher, py, args
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set args = WScript.Arguments
launcher = fso.GetAbsolutePathName( _
    fso.GetParentFolderName(WScript.ScriptFullName) & "\launcher.py")

py = FindPython()
If py = "" Then
    sh.Popup "在这台电脑上没有找到 Python 3。" & vbCrLf & vbCrLf & _
             "1) 先安装 Python 3.10+（安装时勾选 Add python.exe to PATH）；" & vbCrLf & _
             "2) 再双击根目录的 安装依赖.cmd 装好依赖；" & vbCrLf & _
             "3) 然后重新双击本工具的 启动.vbs 或桌面快捷方式。", _
             0, "物化实验报告工具", 48
    WScript.Quit 1
End If

If args.Count < 1 Then
    sh.Run """" & py & """ """ & launcher & """", 0, False
ElseIf args(0) = "--stop" Then
    sh.Run """" & py & """ """ & launcher & """ --stop", 0, False
Else
    sh.Run """" & py & """ """ & launcher & """ """ & args(0) & """", 0, False
End If

Function FindPython()
    Dim roots, vers, r, v, cand
    FindPython = ""
    roots = Array("C:\", _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\")
    vers = Array("313", "312", "311", "310", "39")
    For Each r In roots
        For Each v In vers
            cand = r & "Python" & v & "\python.exe"
            If fso.FileExists(cand) Then
                FindPython = cand
                Exit Function
            End If
        Next
    Next
    If fso.FileExists("C:\Windows\py.exe") Then
        FindPython = "C:\Windows\py.exe"
        Exit Function
    End If
    If sh.Run("""python.exe"" -c ""import sys""", 0, True) = 0 Then FindPython = "python.exe"
End Function
'''

THIN = r'''Option Explicit
' 无黑框启动「%NAME%」。服务在后台运行，没有命令行窗口。
' 要停掉它：入口页上点「停止全部服务」，或双击根目录的 停止服务.vbs。
Dim sh, fso, here, target
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
target = fso.GetAbsolutePathName(fso.GetParentFolderName(here) & "\_tools\hidden-launch.vbs")
sh.Run "wscript.exe //NoLogo """ & target & """ """ & here & """", 0, False
'''

ENTRY = r'''Option Explicit
' 物化实验报告工具 —— 一键启动（无黑框）。
' 双击这里，或双击桌面的「物化实验报告工具」快捷方式：
' 全部已安装模块在后台起来，浏览器自动打开入口页 http://127.0.0.1:8700。
Dim sh, fso, here, target, portal
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
target = fso.GetAbsolutePathName(here & "\_tools\hidden-launch.vbs")
portal = fso.GetAbsolutePathName(here & "\物化实验报告工具")
sh.Run "wscript.exe //NoLogo """ & target & """ """ & portal & """", 0, False
'''

STOP = r'''Option Explicit
' 停止入口页和全部实验模块。
' 后台服务已经没有命令行窗口，收摊就靠这里（停完会弹一个确认框）。
Dim sh, fso, here, target
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
target = fso.GetAbsolutePathName(here & "\_tools\hidden-launch.vbs")
sh.Run "wscript.exe //NoLogo """ & target & """ --stop", 0, False
'''


def write(rel, text):
    path = os.path.join(ROOT, rel)
    with io.open(path, 'w', encoding='utf-16') as fh:
        fh.write(text)
    print('written', rel)


write(r'_tools\hidden-launch.vbs', SHARED)
write(r'启动入口.vbs', ENTRY)
write(r'停止服务.vbs', STOP)
for folder, name in [(u'物化实验报告工具', u'统一入口'),
                     (u'燃烧热工具', u'燃烧热的测定'),
                     (u'溶解热工具', u'溶解热的测定'),
                     (u'紫外光谱工具', u'紫外可见吸收光谱'),
                     (u'表面吸附工具', u'溶液表面吸附'),
                     (u'化学动力学工具', u'化学反应动力学'),
                     (u'高斯计算工具', u'高斯计算（TD-DFT）')]:
    write(os.path.join(folder, u'启动.vbs'), THIN.replace('%NAME%', name))
