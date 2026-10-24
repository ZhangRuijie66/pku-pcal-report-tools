# -*- coding: utf-8 -*-
"""用本机 Microsoft Word（PowerShell COM）把 .docx 导出为 PDF。

这台机器没有 pywin32，也没有 LibreOffice，所以走 PowerShell 的 COM。
缺少 Word 时给出可读错误，由调用方决定怎么提示。
"""
from __future__ import annotations

import os
import shutil
import subprocess

POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
    $doc = $word.Documents.Open($env:PCAL_DOCX, $false, $true)
    $doc.SaveAs2($env:PCAL_PDF, 17)
    $doc.Close(0)
} finally {
    $word.Quit()
}
"""


class PdfError(RuntimeError):
    pass


def _unique_path(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    for i in range(2, 100):
        candidate = '%s (%d)%s' % (root, i, ext)
        if not os.path.exists(candidate):
            return candidate
    return '%s-%d%s' % (root, os.getpid(), ext)


def _run_powershell(docx, pdf, timeout):
    if not POWERSHELL:
        raise PdfError('找不到 PowerShell，无法调用 Microsoft Word 导出 PDF')
    env = dict(os.environ)
    env['PCAL_DOCX'] = os.path.abspath(docx)
    env['PCAL_PDF'] = os.path.abspath(pdf)
    try:
        proc = subprocess.run(
            [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', PS_SCRIPT],
            capture_output=True, timeout=timeout, env=env,
            creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise PdfError('Word 导出 PDF 超时（%d s），请关闭 Word 后重试' % timeout)
    except OSError as exc:
        raise PdfError('无法启动 PowerShell：%s' % exc)
    if proc.returncode != 0 or not os.path.exists(pdf):
        detail = (proc.stderr or proc.stdout or b'').decode('utf-8', 'replace')
        detail = detail.strip().splitlines()[-3:]
        raise PdfError('Word 导出 PDF 失败：' + (' / '.join(detail) or
                                                '返回码 %d' % proc.returncode))


def convert(docx, pdf=None, timeout=180, force=False, runner=None):
    """把 docx 转成 pdf；已存在且比 docx 新时直接复用。返回 pdf 路径。"""
    docx = os.path.abspath(docx)
    if not os.path.isfile(docx) or not docx.lower().endswith('.docx'):
        raise PdfError('不是有效的 .docx 文件：%s' % docx)
    if pdf is None:
        pdf = os.path.splitext(docx)[0] + '.pdf'
    pdf = os.path.abspath(pdf)
    if (not force and os.path.exists(pdf)
            and os.path.getmtime(pdf) >= os.path.getmtime(docx)):
        return pdf
    if os.path.exists(pdf):
        # 旧 PDF 被查看器占用时不要覆盖，换一个带序号的名字
        try:
            with open(pdf, 'a+b'):
                pass
        except OSError:
            pdf = _unique_path(pdf)
    run = runner or _run_powershell
    run(docx, pdf, timeout)
    if not os.path.exists(pdf) or os.path.getsize(pdf) <= 0:
        raise PdfError('Word 没有生成 PDF：%s' % pdf)
    return pdf
