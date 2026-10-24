# -*- coding: utf-8 -*-
"""生成《电解质溶液电导率的测定》实验报告 .docx。

结构参照同课程 2025 年的电导率报告（完整版口径）+ 课程 2026 模板的节名：

    封面
    摘要 / 关键词
    1 引言                          目的 / 原理 / 方法见图1（手写预习笔记）
    2 实验部分[1]
      2.1 仪器和试剂   2.2 实验内容（标定 / 去离子水 / 配液 表1 表2 / 测量）
    3 数据与结果
      3.1 原始数据的定性分析     3.1.1 基本实验数据  3.1.2 电导率-浓度（图2）
      3.2 强电解质的数据处理     3.2.1 表3~5  3.2.2 Kohlrausch 拟合（图3~5）
                                 3.2.3 极限摩尔电导率与文献对比（表6）
      3.3 弱电解质的数据处理     3.3.1 表7 表8（求平均法）  3.3.2 拟合直线法（图6 表9）
    4 讨论与结论
      4.1 强电解质极限摩尔电导率误差分析
      4.2 弱电解质两种 K° 求解方法比较
      4.3 小结
    参考文献

排版口径（skill §3.1）：只"报出一个数值"的句子一律普通文本（变量斜体、
单位正体、± 两侧留空格）；推导与代入计算才用公式对象。
⚠️ rb.para() 只接受一个 segments 参数（列表或字符串），多片段务必包一对方括号。
"""
from __future__ import annotations

import decimal
import os

import numpy as np

from . import conduct
from . import plotting
from .docxkit import ReportBuilder

ITALIC = {'italic': True}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_JPG = os.path.join(ASSETS, '引言图.jpg')

REPORT_TITLE = '电解质溶液电导率的测定'
INTRO_BLANK_LINES = 26

SIG_DIGITS = 2


# ---------------------------------------------------------------- 数值格式
def _place(u, n=SIG_DIGITS):
    return decimal.Decimal(repr(float(u))).adjusted() - n + 1


def _fix(x, exp):
    q = decimal.Decimal(1).scaleb(exp)
    return float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN))


def _fmt(x, exp):
    return '%.*f' % (max(0, -exp), x)


def pm(x, u, n=SIG_DIGITS):
    """「值 ± σ」，末位与 σ 对齐（JJF 1059 / GB/T 8170）。"""
    if u in (None, 0) or not np.isfinite(u):
        return sig_fig(x, 4)
    e = _place(u, n)
    return '%s ± %s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e))


def sig_fig(x, n=4):
    """保留 n 位有效数字（保留末尾的 0），如 0.0121 → '0.01210'。"""
    if x is None or not np.isfinite(x):
        return '—'
    if x == 0:
        return '0'
    d = decimal.Decimal(repr(abs(float(x))))
    exp = d.adjusted()
    q = decimal.Decimal(1).scaleb(exp - n + 1)
    v = d.quantize(q, rounding=decimal.ROUND_HALF_EVEN)
    s = '%.*f' % (max(0, n - 1 - exp), v)
    return ('-' + s) if x < 0 else s


def sci(x, nd=3, exp=None):
    """1.64×10⁻⁵ 形式（普通文本用，指数走真上标）。"""
    if x is None or not np.isfinite(x):
        return '—'
    if x == 0:
        return '0'
    if exp is None:
        exp = int(np.floor(np.log10(abs(x))))
    m = x / 10.0 ** exp
    return '%.*f×10^{%d}' % (nd, m, exp)


def sci_pm(x, u, exp=None):
    """(1.436 ± 0.026)×10⁻⁵ 形式。"""
    if exp is None:
        exp = int(np.floor(np.log10(abs(x))))
    s = 10.0 ** exp
    return '(%s)×10^{%d}' % (pm(x / s, u / s), exp)


def pct(x, n=SIG_DIGITS):
    """相对偏差，2 位有效数字，带 %。"""
    if not np.isfinite(x):
        return '—'
    e = _place(abs(x), n)
    return _fmt(_fix(x, e), e) + '%'


def _latex_sci(x, nd=3, exp=None):
    if x is None or not np.isfinite(x):
        return r'\mathrm{NaN}'
    if x == 0:
        return '0'
    if exp is None:
        exp = int(np.floor(np.log10(abs(x))))
    m = x / 10.0 ** exp
    return r'%.*f\times10^{%d}' % (nd, m, exp)


