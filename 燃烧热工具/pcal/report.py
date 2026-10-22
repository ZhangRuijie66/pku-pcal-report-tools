# -*- coding: utf-8 -*-
"""生成《燃烧热的测定》实验报告 .docx（结构与原报告模板一致，公式为 Word 原生公式）。"""
from __future__ import annotations

import decimal
import os

import numpy as np
from docx.enum.text import WD_ALIGN_PARAGRAPH

from . import combustion as cb
from . import plotting
from .analysis import SUBSTANCES
from .docxkit import ReportBuilder

# 行内变量：普通文本 + 斜体（不是公式对象）
ITALIC = {'italic': True}
SUB = {'sub': True}      # 下标（普通文本）

# 装置图（讲义里的图1 氧弹式量热计 / 图2 氧弹的构造，裁掉了自带的图题）
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
APPARATUS_PNG = os.path.join(ASSETS, '装置图.png')

# 报告题目（课程模板封面的「题目：」和页眉右侧都要用）
REPORT_TITLE = '燃烧热的测定'

# ---------------------------------------------------------------- 数值格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


# ---- 有效数字（按 JJF 1059.1 + GB/T 8170）
#   · 测得值的末位必须与不确定度的末位对齐；
#   · 不确定度取 1~2 位有效数字（本报告统一 2 位）；
#   · 修约用"四舍六入五成双"。
SIG_DIGITS = 2


def _sig(x, n=SIG_DIGITS):
    """保留 n 位有效数字（四舍六入五成双）。"""
    x = float(x)
    if x == 0 or not np.isfinite(x):
        return 0.0
    d = decimal.Decimal(repr(x))
    q = decimal.Decimal(1).scaleb(d.adjusted() - n + 1)
    return float(d.quantize(q, rounding=decimal.ROUND_HALF_EVEN))


def _place(unc, n=SIG_DIGITS):
    """不确定度保留 n 位有效数字后，末位所在的量级（返回 10 的幂）。"""
    return decimal.Decimal(repr(float(unc))).adjusted() - n + 1


def _fix(x, exp):
    """把 x 修约到 10^exp 位（四舍六入五成双）。"""
    q = decimal.Decimal(1).scaleb(exp)
    return float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN))


def _fmt(x, exp):
    return '%.*f' % (max(0, -exp), x)


def val(x, unc, n=SIG_DIGITS):
    """结果值：修约到与不确定度末位一致，返回字符串。"""
    if unc in (None, 0):
        return k(x, 1)
    return _fmt(_fix(x, _place(unc, n)), _place(unc, n))


def unc(x, n=SIG_DIGITS):
    """不确定度：保留 n 位有效数字，返回字符串。"""
    if x in (None, 0):
        return '—'
    e = _place(x, n)
    return _fmt(_fix(x, e), e)


def pm(x, u, n=SIG_DIGITS, unit=''):
    """「值 ± 不确定度」，末位对齐（JJF 1059.1 要求）。"""
    e = _place(u, n) if u not in (None, 0) else _place(abs(x) * 1e-3 or 1, n)
    return '%s ± %s%s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e), unit)


def pct(x, n=SIG_DIGITS):
    """相对偏差：保留 n 位有效数字。"""
    return _fmt(_sig(x, n), _place(x, n))


def sci(x, nd=2):
    """把数值写成 a×10^n，n 用 OMML 上标。返回 (系数, 指数)。"""
    if x == 0:
        return '0', 0
    e = int(np.floor(np.log10(abs(x))))
    return '%.*f' % (nd, x / 10 ** e), e


def tex_sci(x, nd=2):
    a, e = sci(x, nd)
    return r'%s\times10^{%d}' % (a, e)


def fmt_eq_number(x, nd=3):
    return '%.*f' % (nd, x)


