# -*- coding: utf-8 -*-
"""生成《紫外可见吸收光谱仪搭建与量子一维势阱方程检验》实验报告 .docx。

结构参照同课程此前的紫外光谱报告（完整版）：

    封面
    摘要 / 关键词
    1 引言                          目的 / 原理 / 方法见图1（手写预习笔记）
    2 实验部分[1]                    2.1 仪器和试剂   2.2 实验内容
    3 数据与结果
      3.1 光谱仪的标定                                          图2 图3 图4
        3.1.1 长波范围（第一周） 3.1.2 长波范围（第二周） 3.1.3 短波范围
      3.2 光源对吸收光谱的影响                                  图5  表2
      3.3 浓度对吸收光谱的影响                                  图6  表3  图7
      3.4 其余分子的吸收光谱测定结果                            图8 图9 图10 表4
      3.5 Gaussian 理论计算（暂空）
    4 讨论与结论
      4.1 各分子吸收光谱结果讨论
        4.1.1 定性分析   4.1.2 定量分析——一维势箱模型的验证    表5 表6 表7
      4.2 实验操作对测量结果的影响及经验总结
      4.3 小结
    参考文献

公式一律用 Word 原生公式（OMML）；只示出变量值的写法用普通文本（变量斜体、单位正体）。
"""
from __future__ import annotations

import decimal
import os

import numpy as np
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from . import plotting
from . import uv
from .analysis import default_config
from .docxkit import ReportBuilder, add_rich_text

ITALIC = {'italic': True}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_JPG = os.path.join(ASSETS, '引言图.jpg')

REPORT_TITLE = '紫外可见吸收光谱仪搭建与量子一维势阱方程检验'
INTRO_BLANK_LINES = 26          # 引言页预留的空白行（≈13 cm）

SIG_DIGITS = 2


# ---------------------------------------------------------------- 数值格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


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


def val(x, u, n=SIG_DIGITS):
    if u in (None, 0) or not np.isfinite(u):
        return k(x, 3)
    return _fmt(_fix(x, _place(u, n)), _place(u, n))


def unc(u, n=SIG_DIGITS):
    if u in (None, 0) or not np.isfinite(u):
        return '—'
    e = _place(u, n)
    return _fmt(_fix(u, e), e)


def pm(x, u, n=SIG_DIGITS):
    if u in (None, 0) or not np.isfinite(u):
        return k(x, 3)
    e = _place(u, n)
    return '%s ± %s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e))


def pct(x, n=SIG_DIGITS):
    return _fmt(_sig(x, n), _place(x, n))


def sci_pm(x, u, exp=None):
    """(4.3 ± 0.1)×10⁴ 形式；exp 不给就按数值大小自动选。"""
    if exp is None:
        exp = int(np.floor(np.log10(abs(x)))) if x else 5
    s = 10.0 ** exp
    return '(%s)×10^{%d}' % (pm(x / s, u / s), exp)


