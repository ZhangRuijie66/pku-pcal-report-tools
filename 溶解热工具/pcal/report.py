# -*- coding: utf-8 -*-
"""生成《溶解热的测定》实验报告 .docx。

结构参照同课程此前的溶解热报告（精简版）：

    封面
    摘要 / 关键词
    1 引言                     该实验的目的、原理及方法见图1（手写预习笔记扫描）
    2 实验部分[1]              2.1 仪器和试剂   2.2 实验内容
    3 数据与结果
      3.1 浓度的计算                                        表1
      3.2 积分溶解热的计算
        3.2.1 单次实验溶解过程 ΔQ 及积分溶解热 Qs           图2  表2
        3.2.2 第3次实验溶解过程 ΔQ 的手动计算              图3 图4
      3.3 微分冲淡热、微分溶解热和积分冲淡热的计算
        3.3.1 Qs-n0 经验方程的拟合                          图5
        3.3.2 热力学量的计算                                表3
    4 讨论与结论
      4.1 经验公式的合理性
      4.2 体系与环境热交换的校正
      4.3 思考题
      4.4 结果的误差分析
      4.5 小结
    参考文献

公式一律用 Word 原生公式（OMML）；只示出变量值的写法用普通文本（变量斜体、单位正体）。
"""
from __future__ import annotations

import decimal
import os

import numpy as np
from docx.enum.text import WD_ALIGN_PARAGRAPH

from . import dissolution as ds
from . import plotting
from .analysis import SUBSTANCES
from .docxkit import ReportBuilder

ITALIC = {'italic': True}

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
INTRO_PNG = os.path.join(ASSETS, '引言图.jpg')          # 手写预习笔记：目的 / 原理 / 方法
APPARATUS_PNG = os.path.join(ASSETS, '装置图.png')       # 讲义图2（备用，精简版未用）

REPORT_TITLE = '溶解热的测定'
MARK_N0 = (200, 150, 100, 80, 50)
EXAMPLE_ROUND = 3          # 用手动复算演示的那一轮（与参考报告一致，取第 3 组）
# 引言页预留的空白行数（单倍行距下 1 行 ≈ 0.51 cm）：
# 约 13 cm 高，够贴一张预习报告扫描件；贴完若还想要更多空间，把这个数调大。
INTRO_BLANK_LINES = 26


# ---------------------------------------------------------------- 数值格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


SIG_DIGITS = 2


def _sig(x, n=SIG_DIGITS):
    x = float(x)
    if x == 0 or not np.isfinite(x):
        return 0.0
    d = decimal.Decimal(repr(x))
    q = decimal.Decimal(1).scaleb(d.adjusted() - n + 1)
    return float(d.quantize(q, rounding=decimal.ROUND_HALF_EVEN))


def _place(unc, n=SIG_DIGITS):
    return decimal.Decimal(repr(float(unc))).adjusted() - n + 1


def _fix(x, exp):
    q = decimal.Decimal(1).scaleb(exp)
    return float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN))


def _fmt(x, exp):
    return '%.*f' % (max(0, -exp), x)


def val(x, unc, n=SIG_DIGITS):
    if unc in (None, 0):
        return k(x, 1)
    return _fmt(_fix(x, _place(unc, n)), _place(unc, n))


def unc(x, n=SIG_DIGITS):
    if x in (None, 0):
        return '—'
    e = _place(x, n)
    return _fmt(_fix(x, e), e)


def pm(x, u, n=SIG_DIGITS, unit=''):
    e = _place(u, n) if u not in (None, 0) else _place(abs(x) * 1e-3 or 1, n)
    return '%s ± %s%s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e), unit)


