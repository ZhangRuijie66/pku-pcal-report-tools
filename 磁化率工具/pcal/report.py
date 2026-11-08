# -*- coding: utf-8 -*-
"""生成《磁化率的测定》实验报告 .docx。

    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分
    3 数据与结果
      3.1 实验数据记录
      3.2 莫尔盐标定
      3.3 各样品磁化率计算
    4 结果与讨论
      4.1 实验结果 / 4.2 实验讨论 / 4.3 实验结论
    参考文献
"""
from __future__ import annotations

import decimal
import math
import os

import numpy as np
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from . import plotting
from .docxkit import ReportBuilder
from .sigfig import k, pm, sci, sci_pm

ITALIC = {'italic': True}
TITLE = '磁化率的测定'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')


# ---------------------------------------------------------------- 数字格式


















DASH = '—'


# sci / sci_pm 已统一到 pcal/sigfig.py（canonical = _core/sigfig.py），
# 不要在本文件里再各写一份：历史上 6 个模块的本地副本对 None/NaN/inf
# 分化出 6 种行为（有的抛 TypeError/ValueError/OverflowError、有的把
# 破折号塞进科学记数法印成 (—)×10^{-5}），审计 B P1-3。
# sci / sci_pm 已统一到 pcal/sigfig.py（canonical = _core/sigfig.py），
# 不要在本文件里再各写一份：历史上 6 个模块的本地副本对 None/NaN/inf
# 分化出 6 种行为（有的抛 TypeError/ValueError/OverflowError、有的把
# 破折号塞进科学记数法印成 (—)×10^{-5}），审计 B P1-3。
MU_B_SEGS = (' ', ('t', 'μ', ITALIC), ('t', '_{B}', {}))


def _g4(v):
    """表 1 的 4 位小数格：缺测（None / NaN）印 '—'，绝不印 'nan'。"""
    if v is None or not np.isfinite(v):
        return '—'
    return '%.4f' % v