def num_sig(x, n=3):
    """3 位有效数字的普通写法（ε 用）。"""
    if x in (None, 0) or not np.isfinite(x):
        return '—'
    return '%.3g' % x


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    cals = analysis.cals
    c1, c2, c3 = cals['d1_long'], cals['d2_long'], cals['d2_short']
    mol = {r['code']: r for r in analysis.molecule_table}
    beer = analysis.beer
    fit = beer.get('fit') if beer else None
    box = analysis.box

    # ---- 封面
    t1 = cfg.get('room_temp_1')
    t2 = cfg.get('room_temp_2')
    p1 = cfg.get('pressure_1')
    p2 = cfg.get('pressure_2')
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    group_txt = ('%s 组 %s 号' % (group, group_no)) if (group and group_no) else (group or group_no)
    temp_txt = ' & '.join(['%.1f ℃' % float(t) for t in (t1, t2) if t not in (None, '')])
    pres_vals = [ _trim(p) for p in (p1, p2) if p not in (None, '')]
    pres_txt = (' & '.join(pres_vals) + ' kPa') if pres_vals else None
    cover = {
        '题目': REPORT_TITLE,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '组号': group_no,
        '实验日期': cfg.get('date'),
        '室温': temp_txt or None,
        '大气压强': pres_txt or None,
    }
    missing = [key for key, v in cover.items() if key != '组号' and not str(v or '').strip()]
    if missing:
        log('⚠ 封面缺字段：%s（请在界面左侧「报告封面 / 实验条件」里填上）'
            % '、'.join(missing))
    rb.set_cover(cover, title_size=18.0)
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

    cal_pngs = {}
    for key, cal in cals.items():
        cal_pngs[key] = save(plotting.make_calibration_figure(cal),
                             'calib_%s.png' % key)

    source_png = save(plotting.make_source_figure(
        analysis.samples['A3c5'], analysis.samples['A3_DW']), 'source_A3.png')

    conc_items = list(analysis.conc_items)
    conc_png = save(plotting.make_concentration_figure(conc_items), 'conc_A3.png')

    beer_png = None
    if fit and np.isfinite(fit.get('k', np.nan)):
        beer_png = save(plotting.make_beer_figure(beer), 'beer_fit.png')

    voigt_png = None
    a3_key = (getattr(analysis, 'picks_mol', {}) or {}).get('A3') or 'A3c5b'
    if a3_key in analysis.samples:
        voigt_png = save(plotting.make_voigt_figure(analysis.samples[a3_key]),
                         'voigt_A3.png')

    long_items = [analysis.samples[k] for k in ('A2', 'A3c5', 'A4')
                  if k in analysis.samples]
    short_items = [analysis.samples[k] for k in ('A1', 'B1c', 'B2')
                   if k in analysis.samples]
    long_png = save(plotting.make_spectra_figure(
        long_items, labels=['A2', 'A3', 'A4'], xlim=(450, 880)), 'spectra_long.png')
    short_png = save(plotting.make_spectra_figure(
        short_items, labels=['A1', 'B1', 'B2'], xlim=(250, 600)), 'spectra_short.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    eps_segs = []
    if fit and np.isfinite(fit.get('eps', np.nan)):
        eps_segs = ['测得 A3 的摩尔消光系数 ', ('t', 'ε', ITALIC), ' = ',
                    sci_pm(fit['eps'], _eps_sigma(fit)),
                    ' L·mol⁻¹·cm⁻¹（约为文献值 2.00×10⁵ 的 22%，'
                    '受杂散光等系统误差压缩，为下限）。']
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验基于自建紫外可见吸收光谱仪，测量了 A、B 两类共 6 种共轭分子的'
        '紫外可见吸收光谱。以氘灯特征谱线标定了 pixel–波长关系，'
        '考察了光源与浓度对吸收光谱的影响，',
    ] + eps_segs + [
        '各条吸收光谱均用 Voigt 线形作分峰拟合后读取峰位与峰高。'
        '各分子最大吸收波长随共轭体系增大而红移、摩尔消光系数总体增大；'
        '以一维势箱模型对 A 组分子作定量检验，短共轭体系半定量可用，'
        '长共轭体系（B1）明显失效。最后讨论了自建光谱仪杂散光与基线漂移的影响。',
    ]
    rb.para(abs_segs)
    rb.para([{'text': '关键词 ', 'bold': True},
             '紫外-可见光谱；朗伯-比尔定律；Voigt 分峰；一维势箱；摩尔消光系数；光谱仪搭建'])
    rb.blank()

    # ================================================================ 1 引言
    rb.heading('1 引言', page_break_before=True)
    rb.para('该实验的实验目的、实验原理及实验方法如图1所示。')
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
    rb.para('光源（卤钨灯、氘灯），光阑，平凸透镜（f = 75 mm），样品池架，样品池，'
            '可调狭缝，凹面镜（f = −100 mm），光栅（600 线·mm⁻¹，闪耀波长 500 nm），'
            'CCD 检测器，光学平台（面包板），光学元件架，光学支杆套件，遮光器材，安装工具。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('A 组 4 种（A1~A4）与 B 组 2 种（B1~B2）共轭分子的乙醇溶液，'
            '各分子的结构式与浓度如表1所示。')
    _table_reagents(rb)

    rb.heading('2.2 实验内容', 2)
    rb.para('按讲义图2 的光路在光学平台上搭建紫外可见吸收光谱仪。所有光学元件'
            '已预先固定在元件架中，取用时戴手套、只接触元件边缘，轻拿轻放；'
            '安装时保持光路平面与面包板平行（光高一致）、光路准直，'
            '并尽量让光束通过光学元件的中心部分。')
    rb.para('打开氘灯电源，在靠近光源处装上光阑；将平凸透镜套组固定在光源左侧约 75 mm 处，'
            '调整位置使透射光成为平行光；在透镜后固定样品池架；在样品池后安装第二个'
            '平凸透镜套组，用白纸板确定焦点位置并将可调狭缝固定于此处，打开卤钨灯，'
            '使光斑最小且通过狭缝。在狭缝后约 100 mm（凹面镜的焦距）处固定第一个凹面镜'
            '套组，使反射光近似平行；沿反射光方向安装光栅套组，反复调节光栅角度，'
            '直到在白纸板上观察到较强的一级衍射。在光栅的一级衍射方向固定第二个凹面镜套组，'
            '用白纸板确定反射光焦点后把 CCD 固定于此处，并调整光栅与第二个凹面镜的距离，'
            '使 CCD 能接收到完整的光谱范围。最后用遮光罩把狭缝及其后的光路遮好，'
            '狭缝前留一小孔让光射入，再用仪器罩罩住整个光谱仪。')
    rb.para('标定时，打开氘灯扫描光源谱图，在 CCD 控制软件中寻找氘灯的特征峰，'
            '记录各特征峰对应的 pixel 值，与标准波长作线性拟合，即得 pixel–波长的'
            '换算关系。本实验第一周在长波范围完成标定，测定了 A4 的吸收光谱；'
            '第二周重新标定长波范围后，测定了 A3 的浓度系列、A3 的双光源对比以及 A2；'
            '随后将 CCD 向紫外方向移动、重新标定短波范围，测定了 A1、B1、B2。')
    rb.para([
        '测量吸收光谱时，先稳定光源约半小时，调整积分时间与平均次数以获得足够的'
        '信号强度和信噪比。在同一光源条件下分别测定乙醇空白与待测样品，'
        '均为扣除暗背景后的光谱，其中乙醇的信号强度记为 ', ('t', 'I_{0}', ITALIC),
        '、待测样品的记为 ', ('t', 'I', ITALIC), '。',
        '全部测量完成后拷贝数据、关闭光源与电源，并按原样整理仪器。',
    ])

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写标定与光源…')
    _sec_calibration(rb, c1, c2, c3, cal_pngs)
    _sec_source(rb, analysis, source_png)
    log('写浓度与其余分子…')
    _sec_concentration(rb, analysis, fit, conc_items, conc_png, beer_png)
    _sec_molecules(rb, analysis, mol, long_png, short_png, voigt_png)
    _sec_gaussian(rb, cfg, mol)

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    log('写讨论…')
    _sec_qualitative(rb, mol)
    _sec_box(rb, analysis, mol)
    _sec_eps_literature(rb, analysis, mol, fit)
    _sec_operation(rb, analysis)
    _sec_summary(rb, analysis, mol, fit)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] 周公度, 段连运. 结构化学基础（第5版）[M]. 北京：北京大学出版社, 2017.',
            indent_chars=0)
    rb.para("[3] Atkins P W, de Paula J, Keeler J. Atkins' Physical Chemistry[M]. "
            'Oxford: Oxford University Press, 2023.', indent_chars=0)
    rb.para('[4] Frisch M J, Trucks G W, Schlegel H B, et al. Gaussian 09, Revision E.01'
            '[CP]. Wallingford CT: Gaussian Inc., 2009.', indent_chars=0)
    rb.para('[5] Thermo Fisher Scientific (Alfa Aesar). 3,3′-Diethylthiadicarbocyanine '
            'iodide, 99% (CAS 514-73-8): product specification[Z]. 2024.',
            indent_chars=0)
    rb.para('[6] ChemicalBook. 3,3′-二乙基硫二碳碘化氰 (CAS 514-73-8) 物性数据'
            '[DB/OL]. https://www.chemicalbook.cn/CAS_514-73-8.htm, 2026.',
            indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 小工具
def _trim(x):
    try:
        return ('%.1f' % float(x)).rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return str(x)


def _eps_sigma(fit):
    return abs(fit.get('sigma_k', 0.0)) / (1e-6 * 1.0) if fit else 0.0


def _eps_phrase(eps_txt):
    return 'ε = %s L·mol⁻¹·cm⁻¹' % eps_txt


def _table_reagents(rb):
    """表1：分子编号、结构式、浓度。结构式图片插到表格第二列。"""
    rows = []
    for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
        if code == 'A3':
            conc = '0.5, 1.0, 5.0, 10, 20, 50'
        else:
            conc = {'A1': '10', 'A2': '5.0', 'A4': '3.0',
                    'B1': '10', 'B2': '30'}[code]
        rows.append([code, '', conc])
    rb.caption('表1  共轭分子的结构式与浓度')
    t = rb.table(['编号', '结构式', 'c / (μmol·L⁻¹)'], rows,
                 widths_cm=[1.8, 4.6, 4.2], keep_together=True)
    for i, code in enumerate(('A1', 'A2', 'A3', 'A4', 'B1', 'B2')):
        cell = t.cell(i + 1, 1)
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.first_line_indent = Cm(0)
        pf.left_indent = Cm(0)
        pf.space_before = 0
        pf.space_after = 0
        png = os.path.join(ASSETS, '结构%s.png' % code)
        if os.path.exists(png):
            run = p.add_run()
            run.add_picture(png, width=Cm(3.8))


# ---------------------------------------------------------------- 3.1 标定
def _sec_calibration(rb, c1, c2, c3, pngs):
    rb.heading('3.1 光谱仪的标定', 2)
    rb.para('氘灯在 190~400 nm 有连续光谱，同时辐射出 238.30、485.82、581.39、'
            '656.06 nm 的特征谱线。把扫描得到的光源谱图中各特征峰对应的 pixel 值与'
            '标准波长作线性拟合，即可得到 pixel 与波长的换算关系。由于每次移动 CCD '
            '或被测量的波长范围改变后光路几何关系都会略有变化，本实验共做了三次标定：'
            '第一周的长波范围、第二周重新进行的长波范围，以及为测量短波长分子而移动'
            'CCD 后的短波范围。')

    for idx, (title, cal, png, note) in enumerate((
            ('3.1.1 长波范围（第一周）', c1, pngs['d1_long'],
             '本实验中 A4 的测量使用该标定结果。'),
            ('3.1.2 长波范围（第二周）', c2, pngs['d2_long'],
             '本实验中 A3 的浓度系列、A3 的双光源对比以及 A2 使用该标定结果。'),
            ('3.1.3 短波范围（第二周）', c3, pngs['d2_short'],
             '本实验中 A1、B1、B2 使用该标定结果。')), 1):
        rb.heading(title, 3)
        if idx == 1:
            rb.para('第一周标定所用的 CCD 位置在实验结束后被移动过，第二周重新测量时'
                    '光路状态已与第一周不同，因此重新扫描了一次光源谱图并重新标定。')
        if idx == 3:
            rb.para('为测量吸收峰位于 250~460 nm 的短波长分子，需要把 CCD 向紫外方向'
                    '移动，其余部分与长波范围完全相同，移动后重新标定。')
        rb.para('标定结果如图%d所示，其中左图为光源谱图及三个特征峰的位置，'
                '右图为 pixel–波长的线性拟合结果。' % (idx + 1))
        rb.figure(png, caption='图%d  %s的特征峰及线性拟合结果' % (idx + 1, title[6:]),
                  width_cm=15.0)
        rb.para(['直线的拟合结果为：'], keep_next=True)
        rb.equation(r'\lambda=(%s\pm%s)\times \mathrm{pixel}+(%s\pm%s)'
                    % (k(cal['a'], 5), k(cal['sigma_a'], 5),
                       k(cal['b'], 1), k(cal['sigma_b'], 1)))
        rb.para([
            '线性相关系数 ', ('t', 'R^{2}', ITALIC), ' = %s，线性良好。' % k(cal['r2'], 5),
            '由原始数据的 pixel 范围 1~3648 换算得波长范围约 %d~%d nm，'
            % (round(cal['lam_lo']), round(cal['lam_hi'])),
            note,
        ])

    rb.para('得到 pixel–波长的换算关系后，待测分子的吸光度由朗伯–比尔定律换算：',
            keep_next=True)
    rb.equation(r'A=\lg\frac{I_{0}}{I}')
    rb.para([
        '其中 ', ('t', 'I_{0}', ITALIC), ' 为同光源条件下乙醇空白的信号强度，',
        ('t', 'I', ITALIC), ' 为待测样品的信号强度。之后对 ',
        ('t', 'A', ITALIC), '–', ('t', 'λ', ITALIC),
        ' 曲线作平滑与基线校正，再用 Voigt 线形对吸收带作分峰拟合，'
        '取拟合总曲线的极大值作为最大吸收波长 ',
        ('t', 'λ_{max}', ITALIC), ' 与相应的吸光度 ',
        ('t', 'A', ITALIC), '。',
    ])
    rb.para([
        '分峰采用 Voigt 线形。Voigt 线形是高斯线形与洛伦兹线形的卷积，可以同时'
        '描述仪器展宽（高斯）与自然/寿命展宽（洛伦兹），比单一的高斯或洛伦兹线形'
        '更贴合实际吸收带；它由峰位 ', ('t', 'λ_{0}', ITALIC), '、峰高 ',
        ('t', 'A_{0}', ITALIC), '、高斯宽度 ', ('t', 'σ', ITALIC), ' 与洛伦兹宽度 ',
        ('t', 'γ', ITALIC), ' 四个参数确定，半高全宽 ',
        ('t', 'Γ', ITALIC), ' 可由 ', ('t', 'σ', ITALIC), ' 与 ', ('t', 'γ', ITALIC),
        ' 算出。',
    ])
    rb.para([
        '拟合时把整个吸收带写成若干个 Voigt 组元与一条低阶基线之和，',
        'A(λ) = Σ ', ('t', 'V_{i}', ITALIC), '(λ) + ', ('t', 'a', ITALIC),
        ' + ', ('t', 'bλ', ITALIC), '，用非线性最小二乘同时定出各分峰的位置、'
        '峰高、宽度以及基线。分峰个数取 1~2 个：先拟合一个组元，若残差仍明显'
        '（', ('t', 'R^{2}', ITALIC), ' 偏低）且第二个组元与主峰有足够间隔，'
        '再增加一个组元。各条谱的分峰结果与实测曲线一同画出（图9、图10 中的虚线），'
        '3.4 节给出一个分峰的实例。',
    ])


# ---------------------------------------------------------------- 3.2 光源
def _sec_source(rb, analysis, png):
    rb.heading('3.2 光源对吸收光谱的影响', 2)
    rb.para('长波长分子的吸收峰位于 550~800 nm，落入可见区，氘灯在该波段的辐射强度'
            '与稳定性都不如卤钨灯；但氘灯在 656.06 nm 处有一条很强的特征谱线，'
            '若同时打开两灯，这条谱线会叠加在吸收光谱上。为判断长波长分子应当用'
            '哪一种光源，以浓度为 5.0 μmol·L⁻¹ 的 A3 为例，分别在“卤钨灯”和'
            '“卤钨灯 + 氘灯”两种光源条件下测量吸收光谱，结果如图5所示。')
    rb.figure(png, caption='图5  A3 分子在不同光源下的吸收光谱', width_cm=15.0)
    rb.para([
        '由图可见，两种光源下吸收峰的位置基本一致，峰形也相近；但“卤钨灯 + 氘灯”'
        '条件下的谱图在 656 nm 附近出现了一个尖锐的峰，且该处附近吸光度被明显压低。'
        '这正是氘灯 656.06 nm 特征谱线的影响：一方面它作为额外的入射光直接抬高了'
        '检测器读数，另一方面在吸收峰中心处样品几乎吸光了设定波长的光，'
        '到达检测器的光强主要由杂散光构成，使测得的吸光度偏低（即“压顶”效应），'
        '表现为峰顶被削平、峰形畸变。'
    ])
    rb.para('因此，对于吸收峰位于 550 nm 以上的长波长分子，仅使用卤钨灯测量即可，'
            '既保证了足够的信号强度，又避免了氘灯特征谱线的干扰。'
            '对于吸收峰在 400 nm 以下或靠近 400 nm 的短波长分子，卤钨灯在该波段的'
            '辐射很弱、信噪比差，必须使用氘灯。各分子实际选用的光源如表2所示。')
    rows = []
    for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
        it = _sample_of(analysis, code)
        rows.append([code, it['source'] if it else '—'])
    rb.caption('表2  本实验各待测分子选用的光源')
    rb.table(['编号', '光源'], rows, widths_cm=[2.2, 3.2], keep_together=True)


def _sample_of(analysis, code):
    key = (analysis.cfg.get('molecule_default') or {}).get(code)
    return analysis.samples.get(key)


# ---------------------------------------------------------------- 3.3 浓度
def _sec_concentration(rb, analysis, fit, conc_items, conc_png, beer_png):
    rb.heading('3.3 浓度对吸收光谱的影响', 2)
    rb.para('为了考察浓度对吸收光谱的影响，测量了浓度为 0.5、1.0、5.0、10、20 和 '
            '50 μmol·L⁻¹ 的 A3 乙醇溶液的吸收光谱，结果如图6所示。图6 只做了平滑处理，'
            '并未扣除基线，用于定性比较。')
    rb.figure(conc_png, caption='图6  A3 分子不同浓度下的吸收光谱', width_cm=15.0)
    rb.para('由图可见，浓度很低（0.5、1.0 μmol·L⁻¹）时信号很弱、噪声较大，不适合'
            '定量测量；随着浓度增加，吸光度增大，但高浓度下谱线明显展宽，峰顶的噪声'
            '也急剧增大，20 与 50 μmol·L⁻¹ 的吸光度甚至趋于一个平台（约 0.5~0.6），'
            '最大吸收波长也发生明显蓝移。')
    rb.para('这一饱和现象说明检测器接收到了相当一部分“不经过样品吸收”的杂散光。'
            '当样品在吸收峰处的透射光弱到与杂散光本底相当时，继续增大浓度不会再使'
            '测得的吸光度增大，即出现“压顶”；杂散光的波长分布不均匀时，'
            '峰顶不同波长处被抬高的程度不同，表观最大吸收波长也会随之偏移。'
            '按 50 μmol·L⁻¹ 处的平台估计，杂散光本底约为入射光强的 20%。'
            '需要说明的是，这种杂散光在 10 μmol·L⁻¹ 以上就不能再用简单的比例扣除来'
            '修正（扣除结果对很小的测量误差极其敏感），因此本报告全部使用实测吸光度，'
            '只对 0.5~10 μmol·L⁻¹ 的线性区作拟合，所得 ε 应视为下限。')
    rows = []
    for it in conc_items:
        rows.append(['%g' % it['conc'], '%.1f' % it['peak_obs']['lam'],
                     '%.4f' % it['peak_obs']['A']])
    rb.caption('表3  不同浓度下 A3 吸收峰参数（Voigt 分峰拟合）')
    rb.table(['c / (μmol·L⁻¹)', 'λ_{max} / nm', 'A'], rows,
             widths_cm=[3.2, 3.0, 3.0], keep_together=True)

    if fit and beer_png:
        rb.para([
            '由表3可知，20 与 50 μmol·L⁻¹ 两点已进入饱和区，'
            '吸光度不再随浓度线性增大，因此只用 0.5~10 μmol·L⁻¹ 的四个点作线性拟合。'
            '图7把全部六个浓度点都画了出来：实心方块是参与拟合的线性区点，'
            '空心圆是未参与拟合的饱和区点。实线为线性拟合，虚线是它的延长线；'
            '可以看到 20 与 50 μmol·L⁻¹ 两点明显低于延长线，即偏离朗伯–比尔定律。',
        ], keep_next=True)
        rb.figure(beer_png, caption='图7  A3 分子 A–c 关系（全部浓度点，仅线性区拟合）',
                  width_cm=13.5)
        rb.para('拟合结果为：', keep_next=True)
        rb.equation(r'A=(%s\pm%s)\times c+(%s\pm%s)'
                    % (k(fit['k'], 4), k(fit['sigma_k'], 4),
                       k(fit['b'], 3), k(fit['sigma_b'], 3)))
        rb.para([
            '其中 ', ('t', 'c', ITALIC), ' 的单位为 μmol·L⁻¹，线性相关系数 ',
            ('t', 'R^{2}', ITALIC), ' = %s。' % k(fit['r2'], 4),
        ])
        rb.para([
            '朗伯–比尔定律要求吸光度与浓度成正比，即 ',
            ('t', 'A', ITALIC), ' = ', ('t', 'εcb', ITALIC),
            '。本实验比色皿的光程为 ',
            ('t', 'b', ITALIC), ' = 1.00 cm，于是由拟合斜率可求得摩尔消光系数：',
        ], keep_next=True)
        _eexp = int(np.floor(np.log10(abs(fit['eps'])))) if fit['eps'] else 5
        rb.equation(r'\varepsilon=\frac{%.4f}{1.00\times10^{-6}}'
                    r'=%.2f\times10^{%d}\ \mathrm{L}\cdot\mathrm{mol}^{-1}'
                    r'\cdot\mathrm{cm}^{-1}'
                    % (fit['k'], fit['eps'] / 10.0 ** _eexp, _eexp))
        rb.para([
            '即 ', ('t', 'ε', ITALIC), ' = %s L·mol⁻¹·cm⁻¹'
            % sci_pm(fit['eps'], _eps_sigma(fit)),
            '。在线性区内，实测吸光度与浓度符合得很好，但高浓度下的系统性偏低说明'
            '自建光谱仪的杂散光限制了可测吸光度的上限。',
        ])


# ---------------------------------------------------------------- 3.4 其余分子
def _sec_molecules(rb, analysis, mol, long_png, short_png, voigt_png=None):
    rb.heading('3.4 其余分子的吸收光谱测定结果', 2)
    if voigt_png:
        rb.para(['以 5.0 μmol·L⁻¹ 的 A3 为例说明分峰的具体做法。按 3.1 节的方法'
                 '得到 ', ('t', 'A', ITALIC), '–', ('t', 'λ', ITALIC),
                 ' 曲线后，用 1~2 个 Voigt 组元加一条低阶基线拟合整个吸收带，'
                 '结果如图8所示。'])
        rb.figure(voigt_png, caption='图8  A3 吸收光谱的 Voigt 分峰结果（5.0 μmol·L⁻¹）',
                  width_cm=13.0)
        a3_key = (getattr(analysis, 'picks_mol', {}) or {}).get('A3') or 'A3c5b'
        it3 = analysis.samples.get(a3_key)
        vf = it3.get('voigt') if it3 else None
        if vf:
            peaks = vf['peaks']
            comp_txt = '；'.join(
                'λ = %.1f nm（峰高 %.3f，半高全宽 %.0f nm）'
                % (p['center'], p['amp'], p['fwhm']) for p in peaks)
            lead = ('拟合得到 %d 个组元：%s。各分峰按峰高从大到小排列，'
                    '居中的主组元对应 0-0 跃迁，短波长一侧的组元对应振动伴峰。'
                    '总拟合曲线的极大值位于 ' % (vf['n'], comp_txt))
            rb.para([
                lead,
                ('t', 'λ_{max}', ITALIC), ' = %.1f nm' % vf['lam_max'],
                '、', ('t', 'A', ITALIC), ' = %.4f' % vf['A_max'],
                '，与实测谱的峰顶一致，拟合优度 ',
                ('t', 'R^{2}', ITALIC), ' = %.4f。' % vf['r2'],
            ])
    rb.para([
        '其余分子的吸收光谱按同样的方法处理：A2、A3、A4 用卤钨灯，'
        'A1、B1、B2 用氘灯；波长–pixel 的换算关系按 3.1 节所选用的标定结果处理。'
        '对每条吸收光谱作平滑、基线校正和 Voigt 分峰，取总拟合曲线的极大值'
        '作为 ', ('t', 'λ_{max}', ITALIC), ' 与 ', ('t', 'A', ITALIC),
        '，结果按长波长分子与短波长分子两组分别绘于图9和图10'
        '（图中实线为实测曲线，同色虚线为 Voigt 总拟合曲线）。',
    ])
    rb.figure(long_png, caption='图9  长波长分子（A2、A3、A4）的吸收光谱', width_cm=15.0)
    rb.figure(short_png, caption='图10  短波长分子（A1、B1、B2）的吸收光谱',
              width_cm=15.0)
    rb.para('各分子吸收光谱的信息及定量分析结果（最大吸收波长、吸光度、摩尔消光系数）'
            '整理于表4。')
    rows = []
    for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
        r = mol.get(code)
        if not r:
            continue
        rows.append([code, r['source'], '%g' % r['conc'], '%.1f' % r['lam'],
                     '%.4f' % r['A'], '%.2f' % (r['eps'] / 1e5)])
    rb.caption('表4  各分子的吸收光谱信息汇总')
    rb.table(['编号', '光源', 'c / (μmol·L⁻¹)', 'λ_{max} / nm', 'A',
              'ε / (10^{5} L·mol⁻¹·cm⁻¹)'], rows,
             widths_cm=[1.6, 2.2, 2.9, 2.6, 2.2, 4.0], keep_together=True)
    rb.para(['注：', ('t', 'λ_{max}', ITALIC), ' 与 ', ('t', 'A', ITALIC),
             ' 均为 Voigt 分峰拟合总曲线的极大值，', ('t', 'A', ITALIC),
             ' 为实测值；A4 于第一周测定，其余分子于第二周测定。'])


# ---------------------------------------------------------------- 3.5 Gaussian
def _sec_gaussian(rb, cfg, mol):
    rb.heading('3.5 Gaussian 理论计算', 2)
    rb.para('本部分使用 Gaussian 16（Rev. C.01）对上述 6 种共轭分子作量子化学计算：'
            '先用密度泛函理论（DFT，泛函 PBE0、基组 def2-TZVP）优化基态几何结构，'
            '再用含时密度泛函理论（TD-DFT，PBE0/def2-TZVP，配合 IEFPCM 乙醇溶剂模型）'
            '计算前 10 个激发态的激发能与振子强度，取振子强度最大者对应的波长作为'
            '理论最大吸收波长，与实验值比较。几何优化、振动分析与 TD-DFT 计算均提交到'
            '北京大学高性能计算平台（教学二号）完成。')

    g = (cfg or {}).get('gcalc') or {}
    results = g.get('molecules') or []
    if not results:
        rb.para('相关计算正在进行中，本部分结果暂待补充。')
        return

    def _base(name):
        n = str(name)
        for suf in ('_td', '_gs', '_fc', '_freq', '_opt'):
            if n.lower().endswith(suf):
                return n[:-len(suf)]
        return n

    mol_map = {k: v for k, v in (mol or {}).items() if isinstance(v, dict)}
    rows = []
    for m in results:
        name = _base(m.get('name'))
        b = m.get('bright') or {}
        s1 = m.get('s1') or {}
        lam_calc = b.get('wavelength_nm')
        lam_exp = (mol_map.get(name) or {}).get('lam')
        lam_c = ('%.1f' % lam_calc) if lam_calc else '—'
        lam_e = ('%.1f' % lam_exp) if lam_exp else '—'
        if lam_calc and lam_exp:
            d = '%.1f' % (lam_calc - lam_exp)
        else:
            d = '—'
        rows.append((name, lam_c,
                     ('%.3f' % b.get('f')) if b.get('f') is not None else '—',
                     ('%.1f' % s1.get('wavelength_nm')) if s1.get('wavelength_nm') else '—',
                     lam_e, d))

    rb.table(['分子', '计算 λ_{max} / nm', '振子强度 f', 'S_{1} / nm',
              '实验 λ_{max} / nm', 'Δλ / nm'], rows,
             widths_cm=[1.6, 2.9, 2.4, 2.0, 2.9, 2.0], keep_together=True)

    rb.para('表中「计算 λ_{max}」取振子强度最大的允许跃迁（S_{n}），'
            '「S_{1}」为第一激发态；对高对称分子（如苯），S_{1} 可能因对称性禁阻而'
            '振子强度为零，此时应以最大 f 的跃迁与实验比较。'
            'Δλ = 计算值 − 实验值，正值表示计算偏红。')
    rb.para('PBE0/def2-TZVP 级别的 TD-DFT 通常把共轭染料的 π→π* 吸收峰计算得'
            '与实验值相差约 10~40 nm（多为红移），差异主要来自泛函对电荷转移'
            '激发的描述、溶剂模型的近似以及分子构象分布的忽略。')


# ---------------------------------------------------------------- 4.1 定性
def _sec_qualitative(rb, mol):
    rb.heading('4.1 各分子吸收光谱结果讨论', 2)
    rb.heading('4.1.1 定性分析', 3)
    a1, a2, a3, a4 = (mol.get(c, {}).get('lam', float('nan')) for c in ('A1', 'A2', 'A3', 'A4'))
    e = {c: mol.get(c, {}).get('eps', float('nan')) for c in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2')}
    rb.para([
        '对于吸收波长，最直接的趋势是随着共轭体系增大，HOMO–LUMO 能隙减小，'
        '吸收峰红移。表4中 A1~A4 的最大吸收波长依次为 ',
        '%.1f、%.1f、%.1f 和 %.1f nm' % (a1, a2, a3, a4),
        '，每增加一个 C–C=C 共轭单元，吸收峰约红移 70~110 nm，与共轭链增长使 '
        'π 电子离域范围扩大的预期一致。B1（β-胡萝卜素）含有 11 个共轭双键，'
        '其最大吸收波长 %.1f nm 位于蓝紫区，同样符合这一趋势；'
        'B2（2,6-二甲基-2,4,6-辛三烯）只有 3 个共轭双键，最大吸收波长仅 %.1f nm。'
        % (mol.get('B1', {}).get('lam', float('nan')),
           mol.get('B2', {}).get('lam', float('nan'))),
    ])
    rb.para([
        '对于摩尔消光系数，理论上它正比于跃迁偶极矩的平方，而跃迁偶极矩随离域范围'
        '增大而增大，因此共轭体系越大，ε 应当越大。表4中 A1~A4 的 ε 依次为 ',
        '%.2f、%.2f、%.2f 和 %.2f' % (e['A1'] / 1e5, e['A2'] / 1e5, e['A3'] / 1e5, e['A4'] / 1e5),
        '×10⁵ L·mol⁻¹·cm⁻¹，A1、A2、A4 随共轭程度增加而增大；B1 与 B2 的 ε 分别为 ',
        '%.2f 与 %.2f' % (e['B1'] / 1e5, e['B2'] / 1e5),
        '×10⁵ L·mol⁻¹·cm⁻¹，也符合这一趋势；A3 的 ε 明显偏低，原因见 4.1.3 节。'
        '此外 A4 的吸收峰位于 770 nm 附近、已接近 CCD 接收范围的边缘，'
        '信噪比下降，其 ε 的误差也偏大。',
    ])


# ---------------------------------------------------------------- 4.1.2 势箱
def _sec_box(rb, analysis, mol):
    rb.heading('4.1.2 定量分析——一维势箱模型的验证', 3)
    rb.para('一维势箱模型把共轭体系中的 π 电子看作长度为 L 的势阱中的粒子，'
            '能量只能取分立值：', keep_next=True)
    rb.equation(r'E_{n}=\frac{n^{2}h^{2}}{8mL^{2}}')
    rb.para([
        '式中 ', ('t', 'n', ITALIC), ' 为量子数，', ('t', 'm', ITALIC),
        ' 为电子质量，', ('t', 'L', ITALIC), ' 为势阱长度，', ('t', 'h', ITALIC),
        ' 为普朗克常数。对于含 ', ('t', 'N', ITALIC), ' 个 π 电子的共轭体系，'
        '前 ', ('t', 'N', ITALIC), '/2 个能级被占据，最高占据能级的量子数为 ',
        ('t', 'n', ITALIC), ' = ', ('t', 'N', ITALIC), '/2，最低未占能级为 ',
        ('t', 'n', ITALIC), ' + 1，故跃迁能级差与吸收峰波长为：',
    ], keep_next=True)
    rb.equation(r'\Delta E=\frac{(n+1)^{2}h^{2}}{8m_{e}L^{2}}-'
                r'\frac{n^{2}h^{2}}{8m_{e}L^{2}}=\frac{(2n+1)h^{2}}{8m_{e}L^{2}}')
    rb.equation(r'\lambda=\frac{hc}{\Delta E}=\frac{8m_{e}L^{2}c}{(2n+1)h}'
                r'=\frac{3297.8L^{2}}{2n+1}')
    rb.para('其中 λ 与 L 的单位均取 nm，常数 3297.8 nm 由已知物理常数算得。'
            '关键在于如何估计箱长 L。Atkins 给出的办法是假设每个 C–C 键（无论单双键）'
            '的平均键长为 0.140 nm，但由此得到的结果相当粗糙，只能给出数量级正确的估计；'
            '对于含苯环、N 原子和 S 原子的 A 组分子，箱长更难直接估计。'
            '本报告不采用这种估计方法，而是采用“拟合经验箱长”的思路。')

    rb.heading('4.1.2.1 A 组分子的分析', 4)
    a1 = mol.get('A1', {}).get('lam', float('nan'))
    a4 = mol.get('A4', {}).get('lam', float('nan'))
    rb.para('Ai（i = 1~4）分子可以看成 i 个 C–C=C 基团与 2 个等价的苯并噻唑芳香基团'
            '组成（两者等价是因为 N 上的孤对电子可以参与共轭）。假设一个 C–C=C 基团'
            '对箱长的贡献为 x nm、贡献 2 个 π 电子，一个芳香基团对箱长的贡献为 y nm、'
            '贡献 a 个 π 电子（a 暂时不能确定，因为苯环与 S 原子是否参与共轭、'
            '参与程度多大并不清楚），则如表5所示。')
    rb.caption('表5  A 类分子一维势箱模型的假设')
    rb.table(['基团', '对箱长的贡献 / nm', '对电子的贡献'],
             [['C–C=C', ('m', 'x'), '2'],
              ['芳香基团', ('m', 'y'), ('m', 'a')]],
             widths_cm=[4.0, 4.6, 4.0], keep_together=True)
    rb.para([
        '于是对于 Ai 分子，箱长 ', ('t', 'L', ITALIC), ' = ', ('t', 'ix', ITALIC),
        ' + ', ('t', '2y', ITALIC), '，π 电子数 ', ('t', 'N', ITALIC), ' = ',
        ('t', '2i', ITALIC), ' + ', ('t', '2a', ITALIC), '，满足：',
    ], keep_next=True)
    rb.equation(r'\lambda_{i}=3297.8\times\frac{(ix+2y)^{2}}{2i+2a+1}')
    rb.para('这样一来有四个方程、三个未知数。为避免把 a 解成没有物理意义的小数，'
            '考虑到加上苯环与 S 原子后芳香基团最多提供 10 个 π 电子，a 只能取 '
            '0、2、4、6、8、10。下面分别代入这六个值，用 A1 与 A4 的方程解出 x 和 y，'
            '再用得到的结果预测 A2 与 A3 的波长，结果列于表6。')
    rows = []
    for r in analysis.box['a_rows']:
        rows.append(['%d' % r['a'], '%.4f' % r['x'], '%.4f' % r['y'],
                     '%.1f' % r['lam2'], '%.1f' % r['lam3']])
    rows.append(['实验值', '', '',
                 '%.1f' % mol.get('A2', {}).get('lam', float('nan')),
                 '%.1f' % mol.get('A3', {}).get('lam', float('nan'))])
    rb.caption('表6  A 类分子一维势箱模型预测结果')
    rb.table(['a', 'x / nm', 'y / nm', 'λ_{2} 预测值 / nm', 'λ_{3} 预测值 / nm'],
             rows, widths_cm=[1.8, 2.4, 2.4, 3.2, 3.2], keep_together=True)
    rb.para('表6可以提供不少信息。首先 y 随 a 的变化符合预期：参与共轭的电子数越多，'
            '芳香基团对箱长的贡献越大。其次，对 λ₂ 与 λ₃ 的预测在 540~655 nm 之间，'
            '与实验值（562.6 与 659.3 nm）相当接近，说明一维势箱模型在结构上有一定的'
            '合理性。需注意这里说的“结构上”的合理性是有限的：一维势箱要求体系是'
            '一维线性的，而苯环的存在显然打破了这一要求。通过拟合经验参数可以部分规避'
            '这一影响，即箱长不再具有表观的物理意义，而是通过实验拟合出芳香基团的'
            '“有效箱长”，这样基团是否一维线性就变得不那么重要了；'
            '波长与箱长平方成正比、与电子数成反比这一结构关系，仍然是有意义的。')
    rb.para('从表6看，a = 4 和 a = 6 时对 λ₂、λ₃ 的预测与实验值最为接近，a = 0 与 '
            'a = 10 的偏差最大。这说明 N 原子一定参与共轭，S 原子大概率不参与共轭；'
            '苯环虽然参与共轭，但共轭程度有限，不会提供全部 6 个 π 电子。'
            '取 a = %d 时得到的 x = %.4f nm 与 Atkins 给出的 C–C 平均键长 0.140 nm '
            '处于同一量级，也支持这一图像。'
            % (analysis.box.get('a_used', 6), analysis.box.get('x_used', float('nan'))))

    rb.heading('4.1.2.2 B 组分子的分析', 4)
    x_used = analysis.box.get('x_used', float('nan'))
    rb.para([
        '下面尝试把 A 组拟合得到的经验参数外推到 B 组分子（这一外推实际上风险很大）。'
        '取 a = %d 时的结果，即每个 C–C=C 基团贡献 x = %.4f nm，'
        'B 组分子的共轭单元数不能精确对应整数个 C–C=C 基团，故给出范围，'
        '结果列于表7。' % (analysis.box.get('a_used', 6), x_used),
    ])
    rows = []
    for r in analysis.box['b_rows']:
        units = r['units']
        rows.append([r['code'], '%d~%d' % units,
                     '%.2f~%.2f' % (r['L_lo'], r['L_hi']), '%d' % r['n'],
                     '%.0f~%.0f' % (r['lam_lo'], r['lam_hi']),
                     '%.1f' % r['exp']])
    rb.caption('表7  B 类分子一维势箱模型预测结果')
    rb.table(['编号', 'C–C=C 数', '箱长 L / nm', 'N', 'λ 预测值 / nm', 'λ 实验值 / nm'],
             rows, widths_cm=[1.8, 2.6, 2.8, 1.4, 3.4, 3.0], keep_together=True)
    rb.para('由结果可见，对于小分子 B2，预测值（140~315 nm）与实验值（294.3 nm）比较'
            '接近；但对于长共轭体系 B1，预测值为 1066~1290 nm，与实验值 450.7 nm '
            '相差甚远。这一失败的原因是长共轭体系严重偏离一维线性：β-胡萝卜素'
            '的共轭链并非直链，而是存在 s-顺/s-反构象与环的限制，用一维势箱描述'
            '其离域范围已经超出了模型的适用范围。')
    rb.para('综上，可以对一维势箱模型作一个完整的评述：在短共轭体系（A1~A4、B2）中，'
            '模型呈现“定性合理、半定量可用”的特点，其用法是把 C–C 平均键长取为'
            '0.140 nm 左右、对非线性基团用实验拟合的经验箱长替代；对于长共轭体系（B1），'
            '模型已经超出适用范围，顶多具有数量级的估计意义。此时不应勉强去凑参数，'
            '而应承认模型的粗糙性、转而寻找更合理的描述（如自由电子模型、'
            'TD-DFT 计算等）。')




# ---------------------------------------------------------------- 4.1.3 文献对比
def _sec_eps_literature(rb, analysis, mol, fit):
    rb.heading('4.1.3 A3 摩尔消光系数与文献值的比较', 3)
    a3 = mol.get('A3', {})
    eps = fit['eps'] if fit and np.isfinite(fit.get('eps', np.nan)) else float('nan')
    sig = _eps_sigma(fit) if fit else 0.0
    lit = 2.00e5
    rb.para([
        'A3（3,3′-二乙基硫二羰花青碘，CAS 514-73-8，商品名 DiSC2(5)/DTDCI）'
        '是常用的花青染料。厂家给出的甲醇溶液数据为 ',
        ('t', 'λ_{max}', ITALIC), ' ≈ 662 nm、',
        ('t', 'ε', ITALIC), ' = 2.00 × 10⁵ L·mol⁻¹·cm⁻¹^{[5]}；'
        '化学手册中 ', ('t', 'λ_{max}', ITALIC), ' 记为 655 nm^{[6]}。本实验在乙醇中测得 ',
        ('t', 'λ_{max}', ITALIC), ' = %.1f nm、' % a3.get('lam', float('nan')),
        ('t', 'ε', ITALIC), ' = %s L·mol⁻¹·cm⁻¹。'
        % sci_pm(eps, sig),
        '峰位与文献值一致（相差不到 7 nm），但 ε 只有文献值的 %.0f%%，'
        '差别远超出通常的测量误差。' % (eps / lit * 100),
    ])
    rb.caption('表8  A3 摩尔消光系数与文献值的比较')
    rb.table(['来源', '溶剂', 'λ_{max} / nm', 'ε / (10^{5} L·mol⁻¹·cm⁻¹)', '相对文献'],
             [['文献值^{[5]}', '甲醇', '662', '2.00', '1.00'],
              ['本次测量', '乙醇', '%.1f' % a3.get('lam', float('nan')),
               '%.2f' % (eps / 1e5), '%.2f' % (eps / lit)]],
             widths_cm=[3.6, 2.0, 2.8, 4.4, 2.4], keep_together=True)

    rb.para('下面对 ε 的误差来源逐项分析。')
    rb.para([
        '（1）统计误差。线性拟合给出斜率的相对标准误差 ',
        ('t', 'σ_{k}', ITALIC), '/', ('t', 'k', ITALIC), ' = %.1f%%'
        % (abs(fit['sigma_k']) / abs(fit['k']) * 100 if fit else 0),
        '，即 ε 的统计不确定度约 ±%.1f×10⁴。它只占差距的很小一部分。'
        % (sig / 1e4),
    ])
    rb.para('（2）杂散光与漏光（主要系统误差）。自建光谱仪没有完全遮光，'
            '透射光中混有不经过样品吸收的杂散光，证据是：吸光度随浓度的变化在 '
            '10 μmol·L⁻¹ 以上明显偏离线性、趋于平台（表3、图7）；由 50 μmol·L⁻¹ 的'
            '实测吸光度 0.71 反推，仅这一点的平台就意味着杂散光至少占入射光强的 '
            '10^(−0.71) ≈ 19%。杂散光把测得的 A 系统性压低，而且浓度越高压低越多，'
            '因此本实验的 ε 只能算下限。')
    rb.para('（3）杂散光模型的局限。若以文献值 2.00×10⁵ 为真值，可以用带杂散光的'
            '比尔定律反推各浓度点所需的杂散光比例：', keep_next=True)
    rb.equation(r'A_{\mathrm{meas}}=-\lg[f+(1-f)\cdot10^{-\varepsilon bc}]')
    rb.para('式中 f 为杂散光占入射光强的比例。把 6 个浓度点逐一代入，得到 f 在 '
            '0.19~0.52 之间分散——单一的杂散光比例无法同时解释整组数据。'
            '这说明除杂散光外还有其他系统误差（见下），也说明不能用一个固定的 f '
            '逐点扣除。')
    rb.para('（4）光源漂移与空白时间差。第二天同一天内各条谱的整体光强有 10%~20% '
            '的漂移（见 4.2 节），而空白与样品并非同时测量。若两者光强相差 10%，'
            'A 会偏移约 lg 1.1 ≈ 0.04；对 A ≈ 0.25 的 5 μmol·L⁻¹ 点就是约 15% 的误差，'
            '也是低浓度点误差的主要来源。')
    rb.para('（5）基线取点与 Voigt 分峰。基线锚点取在吸收带两侧约 80 nm 处，锚点'
            '吸光度的不确定度约 ±0.005，传递到峰高约 ±0.005~0.01（对 A ≈ 0.25 的点'
            '为 2%~4%）；Voigt 分峰的拟合优度 R² ≈ 0.999，峰高的不确定度约 1%~3%。')
    rb.para('（6）浓度与光程。浓度由逐级稀释配制，移液器误差按每级 1%~2% 累积，'
            '总误差约 3%~5%；比色皿标称光程 1.00 cm，实际偏差约 ±1%。两者都按比例'
            '影响 ε，而且浓度标称值没有独立手段复核——若储备液浓度或某一级稀释存在'
            '偏差，ε 会整体平移。')
    rb.para('（7）溶剂与波长。文献值在甲醇中测得，本实验用乙醇，花青染料的 ε 随溶剂'
            '可有 5%~10% 的变化；波长标定的 ±1.5 nm 落在吸收峰顶部（dA/dλ ≈ 0），'
            '对峰高的影响小于 1%。')
    rb.para([
        '把 (1)、(4)~(7) 的随机与可估误差按方和根合成，约为 ±20%；'
        '而实测 ε 与文献值相差约 4.6 倍（低 78%），远超这一范围。'
        '因此可以判断：ε 偏低主要是系统性的——杂散光压缩吸光度是已经证实的一项，'
        '浓度标称值的可靠性则无法事后排除。两者都会使实测 ε 偏低，故本报告把它'
        '作为下限处理；若要做准确的 ε 测量，需要更好的遮光与狭缝控制、'
        '空白与样品交替测量，并对浓度作独立标定。',
    ])

# ---------------------------------------------------------------- 4.2 操作
def _sec_operation(rb, analysis):
    rb.heading('4.2 实验操作对测量结果的影响及经验总结', 2)
    rb.para('积分时间与平均次数：它们直接决定信噪比。积分时间过短则信号弱、噪声大，'
            '过长则可能使检测器进入非线性区甚至饱和。判断谱图是否足够平滑不能只靠'
            '肉眼观察“看起来很顺”，而要看峰顶附近的随机起伏是否足够小。'
            '此外，空白与待测样品的积分时间、平均次数必须一致，否则两者的积分强度'
            '不可比。')
    rb.para('暗背景扣除：本实验只在最开始测量一次暗背景并一直沿用，但 CCD 暗电流'
            '会随温度和时间漂移，环境光也可能从缝隙进入，更稳妥的做法是每次测量前'
            '重新采集。本次各条谱的基线都有一定漂移，这是 A3 浓度系列偏差较大的'
            '原因之一。')
    rb.para('杂散光与遮光：本次自建光谱仪的杂散光比预期大得多（A3 吸收峰处约相当于'
            '入射光强的 20%），说明遮光不彻底、狭缝也偏宽：狭缝之后是开放光路，'
            '环境光会直接叠加到 CCD 上。改进方向是用遮光材料把狭缝至 CCD 的整段'
            '光路包严，并在信号足够的前提下尽量收窄狭缝与光阑。')
    rb.para('光源与预热：卤钨灯与氘灯都需要预热足够时间才能稳定。本实验中同一天内'
            '连续测量的谱图整体强度存在 10%~20% 的漂移，这与光源尚未完全稳定、'
            '以及光学元件受热后位置微小变化都有关。此外，切换光源（尤其是打开氘灯）'
            '后应重新等待稳定并重测空白。')
    rb.para('比色皿与样品：比色皿外壁的指纹、内壁的气泡都会显著改变透射光强，'
            '取样前后应用擦镜纸擦净外壁并检查有无气泡；高浓度样品容易在比色皿壁'
            '留下残留，应先用乙醇润洗。')
    rb.para('波长标定：CCD 的位置在两次实验之间被移动过，每次改变 CCD 位置后'
            '都必须重新标定；若拟合残差偏大，应检查是否取错了峰。')


# ---------------------------------------------------------------- 4.3 小结
def _sec_summary(rb, analysis, mol, fit):
    rb.heading('4.3 小结', 2)
    parts = ['本实验按照光学原理搭建了简易的紫外可见吸收光谱仪，'
             '用氘灯的特征谱线标定了 pixel–波长关系（三次标定的 R² 均在 0.9998 以上），'
             '并测量了 A、B 两类共 6 种共轭分子的紫外可见吸收光谱。']
    if fit and np.isfinite(fit.get('eps', np.nan)):
        parts.append('通过 A3 的浓度系列考察了浓度对吸收光谱的影响，'
                     '吸光度与浓度在 0.5~10 μmol·L⁻¹ 内符合朗伯–比尔定律（20、50 μmol·L⁻¹ '
                     '因杂散光饱和而偏离），求得摩尔消光系数 ε = %s L·mol⁻¹·cm⁻¹'
                     '（约为文献值 2.00×10⁵ 的 22%%，受杂散光等系统误差压缩，'
                     '为下限值）。'
                     % sci_pm(fit['eps'], _eps_sigma(fit)))
    lam_txt = '、'.join('%s %.1f nm' % (c, mol[c]['lam']) for c in ('A1', 'A2', 'A3', 'A4')
                       if c in mol)
    parts.append('测得的最大吸收波长为：%s；B1 为 %.1f nm，B2 为 %.1f nm。'
                 % (lam_txt, mol.get('B1', {}).get('lam', float('nan')),
                    mol.get('B2', {}).get('lam', float('nan'))))
    parts.append('最大吸收波长随共轭体系增大而红移，摩尔消光系数总体随共轭程度'
                 '增加而增大，均与理论预期一致。')
    parts.append('用一维势箱模型对 A 组分子作了定量验证：短共轭体系可以给出'
                 '半定量的结果，长共轭体系则明显失效；模型的意义更多在于'
                 '提供“波长正比于箱长平方、反比于电子数”这样的结构关系。')
    parts.append('最后，结合实验中的基线与杂散光问题，总结了遮光、预热、'
                 '空白测量与波长标定等操作要点。')
    rb.para(''.join(parts))