def pct(x, n=SIG_DIGITS):
    return _fmt(_sig(x, n), _place(x, n))


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    rounds = analysis.rounds
    fit = analysis.fit
    diff = analysis.diff
    sub = SUBSTANCES.get(cfg.get('solute') or 'kno3', SUBSTANCES['custom'])
    sub_label = sub.get('tex_label') or sub.get('label') or '待测溶质'
    lit = cfg.get('literature_Qs0')
    base = rounds[0]
    ex = rounds[min(EXAMPLE_ROUND, len(rounds)) - 1]

    T_room = base['temperature']
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    group_txt = ('%s 组 %s 号' % (group, group_no)) if (group and group_no) else (group or group_no)
    cover = {
        '题目': REPORT_TITLE,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '组号': group_no,
        '实验日期': cfg.get('date'),
        '室温': '%.1f ℃' % (T_room - 273.15),
        '大气压强': ('%s kPa' % cfg.get('pressure_kPa')) if cfg.get('pressure_kPa') else None,
    }
    # 封面缺字段时模板里那一格会是空的，很容易到最后才发现——直接报到进度里
    missing = [k for k, v in cover.items() if k != '组号' and not str(v or '').strip()]
    if missing:
        log('⚠ 封面缺字段：%s（请在界面左侧「报告封面 / 实验条件」里填上）'
            % '、'.join(missing))
    rb.set_cover(cover)
    rb.set_header_title(REPORT_TITLE)

    os.makedirs(plots_dir, exist_ok=True)

    # ---- 出图
    log('绘制插图…')
    import matplotlib.pyplot as plt

    def save(fig, name):
        p = os.path.join(plots_dir, name)
        fig.savefig(p, dpi=plotting.DPI)
        plt.close(fig)
        del fig
        return p

    params_png = save(plotting.make_params_figure(
        ex, software_Q_kJ=ex.get('software_Q_kJ')), 'params_round%d.png' % ex['index'])
    reyn_png = save(plotting.make_figure(ex['data'], ex['reynolds_diss'],
                                         ex['reynolds_heat'],
                                         ex['fit1'], ex['fit2'], ex['fit3']),
                    'reynolds_round%d.png' % ex['index'])
    fit_png = save(plotting.make_fit_figure(fit, diff, MARK_N0), 'fit_Qs_n0.png')

    # 课程软件自己导出的雷诺校正图（数据文件旁边同名 .png）
    sw_png = None
    p = base and ex['data'].path
    if p:
        cand = os.path.splitext(p)[0] + '.png'
        if os.path.exists(cand):
            sw_png = cand

    Qs0, a, sQs0, sa = fit['Qs0'], fit['a'], fit['sigma_Qs0'], fit['sigma_a']
    n1 = fit['n1']
    i200, i50 = list(MARK_N0).index(200), list(MARK_N0).index(50)

    # ================================================================ 摘要
    log('撰写摘要…')
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验采用电热补偿法测定%s的溶解热。分批次加入溶质并记录温差曲线，'
        '通过雷诺校正和比例换算求得各次热效应，累加即得不同总浓度 ' % sub_label,
        ('t', 'n_{0}', ITALIC), ' 下的积分溶解热 ',
        ('t', 'Q_{s}', ITALIC),
        '。通过经验公式拟合 ',
        ('t', 'Q_{s}', ITALIC), '-', ('t', 'n_{0}', ITALIC),
        ' 数据，外推获得无限稀释积分溶解热 ',
        ('t', 'Q_{s}^{0}', ITALIC),
        ('t', ' = (%s) kJ·mol⁻¹' % pm(Qs0, sQs0)),
        '（拟合相关系数 ',
        ('t', 'R^{2}', ITALIC), ('t', ' = %s' % k(fit['r_square'], 5)),
        '）。进一步由拟合曲线在各点的切线斜率和截距，计算了相应浓度下的微分冲淡热 ',
        ('t', 'q_{d}', ITALIC), ' 与微分溶解热 ', ('t', 'q_{s}', ITALIC),
        '，以及不同浓度间的积分冲淡热 ',
        ('t', 'Q_{d}', ITALIC), '。',
    ]
    if lit:
        abs_segs.append(
            '与手册^{[2]}值 %s kJ·mol⁻¹ 相比，本次结果的相对误差为 %s%%；'
            '分析表明加热过程远长于溶解过程，使体系与环境热交换的补偿不对称，'
            '是结果偏大的主要原因。'
            % (k(float(lit), 2), pct(abs(Qs0 - float(lit)) / abs(float(lit)) * 100)))
    rb.para(abs_segs)

    keywords = '溶解热；电热补偿法；雷诺校正；微分冲淡热；微分溶解热'
    rb.para([{'text': '关键词 ', 'bold': True}, keywords])
    rb.blank()

    # ================================================================ 1 引言
    # 引言整页留空，只预留预习报告图片的位置：把扫描/照片粘进这一页即可。
    # 想改预留高度的，调 INTRO_BLANK_LINES（单倍行距下 1 行 ≈ 0.51 cm）。
    rb.heading('1 引言', page_break_before=True)
    for _ in range(INTRO_BLANK_LINES):
        rb.blank()
    rb.caption('图1  实验目的、原理及方法')

    # ================================================================ 2 实验部分
    rb.heading('2 实验部分^{[1]}', page_break_before=True)
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para('广口保温瓶，磁子，电磁搅拌器，数字温差仪，加热电阻丝，直流稳压电源，'
            '漏斗，秒表，500 mL 容量瓶，公用万用表，分析天平。')
    rb.heading('2.1.2 试剂', 3)
    # 试剂名用「中文名 + LaTeX 化学式」写，让下标成为真下标（KNO₃）
    cn = (sub.get('label') or '').split()
    rb.para('%s %s（AR）。' % (cn[0] if cn else '待测溶质',
                              sub.get('tex_label') or ''))

    rb.heading('2.2 实验内容', 2)
    rb.para('用 500 mL 容量瓶定容 500 mL 蒸馏水，注入容量为 750 mL 的保温瓶中，'
            '加入磁子。连接好线路，打开设备，把直流电源加热器的功率调到 10 W 左右'
            '（本次实验电流约 %s A）。用万用表测量一次电阻值。'
            % k(base['current'], 2))
    rb.para('用称量纸准确称取干燥、磨细的 %s 约 12 g。打开电磁搅拌器，'
            '点击“开始记录”。将温差置零，记录体系温差变化，直到温差读数基本恒定'
            '（否则重新置零）。待温差读数达到平台期后，打开加料口塞子，'
            '通过小漏斗加入样品。待温度降至最低值并达到平台期后，'
            '点击“开始加热”，并打开电阻丝加热开关，记录加热的电流。当温差接近 0 时，'
            '点击“停止加热”并断开加热。待热平衡、温差读数再次达到平台期后，'
            '点击“停止记录”，保存文件。加热时间、溶解和加热过程的温差会一并保存在'
            '文件中，此即一轮完整的测量。' % sub_label)
    rb.para('用同样的方法测量另外 5 个样品，分别约 12、12、5、6 和 8 g。'
            '测完最后一组样品后，用万用表再测一次电阻值，保证前后电阻偏差不大。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写数据与结果…')
    _sec_concentration(rb, analysis, fit, n1, base, T_room)
    _sec_integral(rb, analysis, fit, ex, params_png)
    _sec_manual(rb, ex, reyn_png, sw_png)
    _sec_thermo(rb, analysis, fit, diff, fit_png)

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    _sec_model(rb, analysis, fit, base)
    _sec_heat_exchange(rb, analysis, ex)
    _sec_questions(rb, analysis, ex, fit)
    _sec_error(rb, analysis, fit, cfg, lit, sub_label)
    _sec_summary(rb, analysis, fit, diff, cfg, lit, sub_label)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组, 物理化学实验(2026年秋季试用),'
            '北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] Haynes W M. CRC Handbook of Chemistry and Physics[M]. '
            'CRC Press, 2016: 5-75~5-76.', indent_chars=0)
    rb.para('[3] 赵泽华, 等. 量热实验数据采集处理软件的自主开发与应用[J]. 大学化学, '
            '2025, 40(11): 402.（数据处理算法来源，GPL-3.0 开源）', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ================================================================ 3.1 浓度的计算
def _sec_concentration(rb, analysis, fit, n1, base, T_room):
    rounds = analysis.rounds
    rb.heading('3.1 浓度的计算', 2)
    rb.para([
        '首先对本实验一些基本数据的采用进行声明。实验中读取室温为 ',
        ('t', 'T', ITALIC), ' = %.1f ℃ = %.2f K。后文会分析，温度的波动不是实验结果的'
        '主要影响因素，故将 ' % (T_room - 273.15, T_room),
        ('t', 'T', ITALIC), ' 视为常数。',
    ])
    # 分子量是"从手册查到的常数"，只示出数值 —— 按规范用普通文本，不用公式对象
    rb.para([
        '此外，水和硝酸钾的分子量均采用手册^{[2]}值，也视为常数：',
        ('t', 'M', ITALIC), ('t', '(H_{2}O)', {}),
        ('t', ' = %.3f g·mol⁻¹，' % ds.M_H2O),
        ('t', 'M', ITALIC), ('t', '(KNO_{3})', {}),
        ('t', ' = %.3f g·mol⁻¹。' % base['Mr']),
    ])
    rb.para([
        '后续数据处理要求本实验浓度以 ', ('t', 'n_{0}', ITALIC),
        ' 表示，其计算公式为：',
    ])
    rb.equation(r'n_{0}=\frac{n_{1}}{n_{2}}')
    rb.para([
        '其中 ', ('t', 'n_{1}', ITALIC), ' 和 ', ('t', 'n_{2}', ITALIC),
        ' 分别为溶剂和溶质物质的量。由于溶剂水体积为 500.00 mL 不变，故 ',
        ('t', 'n_{1}', ITALIC), ' 也为常数。查表^{[2]}知 %.1f ℃ 下水的密度为 ' % (T_room - 273.15),
        ('t', 'ρ', ITALIC), ('t', '(H_{2}O)', {}),
        ('t', ' = %.7f g·mL⁻¹，故：' % base['water_density']),
    ])
    rb.equation(r'n_{1}=\frac{500.00\times%.7f}{%.3f}=%.3f\ mol'
                % (base['water_density'], ds.M_H2O, n1))
    rb.para([
        '每组实验加入的硝酸钾质量原始数据 ',
        ('t', 'Δ m', ITALIC),
        ' 列于表1。将之前组的所有质量相加即为每组实验所用硝酸钾总质量 ',
        ('t', 'm', ITALIC), '，由 ', ('t', 'm', ITALIC),
        ' 即可得出溶质物质的量 ', ('t', 'n_{2}', ITALIC),
        '，再用前述公式即可算出 ', ('t', 'n_{0}', ITALIC),
        '。', ('t', 'm', ITALIC), '、', ('t', 'n_{2}', ITALIC), ' 和 ',
        ('t', 'n_{0}', ITALIC), ' 一并列入表1。计算细节以第3组数据为例：',
    ])
    e = rounds[2]
    rb.equation(r'm=\sum_{i\leq3}\Delta m=%s=%s\ g'
                % ('+'.join('%.4f' % r['solute_mass'] for r in rounds[:3]),
                   k(e['cum_m2'], 4)))
    rb.equation(r'n_{2}=\frac{m}{M(KNO_{3})}=\frac{%s}{%.3f}=%.6f\ mol'
                % (k(e['cum_m2'], 4), e['Mr'], e['sum_n2']))
    rb.equation(r'n_{0}=\frac{n_{1}}{n_{2}}=\frac{%s}{%.6f}=%.3f'
                % (k(n1, 3), e['sum_n2'], e['n0']))
    rb.caption('表1  浓度的数据处理结果')
    rb.table(['编号', 'Δ m/g', 'm/g', 'n_{2}/mol', 'n_{0}'],
             [[str(r['index']), '%.4f' % r['solute_mass'], '%.4f' % r['cum_m2'],
               '%.6f' % r['sum_n2'], '%.3f' % r['n0']] for r in rounds],
             font_size=10.5, widths_cm=[1.80, 2.60, 2.60, 3.00, 2.60])
    rb.para(['注：', ('t', 'Δ m', ITALIC), ' 为当次加入的溶质质量，',
             ('t', 'm', ITALIC), ' 为累积质量，',
             ('t', 'n_{2}', ITALIC), ' = ', ('t', 'm/M', ITALIC),
             ('t', '(KNO_{3})', {}), '。'],
            indent_chars=0)
    rb.blank()


# ================================================================ 3.2 积分溶解热
def _sec_integral(rb, analysis, fit, ex, params_png):
    rounds = analysis.rounds
    rb.heading('3.2 积分溶解热的计算', 2)
    rb.heading([('t', '3.2.1 单次实验溶解过程 '), ('t', 'Δ Q', ITALIC),
                ('t', ' 及积分溶解热 '), ('t', 'Q_{s}', ITALIC)], 3)
    rb.para([
        '本次实验的 ', ('t', 'Δ Q', ITALIC),
        ' 用软件进行计算，其计算细节在 3.2.2 节列出手动复算，两者一致。'
        '此处仅对一些参数进行说明。',
    ])
    rb.para([
        '在全部 %d 组实验中，电流值保持在 ' % len(rounds),
        ('t', 'I', ITALIC), ('t', ' = %s A' % k(ex['current'], 2)),
        ' 左右；实验前后测得的加热丝电阻平均为 ',
        ('t', 'R', ITALIC), ('t', ' = %s Ω 与 %s Ω' % (k(ex['R1'], 2), k(ex['R2'], 2))),
        '（相差约 %s Ω，取平均 %s Ω 参与计算）。'
        % (k(abs(ex['R2'] - ex['R1']), 2), k(ex['R_heat'], 3)),
    ])
    rb.para('其次，对于拟合数据点的选取，每段平台均选取线性最强、范围尽可能大的'
            '数据点进行拟合。以第%d组实验为例，各参数的选取如图2所示。' % ex['index'])
    rb.figure(params_png, caption='图2  第%d组实验各参数的选取' % ex['index'], width_cm=14.5)
    rb.para([
        '由图2可读出，软件计算的第%d组实验的吸热为 ' % ex['index'],
        ('t', 'Δ Q', ITALIC), ('t', ' = %.4f kJ。' % (ex['Q'] / 1000)),
    ])
    rb.para([
        '其余实验的 ', ('t', 'Δ Q', ITALIC),
        ' 列于表2。将之前组的所有 ', ('t', 'Δ Q', ITALIC),
        ' 相加即为每组实验的总溶解热 ', ('t', 'Q', ITALIC), '，由 ',
        ('t', 'Q', ITALIC), ' 即可得出积分溶解热 ',
        ('t', 'Q_{s}', ITALIC), '。', ('t', 'Q', ITALIC), ' 和 ',
        ('t', 'Q_{s}', ITALIC), ' 一并列入表2，计算细节以第3组数据为例：',
    ])
    rb.equation(r'Q=\sum_{i\leq3}\Delta Q=%s=%s\ kJ'
                % ('+'.join('%.4f' % (r['Q'] / 1000) for r in rounds[:3]),
                   k(ex['cum_Q'], 4)))
    rb.equation(r'Q_{s}=\frac{Q}{n_{2}}=\frac{%s}{%.6f}=%.4f\ kJ\cdot mol^{-1}'
                % (k(ex['cum_Q'], 4), ex['sum_n2'], ex['Qs']))
    rb.caption('表2  积分溶解热的数据处理结果')
    rb.table(['编号', 'Δ Q/kJ', 'Q/kJ', 'Q_{s}/(kJ·mol⁻¹)'],
             [[str(r['index']), '%.4f' % (r['Q'] / 1000), '%.4f' % r['cum_Q'],
               '%.4f' % r['Qs']] for r in rounds],
             font_size=10.5, widths_cm=[1.80, 2.80, 2.80, 4.20])
    rb.blank()


# ================================================================ 3.2.2 手动复算
def _sec_manual(rb, ex, reyn_png, sw_png):
    rb.heading([('t', '3.2.2 第%d次实验溶解过程 ' % ex['index']),
                ('t', 'Δ Q', ITALIC), ('t', ' 的手动计算')], 3)
    rb.para([
        '为了验证软件计算结果的合理性，同时为了说明 ',
        ('t', 'Δ Q', ITALIC),
        ' 的计算细节，此处以第%d组数据为例，手动计算该实验的 ' % ex['index'],
        ('t', 'Δ Q', ITALIC),
        '。第%d组实验的加热时间 ' % ex['index'],
        ('t', 't', ITALIC),
        ('t', ' = %s − %s = %s s，故加热过程中：'
         % (k(ex['t2'], 3), k(ex['t1'], 3), k(ex['t_heat'], 3))),
    ])
    rb.equation(r"\Delta Q'=I^{2}Rt=%s^{2}\times%s\times%s=%s\ kJ"
                % (k(ex['current'], 2), k(ex['R_heat'], 3), k(ex['t_heat'], 3),
                   k(ex['Q_elec'] / 1000, 4)))
    rb.para([
        '接下来计算溶解过程和加热过程的温差。为了校正体系和环境热交换的影响，'
        '采取雷诺校正进行计算：对于某个过程（溶解或加热），分别对过程前和过程后的'
        '平台区进行线性拟合，将拟合直线外延。作一垂线，若该垂线与曲线图和两条拟合'
        '直线相交的区域面积相等，则该垂线与两条拟合直线的两个交点即为该过程前后'
        '的温差。',
    ])
    rb.para([
        '作出第%d组实验的温差-时间曲线，分别对溶解前（记为 ' % ex['index'],
        ('t', 'A', ITALIC), '）、溶解后加热前（记为 ', ('t', 'B', ITALIC),
        '）和加热后（记为 ', ('t', 'C', ITALIC),
        '）的三段平台区进行拟合，如图3、图4所示。分别找出溶解过程和加热过程的'
        '垂线，使相应的两个区域面积相等。',
    ])
    if sw_png:
        rb.figure(sw_png, caption='图3  第%d组实验的雷诺校正（课程软件）' % ex['index'],
                  width_cm=13.5)
    rb.figure(reyn_png, caption='图4  第%d组实验的雷诺校正（本报告程序复算）' % ex['index'],
              width_cm=13.5)
    rb.para('数据处理的结果如下，首先是三条拟合直线方程：')
    f1, f2, f3 = ex['fit1'], ex['fit2'], ex['fit3']
    for tag, f in (('A', f1), ('B', f2), ('C', f3)):
        rb.equation(r'%s:\ \Delta T=(%s)\times10^{-4}t+(%s)\qquad R^{2}=%s'
                    % (tag, pm(f['k'] * 1e4, f['stddev_k'] * 1e4),
                       pm(f['b'], f['stddev_b']), k(f['r_square'], 3)))
    rb.para([
        '需要说明的是，平台 ', ('t', 'B', ITALIC),
        ' 夹在溶解降温与通电升温之间，时间窗口最短，而且溶解的余热弛豫与通电升温'
        '在时间上部分重叠，因此它的 ',
        ('t', 'R^{2}', ITALIC),
        ' 明显低于两端平台。由于式(12)用的是两个温差之比，而两次校正共用同一条 ',
        ('t', 'B', ITALIC),
        ' 直线，', ('t', 'B', ITALIC),
        ' 的偏差在很大程度上相互抵消，故它对结果的影响远小于 ',
        ('t', 'R^{2}', ITALIC), ' 看上去的程度（见 4.3.1 的不确定度估算）。',
    ])
    rb.para([
        '其次，溶解过程和加热过程雷诺校正垂线的横坐标分别为 ',
        ('t', 't', ITALIC), ('t', ' = %.3f s、' % ex['reynolds_diss']['x0']),
        ('t', "t'", ITALIC), ('t', ' = %.3f s。' % ex['reynolds_heat']['x0']),
    ])
    rb.para([
        '溶解过程的温差计算方法即将 ', ('t', 't', ITALIC), ' 分别代入 ',
        ('t', 'A', ITALIC), ' 和 ', ('t', 'B', ITALIC), ' 方程算出对应的 ',
        ('t', 'Δ T', ITALIC), '，再将两者相减得温差 ',
        ('t', 'Δ Δ T', ITALIC), '。加热过程同理，计算如下：',
    ])
    rb.equation(r'\Delta\Delta T=A(t)-B(t)=%s\ K' % k(ex['dT_diss'], 4))
    rb.equation(r"\Delta\Delta T'=C(t')-B(t')=%s\ K" % k(ex['dT_heat'], 4))
    rb.para('综上，溶解过程的吸热为：')
    rb.equation(r"\Delta Q=\Delta Q'\times\frac{\Delta\Delta T}{\Delta\Delta T'}"
                r"=%s\times\frac{%s}{%s}=%.4f\ kJ"
                % (k(ex['Q_elec'] / 1000, 4), k(ex['dT_diss'], 4),
                   k(ex['dT_heat'], 4), ex['Q'] / 1000))
    if ex.get('software_Q_kJ'):
        rb.para('计算结果表明，手动计算结果 %.4f kJ 与软件计算结果 %.4f kJ 一致，'
                '说明软件计算值是可靠的。' % (ex['Q'] / 1000, ex['software_Q_kJ']))
    rb.blank()


# ================================================================ 3.3 微分热
def _sec_thermo(rb, analysis, fit, diff, fit_png):
    Qs0, a = fit['Qs0'], fit['a']
    rb.heading('3.3 微分冲淡热、微分溶解热和积分冲淡热的计算', 2)
    rb.heading([('t', '3.3.1 '), ('t', 'Q_{s}', ITALIC), ('t', '-'),
                ('t', 'n_{0}', ITALIC), ('t', ' 经验方程的拟合')], 3)
    rb.para([
        '观察 ', ('t', 'Q_{s}', ITALIC), '-', ('t', 'n_{0}', ITALIC),
        ' 经验方程，可发现其与 Langmuir 吸附等温式的形式一样。结合表1和表2，将 ',
        ('t', 'Q_{s}', ITALIC), ' 和 ', ('t', 'n_{0}', ITALIC),
        ' 进行 Langmuir 非线性曲线拟合，拟合结果如图5所示。',
    ])
    rb.figure(fit_png, caption='图5  Q_{s}-n_{0} 经验方程拟合结果', width_cm=12.5)
    rb.para('曲线的拟合结果如下：')
    rb.equation(r'Q_{s}=(%s)\times\frac{(%s)\times n_{0}}{1+(%s)\times n_{0}}'
                % (pm(Qs0, fit['sigma_Qs0'], unit=''), pm(a, fit['sigma_a']),
                   pm(a, fit['sigma_a'])))
    rb.para([
        '可见拟合相关性较好，相关系数 ',
        ('t', 'R^{2}', ITALIC), ('t', ' = %s。对应于各参数，即 ' % k(fit['r_square'], 5)),
        ('t', 'Q_{s}^{0}', ITALIC),
        ('t', ' = (%s) kJ·mol⁻¹，' % pm(Qs0, fit['sigma_Qs0'])),
        ('t', 'a', ITALIC), ('t', ' = %s。' % pm(a, fit['sigma_a'])),
    ])
    rb.para([
        '值得说明的是，对该经验公式的拟合也可以先取倒数，再作线性拟合。'
        '两种方法得出的参数值及 ',
        ('t', 'R^{2}', ITALIC),
        ' 基本一致。为简化步骤，此处采取非线性曲线拟合的方法。',
    ])

    rb.heading('3.3.2 热力学量的计算', 3)
    rb.para([
        '根据实验原理可知，如果对 ', ('t', 'Q_{s}', ITALIC), '-',
        ('t', 'n_{0}', ITALIC),
        ' 曲线上某一点作切线，微分冲淡热 ', ('t', 'q_{d}', ITALIC),
        ' 即为该切线的斜率，微分溶解热 ', ('t', 'q_{s}', ITALIC),
        ' 即为该切线的截距。此外，两个点之间的积分冲淡热 ',
        ('t', 'Q_{d}', ITALIC), ' 即为这两点 ', ('t', 'Q_{s}', ITALIC), ' 之差。',
    ])
    rb.para('对于前文中的曲线方程：')
    rb.equation(r'Q_{s}=%.3f\times\frac{%.4f\times n_{0}}{1+%.4f\times n_{0}}'
                % (Qs0, a, a))
    rb.para([('t', '曲线上任意一点 ', {}), ('t', "n_{0}'", ITALIC),
             ('t', ' 对应的切线方程为：', {})])
    rb.equation(r"Q_{s}-Q_{s}'=\frac{dQ_{s}}{dn_{0}}(n_{0}-n_{0}')")
    rb.para('经过简单的数学计算，得到切线方程的斜率与截距分别为：')
    rb.equation(r"q_{d}=\frac{Q_{s}^{0}a}{(1+a n_{0}')^{2}}"
                r"\qquad q_{s}=\frac{Q_{s}^{0}a^{2}n_{0}'^{2}}{(1+a n_{0}')^{2}}")
    rb.para([
        ('t', 'q_{d}', ITALIC), ' 的单位是 J·mol⁻¹，', ('t', 'q_{s}', ITALIC),
        ' 的单位是 kJ·mol⁻¹。积分冲淡热为两个浓度下积分溶解热之差：',
    ])
    rb.equation(r"Q_{d}=(Q_{s})_{2}-(Q_{s})_{1}")
    rb.para([
        '计算结果列于表3，其中 ', ('t', 'Q_{d}', ITALIC),
        ' 表示该组与上一组之间的积分冲淡热。',
    ])
    rb.caption('表3  各热力学量的计算结果')
    rows = []
    for i, n in enumerate(diff['n0']):
        rows.append([k(n, 0), k(diff['Qs_n0'][i], 3), k(diff['Qs_n2'][i], 2),
                     '—' if i == 0 else k(diff['Qd'][i - 1] / 1000, 4)])
    rb.table(['n_{0}', 'q_{d}/(J·mol⁻¹)', 'q_{s}/(kJ·mol⁻¹)', 'Q_{d}/(kJ·mol⁻¹)'],
             rows, font_size=10.5, widths_cm=[2.00, 3.80, 3.80, 3.80])
    rb.blank()


# ================================================================ 4.1 经验公式
def _sec_model(rb, analysis, fit, base):
    rounds = analysis.rounds
    rb.heading('4.1 经验公式的合理性', 3)
    rb.para('本实验微分冲淡热等热力学量是通过对经验公式的拟合计算的。还有另一种'
            '方法：仅通过原始数据作出样条曲线，用样条插值的方法计算切线方程。'
            '第一种方法强烈依赖于经验公式的可靠性，而后一种方法完全忠实于原始数据，'
            '但容易受到噪声影响。笔者认为该实验应该选取经验公式的方法，'
            '简要理由如下。')
    rb.para([
        '首先从数据上，用该经验公式拟合的相关性非常好（',
        ('t', 'R^{2}', ITALIC), ('t', ' = %s' % k(fit['r_square'], 5)),
        '），这极大程度上证明了该模型的可靠性。',
    ])
    rb.para([
        '其次，该模型的物理图像非常符合理论认识。可以这样理解：每个溶质单元提供'
        '有限数量的、等价的、独立的结合位点，可以与溶剂分子发生特定的、吸热的'
        '相互作用（比如水合、氢键等）。当 ',
        ('t', 'n_{0}', ITALIC), ' → 0 时，因为溶剂分子太少，绝大部分溶质的结合位点'
        '都空着，远未形成完整的溶剂化壳层，此时测量到的整体热效应非常微弱，故 ',
        ('t', 'Q_{s}', ITALIC), ' → 0。当 ', ('t', 'n_{0}', ITALIC),
        ' → ∞ 时，所有可能的特异性的溶质-溶剂结合位点都已被溶剂分子完全占据，此时 ',
        ('t', 'Q_{s}', ITALIC), ' → ', ('t', 'Q_{s}^{0}', ITALIC),
        '（无限稀释积分溶解热）。',
    ])
    first3 = rounds[:3]
    dec = [r['Q'] / 1000 for r in first3]
    rb.para([
        '该物理图像同样能解释实验中观察到的一个现象：在前3次实验中，均加入 12 g '
        '左右的硝酸钾（依次为 %.4f、%.4f、%.4f g），但溶解热却呈下降趋势'
        '（依次为 %.4f、%.4f、%.4f kJ）。这是因为相比于纯溶剂，在第二次溶解时，'
        '新溶质分子进入的已是一个预溶剂化的环境，它们能获得的完整溶剂化机会减少，'
        '只能部分占据剩余的弱作用位点或与已溶剂化溶质竞争，吸收的热量减少。'
        '这本质上也是微分冲淡热随溶液浓度升高而单调递减的直接结果。'
        % (first3[0]['solute_mass'], first3[1]['solute_mass'], first3[2]['solute_mass'],
           dec[0], dec[1], dec[2]),
    ])


# ================================================================ 4.2 热交换校正
def _sec_heat_exchange(rb, analysis, ex):
    rb.heading('4.2 体系与环境热交换的校正', 3)
    rb.para('本实验对于体系和环境的热交换采取的校正方法是雷诺校正，其基本思想如下：')
    rb.para([
        '假设热交换在整个实验期间持续、稳定地进行（表现为温度基线线性漂移），'
        '并假设热效应（如溶解、通电加热）是在某一瞬间 ',
        ('t', 't_{m}', ITALIC),
        ' 突然完成的，这样实测温度曲线就可以看作是一条稳定的漂移基线，'
        '加上在 ', ('t', 't_{m}', ITALIC), ' 时刻的一个温度阶跃。',
    ])
    rb.para([
        '如果热效应真是瞬间完成的，则在 ', ('t', 't_{m}', ITALIC),
        ' 之前，系统的热效应有一部分储存在温度偏差中（表现为面积 ',
        ('t', 'A', ITALIC), '）。在 ', ('t', 't_{m}', ITALIC),
        ' 之后，这部分储存的热量会通过热交换逐渐释放或吸收，使温度回到新基线'
        '（表现为面积 ', ('t', 'B', ITALIC), '）。令 ',
        ('t', 'A', ITALIC), ' = ', ('t', 'B', ITALIC),
        '，意味着在 ', ('t', 't_{m}', ITALIC),
        ' 时刻，由热效应引起的温度偏差的累积刚好达到最大值，并且这个最大值在'
        '数值上等于后续松弛过程的总和。此时 ', ('t', 't_{m}', ITALIC),
        ' 就是等效的瞬时完成时刻。',
    ])
    rb.para([
        '本实验一轮数据需要作两次校正：溶解降温段由平台 ',
        ('t', 'A', ITALIC), ' 与平台 ', ('t', 'B', ITALIC),
        ' 的拟合直线外延相交得到，通电升温段由平台 ',
        ('t', 'B', ITALIC), ' 与平台 ', ('t', 'C', ITALIC),
        ' 得到。第%d组实验的两次校正分别如图3、图4所示，'
        '两条红色虚线就是按上述等面积条件确定的垂线。' % ex['index'],
    ])


# ================================================================ 4.3 思考题
def _sec_questions(rb, analysis, ex, fit):
    rb.heading('4.3 思考题', 3)
    t = ex['sigma_terms']
    sigma_dQ = t['total']
    rounds = analysis.rounds
    sum_sq = 0.0
    for r in rounds:
        sum_sq += r['sigma_Q'] ** 2
        r['_sum_sq'] = sum_sq
    ex_cum = ex['_sum_sq']
    sigma_Q = float(np.sqrt(ex_cum))
    sigma_Qs = sigma_Q / ex['sum_n2']
    order = sorted((('电流 I', t['I']), ('电阻 R', t['R']), ('时间 t', t['t']),
                    ('溶解温差 Δ Δ T', t['d']), ('加热温差 Δ Δ T′', t['h'])),
                   key=lambda kv: -kv[1])

    rb.heading([('t', '4.3.1 由式(12)估算溶解热的平均偏差 '),
                ('t', 'd Δ Q', ITALIC)], 4)
    rb.para([
        '以下计算溶解热的平均偏差 ', ('t', 'd Δ Q', ITALIC),
        '。对于溶解热的计算公式：',
    ])
    rb.equation(r"\Delta Q=I^{2}Rt\times\frac{\Delta\Delta T}{\Delta\Delta T'}")
    rb.para([
        '电流 ', ('t', 'I', ITALIC), ' 的值非常稳定，保守估计 ',
        ('t', 'σ_{I}', ITALIC), ('t', ' = %s A。' % k(analysis.sigma_current, 2)),
        '电阻 ', ('t', 'R', ITALIC), ' 在实验前后相差大约 %s Ω，估计 ' 
        % k(abs(ex['R2'] - ex['R1']), 2),
        ('t', 'σ_{R}', ITALIC), ('t', ' = %s Ω。对于时间 ' % k(analysis.sigma_resistance, 2)),
        ('t', 't', ITALIC), '，假设单次计时的反应误差为 0.5 s，'
        '则时间差的标准差 ',
        ('t', 'σ_{t}', ITALIC),
        ('t', ' = √2 × 0.5 = %s s。' % k(analysis.sigma_time, 2)),
        '对于温差，先按雷诺校正的通用公式（两个基线相减）',
    ])
    rb.equation(r'\Delta\Delta T=(k_{1}t+b_{1})-(k_{2}t+b_{2})')
    rb.para('估计其不确定度：')
    rb.equation(r'\sigma_{\Delta\Delta T}='
                r'\sqrt{(t\sigma_{k_{1}})^{2}+(t\sigma_{k_{2}})^{2}'
                r'+\sigma_{b_{1}}^{2}+\sigma_{b_{2}}^{2}}')
    rb.para([
        '斜率和截距的不确定度均采用 3.2.2 节第%d组实验的值。由此算出其量级只有 '
        '10⁻³ K 上下，说明斜率和截距的误差不是温度误差的主要因素；'
        '不妨设单次测温的误差为 0.005 K，则一个校正温差的误差 ' % ex['index'],
        ('t', 'σ_{Δ Δ T}', ITALIC),
        ('t', ' = 2 × 0.005 = %s K。' % k(analysis.sigma_dT, 2)),
    ])
    rb.para([('t', '综上，', {}), ('t', 'Δ Q', ITALIC),
             ('t', ' 的不确定度计算公式为：', {})])
    rb.equation(r"\sigma_{\Delta Q}^{2}=(2IRt\times\frac{\Delta\Delta T}{\Delta\Delta T'}"
                r"\times\sigma_{I})^{2}+(I^{2}t\times\frac{\Delta\Delta T}{\Delta\Delta T'}"
                r"\times\sigma_{R})^{2}+(I^{2}R\times\frac{\Delta\Delta T}{\Delta\Delta T'}"
                r"\times\sigma_{t})^{2}+(I^{2}Rt\times\frac{\sigma_{\Delta\Delta T}}"
                r"{\Delta\Delta T'})^{2}+(I^{2}Rt\times\frac{\Delta\Delta T\times"
                r"\sigma_{\Delta\Delta T'}}{\Delta\Delta T'^{2}})^{2}")
    rb.para('仍然采用 3.2.2 节第%d组实验的值，代入得各项的绝对贡献：' % ex['index'])
    rb.caption('表4  Δ Q 不确定度各项的贡献（以第%d组实验为例）' % ex['index'])
    rb.table(['来源', '绝对贡献/J', '方差占比/%'],
             [[name, k(v, 2), pct(v ** 2 / sigma_dQ ** 2 * 100)]
              for name, v in order] +
             [['合成', k(sigma_dQ, 2), '100']],
             font_size=10.5, widths_cm=[6.0, 4.0, 4.0])
    rb.equation(r'\sigma_{\Delta Q}=\sqrt{%s}=%.2f\ J=%.2f\ kJ'
                % ('+'.join('%.2f^{2}' % v for _, v in order),
                   sigma_dQ, sigma_dQ / 1000))
    rb.para([
        '由此可见，电流和电阻是误差的主要影响因素。累加各组的贡献，'
        '以第%d组实验为例，后续的物理量不确定度为：' % ex['index'],
    ])
    rb.equation(r'\sigma_{Q}=\sqrt{%s}=%.2f\ kJ'
                % ('+'.join('%.4f^{2}' % (r['sigma_Q'] / 1000) for r in rounds[:ex['index']]),
                   sigma_Q / 1000))
    rb.equation(r'\sigma_{Q_{s}}=\frac{%.2f}{%.6f}=%.2f\ kJ\cdot mol^{-1}'
                % (sigma_Q / 1000, ex['sum_n2'], sigma_Q / 1000 / ex['sum_n2']))
    rb.para([
        '经过估计，各组 ', ('t', 'Q_{s}', ITALIC),
        ' 的不确定度在 0.5~1 kJ·mol⁻¹ 左右。当然，拟合过程会平滑该不确定度，'
        '所以 ', ('t', 'Q_{s}^{0}', ITALIC), ' 的不确定度不太好单独估计，'
        '本报告直接采用非线性拟合协方差矩阵给出的值。',
    ])

    rb.heading('4.3.2 体系和环境的热交换应如何校正', 4)
    rb.para([
        '本实验采用等面积雷诺校正来扣除体系与环境热交换的影响，具体做法是：'
        '把实测的温差-时间曲线看成“稳定漂移的基线 + 某一瞬间完成的热效应阶跃”，'
        '对热效应前后的两段平台分别作最小二乘线性拟合并外延，'
        '再作一条竖线，使该竖线与平滑曲线及两条拟合直线所夹的左右两块面积相等；'
        '此时竖线与两条拟合直线的两个交点之差，就是该热效应本身引起的温差。',
    ])
    rb.para([
        '等面积条件的物理含义正是“热交换的补偿”：曲线偏离基线的部分，'
        '在竖线左侧代表热效应尚未完全表现出来时储存在温度偏差中的热量，'
        '右侧代表这部分热量随后通过热交换逐渐释放（或吸收）的过程；'
        '令两侧面积相等，就等于要求热交换在两段时间内的影响相互抵消。',
    ])
    rb.para([
        '一轮实验要作两次校正：溶解降温段用平台 ',
        ('t', 'A', ITALIC), ' 与 ', ('t', 'B', ITALIC),
        ' 外延，通电升温段用平台 ', ('t', 'B', ITALIC), ' 与 ',
        ('t', 'C', ITALIC),
        ' 外延。由于式(12)用的是两个温差之比，只要两段过程中体系与环境的'
        '热交换情况相同（搅拌速度、温度区间、环境温度一致），'
        '热交换量就能相互抵消，这也是讲义强调“搅拌应快速、稳定、均匀”'
        '以及“加热功率调到 10 W 左右”的原因。',
    ])


# ================================================================ 4.4 结果误差分析
def _sec_error(rb, analysis, fit, cfg, lit, sub_label):
    rounds = analysis.rounds
    ex = rounds[min(EXAMPLE_ROUND, len(rounds)) - 1]
    Qs0 = fit['Qs0']
    # 溶解段与加热段的持续时间（用三次平台之间的时间跨度表示）
    t = ex['data'].t
    p = ex['points']
    t_diss = float(t[p[3]] - t[p[1]])       # End1 -> End2：整个溶解段
    t_heat = float(ex['t_heat'])            # 通电加热时间
    rb.heading('4.4 结果的误差分析', 3)
    if lit:
        dev = abs(Qs0 - float(lit)) / abs(float(lit)) * 100.0
        rb.para([
            '查阅手册^{[2]}可知，25 ℃ 下%s的无限稀释积分溶解热为 ' % sub_label,
            ('t', 'Q_{s}^{0}', ITALIC),
            ('t', ' = %s kJ·mol⁻¹。由于温度对焓变的影响很小，故实验测量值的'
                  '相对误差为：' % k(float(lit), 2)),
        ])
        rb.equation(r'E_{r}=\frac{%.2f-%.2f}{%.2f}\times100\%%=%s\%%'
                    % (Qs0, float(lit), float(lit), pct(dev)))
        rb.para([
            '这是一个较大的误差，不太可能是温度或搅拌这些细节因素导致的。'
            '可能的原因基于实验过程中观察到的一个重要现象：加热所用的时间'
            '（第%d组为 %s s）显著大于溶解所用的时间（约 %s s）。'
            % (ex['index'], k(t_heat, 0), k(t_diss, 0)),
        ])
    else:
        rb.para([
            '第%d组实验中，加热所用的时间（%s s）显著大于溶解所用的时间（约 %s s）。'
            % (ex['index'], k(t_heat, 0), k(t_diss, 0)),
        ])
    rb.para([
        '尽管进行了雷诺校正，假设还是有热交换的影响。溶解过程中，环境对体系注入'
        '热量，使得实际温降偏小，即 ', ('t', 'Δ Δ T', ITALIC),
        ' 偏小；加热过程中，环境从体系吸取热量，导致实际温度上升值偏小，即 ',
        ('t', "Δ Δ T'", ITALIC),
        ' 也偏小。在这两者都偏小的情况下，哪一个占主导取决于溶解过程和加热过程的'
        '持续时间。由于加热时间更长，热交换影响更大，故 ',
        ('t', "Δ Δ T'", ITALIC), ' 偏小占主导，整体上导致 ',
        ('t', "Δ Δ T/Δ Δ T'", ITALIC),
        ' 偏大，即 ', ('t', 'Δ Q', ITALIC), ' 偏大。',
    ])
    rb.para('在实验改进中，可以加大加热功率，使得溶解时间和加热时间近似相等；'
            '如果此时测量结果误差减小，则说明该原因是可靠的。')
    rb.para([
        '另一个可能原因是，在电阻的测量过程中，由于接触问题，使得测量结果偏大，'
        '从而使 ', ('t', 'Δ Q', ITALIC),
        ' 计算偏大。该原因基于以下实验现象：在用万用表测量电阻时，'
        '调整夹子和金属片的位置很容易使测量值越来越大，从而怀疑测量值是偏大的。',
    ])
    rb.para([
        '此外，本报告把水的密度、比热容视为常数（按室温查表^{[2]}），'
        '而实验过程中体系温度与室温并不完全相同，这也会带来少量系统偏差；'
        '容量瓶定容的允差约 0.1%、天平允差 0.2 mg，'
        '两者对 ', ('t', 'n_{0}', ITALIC), ' 的影响都远小于上述两项。',
    ])


# ================================================================ 4.5 小结
def _sec_summary(rb, analysis, fit, diff, cfg, lit, sub_label):
    rounds = analysis.rounds
    Qs0, a = fit['Qs0'], fit['a']
    i200 = list(MARK_N0).index(200)
    rb.heading('4.5 小结', 3)
    rb.para([
        '本实验通过电热补偿法测量%s的溶解热。分批次加入溶质，测出每次实验的热效应。'
        '根据先后加入的溶质总量可求出总浓度，而各次热效应总和即为该浓度下的溶解热。'
        '每轮实验记录一个完整的温差-时间曲线，分为以下部分：平台1（溶解前）—溶解—'
        '平台2（溶解后、加热前）—加热—平台3（加热后）。通过焦耳定律算出加热过程的'
        '热效应，并通过雷诺校正计算溶解和加热过程的温差，由简单的比例关系即可算出'
        '溶解热效应。' % sub_label,
    ])
    rb.para([
        '由此可算出积分溶解热 ', ('t', 'Q_{s}', ITALIC), ' 和浓度 ',
        ('t', 'n_{0}', ITALIC), '。将 ', ('t', 'Q_{s}', ITALIC), '-',
        ('t', 'n_{0}', ITALIC), ' 通过经验公式拟合，得出%s的无限稀释积分溶解热为 '
        % sub_label,
        ('t', 'Q_{s}^{0}', ITALIC), ('t', ' = (%s) kJ·mol⁻¹' % pm(Qs0, fit['sigma_Qs0'])),
        '（', ('t', 'a', ITALIC), ('t', ' = %s，' % pm(a, fit['sigma_a'])),
        ('t', 'R^{2}', ITALIC), ('t', ' = %s）；' % k(fit['r_square'], 5)),
        '同时根据切线的斜率和截距求出了不同浓度下的微分冲淡热 ',
        ('t', 'q_{d}', ITALIC), ' 和微分溶解热 ', ('t', 'q_{s}', ITALIC),
        '，以及不同浓度之间的积分冲淡热 ', ('t', 'Q_{d}', ITALIC),
        '。以 ', ('t', 'n_{0}', ITALIC), ' = 200 为例，',
        ('t', 'q_{d}', ITALIC), ('t', ' = %.3f J·mol⁻¹，' % diff['Qs_n0'][i200]),
        ('t', 'q_{s}', ITALIC), ('t', ' = %.2f kJ·mol⁻¹。' % diff['Qs_n2'][i200]),
    ])
    rb.para('最后，对经验公式的合理性进行了简单分析，由式(12)估算了溶解热的平均'
            '偏差（约 0.1 kJ），并对实验结果的不确定度和误差进行了分析。'
            '分析表明该实验的一个改进方向是增大加热功率，使溶解时间和加热时间'
            '近似相等。')
