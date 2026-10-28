# -*- coding: utf-8 -*-
"""生成《稀溶液法测定极性分子的偶极矩》实验报告 .docx。

结构照同课程 2025 年参考报告（2300012602-李晨曦-偶极矩）：
    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分（2.1 仪器和试剂 / 2.2 实验内容：配制、电容、密度、折射率）
    3 数据与结果
      3.1 摩尔分数的计算（表1）
      3.2 介电常数的数据处理（表2 电容、表3 ε、图2 ε–x 拟合）
      3.3 密度的数据处理（表4 密度、图3 ρ–x 拟合、表5 比重瓶）
      3.4 偶极矩的计算（A/B/C → P̄₂^∞ → R → μ）
    4 讨论与结论
      4.1 主要误差来源（表6 置零归因 + 电容误差假设；4.1.2 温度；4.1.3 原子极化度）
      4.2 直接测量法和外延法所得结果比较（表7）
      4.3 DE45 密度计和比重瓶的比较
      4.4 小结
    参考文献

排版口径与 skill 一致：只报数值的式子一律普通文本；代入计算才用公式对象；
结果末位与不确定度末位对齐（± 两侧留空格）。
"""
from __future__ import annotations

import decimal
import os

import numpy as np
from docx.shared import Cm

from . import dipole
from . import plotting
from .docxkit import ReportBuilder

ITALIC = {'italic': True}
TITLE = '稀溶液法测定极性分子的偶极矩'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')

MATH = lambda s: ('m', s)          # 表格里的公式单元格


# ---------------------------------------------------------------- 数字格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


def _sig(x, n=SIG_DIGITS):
    x = float(x)
    if x == 0 or not np.isfinite(x):
        return 0.0
    d = decimal.Decimal(repr(x))
    q = decimal.Decimal(1).scaleb(d.adjusted() - n + 1)
    return float(d.quantize(q, rounding=decimal.ROUND_HALF_EVEN))


def _place(u, n=SIG_DIGITS):
    return decimal.Decimal(repr(float(u))).adjusted() - n + 1


def _fix(x, exp):
    q = decimal.Decimal(1).scaleb(exp)
    return float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN))


def _fmt(x, exp):
    return '%.*f' % (max(0, -exp), x)


def val(x, u, n=SIG_DIGITS):
    if x is None or not np.isfinite(x):
        return '—'
    if u in (None, 0) or not np.isfinite(u):
        return k(x, 3)
    return _fmt(_fix(x, _place(u, n)), _place(u, n))


def unc(u, n=SIG_DIGITS):
    if u in (None, 0) or not np.isfinite(u):
        return '—'
    e = _place(u, n)
    return _fmt(_fix(u, e), e)


def pm(x, u, n=SIG_DIGITS):
    if x is None or not np.isfinite(x):
        return '—'
    if u in (None, 0) or not np.isfinite(u):
        return k(x, 3)
    e = _place(u, n)
    return '%s ± %s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e))


def pct(x, n=SIG_DIGITS):
    return _fmt(_sig(x, n), _place(x, n))