def _num(v, nd):
    """表格数值格：None / NaN 印 '—'。

    反磁性物质（χ_m < 0，如 K₄Fe(CN)₆）没有永久磁矩，μ/n 是 None；
    直接 '%.*f' % None 会抛 TypeError，所以每一处都要先判 None。
    """
    if v is None or not np.isfinite(v):
        return '—'
    return '%.*f' % (nd, v)


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)

    # ---- 封面
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    group_txt = ('%s 组 %s 号' % (group, group_no)) if (group and group_no) else (group or group_no)
    room = cfg.get('room_temp')
    pres = cfg.get('pressure')
    room_txt = ('%.1f ℃' % float(room)) if room not in (None, '') else None
    pres_txt = ('%.1f kPa' % float(pres)) if pres not in (None, '') else None
    cover = {
        '题目': TITLE,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '实验日期': cfg.get('date'),
        '室温': room_txt,
        '大气压强': pres_txt,
    }
    missing = [key for key, v in cover.items() if not str(v or '').strip()]
    if missing:
        log('封面字段为空：%s' % '、'.join(missing))

    rb.set_cover(cover, title_size=26.0)
    # 页眉：模板页眉里第三段是占位符「物理化学实验 | 实验题目」，
    # 不替换的话每页页眉都印着「实验题目」四个字（其余 10 个模块各调用一次）。
    rb.set_header_title(TITLE)
    log('封面已生成')

    # ---- 摘要
    # ⚠ 「摘要」是**正文段落的加粗标签**，不是标题：早先写成 rb.heading('摘要', 1)
    # 会让 PDF 书签首项变成「摘要」、与「1 引言」同级（审计 B P1-5）。
    # 其余 10 个模块都是 {'text': '摘要 ', 'bold': True, 'cjk': '黑体'} 这种写法。
    samples = analysis['samples']
    sample_names = list(samples.keys())

    # 摘要内容（片段列表：χ_m / μ_B 必须走真下标，不能拼成普通字符串）
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验采用古埃磁天平法测定了莫尔盐、硫酸铜、亚铁氰化钾等物质的磁化率。'
        '以莫尔盐为标准样品标定仪器常数，在室温条件下测量了各样品在不同励磁电流下的'
        '质量变化，计算出各样品的比磁化率、摩尔磁化率、分子磁矩及未成对电子数。'
    ]

    # 添加主要结果
    for name in sample_names:
        s = samples[name]
        if s['chi_m'] is None:
            continue
        abs_segs += [
            '实验测得%s的摩尔磁化率为 ' % name,
            ('t', 'χ_{m}', ITALIC), ' = ', sci(s['chi_m']), ' m^{3}·mol^{-1}',
        ]
        # χ_m < 0 是反磁性物质（如 K₄Fe(CN)₆·3H₂O）：没有永久磁矩，
        # 不能印成「分子磁矩为 0」——那是把反磁性说成「磁矩为零的顺磁体」。
        if s['mu'] is None:
            abs_segs.append(
                '（小于 0，为反磁性物质，无永久磁矩、未成对电子数为 0）。')
            continue
        abs_segs += ['，分子磁矩为 ', '%.3f' % s['mu'], *MU_B_SEGS,
                     '，未成对电子数约为 %.1f。' % s['n']]

    abs_segs.append('实验结果与理论预期基本吻合，验证了古埃磁天平法的可靠性。')

    rb.para(abs_segs)
    rb.para([('关键词', {'bold': True}), ' 磁化率；古埃磁天平；未成对电子数；摩尔磁化率'])
    log('摘要已生成')

    # ---- 1 引言
    rb.heading('1 引言', 1, page_break_before=True)
    rb.para(['该实验的实验目的、实验原理及实验方法如图1所示。'])

    fig_no = 1
    if os.path.exists(INTRO_IMG):
        rb.figure(INTRO_IMG, caption='图1  实验目的、原理及方法', width_cm=14.5)
    else:
        rb.caption('图1  实验目的、原理及方法')
    log('引言已生成')

    # ---- 2 实验部分
    rb.heading('2 实验部分', 1)
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para(['磁天平（配电子天平），样品管，研钵，小广口瓶，脱脂棉。'])
    rb.heading('2.1.2 试剂', 3)
    rb.para(['莫尔盐（AR），CuSO₄·5H₂O（AR），K₄Fe(CN)₆·3H₂O（AR），未知样。'])

    rb.heading('2.2 实验内容', 2)
    rb.para([
        '（1）将标样莫尔盐及其他固体物质在相应研钵中研细，各样品粉末粗细尽量均匀，'
        '装装在小广口瓶中备用，注意盖上瓶盖以防样品风化。'
    ])
    rb.para([
        '（2）在打开磁天平电源前确定已将励磁电流调回 0 A、电流细调调节旋钮左旋至最小。'
        '将擦拭干净的空样品管挂在磁天平悬钩上，调节极缝使样品管与两磁极距离距离相等，'
        '并调节样品管上吊线长度，使样品管的底部恰好处在极缝中心高度处。'
    ])
    rb.para([
        '（3）先在励磁电流为 0 A 时称重，然后调节电流，分别在励磁电流为 3 A 和 4 A 的磁场下称重。'
        '将励磁电流调至 4.5 A 并停留一定时间（至少 1 分钟），将励磁电流调小，'
        '再依次在 4 A、3 A 和 0 A 下称重。'
    ])
    rb.para([
        '（4）将莫尔盐粉末小心装入样品管中至 5 cm 高，将样品管挂在磁天平的悬钩上，'
        '在励磁电流分别为 0 A、3 A 和 4 A 下测定其质量，并记录磁场强度及此时的室温。'
    ])
    rb.para([
        '（5）按同样方法装样至 6 cm，重新测量。'
    ])
    rb.para([
        '（6）倒出样品管中的莫尔盐，将样品管里外用脱脂棉擦、擦净，依次小心装入 '
        'CuSO₄·5H₂O 及 K₄Fe(CN)₆·3H₂O 粉末，注意保持样品与莫尔盐标样在粉末粗细程度、'
        '装填高度及填充密实度的一致，按步骤（3）中的程序进行称量。'
    ])
    rb.para([
        '（7）同法测量未知样品，建议在每个高度平行测定 2 次，结果取平均值以增加可信性。'
    ])
    log('实验部分已生成')

    # ---- 3 数据与结果
    rb.heading('3 数据与结果', 1)
    rb.heading('3.1 实验数据记录', 2)

    T_C = analysis['temperature_C']
    T_K = analysis['temperature_K']
    chi_std = analysis['chi_std']

    rb.para(['室温 %.1f ℃（%.2f K）。' % (T_C, T_K)])

    # 表 1：原始数据
    #
    # ⚠ 口径必须统一：整张表都用**毛重**（空管、莫尔盐、各样品一视同仁），
    # 这样每一行都满足 m − m₀ = Δm。曾经的 bug：样品的 m_field 是 None，
    # 于是回落到 m_zero（= 净质量），印出「m₀ = m = 2.4722、Δm = +0.0054」，
    # 读者一减对不上，而且同表里空管/莫尔盐是毛重、样品是净质量，两种口径混排。
    # 样品的净质量（= 毛重 − 空管质量）交给表注说明。
    table_data = analysis['table']
    headers = ['样品', 'm₀ / g', 'm / g', 'Δm / g']
    rows = []
    for item in table_data:
        # Δm 用毛重口径（= m − m₀），与同行的 m₀/m 严格自洽；
        # 扣空管后的值（item['delta_m']）在正文 3.3 的 χ 公式里使用，不进表 1。
        dm = item.get('delta_m_gross')
        if dm is None:
            dm = item.get('delta_m')
        rows.append([
            item['name'],
            _g4(item.get('m_zero')),
            _g4(item.get('m_field')),
            _g4(dm),
        ])

    rb.caption('表1  不同条件下的样品称量值')
    # 原来没传 widths_cm，四列被 Word 均分成 4.0 cm，表头与数据都不换行但
    # 视觉上过宽、与表 2 不齐。按内容给定列宽，总和 16.0 cm = 正文宽。
    rb.table(headers, rows, widths_cm=[3.4, 4.2, 4.2, 4.2])
    rb.para([
        '注：', ('t', 'm_{0}', ITALIC), ' 为 0 A（无磁场）时的称量值，',
        ('t', 'm', ITALIC), ' 为 3.00 A 时的称量值，',
        ('t', 'Δ m', ITALIC), ' = ', ('t', 'm', ITALIC), ' − ',
        ('t', 'm_{0}', ITALIC),
        '；三者均为含样品管的毛重。各样品的净质量 = 该行毛重 − 空管毛重，'
        '扣除空管后的质量变化 = 该行 ', ('t', 'Δ m', ITALIC), ' − 空管的 ',
        ('t', 'Δ m', ITALIC), '（后者用于 3.3 节的 ', ('t', 'χ', ITALIC),
        ' 计算）。',
    ], indent_chars=0)
    rb.blank()
    log('表1 已生成')

    rb.heading('3.2 莫尔盐标定', 2)
    rb.para([
        '由公式 ', ('m', r'\chi_{\text{莫}} = \frac{9500 \times 10^{-9}}{T + 1} \times 4\pi'),
        '^{[1]} 计算莫尔盐的比磁化率，其中 ', ('t', 'T', ITALIC), ' 为热力学温度。'
    ])
    rb.para([
        '本次实验测得莫尔盐的比磁化率为 ',
        ('m', r'\chi_{\text{莫}} = '),
        ('t', sci(chi_std), {}),
        ('m', r'\ \text{m}^{3}\cdot\text{kg}^{-1}'),
        '。'
    ])

    rb.heading('3.3 各样品磁化率计算', 2)
    rb.para([
        '由公式 ', ('m', r'\chi_{\text{样}} = \chi_{\text{标}} \cdot \frac{m_{\text{标}}}{m_{\text{样}}} \cdot \frac{\Delta m_{\text{样}} - \Delta m_{\text{空}}}{\Delta m_{\text{标}} - \Delta m_{\text{空}}}'),
        ' 计算各样品的比磁化率，再由 ', ('m', r'\chi_{m} = \chi \cdot M'),
        ' 计算摩尔磁化率。'
    ])

    # 表 2：计算结果
    # 表头里的 χ_m / μ_B 必须写成真下标（'χ_m' 会原样印出下划线）。
    # 表头按 '/' 分正斜体的：'/' 前是量符号（斜体），'/' 后是单位（正体），
    # 所以 'μ / μ_{B}' 的 μ_B 落在单位侧、B 自动正体，正合 §3.2。
    #
    # 用真上标（'10^{−6}'）后表头比原来的 Unicode 上标宽，第 2/3 列会折行，
    # 所以给显式列宽（正文宽约 18 cm，五列合计 16.6 cm）。
    headers2 = ['样品', 'χ / (10^{−6} m^{3}·kg^{−1})',
                'χ_{m} / (10^{−6} m^{3}·mol^{−1})', 'μ / μ_{B}', 'n']
    widths2 = [2.4, 4.0, 4.4, 3.2, 2.6]
    rows2 = []
    for name, s in samples.items():
        if s['chi_m'] is None:
            # 未知样没有摩尔质量 → χ_m / μ / n 都算不出来，明确印 '—'
            rows2.append([name, _num(s['chi_mass'] * 1e6, 3), '—', '—', '—'])
            continue
        rows2.append([
            name,
            _num(s['chi_mass'] * 1e6, 3),
            _num(s['chi_m'] * 1e6, 3),
            _num(s['mu'], 3),
            _num(s['n'], 2),
        ])

    rb.caption('表2  各样品磁化率计算结果')
    rb.table(headers2, rows2, widths_cm=widths2)
    log('表2 已生成')

    # 生成图表
    chart_data = analysis['chart']
    if chart_data:
        plot_paths = plotting.generate_all_plots(chart_data, plots_dir)

        # 图 2：摩尔磁化率对比
        rb.heading('3.4 结果图示', 2)
        rb.figure(plot_paths['chi_m'], caption='图2  各样品摩尔磁化率对比', width_cm=13)
        rb.figure(plot_paths['mu'], caption='图3  各样品分子磁矩对比', width_cm=13)
        rb.figure(plot_paths['n'], caption='图4  各样品未成对电子数', width_cm=13)
        log('图表已生成')

    # ---- 4 结果与讨论
    rb.heading('4 结果与讨论', 1)
    rb.heading('4.1 实验结果', 2)

    # 汇总各样品结果
    for name, s in samples.items():
        if s['chi_m'] is None:
            continue
        if s['mu'] is None:
            # 反磁性：没有永久磁矩，不能印「0 μ_B」
            rb.para([
                ('t', name, {}),
                ' 的摩尔磁化率为 ',
                ('t', 'χ_{m}', ITALIC), ' = ', sci(s['chi_m']), ' m^{3}·mol^{-1}',
                '，为反磁性物质，无永久磁矩，未成对电子数为 0。',
            ])
            continue
        rb.para([
            ('t', name, {}),
            ' 的摩尔磁化率为 ',
            ('t', 'χ_{m}', ITALIC), ' = ', sci(s['chi_m']), ' m^{3}·mol^{-1}',
            '，分子磁矩为 ', '%.3f' % s['mu'], *MU_B_SEGS,
            '，未成对电子数约为 ',
            ('t', '%.1f' % s['n'], {}),
            '。'
        ])

    rb.heading('4.2 实验讨论', 2)
    rb.para([
        '（1）本实验采用莫尔盐作为标准样品标定仪器常数。莫尔盐的磁化率已知且稳定，'
        '是常用的磁化率标准物质^{[1]}。'
    ])
    rb.para([
        '（2）样品的装填高度和密实度对测量结果有重要影响。装填不均匀会导致磁场中'
        '样品受力不均匀，引入系统误差。'
    ])
    rb.para([
        '（3）实验过程中应注意保持样品管与磁极的相对位置不变，避免机械振动对称量的影响。'
    ])
    rb.para([
        '（4）对于顺磁性物质，测得的磁化率包含了顺磁和反磁两部分贡献。'
        '在常温下，顺磁贡献远大于反磁贡献，因此可以近似认为测得的是顺磁磁化率^{[3]}。'
        '亚铁氰化钾的 ', ('t', 'χ_{m}', ITALIC), ' 为负，说明反磁贡献占主导，'
        '与其 [Fe(CN)₆]⁴⁻ 低自旋 d⁶ 组态（无未成对电子）一致^{[2]}。'
    ])

    rb.heading('4.3 实验结论', 2)
    rb.para([
        '本实验成功测定了莫尔盐、硫酸铜、亚铁氰化钾等物质的磁化率，'
        '并计算了各样品的摩尔磁化率、分子磁矩和未成对电子数。'
        '实验结果与理论预期基本吻合，验证了古埃磁天平法的可靠性。'
    ])

    # ---- 参考文献
    rb.heading('参考文献', 1)
    rb.para(['[1] 杨文治. 物理化学实验技术[M]. 北京: 北京大学出版社, 1992: 159-183.'])
    rb.para(['[2] 徐光宪, 王祥云. 物质结构(第2版)[M]. 北京: 高等教育出版社, 1987: 457.'])
    rb.para(['[3] 游效曾. 结构分析导论[M]. 北京: 科学出版社, 1980: 328-355.'])

    # ---- 保存
    rb.save(out_path)
    log('报告已保存：%s' % out_path)
    return out_path
