# -*- coding: utf-8 -*-
"""测试公用：按需加载某个工具的 pcal 包，并提供 OMML 解析工具。

11 个工具各自带一份 pcal 包，包名相同；这里用唯一别名加载，避免
sys.modules 互相覆盖。统一核心之后，同一套断言可以对所有工具复用。
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def load_pcal(tool: str) -> str:
    """把 <tool>/pcal 以唯一包名载入，返回包名。"""
    pkg_dir = REPO_ROOT / tool / 'pcal'
    if not pkg_dir.is_dir():
        raise FileNotFoundError(pkg_dir)
    name = 'pcal_test_' + hashlib.md5(tool.encode('utf-8')).hexdigest()[:10]
    if name in sys.modules:
        return name
    spec = importlib.util.spec_from_file_location(
        name, pkg_dir / '__init__.py',
        submodule_search_locations=[str(pkg_dir)])
    if spec is None or spec.loader is None:
        raise ImportError('无法加载 %s' % pkg_dir)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def load_module(tool: str, module: str):
    return importlib.import_module('%s.%s' % (load_pcal(tool), module))


def parse_omml(fragment: str) -> ET.Element:
    """把不带命名空间声明的 OMML 片段包成可解析的 XML。"""
    return ET.fromstring(
        '<root xmlns:m="%s" xmlns:w="%s">%s</root>' % (M_NS, W_NS, fragment))


def omml_runs(fragment: str):
    """返回 [(文本, 是否正体), …]；没有 m:sty=p 的 run 是 Word 默认斜体。"""
    root = parse_omml(fragment)
    out = []
    for run in root.iter(M + 'r'):
        text = run.find(M + 't')
        sty = run.find(M + 'rPr/' + M + 'sty')
        upright = sty is not None and sty.get(M + 'val') == 'p'
        out.append((text.text if text is not None else '', upright))
    return out


def omml_text(fragment: str) -> str:
    return ''.join(text.text or '' for text in parse_omml(fragment).iter(M + 't'))


def find_one(fragment: str, tag: str):
    found = list(parse_omml(fragment).iter(M + tag))
    if len(found) != 1:
        raise AssertionError('期望 1 个 m:%s，实际 %d 个' % (tag, len(found)))
    return found[0]


def run_texts(paragraph):
    """python-docx 段落里每个 run 的 (文本, 斜体, 上标, 下标, 字号)。"""
    out = []
    for run in paragraph.runs:
        size = run.font.size.pt if run.font.size is not None else None
        out.append((run.text, bool(run.italic), bool(run.font.superscript),
                    bool(run.font.subscript), size))
    return out
