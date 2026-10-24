# -*- coding: utf-8 -*-
"""生成《循环伏安法解析电极极化》实验报告 .docx。

结构参照同课程 2025 年的电化学报告（简写版口径）+ 课程 2026 模板的节名：

    封面
    摘要 / 关键词
    1 引言                          目的 / 原理 / 方法见图1（手写预习笔记）
    2 实验部分[1]                    2.1 仪器和试剂   2.2 实验内容
    3 数据与结果
      3.1 N₂氛围下硫酸循环伏安曲线分析
        3.1.1 不同扫速的循环伏安曲线（图2 表1）
        3.1.2 铂电极的电化学活性面积（图3）
      3.2 O₂氛围下硫酸循环伏安曲线分析
        3.2.1 不同搅拌速度的循环伏安曲线（图4）
        3.2.2 ORR 的起始还原电位（图5）
      3.3 N₂氛围下甲醇循环伏安曲线分析
        3.3.1 甲醇的循环伏安曲线（图6）
        3.3.2 MOR 的起始氧化电位（图7）
      3.4 直接甲醇燃料电池的数据处理
        3.4.1 DMFC 的极化曲线（图8 图9）
        3.4.2 DMFC 的输出电压-输出功率曲线（图10）
    4 结果与讨论
      4.1 实验结果（含一小段讨论）  4.2 实验结论
    参考文献

排版口径（skill §3.1）：只"报出一个数值"的句子一律普通文本（变量斜体、
单位正体、± 留空格）；参与推导/代入计算的式子才用公式对象。
"""
from __future__ import annotations

import os

import numpy as np

from . import plotting
from .docxkit import ReportBuilder

ITALIC = {'italic': True}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_JPG = os.path.join(ASSETS, '引言图.jpg')

REPORT_TITLE = '循环伏安法解析电极极化'
INTRO_BLANK_LINES = 26          # 引言页预留的空白行（≈13 cm）


# ---------------------------------------------------------------- 数值格式
def sci(x, nd=3):
    """2.763×10⁻⁷ 形式（普通文本用，×10 的指数走真上标）。nd = 尾数小数位。"""
    if x is None or not np.isfinite(x):
        return '—'
    if x == 0:
        return '0'
    e = int(np.floor(np.log10(abs(x))))
    m = x / 10.0 ** e
    return '%.*f×10^{%d}' % (nd, m, e)