def sci_pm(x, u, exp=-5):
    """(7.95 ± 0.22)×10^{-5} 形式的普通文本片段。"""
    s = 10.0 ** exp
    return '(%s)×10^{%d}' % (pm(x / s, u / s), exp)


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    r = analysis
    title = str(cfg.get('report_title') or TITLE)

    # ---- 封面
    group = str(cfg.get('group') or '').strip()
    group_no = str(cfg.get('group_no') or '').strip()
    group_txt = ('%s 组 %s 号' % (group, group_no)) if (group and group_no) \
        else (group or group_no)
    room = cfg.get('room_temp')
    pres = cfg.get('pressure')
    room_txt = ('%.1f ℃' % float(room)) if room not in (None, '') else None
    pres_txt = ('%.1f kPa' % float(pres)) if pres not in (None, '') else None
    cover = {
        '题目': title,
        '姓名': cfg.get('student_name'),
        '学号': cfg.get('student_id'),
        '组别': group_txt,
        '实验日期': cfg.get('date'),
        '室温': room_txt,
        '大气压强': pres_txt,
    }
    missing = [key for key, v in cover.items() if not str(v or '').strip()]
    if missing:
        log('⚠ 封面缺字段：%s（请在界面左侧「报告封面」里填上）' % '、'.join(missing))
    rb.set_cover(cover, title_size=18.0)
    rb.set_header_title(title)

    os.makedirs(plots_dir, exist_ok=True)

    # ---- 出图
    log('绘制插图…')
    import matplotlib.pyplot as plt

    def save(fig, name):
        path = os.path.join(plots_dir, name)
        fig.savefig(path, dpi=plotting.DPI)
        plt.close(fig)
        return path

    png_eps = save(plotting.make_eps_figure(r), 'eps_x.png')
    png_rho = save(plotting.make_rho_figure(r), 'rho_x.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    rb.para([
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验通过测定不同浓度正丁醇在环己烷溶液中的介电常数（桥法测电容换算）'
        '和密度（DE45 型数字密度计测量），结合 Hedestrand 经验公式外推得总摩尔'
        '极化度 ', ('t', 'P₂^{∞}', ITALIC), ' = ',
        sci_pm(r['P_inf'] * 1e-6, r['s_P'] * 1e-6), ' m^{3}·mol^{-1}。'
        '再由折射率和密度求得摩尔折射度 ', ('t', 'R', ITALIC), ' = ',
        sci_pm(r['R_molar'] * 1e-6, r['s_R'] * 1e-6),
        ' m^{3}·mol^{-1} 作为电子极化度，进而计算转向极化度并得到偶极矩 ',
        ('t', 'μ', ITALIC), ' = (%s) D，与文献值 %.2f D 一致，表明测量准确可靠。'
        % (pm(r['mu'], r['s_mu']), r['lit_mu']),
    ])
    rb.para([{'text': '关键词 ', 'bold': True},
             '偶极矩；摩尔极化度；正丁醇；介电常数；Hedestrand 公式'])
    rb.blank()

    # ================================================================ 1 引言
    rb.heading('1 引言', page_break_before=True)
    rb.para('该实验的实验目的、实验原理及实验方法如图1所示。')
    if os.path.exists(INTRO_IMG):
        rb.figure(INTRO_IMG, caption='图1  实验目的、原理及方法', width_cm=11.0)
    else:
        for _ in range(INTRO_BLANK_LINES):
            rb.blank()
        rb.caption('图1  实验目的、原理及方法')

    # ================================================================ 2 实验部分
    rb.heading('2 实验部分^{[1]}', page_break_before=True)
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para('PCM-1 型精密电容测量仪，电容池，注射器，洗耳球，50 mL 磨口锥形瓶'
            '（7 个），滴管，吸量管，比重瓶，烧杯（50 mL、200 mL 各一个），'
            '电子天平，阿贝折射仪，DE45 型数字密度计，循环水真空泵。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('正丁醇，环己烷，丙酮，去离子水。')
    rb.heading('2.2 实验内容', 2)
    rb.heading('2.2.1 溶液的配制', 3)
    rb.para(['取 2 个磨口锥形瓶用于盛正丁醇和环己烷，另外 5 个用于配制摩尔分数'
             '分别约为 0.05、0.08、0.10、0.12、0.15 的正丁醇/环己烷溶液各 15 mL。'
             '每份溶液的配制如下：将锥形瓶质量去皮。先移取事先计算好体积的正丁醇，'
             '称取此时的质量 ', ('t', 'm_{1}', ITALIC), '；再移取环己烷，'
             '称取此时的总质量 ', ('t', 'm_{2}', ITALIC),
             '，用于计算正丁醇摩尔分数。'])
    rb.heading('2.2.2 介电常数（电容）的测定', 3)
    rb.para(["打开测量仪预热 20 min。拔下「电容池座」屏蔽线插头，按「校零」"
             "按钮使仪器读数为 000.00。插上插头，此时显示值为 ",
             ('t', "C'_{空}", ITALIC), '。取下电容池上盖，将电容池白色容器中'
             '加入环己烷溶液至满池，盖上上盖，读取此时显示值 ',
             ('t', "C'_{环}", ITALIC), '。用滴管吸取容器内溶液，并用洗耳球或'
             '吹风机吹干整个电容池，盖上上盖后显示值为 ',
             ('t', "C'_{空}", ITALIC), '。若 ', ('t', "C'_{空}", ITALIC),
             ' 与初始值相差 0.01 pF 以内方可继续实验（后同）。重复上述步骤'
             '再测一次 ', ('t', "C'_{环}", ITALIC), '，两次 ', ('t', "C'_{环}", ITALIC),
             ' 数据差在 0.01 pF 以内方可继续实验。同法测定 5 组溶液的 ',
             ('t', "C'_{样}", ITALIC), '（平行测定两次）。'])
    rb.heading('2.2.3 密度的测定', 3)
    rb.para('用 DE45 型数字密度计测定正丁醇、环己烷以及各溶液的密度。基本方法'
            '如下：用对应的针管及针头吸取一定量溶液，将溶液注入密度计至气泡被'
            '排出。点击测量，测量完成后先用针管将溶液尽可能吸出，再将排出管与'
            '空气泵相连，等待仪器将残留液完全泵出，进行下一次测量。')
    rb.para(['再用比重瓶测定正丁醇的密度。先称取空瓶质量 ',
             ('t', 'm_{0}', ITALIC), '，再往比重瓶中加入去离子水（标准液），'
             '称取此时的质量 ', ('t', 'm_{w}', ITALIC), '（平行测量两次，'
             '两次数据差小于 2 mg 方可继续实验）。将去离子水倒掉，'
             '加入正丁醇（先用正丁醇润洗比重瓶），称取此时的质量 ',
             ('t', 'm_{B}', ITALIC), '。'])
    rb.heading('2.2.4 折射率的测定', 3)
    rb.para('利用阿贝折射仪测量正丁醇的折射率，平行测定两次取平均。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    _sec_x(rb, r)
    _sec_eps(rb, r, png_eps)
    _sec_rho(rb, r, png_rho)
    _sec_mu(rb, r)

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    _sec_error(rb, r)
    _sec_extrap(rb, r)
    _sec_compare(rb)
    _sec_summary(rb, r)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）'
            '[M]. 北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] Haynes W M. CRC handbook of chemistry and physics[M]. '
            'CRC press, 2016: 5-75~5-76, 6-196~6-198.', indent_chars=0)
    rb.para("[3] Atkins P W, De Paula J, Keeler J. Atkins' physical chemistry"
            '[M]. Oxford university press, 2023.', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 3.1 摩尔分数
def _sec_x(rb, r):
    rb.heading('3.1 摩尔分数的计算', 2)
    rb.para([
        '本报告环己烷摩尔质量 ', ('t', 'M_{1}', ITALIC), ' = %s g·mol^{-1}、'
        % k(r['M1'], 3),
        '正丁醇摩尔质量 ', ('t', 'M_{2}', ITALIC), ' = %s g·mol^{-1}，'
        % k(r['M2'], 3),
        '均采用手册值^{[2]}且视为常数。表1列出各组溶液称取的正丁醇质量 ',
        ('t', 'm_{1}', ITALIC), ' 和溶液总质量 ', ('t', 'm_{2}', ITALIC),
        '，摩尔分数由下式计算（以 1 号溶液为例）：',
    ], keep_next=True)
    s1 = r['solutions'][0]
    rb.equation(r'x=\frac{m_{1}/M_{2}}{m_{1}/M_{2}+(m_{2}-m_{1})/M_{1}}'
                r'=\frac{%.3f/%.3f}{%.3f/%.3f+(%.3f-%.3f)/%.3f}=%.4f'
                % (s1['m1'], r['M2'], s1['m1'], r['M2'],
                   s1['m2'], s1['m1'], r['M1'], s1['x']))
    rb.para('后文将会讨论，本实验的主要误差来源是拟合的不确定度，'
            '故不计算摩尔分数的不确定度。')
    rows = [[str(s['no']), k(s['m1'], 3), k(s['m2'], 3), '%.4f' % s['x']]
            for s in r['solutions']]
    rb.caption('表1  各溶液原始数据及摩尔分数')
    rb.table(['编号', 'm_{1} / g', 'm_{2} / g', 'x'], rows,
             widths_cm=[2.0, 3.4, 3.4, 3.4], keep_together=True)


# ---------------------------------------------------------------- 3.2 介电常数
def _sec_eps(rb, r, png_eps):
    rb.heading('3.2 介电常数的数据处理', 2)
    rb.heading('3.2.1 电容测量结果', 3)
    rb.para(["电容测量的原始数据如表2所示，每组溶液平行测量两次"
             "（两次结果相同，取平均值参与后续计算）。其中 ",
             ('t', "C'_{空}", ITALIC), ' 为每组测量结束、将电容池吹干后的'
             '测量值。'])
    rows = [[
        '环己烷',
        k(r['c_empty'], 2), k(r['c_empty'], 2),
        k(r['c_cyc'], 2), k(r['c_cyc'], 2),
    ]]
    for s in r['solutions']:
        c = s['c_mean']
        rows.append([str(s['no']), k(r['c_empty'], 2), k(r['c_empty'], 2),
                     k(c, 2), k(c, 2)])
    rb.caption('表2  各溶液电容测量原始数据')
    rb.table(['编号', "C'_{空} / pF", "C'_{空} / pF",
              "C'_{样} / pF", "C'_{样} / pF"], rows,
             widths_cm=[2.0, 2.9, 2.9, 2.9, 2.9], keep_together=True)

    rb.heading('3.2.2 介电常数的计算', 3)
    rb.para(['本实验的温度为 ', ('t', 'T', ITALIC), ' = %.1f ℃ = %.2f K。'
             % (r['T_c'], r['T_K']),
             '虽然温度会有一定波动，但并不是本实验的主要误差来源（见 4.1.2），'
             '故可将温度视为常数。首先按手册公式计算环己烷的介电常数：'],
            keep_next=True)
    rb.equation(r'ε_{环}=2.023-0.0016\times(T-293)=%.4f' % r['eps_cyc'])
    rb.para('然后计算分布电容和空气电容：', keep_next=True)
    rb.equation(r"C_{分}=C'_{空}-\frac{C'_{环}-C'_{空}}{ε_{环}-1}=%s\ pF"
                % k(r['C_dist'], 2))
    rb.equation(r"C₀=\frac{C'_{环}-C'_{空}}{ε_{环}-1}=%s\ pF" % k(r['C0'], 2))
    s1 = r['solutions'][0]
    rb.para('故各溶液的介电常数为：', keep_next=True)
    rb.equation(r"ε=\frac{C'_{样}-C_{分}}{C₀}=\frac{%s-%s}{%s}=%.2f"
                % (k(s1['c_mean'], 2), k(r['C_dist'], 2), k(r['C0'], 2),
                   s1['eps']))
    rb.para('各溶液的计算结果如表3所示。同理，本实验的主要误差来源是线性拟合，'
            '故不计算介电常数的不确定度。')
    rows = [[str(s['no']), '%.2f' % s['eps']] for s in r['solutions']]
    rb.caption('表3  各溶液介电常数计算结果')
    rb.table(['编号', 'ε'], rows, widths_cm=[2.4, 3.0], keep_together=True)

    rb.heading(['3.2.3 ', ('t', 'ε', ITALIC), '–', ('t', 'x', ITALIC),
                ' 拟合'], 3)
    rb.para(['结合表1和表3，将介电常数 ', ('t', 'ε', ITALIC), ' 和摩尔分数 ',
             ('t', 'x', ITALIC), ' 进行线性拟合，拟合直线如图2所示。'])
    rb.figure(png_eps, caption='图2  介电常数-摩尔分数拟合直线', width_cm=11.5)
    rb.para('拟合结果如下：', keep_next=True)
    rb.equation(r'ε=(%s\pm%s)x+(%s\pm%s)'
                % (val(r['a'], r['s_a']), unc(r['s_a']),
                   val(r['eps1'], r['s_eps1']), unc(r['s_eps1'])))
    rb.para(['线性相关系数 ', ('t', 'R^{2}', ITALIC), ' = %s。'
             % k(r['eps_fit']['r2'], 4),
             '结果表明拟合的线性还不错。由此得出各参数（字母记号遵从讲义）：'
             '斜率 ', ('t', 'a', ITALIC), ' = (%s ± %s)、' % (val(r['a'], r['s_a']),
                                                             unc(r['s_a'])),
             '截距 ', ('t', 'ε_{1}', ITALIC), ' = (%s ± %s)。'
             % (val(r['eps1'], r['s_eps1']), unc(r['s_eps1']))])


# ---------------------------------------------------------------- 3.3 密度
def _sec_rho(rb, r, png_rho):
    rb.heading('3.3 密度的数据处理', 2)
    rb.heading('3.3.1 密度计测量结果', 3)
    rb.para('DE45 型数字密度计测量的原始数据如表4所示，每组溶液平行测量两次'
            '（两次结果相同，取平均值参与后续计算）。')
    rows = [[str(s['no']), k(s['rho'], 5)] for s in r['solutions']]
    rows.append(['环己烷', k(r['rho_cyc_measured'], 5)])
    rows.append(['正丁醇', k(r['rhoB_de45'], 5)])
    rb.caption('表4  DE45 型密度计测量原始数据')
    rb.table(['编号', 'ρ / (g·cm^{-3})'], rows,
             widths_cm=[2.6, 4.0], keep_together=False)

    rb.heading(['3.3.2 ', ('t', 'ρ', ITALIC), '–', ('t', 'x', ITALIC),
                ' 拟合'], 3)
    rb.para(['结合表1和表4，将溶液密度 ', ('t', 'ρ', ITALIC), ' 和摩尔分数 ',
             ('t', 'x', ITALIC), ' 进行线性拟合，拟合直线如图3所示。'])
    rb.figure(png_rho, caption='图3  密度-摩尔分数拟合直线', width_cm=11.5)
    rb.para('拟合结果如下：', keep_next=True)
    rb.equation(r'ρ=(%s\pm%s)x+(%s\pm%s)'
                % (val(r['b'], r['s_b']), unc(r['s_b']),
                   val(r['rho1'], r['s_rho1']), unc(r['s_rho1'])))
    rb.para(['线性相关系数 ', ('t', 'R^{2}', ITALIC), ' = %s。'
             % k(r['rho_fit']['r2'], 4),
             '由此得出各参数：斜率 ', ('t', 'b', ITALIC), ' = (%s ± %s)、'
             % (val(r['b'], r['s_b']), unc(r['s_b'])),
             '截距 ', ('t', 'ρ_{1}', ITALIC), ' = (%s ± %s) g·cm^{-3}。'
             % (val(r['rho1'], r['s_rho1']), unc(r['s_rho1']))])

    rb.heading('3.3.3 比重瓶测量结果', 3)
    py = r['pycno']
    mw = py['mw']
    rb.para(['利用比重瓶测量密度，瓶重 ', ('t', 'm_{0}', ITALIC), '，'
             '加水后的质量 ', ('t', 'm_{w}', ITALIC), '（平行两次）以及'
             '加正丁醇后的质量 ', ('t', 'm_{B}', ITALIC),
             ' 的原始数据如表5所示。'])
    rb.caption('表5  比重瓶测量原始数据')
    rb.table(['m_{0} / g', 'm_{w1} / g', 'm_{w2} / g', 'm_{B} / g'],
             [[k(py['m0'], 3), k(mw[0], 3),
               k(mw[1], 3) if len(mw) > 1 else '—', k(py['mB'], 3)]],
             widths_cm=[2.9, 2.9, 2.9, 2.9], keep_together=True)
    rb.para(['温度仍取 ', ('t', 'T', ITALIC), ' = %.1f ℃。由水的密度多项式算得 '
             % r['T_c'], ('t', 'ρ_{w}', ITALIC), ' = %s g·cm^{-3}，'
             % k(r['rho_w'], 6),
             '故正丁醇密度的计算公式为：'], keep_next=True)
    rb.equation(r'ρ_{B}=\frac{m_{B}-m_{0}}{m_{w}-m_{0}}ρ_{w}=%s\ g\cdot cm^{-3}'
                % val(r['rhoB_pyc'], 0.00005))
    rb.para(['与 DE45 型密度计的结果（', ('t', 'ρ_{B}', ITALIC), ' = %s '
             % val(r['rhoB_de45'], 0.00005), 'g·cm^{-3}）相比，比重瓶测量的'
             '相对误差为：'], keep_next=True)
    rb.equation(r'E_{r}=\frac{%s-%s}{%s}\times100\%%=%s\%%'
                % (val(r['rhoB_pyc'], 0.00005), val(r['rhoB_de45'], 0.00005),
                   val(r['rhoB_de45'], 0.00005), pct(r['E_r_pyc'])))
    rb.para('两者的相对误差非常小，表明用 DE45 型密度计和比重瓶均能较准确地'
            '测量密度，不存在显著的精确度差异，只是比重瓶在操作上更困难。')



# ---------------------------------------------------------------- 3.4 偶极矩
def _sec_mu(rb, r):
    vA, uA = val(r['A'], r['s_A']), unc(r['s_A'])
    vB, uB = val(r['B'], r['s_B']), unc(r['s_B'])
    vC, uC = val(r['C'], r['s_C']), unc(r['s_C'])
    va, ua = val(r['a'], r['s_a']), unc(r['s_a'])
    vb, ub = val(r['b'], r['s_b']), unc(r['s_b'])
    vP = val(r['P_inf'], r['s_P'])
    vR = val(r['R_molar'], r['s_R'])
    vmu = val(r['mu'], r['s_mu'])

    rb.heading('3.4 偶极矩的计算', 2)
    rb.heading(['3.4.1 总摩尔极化度 ', ('t', 'P₂^{∞}', ITALIC),
                ' 的计算'], 3)
    rb.para([('t', 'P₂^{∞}', ITALIC),
             ' 的计算方法推导遵从讲义（Hedestrand 经验公式），此处不再推导。'
             '首先计算必要的参数，'], keep_next=True)
    rb.para([('t', 'A', ITALIC), '、', ('t', 'B', ITALIC), '、',
             ('t', 'C', ITALIC), ' 及其不确定度的计算公式如下：'], keep_next=True)
    rb.equation(r'A=\frac{ε_{1}-1}{ε_{1}+2}\times\frac{1}{ρ_{1}}'
                r'=%s\ cm^{3}\cdot g^{-1}' % vA)
    rb.equation(r'σ_{A}=\sqrt{(\frac{3σ_{ε_{1}}}{(ε_{1}+2)^{2}}'
                r'\times\frac{1}{ρ_{1}})^{2}+(\frac{ε_{1}-1}{ε_{1}+2}'
                r'\times\frac{σ_{ρ_{1}}}{ρ_{1}^{2}})^{2}}=%s\ cm^{3}\cdot g^{-1}'
                % uA)
    rb.equation(r'B=\frac{M_{1}}{ρ_{1}}=%s\ cm^{3}\cdot mol^{-1}' % vB)
    rb.equation(r'σ_{B}=M_{1}\times\frac{σ_{ρ_{1}}}{ρ_{1}^{2}}'
                r'=%s\ cm^{3}\cdot mol^{-1}' % uB)
    rb.equation(r'C=\frac{3M_{1}}{(ε_{1}+2)^{2}}\times\frac{1}{ρ_{1}}'
                r'=%s\ cm^{3}\cdot mol^{-1}' % vC)
    rb.equation(r'σ_{C}=3M_{1}\times\sqrt{(\frac{2σ_{ε_{1}}}{(ε_{1}+2)^{3}}'
                r'\times\frac{1}{ρ_{1}})^{2}+(\frac{1}{(ε_{1}+2)^{2}}'
                r'\times\frac{σ_{ρ_{1}}}{ρ_{1}^{2}})^{2}}'
                r'=%s\ cm^{3}\cdot mol^{-1}' % uC)
    rb.para([('t', 'P₂^{∞}', ITALIC), ' 及其不确定度的计算公式如下：'],
            keep_next=True)
    rb.equation(r'P₂^{∞}=A(M_{2}-bB)+aC=%s\times(%s-%s\times%s)'
                r'+%s\times%s=%s\ cm^{3}\cdot mol^{-1}'
                r'=%s\times10^{-5}\ m^{3}\cdot mol^{-1}'
                % (vA, k(r['M2'], 3), vb, vB, va, vC, k(r['P_inf'], 2),
                   k(r['P_inf'] / 10.0, 3)))
    rb.equation(r'σ_{P₂^{∞}}=\sqrt{((M_{2}-bB)σ_{A})^{2}+(ABσ_{b})^{2}'
                r'+(Abσ_{B})^{2}+(Cσ_{a})^{2}+(aσ_{C})^{2}}'
                r'=%s\ cm^{3}\cdot mol^{-1}' % unc(r['s_P']))
    rb.para([('t', 'P₂^{∞}', ITALIC), ' 的 SI 单位结果为 ',
             ('t', 'P₂^{∞}', ITALIC), ' = (%s)×10^{-5} m^{3}·mol^{-1}。'
             % pm(r['P_inf'] / 10.0, r['s_P'] / 10.0)])

    rb.heading('3.4.2 摩尔折射度 R 的计算', 3)
    rb.para(['利用阿贝折射仪测量正丁醇的折射率，平均值为 ',
             ('t', 'n', ITALIC), ' = %s。' % val(r['n_d'], r['s_n']),
             '根据实际情况，不妨假设 ', ('t', 'σ_{n}', ITALIC), ' = %s、'
             % k(r['s_n'], 4),
             ('m', r'\sigma_{\rho_{2}}'), ' = %s g·cm^{-3}。' % k(r['s_rho2'], 5),
             '摩尔折射度 ', ('t', 'R', ITALIC), ' 及其不确定度的计算公式如下：'],
            keep_next=True)
    rb.equation(r'R=\frac{n^{2}-1}{n^{2}+2}\times\frac{M_{2}}{ρ_{2}}'
                r'=%s\ cm^{3}\cdot mol^{-1}=%s\times10^{-5}\ m^{3}\cdot mol^{-1}'
                % (vR, k(r['R_molar'] / 10.0, 4)))
    rb.equation(r'σ_{R}=M_{2}\times\sqrt{(\frac{6nσ_{n}}{(n^{2}+2)^{2}}'
                r'\times\frac{1}{ρ_{2}})^{2}+(\frac{n^{2}-1}{n^{2}+2}'
                r'\times\frac{σ_{ρ_{2}}}{ρ_{2}^{2}})^{2}}'
                r'=%s\ cm^{3}\cdot mol^{-1}' % unc(r['s_R']))

    rb.heading(['3.4.3 偶极矩 ', ('t', 'μ', ITALIC), ' 的计算'], 3)
    rb.para('根据实验原理，偶极矩及其不确定度的计算公式如下：', keep_next=True)
    rb.equation(r'μ=12.81\times\sqrt{(P₂^{∞}-R)\times T}'
                r'=12.81\times\sqrt{(%s-%s)\times10^{-5}\times%s}=%s\ D'
                % (k(r['P_inf'] / 10.0, 3), k(r['R_molar'] / 10.0, 4),
                   k(r['T_K'], 2), vmu))
    rb.equation(r'σ_{μ}=12.81\times\sqrt{T}\times'
                r'\frac{\sqrt{σ_{P₂^{∞}}^{2}+σ_{R}^{2}}}'
                r'{2\sqrt{P₂^{∞}-R}}=%s\ D' % unc(r['s_mu']))
    rb.para(['综上，实验测得正丁醇分子的偶极矩为 ', ('t', 'μ', ITALIC),
             ' = (%s) D。' % pm(r['mu'], r['s_mu']),
             '查阅手册^{[2]}，正丁醇分子的偶极矩 ', ('t', 'μ_{0}', ITALIC),
             ' = %.2f D，测量值与文献值一致，足以说明本实验的设计能够使测量'
             '结果较为精确。而该准确度可能带有一定巧合，具体误差分析见第 4 部分。'
             % r['lit_mu']])


# ---------------------------------------------------------------- 4 讨论
def _sec_error(rb, r):
    rb.heading('4.1 本次实验的主要误差来源', 2)
    rb.heading('4.1.1 整体分析', 3)
    rb.para(['虽然偶极矩的测定结果与文献值一致，但这只是准确度。对于精密度，'
             '测量结果具有 ', ('t', 'σ_{μ}', ITALIC), ' = %s D 的不确定度'
             % unc(r['s_mu']),
             '（这里多保留一位，便于比较）。以下采用倒推法讨论不确定度的'
             '主要贡献者。'])
    rb.para(['直接参与 ', ('t', 'μ', ITALIC), ' 的物理量只有总摩尔极化度 ',
             ('t', 'P₂^{∞}', ITALIC), '、摩尔折射度 ', ('t', 'R', ITALIC),
             ' 和温度 ', ('t', 'T', ITALIC), '。其中温度不是主要的误差来源'
             '（见 4.1.2），而 ', ('t', 'σ_{P₂^{∞}}', ITALIC),
             '（%s cm^{3}·mol^{-1}）比 ' % unc(r['s_P']),
             ('t', 'σ_{R}', ITALIC), '（%s cm^{3}·mol^{-1}）大两个数量级。'
             % unc(r['s_R']),
             '故在这三个物理量中，', ('t', 'P₂^{∞}', ITALIC),
             ' 是绝对的主要贡献者。'])
    rb.para(['接着分析总摩尔极化度。直接参与 ', ('t', 'P₂^{∞}', ITALIC),
             ' 的是拟合得到的四个物理量 ', ('t', 'a', ITALIC), '、',
             ('t', 'ε_{1}', ITALIC), '、', ('t', 'b', ITALIC), '、',
             ('t', 'ρ_{1}', ITALIC), '。为了确定哪个物理量占主导，'
             '将每个物理量的不确定度改为 0，所得的新的 ',
             ('t', 'σ_{P₂^{∞}}', ITALIC), ' 如表6所示。'])
    cc = r['c_check']
    s_c_est = cc['sigma_c'] * r['s_a'] / cc['s_a']
    rows = [
        [MATH('a'), k(r['contrib']['a'], 2)],
        [MATH('ε_{1}'), k(r['contrib']['eps1'], 2)],
        [MATH('b'), k(r['contrib']['b'], 2)],
        [MATH('ρ_{1}'), k(r['contrib']['rho1'], 2)],
    ]
    rb.caption('表6  不确定度主要贡献者探究')
    rb.table(['物理量（不确定度改为 0）', 'σ_{P} / (cm^{3}·mol^{-1})'], rows,
             widths_cm=[6.0, 5.2], keep_together=True)
    rb.para(['显而易见，本实验引入不确定度最大的步骤是介电常数-摩尔分数的'
             '线性拟合，其中斜率 ', ('t', 'a', ITALIC),
             ' 是绝对的主要贡献者。当然总摩尔极化度中忽略了摩尔原子极化度 ',
             ('t', 'P_{A}', ITALIC), '，但这并不是主要的误差来源'
             '（见 4.1.3）。'])
    rb.para(['斜率 ', ('t', 'a', ITALIC), ' 的误差来源于拟合数据点的散射。'
             '在没有操作失误的情况下，摩尔分数可以非常精确，故误差的主要来源'
             '就是介电常数的测定误差，而介电常数的测定误差完全取决于电容的'
             '测定误差。综上，本实验的主要误差来源是电容的测量。'
             '不妨估计一下电容测量误差的影响：假设每个电容测量值有 %s pF 的'
             '误差（' % k(cc['sigma_c'], 2), ('t', "σ_{C'}", ITALIC),
             ' = %s pF），则：' % k(cc['sigma_c'], 2)], keep_next=True)
    rb.equation(r"σ_{C_{分}}=σ_{C'}\times\sqrt{(1+\frac{1}{ε_{环}-1})^{2}"
                r"+(\frac{1}{ε_{环}-1})^{2}}=%s\ pF" % k(cc['s_Cdist'], 3))
    rb.equation(r"σ_{C₀}=σ_{C'}\times\sqrt{2\times(\frac{1}{ε_{环}-1})^{2}}"
                r"=%s\ pF" % k(cc['s_C0'], 3))
    rb.equation(r"σ_{ε}=\sqrt{(\frac{σ_{C'}}{C₀})^{2}+(\frac{σ_{C_{分}}}{C₀})^{2}"
                r"+(\frac{(C'_{样}-C_{分})σ_{C₀}}{C₀^{2}})^{2}}=%s"
                % k(cc['s_eps'], 3))
    rb.para(["式中 ", ('t', "C'_{样}", ITALIC), ' 取 1 号溶液的值。'
             '若每个介电常数 ', ('t', 'σ_{ε}', ITALIC), ' = %s，'
             % k(cc['s_eps'], 3),
             '则 5 组数据拟合斜率的不确定度为：'], keep_next=True)
    rb.equation(r'σ_{a}=\frac{σ_{ε}}{\sqrt{Sₓₓ}}=%s'
                % k(cc['s_a'], 2))
    rb.para(['其中 ', ('t', 'Sₓₓ', ITALIC), ' = %s×10^{-3} 是摩尔分数的'
             '离差平方和。这个值已经显著大于本次测量的 ' % k(r['eps_fit']['sxx'] * 1e3, 3),
             ('t', 'σ_{a}', ITALIC), ' = %s。如果 ' % unc(r['s_a']),
             ('t', 'σ_{a}', ITALIC), ' = %s，则会导致 ' % k(cc['s_a'], 2),
             ('t', 'σ_{P₂^{∞}}', ITALIC), ' = %s cm^{3}·mol^{-1}、'
             % k(cc['s_P'], 2),
             ('t', 'σ_{μ}', ITALIC), ' = %s D，大约是现在的两倍。'
             % k(cc['s_mu'], 3),
             '观察发现 ', ('t', 'σ_{a}', ITALIC), ' 和 ', ('t', 'σ_{ε}', ITALIC),
             ' 与电容的测量精度成正比：这一方面可以估测本次实验电容测量的'
             '不确定度，大约为 ', ('t', "σ_{C'}", ITALIC), ' ≈ %s×%s÷%s = %s pF；'
             % (k(cc['sigma_c'], 2), unc(r['s_a']), k(cc['s_a'], 2),
                k(s_c_est, 3)),
             '另一方面表明，如果有更高级的测量技术使电容测量的精度降为 '
             '0.001 pF，则 ', ('t', 'σ_{a}', ITALIC),
             ' 会变成约 %s，实验结果的不确定度会有显著提升。'
             % k(cc['s_a'] * 0.1, 3)])
    rb.para('综上，电容测量的细节（如溶剂是否吹干、是否恒温）是决定实验结果'
            '好坏的关键，同时也说明提升电容的测量精度是改进实验的首要考虑因素。')

    rb.heading('4.1.2 温度不是主要的误差来源', 3)
    tc = r['T_check']
    rb.para('假设测量时温度有 σ_T = %.1f ℃ 的波动（已经相当保守），'
            '则偶极矩不确定度的计算公式为：' % tc['sigma_T'], keep_next=True)
    rb.equation(r'σ_{μ}=12.81\times\frac{1}{2}\times\sqrt{\frac{T}{P₂^{∞}-R}'
                r'\times(σ_{P₂^{∞}}^{2}+σ_{R}^{2})'
                r'+\frac{P₂^{∞}-R}{T}\timesσ_{T}^{2}}=%s\ D' % unc(tc['s_mu']))
    rb.para('该结果与不考虑温度误差的不确定度十分接近，'
            '故温度不是主要的误差来源。')

    rb.heading('4.1.3 对摩尔原子极化度的忽略不是主要的误差来源', 3)
    pa = r['P_atom']
    rb.para(['查阅教材^{[3]}，摩尔原子极化度 ', ('t', 'P_{A}', ITALIC),
             ' 大约占总摩尔极化度的 %d%%。' % round(pa['frac'] * 100),
             '对于本次实验 ', ('t', 'P₂^{∞}', ITALIC), ' = %s cm^{3}·mol^{-1}，'
             % val(r['P_inf'], r['s_P']),
             '该误差的贡献大约为 %s cm^{3}·mol^{-1}。' % k(pa['s_add'], 2),
             '修正后的不确定度为：'], keep_next=True)
    rb.equation(r'σ_{P₂^{∞}}=\sqrt{%s^{2}+%s^{2}}=%s\ cm^{3}\cdot mol^{-1}'
                % (unc(r['s_P']), k(pa['s_add'], 2), k(pa['s_P_corr'], 2)))
    rb.para(['由此计算出的 ', ('t', 'σ_{μ}', ITALIC), ' = %s D，'
             % unc(pa['s_mu']),
             '只影响到小数点后第 3 位，故对摩尔原子极化度的忽略不是主要的'
             '误差来源。'])


def _sec_extrap(rb, r):
    rb.heading('4.2 直接测量法和外延法所得结果比较', 2)
    rb.para('在数据处理的过程中发现了一个不正常的现象：介电常数和密度对摩尔'
            '分数线性拟合后，外推得到的纯溶剂的介电常数和密度显著小于环己烷'
            '的实测值，结果列于表7。')
    rows = [
        [MATH('ε_{1}'), k(r['eps_cyc'], 3), val(r['eps1'], r['s_eps1'])],
        [MATH('ρ_{1}'), k(r['rho_cyc_measured'], 5),
         val(r['rho1'], r['s_rho1'])],
    ]
    rb.caption('表7  环己烷物理量实测值和外推值比较')
    rb.table(['物理量', '实测值', '外推值'], rows,
             widths_cm=[3.4, 3.4, 3.4], keep_together=True)
    rb.para('表中 ρ₁ 以 g·cm⁻³ 计。由于介电常数是理论计算得到的，'
            '且密度的测量不太可能引入较大误差，故一定是外推值出了问题。'
            '在实验操作没有显著问题的情况下，只能从实验原理的角度考虑原因：'
            '本实验最重要的假设是稀溶液假设，所有的线性拟合只能在稀溶液条件'
            '下进行。出现该现象是因为本实验选取的浓度范围（x ≈ 0.05~0.15）'
            '已经超出了稀溶液。文献表明，实际的介电常数/密度-摩尔分数曲线是'
            '一条 S 型曲线：开始斜率较低，中间较高，后来又较低。本实验的'
            '5 个浓度属于中间段，线性还不错，但截距显著偏低。讲义不选更稀的'
            '溶液，可能是因为更稀的溶液更容易在配制与挥发上引入较大的人为'
            '误差；而选取中间段也能得到较精确的结果，增加了实验的鲁棒性，'
            '但这种选取在理论上并不严谨，所以实验结果的准确度带有一定巧合。')
    rb.para('综上，第二个改进方向是：配制大量不同浓度（尤其低浓度）的溶液'
            '绘制介电常数/密度-摩尔分数曲线，确认所选浓度是否属于稀溶液范围；'
            '再在稀溶液范围内寻找兼顾理论严谨性与鲁棒性的浓度点。')


def _sec_compare(rb):
    rb.heading('4.3 DE45 型数字密度计和比重瓶（管）的比较', 2)
    rb.para('经过对 DE45 型数字密度计和比重瓶在实验结果和操作上的对比，'
            '可以从以下方面进行比较。测量速度：密度计很快，几分钟即可测定'
            '一个样品；比重瓶对操作要求较高且需测基准物质，耗时较长。'
            '样品用量：密度计用量少，2 mL 已足够；比重瓶要充满整个瓶体，'
            '用量较多。操作难度：密度计简单培训即可操作；比重瓶（管）'
            '需要熟练技巧，操作细节（瓶内不能有气泡、液面对齐刻度）'
            '对结果准确性影响极大。精度与准确度：密度计精度高、重复性好，'
            '可达 0.00001 g·cm⁻³；比重瓶（管）准确度高，是基准方法之一，'
            '但实际精度受限于天平精度和操作者水平。成本：密度计更贵，'
            '且有清洗溶剂、干燥用气体的运行成本。')
    rb.para('综上，需要大量测量溶液密度时（如绘制工作曲线）用密度计更方便；'
            '对准确度有极高要求时（如标准物质的基准定值）则应使用比重瓶（管）。')


def _sec_summary(rb, r):
    rb.heading('4.4 小结', 2)
    rb.para(['本实验通过测量正丁醇的摩尔转向极化度，由其与偶极矩的关系测定'
             '了正丁醇的偶极矩 ', ('t', 'μ', ITALIC), '。摩尔转向极化度由'
             '总摩尔极化度 ', ('t', 'P₂^{∞}', ITALIC), ' 减去摩尔电子'
             '极化度（即摩尔折射度 ', ('t', 'R', ITALIC), '）确定。'])
    rb.para(['前者通过 Hedestrand 经验公式，以环己烷为溶剂，测量不同浓度'
             '溶液的介电常数和密度确定：桥法测电容换算介电常数，'
             'DE45 型密度计测密度，两条线性拟合外推得 ',
             ('t', 'P₂^{∞}', ITALIC), ' = (%s)×10^{-5} m^{3}·mol^{-1}；'
             % pm(r['P_inf'] / 10.0, r['s_P'] / 10.0),
             '后者由折射率和密度算得 ', ('t', 'R', ITALIC), ' = (%s)×10^{-5} '
             % pm(r['R_molar'] / 10.0, r['s_R'] / 10.0),
             'm^{3}·mol^{-1}。最终测得正丁醇的偶极矩 ',
             ('t', 'μ', ITALIC), ' = (%s) D，与文献值 %.2f D 一致，表明测量'
             '较为精确。' % (pm(r['mu'], r['s_mu']), r['lit_mu']),
             '讨论部分表明，本实验的主要误差来源是电容的测量；改进方向有'
             '两个方面：提高电容测量的精度以降低结果的不确定度，'
             '以及探究更稀浓度的溶液是否还能得到相对准确的结果。'])
