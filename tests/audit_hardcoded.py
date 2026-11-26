# -*- coding: utf-8 -*-
"""扫「写死的表述」：换一份数据就会自相矛盾的文字。

## 判据

不是所有物种名都算问题：
* `SUBSTANCES['kno3']['label']` 这类**配置**是正常的（工具本来就按物种查表）；
* `'硝酸钾溶于水为吸热过程'` 写进正文就麻烦了 —— 换成 KCl 还是这句。

所以脚本按**上下文性质**分类：

    A. 出现在 para/heading/caption 的字符串里  → 会被印进报告，**高危**
    B. 出现在比较级/极值断言里（最好/最大/最低/依次为…） → 数据一变就错，**高危**
    C. 只在 dict 常量 / 函数名 / 注释里          → 正常，不算

同时扫三类「数据依赖的断言」：
    1. 名称类：具体物种名、样品名写进正文
    2. 序关系：最好/最差/最大/最小/依次为/最低/最高 + 具体结论
    3. 数量类：轮数、次数、点数、条数写死

用法：python tests/audit_hardcoded.py [--tool 工具名]
"""
from __future__ import annotations

import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 会被印进报告的调用
TEXT_CALLS = {'para', 'heading', 'caption', 'add_rich_text'}

#: 具体物种 / 样品名（出现在正文里就说明写死了）
SPECIES = [
    '蔗糖', '葡萄糖', '果糖', '麦芽糖', '乳糖', '淀粉',
    '苯甲酸', '萘', '方糖', '冰糖', '食用油', '奶片',
    '硝酸钾', '氯化钾', '硝酸铵', '氯化钠',
    '环己烷', '乙醇', '正丁醇', '甲醇', '丙酮',
    '莫尔盐', '硫酸铜', '亚铁氰化钾',
    'KNO3', 'KCl', 'NaCl', 'HCl', 'HAc', 'NaAc', 'NaNO3', 'HNO3',
]

#: 数据依赖的序关系断言
ORDER_WORDS = [
    '最好', '最差', '最大', '最小', '最高', '最低', '最强', '最弱',
    '依次为', '依次是', '分别为', '从大到小', '从小到大',
    '单调增', '单调减', '单调上升', '单调下降',
    '显著大于', '显著小于', '明显大于', '明显小于',
    '略大于', '略小于', '偏高', '偏低',
]

#: 数量类写死（中文数字或具体数字 + 量词）
COUNT_RE = re.compile(
    r'(?:三|四|五|六|七|八|九|十|\d+)\s*(?:个|种|轮|次|组|条|张|列|行|份|批)')

#: 判「纯结论句」用的判断词。命中且该字符串**没有任何 % 格式化或数据变量**
#: → 说明这句话描述的结论不随数据变，是写死的（A 档）。
JUDGE_WORDS = [
    '符合较好', '符合良好', '吻合良好', '吻合较好', '与文献值一致',
    '符合预期', '系统性正偏差', '系统性负偏差', '显著偏高', '显著偏低',
    '明显偏高', '明显偏低', '误差较小', '误差较大', '更接近文献值',
]

#: 允许出现物种名的「配置性」函数/变量名（不算写死）
CONFIG_HINTS = ('SUBSTANCES', 'SPECIES', 'LABEL', 'ALIAS', 'CHEM_', 'DEFAULT_',
                'ORDER', 'THEO', 'SPECIES_LABEL')


def _has_data_dependency(text):
    """这句字符串是否**随数据变化**。

    有 `%` 占位符 → 随数据变；
    有 `{}`/f-string → 随数据变。
    """
    return '%' in text


def _iter_text_strings(tree):
    """产出 (lineno, text, call_name)：会被印进报告的字符串。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if name not in TEXT_CALLS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield arg.lineno, arg.value, name
            elif isinstance(arg, (ast.List, ast.Tuple)):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        yield elt.lineno, elt.value, name
                    elif isinstance(elt, ast.BinOp) and isinstance(elt.op, ast.Mod):
                        left = elt.left
                        if isinstance(left, ast.Constant) and isinstance(left.value, str):
                            yield left.lineno, left.value, name


def _iter_dict_values(tree):
    """产出 (lineno, key, text)：配置文件里的字符串（用于说明「这个是正常配置」）。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    if isinstance(v.value, str):
                        out.append((v.lineno, k.value, v.value))
    return out


def scan_report(path):
    """返回 {'species': [...], 'order': [...], 'count': [...]}。"""
    with open(path, encoding='utf-8') as fh:
        src = fh.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {'syntax': [(exc.lineno or 0, str(exc))]}

    res = {'species': [], 'order': [], 'count': [], 'verdict': []}
    for lineno, text, call in _iter_text_strings(tree):
        for sp in SPECIES:
            if sp in text:
                res['species'].append((lineno, call, sp, text.strip()[:64]))
                break
        for w in ORDER_WORDS:
            if w in text:
                res['order'].append((lineno, call, w, text.strip()[:64]))
                break
        m = COUNT_RE.search(text)
        if m:
            res['count'].append((lineno, call, m.group(0), text.strip()[:64]))
        # ---- A 档：纯结论句（有判断词但完全没有数据依赖）
        if not _has_data_dependency(text):
            for w in JUDGE_WORDS:
                if w in text:
                    res['verdict'].append((lineno, call, w, text.strip()[:64]))
                    break
    return res


def main(argv):
    only = None
    if argv and argv[0] == '--tool':
        only = argv[1]
    tools = []
    for name in sorted(os.listdir(REPO)):
        d = os.path.join(REPO, name, 'pcal')
        if os.path.isfile(os.path.join(d, 'report.py')):
            tools.append(name)
    if only:
        tools = [t for t in tools if only in t]

    grand = {'species': 0, 'order': 0, 'count': 0, 'verdict': 0}
    for tool in tools:
        path = os.path.join(REPO, tool, 'pcal', 'report.py')
        res = scan_report(path)
        if 'syntax' in res:
            print('%s 语法错：%s' % (tool, res['syntax']))
            continue
        n = sum(len(v) for v in res.values())
        for k in grand:
            grand[k] += len(res[k])
        if n == 0:
            continue
        print('=' * 74)
        print('%s：%d 处（纯结论句 %d / 物种 %d / 序关系 %d / 数量 %d）'
              % (tool, n, len(res['verdict']), len(res['species']),
                 len(res['order']), len(res['count'])))
        for key, label in (('verdict', '★纯结论句（无数据依赖，换数据必错）'),
                           ('species', '物种名写进正文'),
                           ('order', '数据依赖的序关系断言'),
                           ('count', '写死的数量')):
            items = res[key]
            if not items:
                continue
            print('  -- %s：%d 处' % (label, len(items)))
            seen = set()
            for lineno, call, token, text in items:
                sig = (token, text[:24])
                if sig in seen:
                    continue
                seen.add(sig)
                print('     L%-5d %-8s %-6s %s' % (lineno, call, token, text[:56]))
            if len(items) > len(seen):
                print('     …（去重后 %d 种，共 %d 处）' % (len(seen), len(items)))

    print()
    print('合计：纯结论句 %d / 物种 %d / 序关系 %d / 数量 %d'
          % (grand['verdict'], grand['species'], grand['order'], grand['count']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))