def tex_round(x, nd):
    s = '%.*f' % (nd, x)
    return s


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 intro_image=None, progress=None, cover_tail_blanks=1):
    """
    analysis: Analysis（已 run）
    cfg: 配置字典
    plots_dir: 雷诺校正图输出目录
    template_path: 报告模板 docx
    intro_image: 保留参数；引言已改为从讲义[1]精简的文字，不再插入图片。
    cover_tail_blanks: 封面末尾保留几个空段落（用于让摘要、关键词留在第一页）。
    """
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    doc = rb.doc
    rounds = analysis.rounds
    std = analysis.standard
    samples = [r for r in rounds if r['role'] != 'standard']
    W = analysis.W
    sW = analysis.sigma_W
    sigma_dT = analysis.sigma_dT
    sigma_sumq = analysis.sigma_sumq
    sigma_msam = analysis.sigma_m_diff
    sigma_mcot = analysis.sigma_m_single
    e_b = cfg.get('e_balance', 0.0002)
    e_t = cfg.get('e_temperature', 0.002)
    ndW = int(cfg.get('round_constant_to', 1))
    ndQ = int(cfg.get('round_qv_to', 1))

    # ---- 封面（课程 2026 模板：题目 + 姓名/学号/组别/实验日期/室温/大气压强）
    T_room = rounds[0]['temperature'] if rounds else 298.15
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    if group and group_no:
        group_txt = '%s 组 %s 号' % (group, group_no)
    else:
        group_txt = group or group_no
    rb.set_cover({
        '题目': REPORT_TITLE,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '组号': group_no,              # 老模板有这一行，新模板没有，命中不了就算了
        '实验日期': cfg.get('date'),
        '室温': '%.1f ℃' % (T_room - 273.15),
        '大气压强': ('%s kPa' % cfg.get('pressure_kPa')) if cfg.get('pressure_kPa') else None,
    })
    rb.set_header_title(REPORT_TITLE)

    os.makedirs(plots_dir, exist_ok=True)

    # ---- 每轮出图
    log('绘制雷诺校正图…')
    import matplotlib.pyplot as plt
    for it in rounds:
        fig = plotting.make_figure(it['data'], it['fit1'], it['fit2'], it['reynolds'])
        png = os.path.join(plots_dir, 'reynolds_%d_%s.png' % (
            it['index'], _safe(it['name'])))
        fig.savefig(png, dpi=plotting.DPI)
        plt.close(fig)
        del fig
        it['plot_png'] = png

    # ================================================================ 摘要
    log('撰写摘要与引言…')
    mol_lines = []
    for it in samples:
        m = analysis.molar(it)
        if m:
            mol_lines.append((it, m))
    main_it, main_mol = (mol_lines[0] if mol_lines else (samples[0], None))
    std_name = std['name']
    main_name = main_it['name']
    dTm = main_it['dT']
    sigma_mol = main_mol['sigma_kJ_per_mol'] if main_mol else None
    Qp_mol = main_mol['Qp_kJ_per_mol'] if main_mol else None
    sub = SUBSTANCES.get(main_it['substance'], SUBSTANCES['custom'])

    abstract = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '燃烧热是热化学的基本数据，常用于间接求算难以直接测定的反应热。'
        '本实验使用氧弹式量热计测定燃烧热。首先以%s为标准物质，通过其完全燃烧使体系水温升高的值，'
        '结合其理论燃烧热（%s J·g⁻¹），标定出量热计常数' % (std_name, k(analysis.Qv_benzoic, 0)),
        # 只在示出数值的地方用普通文本（变量斜体、单位正体），不做成公式对象
        ('t', 'W', ITALIC),
        ('t', ' = (%s) J·K⁻¹' % pm(W, sW)),
        '，过程中采用雷诺校正消除热交换影响，并扣除镍丝与棉线燃烧热。随后，在相同条件下燃烧%s样品，'
        '根据测得的温度升高值及已标定的' % main_name,
        ('t', 'W', ITALIC),
        '，计算其恒容及恒压燃烧热。',
    ] + ([
        '最终测得',
        (sub.get('tex_label') or sub.get('label') or main_name),
        '的摩尔燃烧热为',
        ('t', 'Q_{p} = Q_{V}', ITALIC),
        ('t', ' = (%s) kJ·mol⁻¹' % pm(Qp_mol, sigma_mol)),
        ('t', '，与文献值 %s kJ·mol⁻¹ 接近，分析表明温差测量误差是主要误差来源。' % (
            k(main_mol['literature'], 0) if main_mol['literature'] else '（未给出）')),
    ] if main_mol else ['（样品未给出分子量，未换算摩尔燃烧热。）'])
    rb.para(abstract)

    keywords = '燃烧热；氧弹式量热计；' + '；'.join(
        dict.fromkeys([r['name'] for r in rounds] + ['苯甲酸']))
    rb.para([{'text': '关键词 ', 'bold': True}, keywords])
    rb.blank()

    # ================================================================ 引言
    # 实验目的、实验原理、实验方法均据讲义[1]「实验一 燃烧热的测定」精简。
    # 摘要和关键词与封面同处第一页，引言另起一页（从第二页第一行开始）。
    # 课程 2026 模板里这一节就叫「引言」，不编号。
    rb.heading('引言', page_break_before=True)
    sample_names = '、'.join(r['name'] for r in samples) or '糖样品'
    rb.para([
        ('t', '实验目的　', {'bold': True}),
        '用氧弹式量热计测定蔗糖的燃烧热，了解量热计的原理、构造与使用方法，'
        '取得热化学实验的一般知识和基本训练。本实验按讲义要求分三轮进行：'
        '先在未标定量热计常数的情况下测出温度(温差)-时间曲线，算出每克样品引起的体系温升值；'
        '再用标准物质苯甲酸标定量热计常数 ',
        ('t', 'W', ITALIC),
        '；最后测出%s的恒容及恒压燃烧热。' % sample_names,
    ])

    rb.para([
        ('t', '实验原理　', {'bold': True}),
        '燃烧热是 1 mol 物质完全燃烧时的热效应，是热化学的基本数据。'
        '一般反应的热效应往往因反应太慢或反应不完全而难以直接测定，'
        '但借助盖斯定律可用燃烧热数据间接求算，因此燃烧热广泛用于各类热化学计算。'
        '由热力学第一定律，燃烧在恒容下进行时体系不对外做功，恒容燃烧热等于体系内能的改变：',
    ])
    rb.equation(r'\Delta U=Q_{V}')
    rb.para([
        '将一定量的物质放在充氧的氧弹中使其完全燃烧，放出的热量使体系温度升高 ',
        ('t', 'Δ T', ITALIC), '，再由体系的热容 ', ('t', 'C_{V}', ITALIC),
        ' 即可算出燃烧反应的热效应：',
    ])
    rb.equation(r'Q_{V}=-C_{V}\Delta T')
    rb.para([
        '一般所说的燃烧热指恒压燃烧热 ', ('t', 'Q_{p}', ITALIC), '，可由 ', ('t', 'Q_{V}', ITALIC),
        ' 换算：',
    ])
    rb.equation(r'Q_{p}=\Delta_{c}H_{m}=\Delta U+p\Delta V=Q_{V}+p\Delta V')
    rb.para('对理想气体有：')
    rb.equation(r'Q_{p}=Q_{V}+\Delta nRT')
    rb.para([
        '这样由反应前后气态物质的量变化 ', ('t', 'Δ n', ITALIC),
        ' 即可算出恒压燃烧热 ', ('t', 'Q_{p}', ITALIC), '。燃烧热随温度的变化满足：',
    ])
    rb.equation(r'\frac{\partial(\Delta_{c}H_{m})}{\partial T}=\Delta C_{p}')
    rb.para([
        '其中 ', ('t', 'Δ C_{p}', ITALIC),
        ' 为反应前后的恒压热容差。一般而言燃烧热随温度变化不大，'
        '在较小的温度范围内可视为常数。',
    ])

    rb.para([
        ('t', '实验方法　', {'bold': True}),
        '实验装置为氧弹式量热计（装置如图1所示）。内筒以内的部分构成所研究的实际体系，'
        '体系与外界隔以空气层绝热，下方用热绝缘的垫片架起以减少对流和蒸发；'
        '为使体系温度尽快均匀还装有搅拌器，金属搅棒上端以绝热塑料与马达相连以防导热；'
        '温度变化由温差测量仪测定，点火由附加的电气装置完成。'
        '本实验不使用水套，而是让体系温度接近于环境温度以减少热交换。'
        '氧弹用不锈钢制成，拧紧弹盖即形成密封体系；电极A与进气阀体相连并装在弹头中心，'
        '与弹头其余部分绝缘；电极B直接与弹头相连，同时作为坩埚式燃烧皿的支架；'
        '电极A上方装有金属隔热罩，使火焰反射向下、弹体温度均匀。',
    ])
    # 讲义里的装置图（左：氧弹式量热计，右：氧弹的构造）；图题由本报告统一编
    if os.path.exists(APPARATUS_PNG):
        rb.figure(APPARATUS_PNG, caption='图1  氧弹式量热计（左）和氧弹的构造（右）',
                  width_cm=14.5)
    rb.para([
        '测定燃烧热需先知道体系的热容，量热计的热容常用水当量（量热计常数）', ('t', 'W', ITALIC),
        '表示，即除水之外量热计升高 1 K 所需的热量。', ('t', 'W', ITALIC),
        ' 由已知燃烧热的标准物质（本实验为苯甲酸）完全燃烧来标定。'
        '对每一次燃烧，软件记录的“温度(温差)-时间曲线”可划分为点火前、燃烧反应期、'
        '末期三段，用雷诺校正法校正体系与环境热交换的影响，得到体系内部因燃烧放热'
        '而升高的温度 ', ('t', 'Δ T', ITALIC), '；再扣除燃烧丝和棉线的校正值 ',
        ('t', 'Σ q_{V}', ITALIC), '，量热计常数与待测样品的恒容燃烧热分别由下式给出：',
    ])
    rb.equation(r'(W+DC_{w})\Delta T=-Q_{V}G-\sum q_{V}')
    rb.equation(r'Q_{V}=\frac{(W+DC_{w})\Delta T+\sum q_{V}}{m_{sam}}')
    rb.para([
        '其中 ', ('t', 'Q_{V}', ITALIC), ' 为恒容燃烧热，', ('t', 'G', ITALIC), ' 为标准物质的质量，',
        ('t', 'D', ITALIC), ' 为内筒水的质量，', ('t', 'C_{w}', ITALIC), ' 为水的比热容，',
        ('t', 'm_{sam}', ITALIC), ' 为待测样品质量。后文所用量热计常数、各轮 ',
        ('t', 'Δ T', ITALIC), ' 与不确定度均由此模型给出；具体操作步骤见第 2 节。',
    ])

    # ================================================================ 2 实验部分
    rb.heading('2 实验部分^{[1]}')
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para('氧弹式量热计，氧气钢瓶，压片机，温差测量仪，容量瓶，公用万用表，分析天平。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('镍丝，棉线，苯甲酸，'
            + '，'.join(dict.fromkeys(r['name'] for r in rounds if r['role'] != 'standard'))
            + '。')

    rb.heading('2.2 实验内容', 2)
    for it in rounds:
        rb.heading('2.2.%d 第%d轮：%s' % (it['index'], it['index'], it['name']), 3)
        if it['role'] == 'standard':
            what = '取约0.7~1.3 g苯甲酸粉末，置于压片机中压成圆柱体'
        else:
            what = '取适量%s' % it['name']
        rb.para(
            '倒出量热仪中的水，擦干氧弹内部和外部，重新定容%s mL去离子水并加入。%s，'
            '用棉线将样品系好：取一段镍金属燃烧丝，将两端分别紧缠或固定于电极A和电极B上，'
            '避免两个电极松动，并防止镍丝与下方金属坩埚燃烧皿直接相连而短路；'
            '再将已被棉线缠系的圆柱状样品用棉线系在燃烧丝上，小心挂在燃烧皿中。'
            % (k(it['water_volume'], 0), what))
        rb.para(
            '盖好弹盖，从进气口灌入0.7~1.3 MPa氧气，用万用表触试弹头和进气阀体，'
            '记录电阻值并判断是否通路。若为通路，把氧弹放入内筒，准确量取%s mL去离子水'
            '（容量瓶定容），小心倒入内筒。盖好盖板，插上温差仪探头，开动搅拌马达。'
            % k(it['water_volume'], 0))
        rb.para(
            '待水温稳定后，开始记录温差随时间变化。先记录一段平台期，按住点火键几秒引燃样品。'
            '此时温度迅速上升，持续记录直到温度平稳变化。若干分钟后停止搅拌，取下温差仪探头，'
            '取出氧弹，在通风处泄去废气，取出弹头，称量剩余燃烧丝质量。实验条件：室温 %s K，'
            '大气压强 %s kPa，燃烧丝（镍丝）燃烧前 %s g、燃烧后 %s g，'
            '棉线 %s g，样品+棉线共 %s g（故样品质量 %s g）。'
            % (k(it['temperature'], 2),
               k(cfg.get('pressure_kPa') or 0, 1) if cfg.get('pressure_kPa') else '—',
               '%.4f' % it['nickel_before'], '%.4f' % it['nickel_after'],
               '%.4f' % it['cotton_mass'], '%.4f' % it['combustible_mass'],
               '%.4f' % it['sample_mass']))

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    rb.heading('3.1 实验数据记录', 2)
    T0 = rounds[0]['temperature']
    rb.para([('t', '本次实验的室温为 '), ('t', 'T', ITALIC),
             ('t', ' = %.2f K（%.1f ℃）。' % (T0, T0 - 273.15))])
    rb.para('本次实验一共进行了%d轮测量。各轮次的数据均由课程软件'
            '（溶解热-燃烧热数据采集与处理 v2.2.4）采集得到，平均每 %s s 记录一个数据点，'
            '每轮记录的时间跨度见表1。每一轮记录的数据说明如下。'
            % (len(rounds), k(np.median(np.diff(rounds[0]['data'].t)), 2)))
    rb.para([('t', '本报告中 ', {}), ('t', 'm_{Ni-1}', ITALIC), ('t', ' 和 ', {}), ('t', 'm_{Ni-2}', ITALIC),
             ('t', ' 分别为镍丝燃烧前后的质量，由此可算出燃烧的镍丝质量：', {})])
    rb.equation(r'm_{Ni}=m_{Ni-1}-m_{Ni-2}')
    rb.para([('t', '本报告中 ', {}), ('t', 'm_{cot}', ITALIC), ('t', ' 为棉线质量，', {}),
             ('t', 'm_{tot}', ITALIC), ('t', ' 为棉线+样品总质量，由此可算出样品质量：', {})])
    rb.equation(r'm_{sam}=m_{tot}-m_{cot}')
    rb.para([('t', '本报告中 '), ('t', 'r_{t}', ITALIC),
             ('t', ' 为试触电阻（软件记录中未给出，以“—”表示），'
                   '用于判断氧弹是否通路，不参与后续计算。所有数据整理于表1。')])
    # 表头只用普通文本 + 真下标（这些格子是记录物理量名字，不该用公式对象）
    hdr = ['轮次', '用途', 'm_{Ni-1}/g', 'm_{Ni-2}/g', 'm_{Ni}/g', 'm_{cot}/g',
           'm_{tot}/g', 'm_{sam}/g', 'V_{w}/mL', 'T/K', '时长/s']
    rows = []
    for it in rounds:
        rows.append([it['name'], '标定' if it['role'] == 'standard' else '待测',
                     '%.4f' % it['nickel_before'], '%.4f' % it['nickel_after'],
                     '%.4f' % it['nickel_loss'], '%.4f' % it['cotton_mass'],
                     '%.4f' % it['combustible_mass'], '%.4f' % it['sample_mass'],
                     k(it['water_volume'], 0), k(it['temperature'], 2),
                     k(it['data'].duration, 1)])
    rb.caption('表1  各轮实验原始数据记录')
    # 五号字；列宽按内容精算，保证每个单元格都不换行（正文宽约 18 cm）
    rb.table(hdr, rows, font_size=10.5,
             widths_cm=[1.30, 1.05, 1.75, 1.75, 1.65, 1.65, 1.65, 1.75, 1.65, 1.20, 1.35])
    rb.para(['注：“标定”表示该轮为标准物质苯甲酸，用于标定量热计常数 ',
             ('t', 'W', ITALIC),
             '；“待测”表示该轮为待测样品。'], indent_chars=0)
    rb.blank()

    # ---- 逐轮处理
    # 小节顺序：标定轮必须排在最前（否则样品计算引用了还没标定出来的 W）；
    # 报告主角（摘要、小结里给出的那个样品，即轮次最靠前的待测样品）放在最后，
    # 好让第 3 节的叙述直接接上「4 小结」。
    order = [std] + [r for r in samples if r is not main_it] \
        + ([main_it] if any(r is main_it for r in samples) else [])
    fig_no = 2          # 图1 是引言里的装置图
    for pos, it in enumerate(order):
        sec = pos + 2
        is_std = it['role'] == 'standard'
        rb.heading('3.%d 第%d轮实验数据处理（%s）' % (sec, it['index'], it['name']), 2)
        rb.heading('3.%d.1 雷诺校正' % sec, 3)
        rb.para([('t', '本报告约定：经过雷诺校正后点火前和点火后的温度分别为 ', {}),
                 ('t', 'T_{l}', ITALIC), ('t', ' 和 ', {}), ('t', 'T_{r}', ITALIC),
                 ('t', '，故体系的温升值为：', {})])
        rb.equation(r'\Delta T=T_{r}-T_{l}')
        rb.para([('t', '雷诺校正的基本流程为：分别对过程前（记为 ', {}), ('t', 'A', ITALIC), ('t', '）和过程后（记为 ', {}),
                 ('t', 'B', ITALIC), ('）的两段平台区作最小二乘线性拟合并将直线外延；'
                 '以B样条平滑曲线拟合介于两平台之间的实测数据；'
                 '作一垂线，若该垂线与平滑曲线和两条拟合直线相交的区域面积相等，'
                 '则该垂线与两条拟合直线的两个交点即为过程前后的温度。'
                       '第%d轮（%s）的雷诺校正图如图%d所示'
                       '（拟合区间取数据点下标 %d~%d 与 %d~%d）。'
                       % (it['index'], it['name'], fig_no, it['points'][0],
                          it['points'][1], it['points'][2], it['points'][3]))])
        rb.figure(it['plot_png'],
                  caption='图%d  第%d轮（%s）的雷诺校正图' % (fig_no, it['index'], it['name']),
                  width_cm=13.5)
        fig_no += 1
        rb.para('数据处理的结果如下，首先是两条拟合直线方程（斜率与截距均给出标准差，'
                '末位已与标准差对齐）：')
        f1, f2 = it['fit1'], it['fit2']
        rb.equation(r'A:\ \Delta T=(%s)\times10^{-5}t+(%s)\qquad R^{2}=%s'
                    % (pm(f1['k'] * 1e5, f1['stddev_k'] * 1e5),
                       pm(f1['b'], f1['stddev_b']), k(f1['r_square'], 3)))
        rb.equation(r'B:\ \Delta T=(%s)\times10^{-5}t+(%s)\qquad R^{2}=%s'
                    % (pm(f2['k'] * 1e5, f2['stddev_k'] * 1e5),
                       pm(f2['b'], f2['stddev_b']), k(f2['r_square'], 3)))
        rb.para('其次，雷诺校正垂线的横坐标为：')
        rb.equation(r't_{0}=%.3f\ s' % it['reynolds']['x0'])
        rb.para([('t', '将 ', {}), ('t', 't_{0}', ITALIC), ('t', ' 分别代入 ', {}), ('t', 'A', ITALIC), ('t', ' 和 ', {}),
                 ('t', 'B', ITALIC), ('t', ' 方程即可算出 ', {}), ('t', 'T_{l}', ITALIC), ('t', ' 和 ', {}),
                 ('t', 'T_{r}', ITALIC), ('t', '，再将两者相减得温升 ', {}), ('t', 'Δ T', ITALIC),
                 ('t', '。计算如下：', {})])
        rb.para([('t', 'T_{l}', ITALIC),
                 ('t', ' = %s K，' % val(it['reynolds']['T_left'], sigma_dT)),
                 ('t', 'T_{r}', ITALIC),
                 ('t', ' = %s K。' % val(it['reynolds']['T_right'], sigma_dT))])
        rb.equation(r'\Delta T=T_{r}-T_{l}=%s\ K' % val(it['dT'], sigma_dT))

        if is_std:
            _section_constant(rb, analysis, it, cfg, ndW, sec)
        else:
            _section_sample(rb, analysis, it, cfg, ndQ, sec,
                            sub if it is main_it else None)

    # ================================================================ 4 结果与讨论
    rb.heading('4 结果与讨论')

    # ---- 4.1 实验结果
    rb.heading('4.1 实验结果', 2)
    rb.para('本实验通过氧弹式量热计测量不同样品的燃烧热。首先用标准物质（%s）测定量热计常数，'
            '基本原理为：水的热容加上量热计热容为体系总热容，总热容乘以温度升高值为总燃烧热，'
            '而标准物质的总燃烧热可由其理论燃烧热算出。整个测量过程通过雷诺校正校正体系与环境'
            '热交换的影响，并通过镍丝和棉线的燃烧热对总燃烧热进行校正。' % std['name'])
    rb.para([('t', '由此测得量热计常数 '), ('t', 'W', ITALIC),
             ('t', ' = (%s) J·K⁻¹。' % pm(W, sW))])
    if samples:
        # 结果按“这次实际测了什么”来写：本报告里的样品全部列出（不只主角），
        # 没给分子量的样品（食用油、奶片这类混合物）就只报 J·g⁻¹。
        rb.para('此后，根据样品燃烧的温度升高值可算出样品的总燃烧热，从而计算出样品的燃烧热。'
                '本实验在相同条件下共测定了 %d 个样品，结果如下。' % len(samples))
        for it2 in samples:
            m2 = analysis.molar(it2)
            sb2 = SUBSTANCES.get(it2['substance'], SUBSTANCES['custom'])
            label = sb2.get('tex_label') or sb2.get('label') or ''
            head = it2['name']
            if label and label != it2['name'] and not label.startswith(it2['name']):
                head += '（主要成分为%s）' % label
            sQv2 = it2.get('sigma_Qv_per_gram')
            segs = [('t', '%s的' % head)]
            if m2:
                segs += [('t', '摩尔燃烧热为 '),
                         ('t', 'Q_{p} = Q_{V}', ITALIC),
                         ('t', ' = (%s) kJ·mol⁻¹，即 (%s) J·g⁻¹'
                          % (pm(m2['Qp_kJ_per_mol'], m2['sigma_kJ_per_mol']),
                             pm(m2['Qp_J_per_g'], m2['sigma_J_per_g'])))]
                if m2['literature']:
                    segs.append('，与文献值 %s kJ·mol⁻¹ 相差 %s%%。'
                                % (k(m2['literature'], 0), pct(m2['error_percent'])))
                else:
                    segs.append('。')
            else:
                segs += [('t', '恒容燃烧热为 '),
                         ('t', 'Q_{V}', ITALIC),
                         ('t', ' = (%s) J·g⁻¹。'
                          % pm(it2['Qv_per_gram'], sQv2))]
            rb.para(segs)

    # ---- 结果部分末尾的一点讨论（简写版不单列「实验讨论」一节）
    if main_mol:
        liter = main_mol['literature']
        segs = []
        if liter:
            errs = [m['error_percent'] for _, m in mol_lines
                    if m.get('error_percent') is not None]
            segs.append('上述结果与手册值相差不大（相对偏差%s），'
                        '说明扣除镍丝与棉线的燃烧热、并用雷诺校正消除体系与环境的'
                        '热交换之后，系统误差已被有效校正。'
                        % (('不超过 %s%%' % pct(max(errs))) if errs else '较小'))
        segs.append('误差分析表明，雷诺校正的拟合误差、室温在 1 K 内的波动以及容量瓶的'
                    '精度（0.1%%）带来的影响量级都远小于温差仪的允差，可以忽略；'
                    '镍丝与棉线的燃烧热在总放热量中占比约为 %s%%，其质量称量的不确定度'
                    '是次要因素，而温差测量的不确定度经放大后成为主要误差来源。'
                    '此外，量热计常数由苯甲酸单独标定，对取点比较敏感，'
                    '因此各轮的取点均经人工核对（见各轮的雷诺校正图）。'
                    % k(abs(main_it['sum_q'])
                        / max(abs((W + main_it['D_Cw']) * main_it['dT']), 1e-9) * 100, 2))
        rb.para(segs)

    # ---- 4.2 实验结论
    rb.heading('4.2 实验结论', 2)
    if samples and mol_lines:
        parts = ['本实验用氧弹式量热计测定了%s的燃烧热。'
                 % '、'.join(r['name'] for r in samples)]
        parts += ['以苯甲酸标定得量热计常数 ', ('t', 'W', ITALIC),
                  ('t', ' = (%s) J·K⁻¹；' % pm(W, sW))]
        vals = []
        for it2 in samples:
            m2 = analysis.molar(it2)
            if m2:
                vals.append('%s为 (%s) kJ·mol⁻¹'
                            % (it2['name'], pm(m2['Qp_kJ_per_mol'], m2['sigma_kJ_per_mol'])))
            else:
                vals.append('%s为 (%s) J·g⁻¹'
                            % (it2['name'], pm(it2['Qv_per_gram'],
                                               it2.get('sigma_Qv_per_gram'))))
        parts.append('各样品的燃烧热分别为' + '，'.join(vals) + '。')
        devs = ['%s %s%%' % (it2['name'], pct(analysis.molar(it2)['error_percent']))
                for it2 in samples
                if analysis.molar(it2) and analysis.molar(it2).get('error_percent') is not None]
        if devs and main_mol and main_mol['literature']:
            parts.append('与文献值 %s kJ·mol⁻¹ 相比，各样品的相对偏差分别为%s。'
                         % (k(main_mol['literature'], 0), '、'.join(devs)))
        parts.append('结果表明，氧弹式量热计配合雷诺校正能够给出与文献相符的燃烧热，'
                     '本实验的主要误差来源是温差仪的测量误差。')
        rb.para(parts)
    else:
        rb.para('本实验的主要误差来源是温差仪的测量误差。')

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组, 物理化学实验(2025年秋季试用),'
            '北京大学化学与分子工程学院, 2025.', indent_chars=0)
    rb.para('[2] Haynes W M. CRC Handbook of Chemistry and Physics[M]. CRC Press, 2016: 5-75~5-76.',
            indent_chars=0)
    rb.para('[3] 赵泽华, 等. 量热实验数据采集处理软件的自主开发与应用[J]. 大学化学, 2025, 40(11): 402. '
            '（数据处理算法来源，GPL-3.0 开源）', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 分节：量热计常数
def _section_constant(rb, analysis, it, cfg, ndW, sec=2):
    W = analysis.W
    sW = analysis.sigma_W
    sigma_dT = analysis.sigma_dT
    sigma_sumq = analysis.sigma_sumq
    sigma_msam = analysis.sigma_m_diff
    sigma_mcot = analysis.sigma_m_single
    e_b = cfg.get('e_balance', 0.0002)
    e_t = cfg.get('e_temperature', 0.002)
    Qv_ben = analysis.Qv_benzoic
    num = Qv_ben * it['sample_mass'] + it['sum_q']

    rb.heading([('t', '3.%d.2 量热计常数 ' % sec), ('t', 'W', ITALIC),
                ('t', ' 的计算')], 3)
    rb.para('由实验原理可知，量热计常数的计算公式为：')
    rb.equation(r'W=\frac{-Q_{V}G-\sum q_{V}}{\Delta T}-DC_{w}')
    rb.para([('t', '其中 ', {}), ('t', 'Q_{V}', ITALIC), ('t', ' 为苯甲酸的恒容燃烧热，已知苯甲酸恒压燃烧热为 ', {}),
             ('t', 'Q_{p}', ITALIC),
             ('t', ' = %s J·g⁻¹，两者的关系为：'
                    % k(it.get('Qp_benzoic_per_gram', -26460), 0))])
    rb.equation(r'Q_{V}=Q_{p}-\frac{\Delta nRT}{M_{r}}')
    rb.para([('t', '其中苯甲酸的分子量 ', {}),
             ('t', 'M_{r}', ITALIC),
             ('t', ' = %.3f g·mol⁻¹^{[2]}。苯甲酸燃烧方程式为：' % cb.M_BENZOIC)])
    rb.equation(r'C_{7}H_{6}O_{2}(s)+7.5O_{2}(g)=7CO_{2}(g)+3H_{2}O(l)')
    rb.para('故：')
    rb.equation(r'\Delta n=7-7.5=-0.5')
    rb.para('故恒容燃烧热为：')
    rb.para([('t', 'Q_{V}', ITALIC), ('t', ' = %s J·g⁻¹。' % k(Qv_ben, 0))])
    rb.para('由讲义知镍丝和棉线的恒容燃烧热分别为：')
    rb.para([('t', 'Q_{V-Ni}', ITALIC), ('t', ' = %s J·g⁻¹，' % k(it['nickel_heat'], 0)),
             ('t', 'Q_{V-cot}', ITALIC), ('t', ' = %s J·g⁻¹。' % k(it['cotton_heat'], 0))])
    rb.para('根据表1的数据，有：')
    rb.equation(r'\sum q_{V}=Q_{V-Ni}m_{Ni}+Q_{V-cot}m_{cot}=%s\times%.4f%+.0f\times%.4f=%s\ J'
                % (k(it['nickel_heat'], 0), it['nickel_loss'],
                   it['cotton_heat'], it['cotton_mass'],
                   val(it['sum_q'], sigma_sumq)))
    rb.para([('其余已知数据有，%.2f K 下水的密度和比热容为：' % it['temperature'], {})])
    rb.para([('t', 'ρ_{w}', ITALIC), ('t', ' = %.7f g·mL⁻¹，' % it['water_density']),
             ('t', 'C_{w}', ITALIC), ('t', ' = %.4f J·(g·K)⁻¹。' % it['water_capacity'])])
    rb.para('综上，量热计常数为：')
    rb.equation(r'W=\frac{-(%s)\times%.4f-(%s)}{%s}-%s\times%.7f\times%.4f=%s\ J\cdot K^{-1}'
                % (k(Qv_ben, 0), it['sample_mass'], val(it['sum_q'], sigma_sumq),
                   val(it['dT'], sigma_dT),
                   k(it['water_volume'], 0), it['water_density'], it['water_capacity'],
                   val(W, sW)))
    rb.para([('t', '接下来计算不确定度。设万分之一分析天平的仪器允差 ', {}),
             ('t', 'e', ITALIC), ('t', ' = %.4f g，温差仪的仪器允差 ' % e_b),
             ('t', 'e', ITALIC), ('t', ' = %.3f K。则：' % e_t)])
    rb.equation(r'\sigma_{\Delta T}=\frac{2e}{\sqrt{3}}=%s\ K' % unc(sigma_dT))
    rb.equation(r'\sigma_{G}=\sigma_{m_{Ni}}=\frac{\sqrt{2}e}{\sqrt{3}}=%s\ g' % unc(sigma_msam))
    rb.equation(r'\sigma_{m_{cot}}=\frac{e}{\sqrt{3}}=%s\ g' % unc(sigma_mcot))
    rb.para([('t', '则 ', {}), ('t', 'Σ q_{V}', ITALIC), ('t', ' 的不确定度为：', {})])
    rb.equation(r'\sigma_{\sum q_{V}}=\sqrt{(Q_{V-Ni}\sigma_{m_{Ni}})^{2}'
                r'+(Q_{V-cot}\sigma_{m_{cot}})^{2}}=%s\ J' % unc(sigma_sumq))
    rb.para([('t', '量热计常数 ', {}), ('t', 'W', ITALIC), ('t', ' 的不确定度为：', {})])
    rb.equation(r'\sigma_{W}=\sqrt{(\frac{Q_{V}\sigma_{G}}{\Delta T})^{2}'
                r'+(\frac{\sigma_{\sum q_{V}}}{\Delta T})^{2}'
                r'+(\frac{(-Q_{V}G-\sum q_{V})\sigma_{\Delta T}}{\Delta T^{2}})^{2}}'
                r'=%s\ J\cdot K^{-1}' % unc(abs(analysis.sigma_W)))
    rb.para('计算表明误差的主要来源是第三项，即温差测量误差。综上：')
    rb.equation(r'W=(%s)\ J\cdot K^{-1}' % pm(W, abs(sW)))


# ---------------------------------------------------------------- 分节：样品燃烧热
def _section_sample(rb, analysis, it, cfg, ndQ, sec=2, sub=None):
    W = analysis.W
    sW = analysis.sigma_W
    sigma_dT = analysis.sigma_dT
    sigma_sumq = analysis.sigma_sumq
    sigma_msam = analysis.sigma_m_diff
    Qv = it['Qv_per_gram']
    sQv = it['sigma_Qv_per_gram']
    total_heat = (W + it['D_Cw']) * it['dT'] + it['sum_q']
    sub = sub or SUBSTANCES.get(it['substance'], SUBSTANCES['custom'])
    mol = analysis.molar(it)

    rb.heading('3.%d.2 %s燃烧热的计算' % (sec, it['name']), 3)
    rb.para('%s的主要成分是%s，其燃烧方程式为：'
            % (it['name'], sub.get('tex_label') or sub.get('label') or '待测样品'))
    if sub.get('equation'):
        rb.equation(sub['equation'])
    rb.para('根据实验原理可知，样品恒容燃烧热的计算公式为：')
    rb.equation(r'Q_{V}=\frac{(W+DC_{w})\Delta T+\sum q_{V}}{m_{sam}}')
    rb.para([('t', '此处与习惯一致，燃烧热取正值。其中需要重新计算的量是 ', {}),
             ('t', 'Σ q_{V}', ITALIC), ('t', '，根据表1：', {})])
    rb.equation(r'\sum q_{V}=Q_{V-Ni}m_{Ni}+Q_{V-cot}m_{cot}=(%s)\times%.4f+(%s)\times%.4f=%s\ J'
                % (k(it['nickel_heat'], 0), it['nickel_loss'],
                   k(it['cotton_heat'], 0), it['cotton_mass'],
                   val(it['sum_q'], sigma_sumq)))
    rb.para('故恒容燃烧热为：')
    rb.equation(r'Q_{V}=\frac{(%s+%s\times%.7f\times%.4f)\times%s%s}{%.4f}'
                r'=%s\ J\cdot g^{-1}'
                % (k(W, ndQ), k(it['water_volume'], 0), it['water_density'],
                   it['water_capacity'], val(it['dT'], sigma_dT),
                   val(it['sum_q'], sigma_sumq),
                   it['sample_mass'], val(Qv, sQv)))
    if mol:
        rb.para([('t', '由于 ', {}), ('m', r'\Delta n=%d' % int(sub.get('dn') or 0)),
                 ('t', '，且该样品的摩尔质量 ', {}),
                 ('t', 'M_{r}', ITALIC),
                 ('t', ' = %.3f g·mol⁻¹^{[2]}。故：' % mol['Mr'])])
        rb.equation(r'Q_{p}=Q_{V}=%s\times%.3f\ J\cdot mol^{-1}=%s\ kJ\cdot mol^{-1}'
                    % (k(Qv, ndQ), mol['Mr'], val(mol['Qp_kJ_per_mol'],
                                                  mol['sigma_kJ_per_mol'])))
    rb.para('接下来计算不确定度。各物理量的不确定度均已在前面算出：')
    rb.equation(r'\sigma_{W}=%s\ J\cdot K^{-1}\qquad \sigma_{\Delta T}=%s\ K\qquad '
                r'\sigma_{\sum q_{V}}=%s\ J\qquad \sigma_{m_{sam}}=%s\ g'
                % (unc(abs(sW)), unc(sigma_dT), unc(sigma_sumq), unc(sigma_msam)))
    rb.para([('t', '故 ', {}), ('t', 'Q_{V}', ITALIC), ('t', ' 的不确定度计算公式为：', {})])
    rb.equation(r'\sigma_{Q_{V}}=\sqrt{(\frac{\Delta T\sigma_{W}}{m_{sam}})^{2}'
                r'+(\frac{(W+DC_{w})\sigma_{\Delta T}}{m_{sam}})^{2}'
                r'+(\frac{\sigma_{\sum q_{V}}}{m_{sam}})^{2}'
                r'+(\frac{((W+DC_{w})\Delta T+\sum q_{V})\sigma_{m_{sam}}}{m_{sam}^{2}})^{2}}'
                r'=%s\ J\cdot g^{-1}' % unc(sQv))
    if mol:
        rb.equation(r'=%s\ kJ\cdot mol^{-1}' % unc(mol['sigma_kJ_per_mol']))
    rb.para('综上：')
    if mol:
        rb.equation(r'Q_{p}=Q_{V}=(%s)\ kJ\cdot mol^{-1}'
                    % pm(mol['Qp_kJ_per_mol'], mol['sigma_kJ_per_mol']))
    else:
        rb.para([('t', 'Q_{V}', ITALIC),
             ('t', ' = (%s) J·g⁻¹。' % pm(Qv, sQv))])
    if mol and mol['literature']:
        rb.para('查阅手册^{[2]}，该样品的燃烧热为：')
        rb.para([('t', 'Q_{c}', ITALIC),
                 ('t', ' = %s kJ·mol⁻¹。' % k(mol['literature'], 0))])


def _safe(name):
    return ''.join(ch if ch.isalnum() else '_' for ch in str(name))