def _latex_num(x, nd):
    if not np.isfinite(x):
        return r'\mathrm{NaN}'
    return '%.*f' % (nd, float(x))


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    ctx = analysis.ctx
    fits = analysis.fits
    esa = analysis.esa or {}
    kmean = analysis.kmean
    kfit = analysis.kfit

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

    fig_kc = save(plotting.make_kappa_c_figure(analysis), 'fig2_kappa_c.png')
    fit_pngs = {}
    for key in ('NaNO3', 'NaAc', 'HNO3'):
        if key in fits:
            fit_pngs[key] = save(plotting.make_kohlrausch_figure(analysis, key),
                                 'fit_%s.png' % key)
    fig_kfit = None
    if kfit:
        fig_kfit = save(plotting.make_kfit_figure(analysis), 'fig6_kfit.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    f_na = fits['NaNO3']
    f_naac = fits['NaAc']
    f_hno3 = fits['HNO3']
    rb.para([
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验测量了不同浓度 NaNO₃、NaAc、HNO₃ 和 HAc 溶液的电导率。'
        '通过 Kohlrausch 拟合得强电解质的极限摩尔电导率：NaNO₃ ',
        ('t', '(%s) S·m⁻²·mol⁻¹' % pm(f_na['lam_inf'], f_na['sigma_inf']), {}),
        '、NaAc ',
        ('t', '(%s) S·m⁻²·mol⁻¹' % pm(f_naac['lam_inf'], f_naac['sigma_inf']), {}),
        '、HNO₃ ',
        ('t', '(%s) S·m⁻²·mol⁻¹' % pm(f_hno3['lam_inf'], f_hno3['sigma_inf']), {}),
        '。对于 HAc，由离子独立运动定律得极限摩尔电导率为 ',
        ('t', '(%s) S·m⁻²·mol⁻¹' % pm(esa['lam_inf'], esa['sigma']), {}),
        '，再分别通过求平均法和拟合直线法求得其标准电离平衡常数为 ',
        ('t', sci_pm(kmean['mean'], kmean['sigma']), {}),
        ' 和 ', ('t', sci_pm(kfit['K'], kfit['sigma_K']), {}),
        '，并对两种方法进行了比较。',
    ])
    rb.para([{'text': '关键词 ', 'bold': True},
             '电导率；极限摩尔电导率；Kohlrausch 定律；离子独立运动定律；标准电离平衡常数'])
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
    rb.para('100 mL 容量瓶，25 mL、10 mL、5 mL、1 mL 移液管，烧杯，具塞试管，'
            '洗耳球。DDSJ-307F 电导率仪，铂黑电导电极。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('KCl 溶液（0.01 mol·dm⁻³），HNO₃ 溶液（0.1 mol·dm⁻³），'
            'NaNO₃ 溶液（0.25 mol·dm⁻³），NaAc 溶液（0.25 mol·dm⁻³），'
            'HAc 溶液（0.25 mol·dm⁻³），去离子水。')

    rb.heading('2.2 实验内容', 2)
    rb.heading('2.2.1 电导池常数的测定和校正', 3)
    rb.para('电导池常数事先已初步标定。测定标准 KCl 溶液的电导率，'
            '若读数在 (1415 ± 5) μS·cm⁻¹ 内则视为标定成功；若偏差较大，'
            '则利用 KCl 溶液的理论电导率重新标定电导池常数。'
            '记录标定前后的电导池常数及对应的 KCl 读数。')
    rb.heading('2.2.2 测定去离子水的电导率', 3)
    rb.para('用去离子水淋洗电导电极，在试管中装入去离子水，测其电导率 '
            'κ_{w}。')
    rb.heading('2.2.3 配制不同浓度的溶液', 3)
    rb.para('按表1和表2配制不同浓度的 NaNO₃、NaAc、HAc 和 HNO₃ 溶液。'
            '移液管与容量瓶必须清洗干净，配制浓度要准确。')
    _table_preparation(rb)
    rb.heading('2.2.4 测定不同浓度溶液的电导率', 3)
    rb.para('用去离子水和待测液分别淋洗电导电极 2~3 次，以浓度从低到高的'
            '顺序测量各待测液的电导率，铂电极片应完全浸入溶液中。'
            '实验完毕后用去离子水淋洗电极并放回电极保护瓶，'
            '确认去离子水电导率在 6.5 μS·cm⁻¹ 以下，关闭电导率仪电源。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写定性分析…')
    _sec_qualitative(rb, analysis, fig_kc)
    log('写强电解质…')
    _sec_strong(rb, analysis, fit_pngs)
    log('写弱电解质…')
    _sec_weak(rb, analysis, fig_kfit)

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    log('写讨论…')
    _sec_error_analysis(rb, analysis)
    _sec_method_compare(rb, analysis)
    _sec_summary(rb, analysis)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] Haynes W M. CRC Handbook of Chemistry and Physics[M]. '
            'Boca Raton: CRC Press, 2016: 5-75~5-76.', indent_chars=0)
    rb.para('[3] 傅献彩, 侯文华, 等. 物理化学（第六版）下册[M]. '
            '北京: 高等教育出版社, 2022.', indent_chars=0)
    rb.para('[4] Montgomery D C, Peck E A, Vining G G. Introduction to Linear '
            'Regression Analysis[M]. Hoboken: John Wiley & Sons, 2021.',
            indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 配制表
_PREP_COMMON = [
    ('1', '0.025', '100', '0.25', '10'),
    ('2', '0.01', '100', '0.25', '4'),
    ('3', '0.005', '100', '0.25', '2'),
    ('4', '0.0025', '100', '0.25', '1'),
    ('5', '0.00125', '100', '0.25', '0.5'),
]
_PREP_HNO3 = [
    ('1', '0.01', '100', '0.1', '10'),
    ('2', '0.005', '100', '0.1', '5'),
    ('3', '0.0025', '100', '0.1', '2.5'),
    ('4', '0.001', '100', '0.1', '1'),
    ('5', '0.0005', '100', '0.1', '0.5'),
]
_PREP_HEAD = ['瓶号', '浓度 / (mol·dm⁻³)', '定容体积 / mL',
              '母液浓度 / (mol·dm⁻³)', '量取体积 / mL']
_PREP_W = [1.2, 3.6, 2.8, 4.0, 3.0]


def _table_preparation(rb):
    rb.caption('表1  不同浓度电解质溶液的配制（NaNO₃、NaAc、HAc 溶液）')
    rb.table(_PREP_HEAD, _PREP_COMMON, widths_cm=_PREP_W)
    rb.caption('表2  不同浓度 HNO₃ 电解质溶液的配制')
    rb.table(_PREP_HEAD, _PREP_HNO3, widths_cm=_PREP_W)


# ---------------------------------------------------------------- 3.1
def _sec_qualitative(rb, an, fig_kc):
    ctx = an.ctx
    pres = an.cfg.get('pressure')
    rb.heading('3.1 原始数据的定性分析', 2)
    rb.heading('3.1.1 基本实验数据', 3)
    rb.para(['实验温度：', ('t', '%.1f ℃' % ctx['temp'], {}),
             '，大气压：',
             ('t', ('%.1f kPa' % float(pres)) if pres else '—', {}), '。'])
    rb.para(['实验使用的电极标注的电导池常数是 ',
             ('t', '%.3f cm⁻¹' % ctx['cell_label'], {}),
             '，此时测得标准 KCl 溶液的电导率为 ',
             ('t', '%.0f μS·cm⁻¹' % ctx['kcl_label'], {}),
             '。标定后的电导池常数是 ',
             ('t', 'K_{cell}', ITALIC), ' = ',
             ('t', '%.3f cm⁻¹' % ctx['cell'], {}),
             '，此时测得标准 KCl 溶液的电导率为 ',
             ('t', '%.0f μS·cm⁻¹' % ctx['kcl_after'], {}),
             '。去离子水的电导率为 ', ('t', 'κ_{w}', ITALIC), ' = ',
             ('t', '%.2f μS·cm⁻¹' % ctx['kappa_w_us']), '。'])
    rb.para(['需要说明的是，此后的测量数据记录均未记录温度，是因为实验所用的'
             '电导率仪对温度进行了线性补偿，补偿系数为 ',
             ('t', '%.2f %%/℃' % ctx['compensation'], {}),
             '。故电导率均可视为在 25 ℃ 下测量。'])

    rb.heading('3.1.2 电导率-浓度变化情况', 3)
    rb.para(['本节对电导率随溶液浓度变化的规律作定性分析，数据的具体处理过程'
             '统一安排在后续的定量分析部分。根据表3、表5和表7的数据处理结果，'
             '可以得到 NaNO₃、HNO₃ 和 HAc 的校正电导率（',
             ('t', 'κ_{corrected}', ITALIC), '）和浓度（',
             ('t', 'c', ITALIC), '），由此作出 κ_{corrected}–c 曲线，'
             '如图2所示。'])
    rb.figure(fig_kc, caption='图2  NaNO₃、HNO₃ 和 HAc 的电导率-浓度关系曲线',
              width_cm=12.5)
    rb.para(['可以看出对于强电解质，电导率随浓度增加而显著增加，且接近线性。'
             '观察电导率公式：'])
    rb.equation(r'\kappa=\Lambda_{m}\times c')
    rb.para(['对于强电解质稀溶液，', ('t', 'Λ_{m}', ITALIC), ' 的变化较小'
             '（从表3~表5的计算结果也可以看出），可近似看成常数；而由于完全电离，'
             '溶液中的离子数目与浓度 ', ('t', 'c', ITALIC),
             ' 成正比，所以电导率近似与 ', ('t', 'c', ITALIC), ' 成正比。'
             '值得一提的是，本实验中浓度均较低；如果浓度继续增大，正负离子相互'
             '作用力增大，离子迁移受阻，电导率反而会降低，所以完整的强电解质'
             '电导率-浓度关系曲线应该有极大值。'])
    rb.para(['HNO₃ 变化曲线的斜率比 NaNO₃ 大，即相同浓度下 HNO₃ 的摩尔电导率'
             '更大，这是 H⁺ 和 Na⁺ 运动速度的差异所致：H⁺ 在水中并不是靠'
             '「自身移动」导电，而是通过 Grotthuss 机制在氢键网络中接力传递，'
             '迁移速度比 Na⁺ 大很多。顺便指出，除 H⁺ 这种特殊离子之外，'
             '离子的迁移速度遵循 Stokes 定律，即与电荷成正比、与水合半径成反比。'
             '对于弱电解质 HAc，电导率随浓度的变化不显著，这是因为浓度增加使'
             '解离度减小，溶液中离子数目其实变化不大。'])


# ---------------------------------------------------------------- 3.2
def _sec_strong(rb, an, fit_pngs):
    fits = an.fits
    rb.heading('3.2 强电解质的数据处理', 2)
    rb.heading('3.2.1 原始数据记录及基本数据处理', 3)
    rb.para('NaNO₃、NaAc 和 HNO₃ 的不同浓度溶液电导率原始数据及基本数据处理'
            '分别如表3、表4和表5所示。')
    rb.para('有必要说明有效数字：HNO₃ 的母液浓度为 0.1 mol·dm⁻³，但这显然不'
            '意味着结果只保留 1 位有效数字。鉴于配制过程中有效数字最低为 4 位'
            '（10 mL 移液管精度为 10.00 mL），浓度均保留 4 位有效数字；电导率'
            '保留 3~4 位是因为电导率仪在不同量程下的有效位数本就不同，'
            '表中保持原始读数不变，后续结果再统一有效数字。')
    rb.para('浓度和电导率按如下关系换算成标准单位制：')
    rb.equation(r'1\ mol\cdot dm^{-3}=10^{3}\ mol\cdot m^{-3},\qquad'
                r'1\ \mu S\cdot cm^{-1}=10^{-4}\ S\cdot m^{-1}')
    rb.para('校正电导率等于测量电导率减去去离子水的电导率：')
    rb.equation(r'\kappa_{corrected}=\kappa_{measured}-\kappa_{w}')
    rb.para('摩尔电导率等于校正电导率除以浓度：')
    rb.equation(r'\Lambda_{m}=\frac{\kappa_{corrected}}{c}')

    for idx, key in enumerate(('NaNO3', 'NaAc', 'HNO3'), 3):
        rows = an.tables[key]
        table_rows = []
        for i, r in enumerate(rows, 1):
            table_rows.append([str(i), sig_fig(r['c'], 4), sig_fig(r['kappa'], 4),
                               sig_fig(r['kappa_corr'], 4),
                               sig_fig(r['lam'], 4)])
        rb.caption('表%d  不同浓度 %s 电导率原始数据'
                   % (idx, conduct.SPECIES_LABEL[key]))
        rb.table(['瓶号', 'c / (mol·m⁻³)', 'κ_{measured} / (S·m⁻¹)',
                  'κ_{corrected} / (S·m⁻¹)', 'Λ_{m} / (S·m²·mol⁻¹)'],
                 table_rows, widths_cm=[1.4, 2.9, 3.8, 3.8, 3.8])

    rb.heading('3.2.2 Kohlrausch极限定律的拟合', 3)
    rb.para('Kohlrausch 极限定律表明，在低浓度下，强电解质的摩尔电导率满足：')
    rb.equation(r'\Lambda_{m}=\Lambda_{m}^{\infty}-B\sqrt{c}')
    rb.para(['故以 ', ('t', 'Λ_{m}', ITALIC), ' 对 ', ('t', '√c', ITALIC),
             ' 作线性拟合，截距即为该物种的极限摩尔电导率 ',
             ('t', 'Λ_{m}^{∞}', ITALIC), '。三个物种的拟合结果分别如图3~图5所示。'])
    for idx, key in enumerate(('NaNO3', 'NaAc', 'HNO3'), 3):
        f = fits[key]
        rb.figure(fit_pngs[key],
                  caption='图%d  %s 的 Λ_{m}–√c 拟合直线'
                          % (idx, conduct.SPECIES_LABEL[key]),
                  width_cm=11.5)
        sign = '-' if f['k'] < 0 else '+'
        rb.equation(r'\Lambda_{m}=(%(b)s)%(s)s(%(k)s)\times\sqrt{c}'
                    % {'b': pm(f['lam_inf'], f['sigma_inf']), 's': sign,
                       'k': pm(abs(f['k']), f['sigma_k'])})
        rb.para(['相关系数 ', ('t', 'r', ITALIC), ' = ',
                 ('t', '%.2f' % f['r'], ITALIC), '。'])
    f_hno3 = fits['HNO3']
    rb.para(['与电导率不同，强电解质的摩尔电导率随浓度增加而降低：溶液中能导电'
             '的物质的量已给定（1 mol），浓度升高时正负离子相互作用力增加并形成'
             '离子氛，两种效应都阻碍离子在电场下的定向运动。注意到 HNO₃ 前两个'
             '数据点违背了这一规律，线性特别差（',
             ('t', 'r', ITALIC), ' = ', ('t', '%.2f' % f_hno3['r'], ITALIC),
             '），这是因为 HNO₃ 容易挥发，低浓度下少量挥发就会显著改变浓度，'
             '导致电导率偏低，详见 4.1 节的讨论。'])

    rb.heading('3.2.3 极限摩尔电导率的计算', 3)
    combo = an.esa['combo']
    add_names = '+'.join(conduct.SPECIES_LABEL[k] for k in combo['add'])
    sub_names = '-'.join(conduct.SPECIES_LABEL[k] for k in combo['sub'])
    rb.para('根据三条拟合直线的截距，得到各强电解质的极限摩尔电导率'
            '（不确定度为拟合截距的标准误）：')
    for key in ('NaNO3', 'NaAc', 'HNO3'):
        f = fits[key]
        rb.para([('t', 'Λ_{m}^{∞}', ITALIC),
                 ('t', '(%s)' % conduct.CHEM_MARK[key], {}),
                 ' = ',
                 ('t', '(%s) S·m⁻²·mol⁻¹' % pm(f['lam_inf'], f['sigma_inf']), {})])
    rb.para(['弱电解质不符合 Kohlrausch 经验公式，其极限摩尔电导率由离子独立'
             '运动定律从强电解质结果组合而来。本实验的组合关系为 '
             'Λ_{m}^{∞}(HAc) = %s − %s，即：' % (add_names, sub_names)])
    lam_hac, sig_hac = an.esa['lam_inf'], an.esa['sigma']
    rb.equation(r'\Lambda_{m}^{\infty}(\mathrm{HAc})'
                r'=\Lambda_{m}^{\infty}(\mathrm{NaAc})'
                r'+\Lambda_{m}^{\infty}(\mathrm{HNO}_{3})'
                r'-\Lambda_{m}^{\infty}(\mathrm{NaNO}_{3})'
                r'=%s\ S\cdot m^{2}\cdot mol^{-1}'
                % _latex_num(lam_hac, 5))
    rb.para('不确定度按方和根合成：')
    parts = '+'.join('%s^{2}' % _latex_num(fits[k]['sigma_inf'], 5)
                     for k in (combo['add'] + combo['sub']))
    rb.equation(r'\sigma_{\Lambda_{m}^{\infty}(\mathrm{HAc})}='
                r'\sqrt{%s}=%s\ S\cdot m^{2}\cdot mol^{-1}'
                % (parts, _latex_num(sig_hac, 5)))
    rb.para(['综上，实验所得 HAc 的极限摩尔电导率为 ',
             ('t', 'Λ_{m}^{∞}', ITALIC), ('t', '(HAc)', {}),
             ' = ', ('t', '(%s) S·m⁻²·mol⁻¹' % pm(lam_hac, sig_hac), {}), '。'])
    rb.para(['查阅手册^{[2]}，25 ℃ 下各离子的极限摩尔电导率为：'
             'Na⁺ 0.005008、Ac⁻ 0.00409、H⁺ 0.034965、NO₃⁻ 0.007142 '
             'S·m⁻²·mol⁻¹。由离子独立运动定律求得各物种的理论值，'
             '与实验值一起整理成表6，相对误差以 NaNO₃ 为例：'])
    na = an.lit_table[0]
    rb.equation(r'E_{r}(NaNO_{3})=\frac{%(a)s-%(b)s}{%(b)s}\times100\%%=%(er)s'
                % {'a': _latex_num(na['exp'], 5), 'b': _latex_num(na['theo'], 5),
                   'er': pct(na['er'])})
    rb.caption('表6  各物种极限摩尔电导率实验值（exp）与理论值（theo）的比较')
    rows6 = []
    for row in an.lit_table:
        rows6.append([conduct.SPECIES_LABEL[row['key']],
                      '%s S·m⁻²·mol⁻¹' % pm(row['exp'], row['sigma']),
                      sig_fig(row['theo'], 5), pct(row['er'])])
    rb.table(['物种', 'Λ_{m}^{∞}（实验值）', 'Λ_{m}^{∞}（理论值）', 'E_{r}'],
             rows6, widths_cm=[2.2, 5.6, 3.6, 2.6])


# ---------------------------------------------------------------- 3.3
def _sec_weak(rb, an, fig_kfit):
    esa = an.esa
    kmean = an.kmean
    kfit = an.kfit
    rb.heading('3.3 弱电解质的数据处理', 2)
    rb.heading('3.3.1 原始数据记录及基本数据处理', 3)
    rb.para(['HAc 的不同浓度溶液电导率原始数据及基本数据处理如表7所示，'
             '单位换算、校正电导率和摩尔电导率的计算方法与 3.2.1 节相同，'
             '其余数据处理的细节如下。电离度的计算公式是近似得出的：'])
    rb.equation(r'\alpha=\frac{\Lambda_{m}}{\Lambda_{m}^{\infty}}')
    rb.para(['其中 ', ('t', 'Λ_{m}^{∞}', ITALIC), ' = ',
             ('t', '(%s) S·m⁻²·mol⁻¹' % pm(esa['lam_inf'], esa['sigma']), {}),
             '，为实验测得的极限摩尔电导率。标准电离平衡常数由定义即可推出：'])
    rb.equation(r'K^{\ominus}=\frac{(c/c^{\ominus})\alpha^{2}}{1-\alpha}')
    rb.para(['其中 ', ('t', 'c^{⊖}', ITALIC), ' = 1000 mol·m⁻³。'
             '各浓度下的计算结果见表7。'])
    table_rows = []
    for i, (b, r) in enumerate(zip(kmean['bottles'], an.tables['HAc']), 1):
        table_rows.append([
            str(i), sig_fig(r['c'], 4), sig_fig(r['kappa'], 4),
            sig_fig(r['kappa_corr'], 4), sig_fig(r['lam'], 4),
            sig_fig(b['alpha'], 3), sci(b['k'], 3, -5)])
    rb.caption('表7  不同浓度 HAc 溶液的电导率、摩尔电导率、电离度和标准电离平衡常数')
    rb.table(['瓶号', 'c / (mol·m⁻³)', 'κ_{measured} / (S·m⁻¹)',
              'κ_{corrected} / (S·m⁻¹)', 'Λ_{m} / (S·m²·mol⁻¹)',
              'α', 'K^{⊖}'],
             table_rows, widths_cm=[1.0, 2.0, 2.6, 2.6, 2.9, 1.6, 3.0])

    rb.para(['5 组数据平衡常数 ', ('t', 'K^{⊖}', ITALIC), ' 的平均值为：'])
    ks_txt = '+'.join(_latex_num(b['k'] * 1e5, 3) for b in kmean['bottles'])
    rb.equation(r'K^{\ominus}=\frac{%s}{5}\times10^{-5}=%s\times10^{-5}'
                % (ks_txt, _latex_num(kmean['mean'] * 1e5, 3)))
    rb.para(['下面估算其不确定度。联立摩尔电导率、电离度和标准电离平衡常数的'
             '计算式，可得 ', ('t', 'K^{⊖}', ITALIC), ' 的总计算式：'])
    rb.equation(r'K^{\ominus}=\frac{1}{c^{\ominus}}\times'
                r'\frac{\kappa_{corrected}^{2}}'
                r'{c(\Lambda_{m}^{\infty})^{2}-\kappa_{corrected}\Lambda_{m}^{\infty}}')
    rb.para(['电导率读数的不确定度按「末位数字取 2」估计：1 号溶液读数 '
             '0.0258 S·m⁻¹ 的不确定度为 ', ('t', 'σ_{κ}', ITALIC),
             ' = 0.0002 S·m⁻¹，其余溶液为 0.00002 S·m⁻¹。'
             '水的电导率不确定度比溶液低 1~2 个数量级，可忽略，'
             '故校正电导率的不确定度近似等于测量电导率的不确定度。'
             '浓度在分母上，其不确定度影响很小，视为常数；',
             ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 的标准误已在 3.2.3 节求出。于是：'])
    rb.equation(r'\sigma_{K^{\ominus}}=\sqrt{\left(\frac{\partial K^{\ominus}}'
                r'{\partial\kappa_{corrected}}\sigma_{\kappa_{corrected}}\right)^{2}'
                r'+\left(\frac{\partial K^{\ominus}}{\partial\Lambda_{m}^{\infty}}'
                r'\sigma_{\Lambda_{m}^{\infty}}\right)^{2}}')
    rb.para('两个偏导数分别为：')
    rb.equation(r'\frac{\partial K^{\ominus}}{\partial\kappa_{corrected}}='
                r'\frac{1}{c^{\ominus}}\times'
                r'\frac{\kappa_{corrected}\Lambda_{m}^{\infty}'
                r'(2c\Lambda_{m}^{\infty}-\kappa_{corrected})}'
                r'{\left(c(\Lambda_{m}^{\infty})^{2}'
                r'-\kappa_{corrected}\Lambda_{m}^{\infty}\right)^{2}}')
    rb.equation(r'\frac{\partial K^{\ominus}}{\partial\Lambda_{m}^{\infty}}='
                r'-\frac{1}{c^{\ominus}}\times'
                r'\frac{\kappa_{corrected}^{2}'
                r'(2c\Lambda_{m}^{\infty}-\kappa_{corrected})}'
                r'{\left(c(\Lambda_{m}^{\infty})^{2}'
                r'-\kappa_{corrected}\Lambda_{m}^{\infty}\right)^{2}}')
    rb.para(['代入各溶液的 ', ('t', 'c', ITALIC), ' 和 ',
             ('t', 'κ_{corrected}', ITALIC),
             '，得到各瓶的不确定度（表8）。总不确定度按独立测量合成：'])
    sig_parts = '+'.join(_latex_num(b['sigma_k'] ** 2 / 1e-14, 2)
                         for b in kmean['bottles'])
    rb.equation(r'\sigma_{K^{\ominus}}=\frac{\sqrt{%s}}{5}\times10^{-7}=%s\times10^{-7}'
                % (sig_parts, _latex_num(kmean['sigma'] * 1e7, 2)))
    rb.caption('表8  不同浓度 HAc 的平衡常数不确定度')
    rb.table(['瓶号', 'σ_{K⊖}'],
             [[str(i + 1), sci(b['sigma_k'], 2, -7)]
              for i, b in enumerate(kmean['bottles'])],
             widths_cm=[3.0, 4.6])
    rb.para(['综上，通过求平均法求出的标准电离平衡常数为 ',
             ('t', 'K^{⊖}', ITALIC), ' = ',
             ('t', sci_pm(kmean['mean'], kmean['sigma']), {}), '。'])

    rb.heading('3.3.2 HAc的拟合直线', 3)
    rb.para('联立电离度和标准电离平衡常数的计算公式，可得：')
    rb.equation(r'K^{\ominus}=\frac{(c/c^{\ominus})\Lambda_{m}^{2}}'
                r'{\Lambda_{m}^{\infty}(\Lambda_{m}^{\infty}-\Lambda_{m})}')
    rb.para('整理得：')
    rb.equation(r'(c/c^{\ominus})\Lambda_{m}=(\Lambda_{m}^{\infty})^{2}K^{\ominus}'
                r'\frac{1}{\Lambda_{m}}-\Lambda_{m}^{\infty}K^{\ominus}')
    rb.para(['由此可知，以 ', ('t', '(c/c^{⊖})Λ_{m}', ITALIC), ' 对 ',
             ('t', '1/Λ_{m}', ITALIC), ' 作线性拟合，其斜率 ',
             ('t', 'k', ITALIC), ' = ', ('t', '(Λ_{m}^{∞})^{2}K^{⊖}', ITALIC),
             '，再结合 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 的值即可求出 ', ('t', 'K^{⊖}', ITALIC), '，拟合结果如图6所示。'])
    rb.figure(fig_kfit,
              caption='图6  HAc 的 (c/c^{⊖})Λ_{m}–1/Λ_{m} 拟合直线',
              width_cm=11.5)
    rb.equation(r'(c/c^{\ominus})\Lambda_{m}=(%s)\frac{1}{\Lambda_{m}}-(%s)'
                % (sci_pm(kfit['k'], kfit['sigma_k'], -8),
                   sci_pm(kfit['b'], kfit['sigma_b'], -6)))
    rb.para(['相关系数 ', ('t', 'r', ITALIC), ' = ',
             ('t', '%.5f' % kfit['r'], ITALIC), '，线性极好。由此可知：'])
    rb.equation(r'k=(\Lambda_{m}^{\infty})^{2}K^{\ominus}=%s'
                % _latex_sci(kfit['k'], 4, -8))
    rb.para(['代入 ', ('t', 'Λ_{m}^{∞}', ITALIC), ' = ',
             ('t', sig_fig(esa['lam_inf'], 5), {}), '，得：'])
    rb.equation(r'K^{\ominus}=\frac{%s}{%s^{2}}=%s\times10^{-5}'
                % (_latex_sci(kfit['k'], 4, -8),
                   _latex_num(esa['lam_inf'], 5),
                   _latex_num(kfit['K'] * 1e5, 3)))
    rb.para('不确定度公式为：')
    rb.equation(r'\sigma_{K^{\ominus}}='
                r'\sqrt{\left(\frac{\sigma_{k}}{(\Lambda_{m}^{\infty})^{2}}\right)^{2}'
                r'+\left(\frac{2k\sigma_{\Lambda_{m}^{\infty}}}'
                r'{(\Lambda_{m}^{\infty})^{3}}\right)^{2}}=%s\times10^{-7}'
                % _latex_num(kfit['sigma_K'] * 1e7, 2))
    rb.para(['综上，通过拟合直线法求出的标准电离平衡常数为 ',
             ('t', 'K^{⊖}', ITALIC), ' = ',
             ('t', sci_pm(kfit['K'], kfit['sigma_K']), {}), '。'])
    ka = conduct.KA_HAC
    er_mean = (kmean['mean'] - ka) / ka * 100.0
    er_fit = (kfit['K'] - ka) / ka * 100.0
    rb.para(['查阅手册^{[2]}，HAc 的理论 ', ('t', 'p', {}), ('t', 'K_{a}', ITALIC), ' = 4.756，'
             '对应 ', ('t', 'K_{a}', ITALIC), ' = ',
             ('t', sci(ka, 4, -5), {}),
             '。两种方法的相对误差分别为 ', pct(er_mean), ' 和 ', pct(er_fit),
             '，整理在表9中。'])
    rb.caption('表9  两种方法所得平衡常数和相对误差')
    rb.table(['方法', 'K^{⊖}', 'E_{r}'],
             [['求平均法', sci_pm(kmean['mean'], kmean['sigma']), pct(er_mean)],
              ['拟合直线法', sci_pm(kfit['K'], kfit['sigma_K']), pct(er_fit)]],
             widths_cm=[3.4, 6.6, 3.0])


# ---------------------------------------------------------------- 4 讨论
def _sec_error_analysis(rb, an):
    rb.heading('4.1 强电解质极限摩尔电导率误差分析', 2)
    er_txt = '、'.join('%s %s' % (conduct.SPECIES_LABEL[r['key']], pct(r['er']))
                       for r in an.lit_table[:3])
    rb.para('根据表6，各强电解质极限摩尔电导率的相对误差都不大（' + er_txt +
            '），但这个相对误差并不完全可信，分析如下。')
    rb.para('首先对于 HNO₃，其拟合直线线性极差，很难说有明确的物理意义，'
            '所以 HNO₃ 相对误差较小大概率是巧合：HNO₃ 容易挥发，稀溶液中'
            '少量挥发就会显著降低表观电导率；如果让稀溶液的数据符合预期'
            '（比浓溶液更高），截距会显著高于真值。对于 NaNO₃ 和 NaAc，'
            '拟合直线的线性相对较好，其相对误差也较小，一定程度上佐证了'
            ' Kohlrausch 经验公式的可靠性。')
    rb.para('线性欠佳的更系统性原因在于：极低浓度下摩尔电导率较高，但绝对'
            '电导率很低，仪器噪声与杂质的影响很大。杂质可能来自空气及呼吸'
            '带出的 CO₂；仪器方面，铂电极片的浸入深度、摆放位置都可能改变'
            '有效电导池面积，这些影响对稀溶液尤为显著。此外，Kohlrausch 经验'
            '公式只对「极稀溶液」成立，NaAc 还可能轻微水解，但本实验的浓度'
            '已处于一般文献认可的极稀范围内，不构成主要因素。'
            '（同组同学数据之间的 F 检验与 t 检验需要共享数据，'
            '见口头汇报，本报告从略。）')


def _sec_method_compare(rb, an):
    rb.heading('4.2 弱电解质两种 K° 求解方法比较', 2)
    rb.para(['求平均法的误差显著大于拟合直线法，这符合理论预期。对于求平均法，'
             '各瓶 ', ('t', 'K^{⊖}', ITALIC), ' 由 ', ('t', 'α', ITALIC),
             ' 逐点计算而来：浓度较高、离解度较小时 ', ('t', 'α', ITALIC),
             ' 接近 0，分母 (1−α) 接近 1，计算尚可；浓度较低时 ',
             ('t', 'α', ITALIC), ' 增大，', ('t', 'Λ_{m}', ITALIC),
             ' 测量上的微小随机误差在与 (1−α) 相除时被急剧放大，'
             '所以低浓度端单个 ', ('t', 'K^{⊖}', ITALIC),
             ' 的偏差非常大——表7 中浓度越低、平衡常数越偏离文献值正是这一点'
             '的体现。'])
    rb.para(['而拟合直线法利用全部数据点共同估计一个参数。根据 Gauss–Markov '
             '定理^{[4]}，在误差主要存在于 y 且满足 OLS 假设（残差独立、同方差、'
             '零均值）时，斜率的估计方差最小：线性拟合通过最小二乘平滑了随机'
             '误差，最终结果不会因单一数据点的过大误差而受很大影响。严格地说，'
             'x 与 y 都由同一个带噪测量 ', ('t', 'Λ_{m}', ITALIC),
             ' 构成，并不完全满足 OLS 假设；好在 ', ('t', 'Λ_{m}', ITALIC),
             ' 的相对不确定度很低，总体上拟合直线法仍然更好。'])


def _sec_summary(rb, an):
    esa, kmean, kfit = an.esa, an.kmean, an.kfit
    rb.heading('4.3 小结', 2)
    rb.para(['本实验先用标准 KCl 溶液对电导率仪进行标定，随后分别测量了不同'
             '浓度 NaNO₃、NaAc、HNO₃ 和 HAc 溶液的电导率。利用 Kohlrausch '
             '经验公式对三种强电解质作 ', ('t', 'Λ_{m}', ITALIC), '–',
             ('t', '√c', ITALIC), ' 线性拟合、外推得到极限摩尔电导率：NaNO₃ ',
             ('t', '(%s)' % pm(an.fits['NaNO3']['lam_inf'],
                               an.fits['NaNO3']['sigma_inf']), {}),
             '、NaAc ',
             ('t', '(%s)' % pm(an.fits['NaAc']['lam_inf'],
                               an.fits['NaAc']['sigma_inf']), {}),
             '、HNO₃ ',
             ('t', '(%s)' % pm(an.fits['HNO3']['lam_inf'],
                               an.fits['HNO3']['sigma_inf']), {}),
             ' S·m⁻²·mol⁻¹，与文献值吻合良好；针对拟合线性欠佳的问题，'
             '从 HNO₃ 挥发与极稀溶液的噪声/杂质影响两方面作了归因分析。'])
    rb.para(['弱电解质 HAc 不符合 Kohlrausch 经验公式，其极限摩尔电导率由'
             '离子独立运动定律组合得 ',
             ('t', '(%s)' % pm(esa['lam_inf'], esa['sigma']), {}),
             ' S·m⁻²·mol⁻¹。进而通过 Ostwald 稀释定律，分别用求平均法和'
             '拟合直线法求得标准电离平衡常数 ',
             ('t', sci_pm(kmean['mean'], kmean['sigma']), {}), ' 与 ',
             ('t', sci_pm(kfit['K'], kfit['sigma_K']), {}),
             '，后者与文献值 1.754×10⁻⁵ 明显更接近，验证了线性拟合'
             '处理带噪数据的优势。'])
