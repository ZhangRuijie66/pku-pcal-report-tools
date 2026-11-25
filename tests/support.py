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
# 测试用的真实实验数据切片（随仓库走，见 tests/fixtures/README.md）。
# 以前测试直接读仓库外的 `1 燃烧热/`、`2 溶解热/`、`3 紫外光谱搭建/数据/`，
# 那些目录不受 git 跟踪 —— 新 clone 上数值基准会静默降级成 skip，看起来全绿
# 实际少跑好几项。改成读 fixtures 后，任何机器上结果一致。
FIXTURES = REPO_ROOT / 'tests' / 'fixtures'
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
    """按唯一别名载入某个工具的 pcal 子模块。

    ``pcal/server.py`` 里有 ``sys.path.insert(0, ROOT)`` + ``from pcal import …``，
    所以**导入 server 必然把该工具的 pcal 以裸包名留在 sys.modules 里**
    （`server` 依赖它，删了会破坏已导入的 server）。这种情况交给
    ``drop_bare_pcal()`` 由调用方在合适时机清理；这里自动清一次，
    让「载入 server 之后紧接着载入别的工具」不再串味。

    ⚠️ 只是把裸 'pcal' 从 sys.modules 摘掉，已导入的 server 模块对象仍可用
    （它内部的 `pcal` 引用是模块对象，不靠 sys.modules 查找）。
    """
    before = set(sys.modules)
    mod = importlib.import_module('%s.%s' % (load_pcal(tool), module))
    if module == 'server':
        # 先确认这个 server 确实能用（它的依赖已在导入时绑定好），再清裸包名，
        # 这样后面载入别的工具时不会拿到这个工具的 pcal。
        drop_bare_pcal(before)
    return mod


def drop_bare_pcal(before=None):
    """清掉 ``sys.modules`` 里的**裸包名** ``pcal`` 及其子模块。

    为什么需要：每个工具的 ``pcal/server.py`` 都有
    ``sys.path.insert(0, ROOT)`` + ``from pcal import …``。导入任一 server
    就会把**那个工具**的 pcal 以裸包名注册进 sys.modules；之后别的工具的
    server（如紫外的 ``from pcal import gcalc_bridge``）拿到的却是前一个工具的
    pcal，报 ``ImportError: cannot import name 'xxx'``。

    症状是**顺序依赖**：单跑某个文件全绿，全量跑就 1~3 项 ERROR
    （2026-11-09 电化学踩过、2026-11-25 蒸气压又踩过一次，
    那次是 test_uv_calibration 留在 sys.modules 里的紫外 pcal 把
    蒸气压的 `from pcal import vapor` 顶掉了）。

    ``before``：导入前拍的 ``set(sys.modules)``。给了就只删**新出现的**，
    避免把外层已经装好的 pcal 删掉（更安全）。
    """
    if before is None:
        names = [n for n in sys.modules if n == 'pcal' or n.startswith('pcal.')]
    else:
        names = [n for n in sys.modules
                 if n not in before and (n == 'pcal' or n.startswith('pcal.'))]
    for name in names:
        del sys.modules[name]
    return len(names)


def load_module_isolated(tool: str, module: str):
    """``load_module`` 的隔离版：导完顺手清掉裸 ``pcal``。

    返回已导入的模块对象（模块对象本身仍然可用，删的只是 sys.modules 里的
    注册项；``pcal_test_<hash>`` 那套唯一别名不受影响）。
    """
    before = set(sys.modules)
    mod = load_module(tool, module)
    drop_bare_pcal(before)
    return mod


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