def fv(x, nd=3):
    """普通小数；缺数据给「—」。"""
    if x is None or not np.isfinite(x):
        return '—'
    return '%.*f' % (nd, float(x))


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    esa = analysis.esa
    orr = analysis.orr
    mor = analysis.mor
    d = analysis.dmfc or {}

    # ---- 封面
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    group_txt = ('%s 组 %s 号' % (group, group_no)) if (group and group_no) \
        else (group or group_no)
    temp = cfg.get('room_temp')
    pres = cfg.get('pressure')
    cover = {
        '题目': REPORT_TITLE,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '组号': group_no,
        '实验日期': cfg.get('date'),
        '室温': ('%.1f ℃' % float(temp)) if temp not in (None, '') else None,
        '大气压强': ('%.1f kPa' % float(pres)) if pres not in (None, '') else None,
    }
    missing = [key for key, v in cover.items() if key != '组号'
               and not str(v or '').strip()]
    if missing:
        log('⚠ 封面缺字段：%s（请在界面左侧「报告封面 / 实验条件」里填上）'
            % '、'.join(missing))
    rb.set_cover(cover, title_size=22.0)
    rb.set_header_title(REPORT_TITLE)

    os.makedirs(plots_dir, exist_ok=True)

    # ---- 出图
    log('绘制插图…')
    import matplotlib.pyplot as plt

    def save(fig, name):
        p = os.path.join(plots_dir, name)
        fig.savefig(p, dpi=plotting.DPI)
        plt.close(fig)
        return p

    fig_n2 = save(plotting.make_n2_series_figure(analysis), 'fig2_n2_series.png')
    fig_esa = save(plotting.make_esa_figure(analysis), 'fig3_esa.png')
    fig_o2 = save(plotting.make_o2_series_figure(analysis), 'fig4_o2_series.png')
    fig_orr = save(plotting.make_orr_overlay_figure(analysis), 'fig5_orr_overlay.png')
    fig_meoh = save(plotting.make_meoh_figure(analysis), 'fig6_meoh.png')
    fig_mor = save(plotting.make_mor_overlay_figure(analysis), 'fig7_mor_overlay.png')
    fig_curves = save(plotting.make_orr_mor_figure(analysis), 'fig8_orr_mor.png')
    fig_pol = save(plotting.make_dmfc_polarization_figure(analysis), 'fig9_polarization.png')
    fig_pow = save(plotting.make_dmfc_power_figure(analysis), 'fig10_power.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    rb.para([
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验通过循环伏安法研究了硫酸及甲醇溶液的电化学行为。在氮气饱和的硫酸中，'
        '扫速增大使峰电流显著增大，基于 0.1 V·s⁻¹ 的 CV 曲线计算得到铂电极的'
        '电化学活性面积为 ', fv(esa.get('area_mm2'), 2), ' mm²。'
        '在氧气饱和条件下，搅拌增强仅显著影响低电势区电流，'
        '按统一的差值判据确定 ORR 的起始还原电势为 ',
        fv(orr.get('onset_red')), ' V（氧化支为 ', fv(orr.get('onset_ox')),
        ' V）。在含甲醇的氮气饱和溶液中，测得 MOR 的起始氧化电势为 ',
        fv(mor.get('onset')), ' V。结合 ORR 与 MOR 曲线，通过线性插值得到 '
        'DMFC 单池的极化曲线与输出电压-输出功率曲线，最大输出功率为 ',
        sci(d.get('P_max'), 2), ' W，对应输出电压 ', fv(d.get('E_at_Pmax')), ' V。',
    ])
    rb.para([{'text': '关键词 ', 'bold': True},
             '循环伏安法；直接甲醇燃料电池；电化学活性面积；氧还原反应；甲醇氧化反应'])
    rb.blank()

    # ================================================================ 1 引言
    rb.heading('1 引言', page_break_before=True)
    rb.para('该实验的实验目的、实验原理及实验方法（涵盖在实验原理中）如图1所示。')
    if os.path.exists(INTRO_JPG):
        rb.figure(INTRO_JPG, caption='图1  实验目的、原理及方法', width_cm=11.0)
    else:
        for _ in range(INTRO_BLANK_LINES):
            rb.blank()
        rb.caption('图1  实验目的、原理及方法')

    # ================================================================ 2 实验部分
    rb.heading('2 实验部分^{[1]}', page_break_before=True)
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para('三电极电解池，工作电极（W.E.）为铂圆盘电极，辅助电极（C.E.）为铂片电极，'
            '参比电极（R.E.）为双盐桥饱和甘汞电极（SCE）。实验步骤中所有电势值'
            '均以 SCE 作参比。CHI 电化学工作站，磁力搅拌恒温槽，温度计，'
            '氧气钢瓶，氮气钢瓶。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('电解质：0.05 mol·L⁻¹ 硫酸水溶液，0.1 mol·L⁻¹ 硫酸水溶液和'
            ' 0.1 mol·L⁻¹ 甲醇水溶液。')

    rb.heading('2.2 实验内容', 2)
    rb.heading('2.2.1 电极的前处理', 3)
    rb.para('依次用去离子水、0.05 mol·L⁻¹ 硫酸水溶液润洗玻璃容器，将二次盐桥中的'
            '去离子水换成 0.05 mol·L⁻¹ 硫酸水溶液。正确连接电极与导线，'
            '向电解池中加入 0.05 mol·L⁻¹ 硫酸水溶液和磁子。')
    rb.para('用 CV 法清洁活化电极，观察曲线形状基本不变后停止活化，'
            '调整 Sensitivity 以避免 overflow。持续通入 N₂，当电流零线基本穿过'
            '双电层中间时可认为饱和。活化时扫描范围为 −0.25~1.2 V，'
            '扫描速度为 0.5 V·s⁻¹。N₂ 饱和后，将扫描范围扩大为 −0.35~1.4 V，'
            '观察氢析出峰并确定低电位（氢析出峰刚刚出现的电位）。')
    rb.para('本实验低电位为 −0.26 V，高电位为 1.1 V，起始电位为 0.65 V，'
            '后面不再赘述。')
    rb.heading('2.2.2 N₂氛围下硫酸水溶液的循环伏安曲线', 3)
    rb.para('在 N₂ 饱和下分别测定扫速为 0.5、0.2、0.1 V·s⁻¹ 的 CV 曲线。')
    rb.heading('2.2.3 O₂氛围下硫酸水溶液的循环伏安曲线', 3)
    rb.para('停止通 N₂，改通 O₂。待饱和后分别测定三种条件的 CV 曲线：'
            '快速搅拌（通气且搅拌）、低速搅拌（仅通气不搅拌）、电解质静止'
            '（不通气且不搅拌）。扫描速度固定在 0.1 V·s⁻¹。')
    rb.heading('2.2.4 N₂氛围下甲醇水溶液的循环伏安曲线', 3)
    rb.para('将电解池中溶液更换为 0.1 mol·L⁻¹ 硫酸水溶液和 0.1 mol·L⁻¹ 甲醇'
            '水溶液的等体积混合液，通入 N₂ 使其饱和，测定 CV 曲线。'
            '扫描速度固定在 0.1 V·s⁻¹。')
    rb.para('全部实验做完后，重新清洗电解池和电极，并重新测量 N₂ 饱和下'
            ' 0.05 mol·L⁻¹ 硫酸水溶液的 CV 曲线，确认与开始时一致，'
            '随后将仪器复原到初始状态。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写 N₂ 系列与电化学活性面积…')
    _sec_n2(rb, analysis, fig_n2, fig_esa)
    log('写 O₂ 系列与甲醇…')
    _sec_o2(rb, analysis, fig_o2, fig_orr)
    _sec_meoh(rb, analysis, fig_meoh, fig_mor)
    log('写 DMFC…')
    _sec_dmfc(rb, analysis, fig_curves, fig_pol, fig_pow)

    # ================================================================ 4 结果与讨论
    rb.heading('4 结果与讨论')
    log('写结果与结论…')
    _sec_results(rb, analysis)
    _sec_conclusion(rb, analysis)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] Bard A J, Faulkner L R, White H S. Electrochemical Methods: '
            'Fundamentals and Applications[M]. Hoboken: John Wiley & Sons, 2022.',
            indent_chars=0)
    rb.para('[3] 郭鹤桐, 覃奇贤. 电化学教程[M]. 天津: 天津大学出版社, 2000.',
            indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 3.1 N₂ 系列
def _sec_n2(rb, an, fig_n2, fig_esa):
    esa = an.esa
    rb.heading('3.1 N₂氛围下硫酸循环伏安曲线分析', 2)
    rb.heading('3.1.1 不同扫速的循环伏安曲线', 3)
    rb.para('观察 −0.35~1.4 V 的扫描曲线，可发现 −0.26 V 正好是氢析出峰的开端，'
            '故将低电位设为 −0.26 V。将 N₂ 饱和下扫速分别为 0.5、0.2、'
            '0.1 V·s⁻¹ 的 0.05 mol·L⁻¹ 硫酸溶液的 CV 曲线叠加，如图2所示，'
            '数据点取自 Segment 5 和 6。')
    rb.figure(fig_n2, caption='图2  不同扫速下N₂饱和硫酸溶液CV曲线', width_cm=12.5)
    rb.para('首先对曲线形状作定性分析。在 −0.3~0.0 V，曲线的还原支有氢吸附双峰'
            '（在铂电极表面进行），氧化支有氢脱附的双峰。存在双峰是由于不同'
            '吸附态的存在：电势更负的峰表示氢的弱吸附，电势更正的峰表示氢的'
            '强吸附。这对双峰的位置大致对称，说明氢的吸脱附反应可逆性较好。'
            '而在 0.4~0.6 V，还原支有一个较高的含氧物种脱附峰，氧化支虽有'
            '含氧物种吸附的峰但峰型较差、相对不明显，故含氧物种的吸脱附'
            '可逆性较差，视为不可逆反应。')
    rb.para('在 0.0~0.4 V 没有显著的法拉第反应发生，电流主要由电极/溶液界面的'
            '电容充放电产生，称为双电层。从图2可看出电流零线大致穿过双电层'
            '中间，说明 N₂ 已饱和。')
    rb.para('在不同扫速下，氢吸附/脱附峰的峰电位随扫速增大几乎不变，而含氧物种'
            '脱附峰的峰电位随扫速增加略微向负电位移动。这与理论相符：对可逆'
            '电极反应（氢），峰电位与扫描速率无关；对不可逆电极反应（含氧物种），'
            '峰电位随扫描速率增加向阴极方向移动。')
    rb.para('峰电流随扫描速率的增大而增大。仅看含氧物种的脱附峰，不同扫描速率'
            '下的峰电流如表1所示（取 CHI 峰分析中 Segment 5 的读数，'
            '为相对基线的峰高）。')
    rows = []
    for r in an.table1:
        rows.append([fv(r['v'], 1), sci(r['ip'], 3)])
    rb.caption('表1  含氧物种脱附峰不同扫速下的峰电流')
    rb.table(['v / V·s⁻¹', 'i_{pc} / A'], rows, widths_cm=[5.0, 6.0])
    rb.para([
        '从表1数据可看出，低扫速下 ', ('t', 'i_{pc}', ITALIC), ' 与 ',
        ('t', 'v', ITALIC), '（而不是 ', ('t', 'v^{1/2}', ITALIC), '）接近成正比：'
        '0.2 V·s⁻¹ 与 0.1 V·s⁻¹ 的峰电流之比约为 2。回想 Randles–Ševčík '
        '方程^{[2]}，当反应为扩散控制时 ', ('t', 'i_{pc}', ITALIC), ' 与 ',
        ('t', 'v^{1/2}', ITALIC), ' 成正比，为吸附控制时与 ', ('t', 'v', ITALIC),
        ' 成正比。定量结果从另一方面佐证了该峰是吸附峰而不是扩散峰；'
        '最高扫速 0.5 V·s⁻¹ 下比值略偏离线性，可能与高扫速下吸附未达准平衡有关。',
    ])

    rb.heading('3.1.2 铂电极的电化学活性面积', 3)
    rb.para('扫速为 0.1 V·s⁻¹ 时 CV 曲线最稳定，因此通过该曲线计算铂的'
            '电化学活性面积（后续实验扫速均固定在 0.1 V·s⁻¹，且均用该曲线'
            '作为空白）。将曲线单独绘制在图3中，数据点同样取自 Segment 5 和 6。')
    rb.figure(fig_esa, caption='图3  铂的电化学活性面积的计算', width_cm=12.5)
    rb.para('铂的电化学活性面积通过氢脱附峰求得。以下对峰电量的公式作简单推导。'
            '已知扫描速率是电位随时间的变化率（对于单向扫描）：')
    rb.equation(r'v=\frac{dE}{dt}')
    rb.para([
        '单向扫描的一个峰面积为 ', ('m', 'A=\\int i\\,dE'), '，故电量：',
    ])
    rb.equation(r'Q=\int i\,dt=\int \frac{i}{v}\,dE=\frac{A}{v}')
    rb.para([
        '故氢脱附峰的电量等于氢脱附峰的峰面积与扫描速率之比。峰面积积分的基线'
        '应设定为双电层电流的上基线，本报告取氢区之后双电层窗口'
        '（0.10~0.20 V）内电流的平均值 ', ('t', fv(esa['baseline'] * 1e6, 3),
                                          ITALIC), '×10⁻⁶ A 作为基线'
        '（图3中虚线）。如图3所示，对阴影区域（', ('t', fv(esa['lo'], 2), ITALIC),
        '~', ('t', fv(esa['hi'], 2), ITALIC), ' V）积分的结果为 ',
        ('t', 'A', ITALIC), ' = ', sci(esa['A']), ' A·V，故峰电量：',
    ])
    rb.equation(r'Q=\frac{%(A)s}{%(v)s}=%(Q)s\ \mathrm{C}'
                % {'A': _latex_sci(esa['A']), 'v': _latex_num(esa['v'], 2),
                   'Q': _latex_sci(esa['Q'])})
    rb.para([
        '已知铂表面满单层氢脱附的电量为 2.1×10⁻⁴ C·cm⁻²，故电化学活性面积：',
    ])
    rb.equation(r'\mathrm{ESA}=\frac{%(Q)s}{2.1\times10^{-4}}=%(cm2)s\ \mathrm{cm}^{2}'
                r'=%(mm2)s\ \mathrm{mm}^{2}'
                % {'Q': _latex_sci(esa['Q']),
                   'cm2': _latex_num(esa['area_cm2'], 4),
                   'mm2': _latex_num(esa['area_mm2'], 2)})


# ---------------------------------------------------------------- 3.2 O₂ 系列
def _sec_o2(rb, an, fig_o2, fig_orr):
    orr = an.orr
    rb.heading('3.2 O₂氛围下硫酸循环伏安曲线分析', 2)
    rb.heading('3.2.1 不同搅拌速度的循环伏安曲线', 3)
    rb.para('O₂ 饱和下，将不同搅拌速度下各 CV 曲线的还原支与 N₂ 饱和下的空白'
            '曲线合并，结果如图4所示，其中数据点均取自 Segment 5。')
    rb.figure(fig_o2, caption='图4  不同搅速下O₂饱和硫酸溶液的CV曲线', width_cm=12.5)
    rb.para('从图4可看出，在高电位区域，不同搅拌速度的 CV 曲线几乎重合。'
            '高电位区域可分成两个部分：在 0.7 V 以上，O₂ 还未开始还原，'
            '曲线自然重合；而在 0.5~0.7 V，O₂ 已经开始还原而曲线仍接近重合。'
            '这是因为该区域是动力学控制区，此时反应速控因素不是 O₂ 能否运送到'
            '电极表面，而是 O₂ 分子在电极表面发生断键、电子转移这一系列化学'
            '反应本身的速度。这个本征反应速度只与电极电位、电极催化剂活性'
            '和温度有关，与传质关系很小。')
    rb.para([
        '在低电位区域，搅拌越剧烈，电流越大。该区域为扩散控制区，'
        '此时反应速控因素完全转变为 O₂ 从溶液传输到电极表面的速度。'
        '根据极限扩散电流公式^{[2]}，极限扩散电流与扩散层厚度 ',
        ('t', 'δ', ITALIC), ' 成反比，而搅拌增强了对流、减薄了电极表面的'
        '扩散层厚度，从而极大地提高了 O₂ 的传质速率。',
    ])
    rb.para('从图中还可明显看出，快速搅拌下曲线发生剧烈震荡。这是因为过度剧烈'
            '的搅拌破坏了原本理想的层流模型，电极表面扩散层厚度在时间和空间上'
            '都不再稳定，而是随机、快速地波动，直接表现为电流信号的强烈噪声。')

    rb.heading('3.2.2 ORR的起始还原电位', 3)
    rb.para('将 O₂ 饱和低速搅拌的 CV 曲线与 N₂ 饱和的 CV 曲线叠加，'
            '结果如图5所示，其中数据点均取自 Segment 5 和 6。')
    rb.figure(fig_orr, caption='图5  低速搅拌下N₂/O₂饱和硫酸溶液的CV曲线',
              width_cm=12.5)
    thr = orr.get('threshold', 1e-6)
    rb.para([
        '起始还原电位的判定方式为：将 O₂ 和 N₂ 的饱和曲线对比，沿扫描方向'
        '当两者差值开始大于 ', sci(thr, 1), ' A 时的电位即为起始还原电位'
        '（这是人为判定因素，因为曲线的波动很大；本报告对还原支与氧化支'
        '采用同一机械判据以避免读图的主观性）。由此读出还原支的起始还原电位为 ',
        ('t', fv(orr.get('onset_red')), ITALIC), ' V，氧化支的起始还原电位为 ',
        ('t', fv(orr.get('onset_ox')), ITALIC), ' V。',
    ])
    rb.para('正向和反向扫描的起始还原电位有所不同，原因如下：正向扫描时 Pt 表面'
            '同时被氧化（含氧物种的吸附），活性位减少，O₂ 还原反应被抑制；'
            '而反向扫描时表面 PtO 结合物被还原恢复为金属态（含氧物种的脱附），'
            'ORR 反应位点重新暴露。由于 ORR 是还原支扣除空白的结果，'
            '仅用还原支进行后续分析。')


# ---------------------------------------------------------------- 3.3 甲醇
def _sec_meoh(rb, an, fig_meoh, fig_mor):
    mor = an.mor
    rb.heading('3.3 N₂氛围下甲醇循环伏安曲线分析', 2)
    rb.heading('3.3.1 甲醇的循环伏安曲线', 3)
    rb.para('N₂ 饱和下，甲醇+硫酸等体积混合溶液的 CV 曲线如图6所示，'
            '其中数据点取自 Segment 5 和 6。')
    rb.figure(fig_meoh, caption='图6  N₂饱和下甲醇+硫酸溶液的CV曲线',
              width_cm=12.5)
    rb.para('对该曲线的形状作定性分析。正向扫描时的主氧化峰很好理解，而逆向扫描'
            '时也出现一个类似的「次氧化峰」：正向扫描时铂表面开始氧化（含氧物种'
            '的吸附），部分活性位点被阻塞；逆向扫描时铂氧化层逐渐还原（含氧物种'
            '的脱附），新暴露的铂表面仍然接触未反应完全的甲醇，从而出现一个较小'
            '的二次氧化峰。两个峰展宽甚至叠加，可能因为铂电极表面粗糙（多晶），'
            '不同晶面活性位电势分布较宽。')
    rb.para('另一个值得分析的特征是，甲醇 CV 曲线在 0.0~0.3 V 附近没有显著的'
            '电流变化（氢吸脱附峰消失）。这是因为甲醇改变了氢的吸脱附性质：'
            '甲醇脱氢会生成强吸附的 CO 中间体，该中间体完全阻塞了氢吸附位点。')

    rb.heading('3.3.2 MOR的起始氧化电位', 3)
    rb.para('将甲醇的 CV 曲线与无甲醇的空白曲线叠加，结果如图7所示。')
    rb.figure(fig_mor, caption='图7  N₂饱和下甲醇/空白溶液的CV曲线',
              width_cm=12.5)
    thr = mor.get('threshold', 1e-6)
    rb.para([
        'MOR 起始氧化电位的判断方式与 ORR 一致，只是在氧化支上沿扫描方向'
        '当甲醇曲线比空白曲线更负 ', sci(thr, 1), ' A 时读取（氢区的差异方向'
        '相反——空白曲线因氢脱附而更负，不会误触发）。从数据中读出 MOR 的'
        '起始氧化电位为 ', ('t', fv(mor.get('onset')), ITALIC), ' V。'
        '同样可发现正向扫描和逆向扫描的起始氧化电位有区别，原因同 3.2.2。',
    ])


# ---------------------------------------------------------------- 3.4 DMFC
def _sec_dmfc(rb, an, fig_curves, fig_pol, fig_pow):
    d = an.dmfc
    rb.heading('3.4 直接甲醇燃料电池的数据处理', 2)
    rb.heading('3.4.1 DMFC的极化曲线', 3)
    rb.para('将 O₂ 饱和 CV 曲线的还原支和甲醇 CV 曲线的氧化支扣除空白后，'
            '分别得到 ORR 和 MOR 曲线。将这两条曲线画在同一个坐标轴里'
            '（取电流量值），如图8所示。')
    rb.figure(fig_curves, caption='图8  ORR和MOR曲线', width_cm=13.5)
    if d:
        rb.para([
            '电池工作区域的判定方法为：存在相同的电流值，使得 ORR 和 MOR 均'
            '存在电势，且 ORR 电势大于 MOR。此外，工作区域须在此前判断的 ORR '
            '初始还原电位和 MOR 初始氧化电位范围内，即 ',
            ('t', fv(an.mor.get('onset')), ITALIC), '~',
            ('t', fv(an.orr.get('onset_red')), ITALIC), ' V。'
            'DMFC 电池的工作区域就是图8中间的三角区域。从数据中读出 ORR 和 '
            'MOR 的交点电位为 ', ('t', fv(d.get('E_intersect')), ITALIC),
            ' V。故将 MOR 曲线 ', ('t', fv(an.mor.get('onset')), ITALIC), '~',
            ('t', fv(d.get('E_intersect')), ITALIC), ' V 和 ORR 曲线 ',
            ('t', fv(d.get('E_intersect')), ITALIC), '~',
            ('t', fv(an.orr.get('onset_red')), ITALIC),
            ' V 的数据点单提出来，即为 DMFC 电池，如图9所示。',
        ])
    else:
        rb.para('ORR 与 MOR 曲线没有可用的公共工作区，请检查起始电位判据。')
    rb.figure(fig_pol, caption='图9  DMFC电池的极化曲线', width_cm=13.0)

    rb.heading('3.4.2 DMFC的输出电压-输出功率曲线', 3)
    if d:
        n_pts = len(d['i_grid'])
        rb.para([
            '为了获得特定电流下的输出功率，需要对图9曲线进行插值。'
            '根据图9值域选取电流范围为 ', sci(d['i_grid'][0], 1), ' A ~ ',
            sci(d['i_grid'][-1], 3), ' A（到两支曲线的交点为止），'
            '步长为 ', sci(d['i_grid'][1] - d['i_grid'][0], 1),
            ' A，也即一共 %d 个采样点。然后选取线性插值方法，'
            '获得各个电流下的 ' % n_pts, ('t', 'E_{ORR}', ITALIC), ' 和 ',
            ('t', 'E_{MOR}', ITALIC), ' 数据点。根据公式：',
        ])
        rb.equation(r'E_{cell}=E_{ORR}-E_{MOR}')
        rb.equation(r'P=IE_{cell}')
        rb.para([
            '可以获得一系列 ', ('t', 'P', ITALIC), ' 和 ',
            ('t', 'E_{cell}', ITALIC), '，由此作出的 ',
            ('t', 'P', ITALIC), '–', ('t', 'E_{cell}', ITALIC),
            ' 曲线如图10所示。顶端处曲线的不光滑可能是线性插值方法有一定误差'
            '所致。由图10可以读出，最大输出功率为 ',
            ('t', sci(d['P_max'], 2), ITALIC), ' W，此时的输出电压 ',
            ('t', 'E_{cell}', ITALIC), ' = ',
            ('t', fv(d['E_at_Pmax']), ITALIC), ' V。',
        ])
    else:
        rb.para('缺少 DMFC 工作区数据，无法绘制功率曲线。')
    rb.figure(fig_pow, caption='图10  DMFC电池的输出电压-输出功率曲线',
              width_cm=13.0)


# ---------------------------------------------------------------- 4 结果与讨论
def _sec_results(rb, an):
    esa, orr, mor, d = an.esa, an.orr, an.mor, an.dmfc or {}
    rb.heading('4.1 实验结果', 2)
    rb.para([
        '本实验在 N₂ 饱和的 0.05 mol·L⁻¹ 硫酸中测定了 0.5、0.2、0.1 V·s⁻¹ '
        '三个扫速的 CV 曲线：氢吸脱附峰位置基本不随扫速移动（可逆），'
        '含氧物种脱附峰随扫速增大略向负方向移动（不可逆）；峰电流随扫速增大'
        '而增大，且更接近与 ', ('t', 'v', ITALIC), ' 成正比，为吸附控制特征。'
        '由 0.1 V·s⁻¹ 曲线的氢脱附峰电量得到铂电极的电化学活性面积为 ',
        ('t', fv(esa.get('area_mm2'), 2), ITALIC), ' mm²。',
    ])
    rb.para([
        '在 O₂ 饱和条件下，搅拌只显著改变低电势区（扩散控制区）的电流：'
        '搅拌越强电流越大，快速搅拌下因层流被破坏而出现强烈噪声；高电势区'
        '（动力学控制区）曲线基本重合。按统一的差值判据（扣空白信号越过 ',
        sci(orr.get('threshold', 1e-6), 1), ' A）确定 ORR 还原支起始还原电势为 ',
        ('t', fv(orr.get('onset_red')), ITALIC), ' V、氧化支为 ',
        ('t', fv(orr.get('onset_ox')), ITALIC), ' V，'
        '后者更负源于反向扫描时铂氧化物被还原、活性位点重新暴露。',
    ])
    rb.para([
        '在 N₂ 饱和的甲醇+硫酸溶液中，CV 曲线出现正向主氧化峰与逆向次氧化峰，'
        '且氢区电流消失（CO 中间体阻塞氢吸附位点）；MOR 起始氧化电势为 ',
        ('t', fv(mor.get('onset')), ITALIC), ' V。由扣空白的 ORR 与 MOR 曲线'
        '得到 DMFC 工作区，两支曲线交点电位 ',
        ('t', fv(d.get('E_intersect')), ITALIC), ' V，'
        '线性插值给出的最大输出功率为 ', ('t', sci(d.get('P_max'), 2), ITALIC),
        ' W，对应输出电压 ', ('t', fv(d.get('E_at_Pmax')), ITALIC), ' V，'
        '远低于 DMFC 的理论开路电压 1.214 V，体现了两极较大的活化过电势。',
    ])
    rb.para('需要说明的是：起始电位按「扣空白差值越过阈值」的机械判据读取，'
            '与读图的主观判定相比更可复现，但数值对阈值与平滑窗口的选取敏感；'
            '电化学活性面积对积分上限与双电层基线的选取同样敏感（上限移动 '
            '0.05 V 可使结果变化约百分之几），故上述两个判据都在界面上开放了'
            '可调参数，报告中的数值对应本页注明的默认设置。')


def _sec_conclusion(rb, an):
    esa, orr, mor, d = an.esa, an.orr, an.mor, an.dmfc or {}
    rb.heading('4.2 实验结论', 2)
    rb.para([
        '本实验运用循环伏安法，对 0.05 mol·L⁻¹ 硫酸水溶液以及 0.1 mol·L⁻¹ '
        '硫酸与 0.1 mol·L⁻¹ 甲醇等体积混合溶液的电化学行为进行了研究：'
        '利用氢脱附峰电量求得铂电极电化学活性面积 ',
        ('t', fv(esa.get('area_mm2'), 2), ITALIC), ' mm²；'
        '考察了扫速与搅拌对 CV 曲线的影响，确定 ORR 起始还原电势 ',
        ('t', fv(orr.get('onset_red')), ITALIC), ' V、MOR 起始氧化电势 ',
        ('t', fv(mor.get('onset')), ITALIC), ' V；最后结合 ORR 与 MOR 曲线'
        '得到 DMFC 单池的极化曲线与功率曲线，最大输出功率 ',
        ('t', sci(d.get('P_max'), 2), ITALIC), ' W（输出电压 ',
        ('t', fv(d.get('E_at_Pmax')), ITALIC), ' V）。',
    ])


# ---------------------------------------------------------------- 小工具
def _latex_sci(x, nd=3):
    """LaTeX 里的 2.763\times 10^{-7}（给公式用）。"""
    if x is None or not np.isfinite(x):
        return r'\mathrm{NaN}'
    if x == 0:
        return '0'
    e = int(np.floor(np.log10(abs(x))))
    m = x / 10.0 ** e
    return r'%.*f\times10^{%d}' % (nd, m, e)


def _latex_num(x, nd=3):
    if x is None or not np.isfinite(x):
        return r'\mathrm{NaN}'
    return '%.*f' % (nd, float(x))
