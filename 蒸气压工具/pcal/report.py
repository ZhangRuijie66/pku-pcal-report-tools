# -*- coding: utf-8 -*-
"""生成《液体饱和蒸气压的测定》实验报告 .docx。

结构照同课程 2025 年参考报告（2300012602-李晨曦-蒸气压）：
    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分（2.1 仪器和试剂 / 2.2 实验内容）
    3 数据与结果
      3.1 动态法测定水的蒸气压（表1~3、图2~3）
      3.2 静态法测定环己烷的蒸气压（表4~6、图4~5）
    4 讨论与结论（4.1/4.2 误差分析、4.3 楚顿规则、4.4 小结）
    参考文献

排版口径与 skill 一致：只报数值的式子一律普通文本（变量斜体 + 单位正体），
参与推导/代入计算的才用公式对象；结果末位与不确定度末位对齐（± 两侧留空格）。
相对偏差按打印出来的修约值计算，保证正文里等式两边自洽。
"""
from __future__ import annotations

import decimal
import os

import numpy as np
from docx.shared import Cm

from . import plotting
from .docxkit import ReportBuilder

ITALIC = {'italic': True}
TITLE = '液体饱和蒸气压的测定'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')

# ln(p/p^{⊖})：整块给表头/正文都会把 ln 排成斜体，拆成片段
SEG_LNPP = [('t', 'ln(', {}), ('t', 'p', ITALIC), ('t', '/', {}),
            ('t', 'p', ITALIC), ('t', '^{⊖})', {})]
HDR_LNPP = [(t, o) for _, t, o in SEG_LNPP]


# ---------------------------------------------------------------- 数字格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


def smart(x, nd=2):
    """按精度打印并去掉末尾多余的 0：353.90 → '353.9'，373.15 → '373.15'。"""
    s = '%.*f' % (nd, float(x))
    return s.rstrip('0').rstrip('.') if '.' in s else s


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


def signed_pct(x):
    if x is None or not np.isfinite(x):
        return '—'
    return ('+' if x >= 0 else '') + pct(x) + '%'


def rel_pct(x_printed, lit):
    """相对偏差按打印出来的修约值算，正文等式两边才能自洽（参考报告口径）。"""
    return (float(x_printed) - float(lit)) / float(lit) * 100.0


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    water = analysis['water']
    cyclo = analysis['cyclo']
    p1 = float(analysis.get('p1', 101.3))
    trouton = float(analysis.get('trouton', 88.0))
    liquids = [m for m in (water, cyclo) if m.get('fit')]

    # 打印精度下的相对偏差（4.x 的 E_r 等式与摘要、汇总表共用）
    for m in liquids:
        f = m['fit']
        lit = m['lit']
        m['rel_tb_p'] = rel_pct(val(f['tb'], f['sigma_tb']), lit['tb'])
        m['rel_dh_p'] = rel_pct(val(f['dh_kJ'], f['sigma_dh_kJ']), lit['dh'])

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
        log('⚠ 封面缺字段：%s（请在界面左侧「报告封面」里填上）' % '、'.join(missing))
    rb.set_cover(cover, title_size=22.0)
    rb.set_header_title(TITLE)

    os.makedirs(plots_dir, exist_ok=True)

    # ---- 出图
    log('绘制插图…')
    import matplotlib.pyplot as plt

    def save(fig, name):
        path = os.path.join(plots_dir, name)
        fig.savefig(path, dpi=plotting.DPI)
        plt.close(fig)
        return path

    pngs = {}
    for m in liquids:
        pngs[m['key']] = (
            save(plotting.make_curve_figure(m), 'pt_%s.png' % m['key']),
            save(plotting.make_fit_figure(m), 'fit_%s.png' % m['key']),
        )

    # ---- 图/表编号：图1 固定给引言占位；缺数据的液体不占号，后面顺延
    tbl_no, fig_no = {}, {}
    n_tbl, n_fig = 0, 1
    for m in liquids:
        tbl_no[m['key']] = (n_tbl + 1, n_tbl + 2, n_tbl + 3)
        fig_no[m['key']] = (n_fig + 1, n_fig + 2)
        n_tbl += 3
        n_fig += 2
    tbl_summary = n_tbl + 1 if liquids else None

    # ================================================================ 摘要
    log('撰写摘要…')
    abs_segs = [{'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
                '本实验用动态法测定了不同外压下纯水的沸点，用静态法测定了环己烷'
                '在不同外压下气液平衡的温度，经克拉贝龙-克劳修斯方程线性拟合，'
                '求得常压沸点、摩尔蒸发焓与摩尔蒸发熵。']
    for m in liquids:
        f = m['fit']
        abs_segs += [
            '%s的 ' % m['name'], ('t', 'T_{b}', ITALIC), ' = (%s) K、'
            % pm(f['tb'], f['sigma_tb']),
            ('t', 'Δ_{vap}H_{m}', ITALIC), ' = (%s) kJ·mol^{-1}、'
            % pm(f['dh_kJ'], f['sigma_dh_kJ']),
            ('t', 'Δ_{vap}S_{m}', ITALIC), ' = (%s) J·mol^{-1}·K^{-1}；'
            % pm(f['ds'], f['sigma_ds']),
        ]
    if liquids:
        names = '、'.join(m['name'] for m in liquids)
        rels = ' 与 '.join(signed_pct(m['rel_dh_p']) for m in liquids)
        abs_segs += ['与文献值相比，%s摩尔蒸发焓的相对偏差分别为 %s。'
                     % (names, rels)]
    hot = [m for m in liquids if m['rel_tb_p'] > 0]
    if hot:
        abs_segs.append('%s的常压沸点存在系统性正偏差，可能与测温系统的固有误差'
                        '有关。' % '、'.join(m['name'] for m in hot))
    abs_segs.append('最后将蒸发熵与楚顿规则进行了比较。')
    rb.para(abs_segs)
    rb.para([{'text': '关键词 ', 'bold': True},
             '饱和蒸气压；克拉贝龙-克劳修斯方程；摩尔蒸发焓；楚顿规则；环己烷'])
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
    rb.heading('2.1.1 试剂', 3)
    rb.para('环己烷（AR），二次去离子水。')
    rb.heading('2.1.2 仪器', 3)
    rb.para('平衡管，1000 mL 烧杯，250 mL 两口圆底烧瓶，数字式温度-压力测定仪，'
            '电加热器，循环水真空泵，带电热套的磁力搅拌装置，冷凝水循环系统，'
            '真空缓冲罐，直形冷凝管，搅拌磁子，真空脂，电脑（自备）。')

    rb.heading('2.2 实验内容', 2)
    rb.heading('2.2.1 动态法测定水的蒸气压', 3)
    rb.para('将盛有约 150 mL 二次水和一个磁子的两口圆底烧瓶置于电加热套上，'
            '在磨口处涂真空脂，将其与冷凝管连接。开启搅拌，将温度探头通过橡皮塞'
            '插入烧瓶的侧口，使探头尖端刚刚与液面接触。关闭大气阀，打开真空阀'
            '降压至约 50 kPa，检验系统气密性（若压力值在 3 min 内无显著变化，'
            '则气密性良好）。打开冷凝水，搅拌加热，当烧瓶中水沸腾且温度保持平稳时，'
            '记下相应的温度、压力值。微微开启大气阀，使压力升高约 5 kPa，'
            '重复上述步骤，记录温度、压力值。如此反复，最后一次将系统与大气完全'
            '相通，平行测定 3 次大气压沸点。最后，从实验室的表上读取大气压和'
            '室内温度。')
    rb.heading('2.2.2 静态法测定环己烷的蒸气压', 3)
    rb.para('实验室事先已装好仪器。打开冷凝水，关闭大气阀，打开真空阀降压至'
            '约 50 kPa，检验系统气密性（若压力值在 3 min 内无显著变化，'
            '则气密性良好）。使体系与大气相通，水浴加热至 83 ℃ 左右，停止加热。'
            '温度下降过程中 b 管液面开始下降，c 管液面开始上升。当两管液面相平时，'
            '迅速记录相应的温度和压力。再次加热，重复上述步骤，平行测定 3 次。'
            '测完常压沸点后迅速关闭大气阀。微微开启真空阀，使压力降低约 5 kPa，'
            '此时液体沸腾。逐渐降温，在两管液面相平时迅速记录相应的温度和压力。'
            '如此重复至体系压力降至约 50 kPa。最后，开启大气阀，从实验室的表上'
            '读取大气压和室内温度。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    for i, m in enumerate(liquids):
        log('写%s…' % m['section'])
        _sec_liquid(rb, m, p1, i + 1, tbl_no[m['key']], fig_no[m['key']],
                    pngs[m['key']])

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    for i, m in enumerate(liquids):
        log('写%s的误差分析…' % m['name'])
        _sec_error(rb, m, p1, i + 1)
    if liquids:
        _sec_trouton(rb, liquids, trouton)
        _sec_summary(rb, liquids, tbl_summary)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）'
            '[M]. 北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] Haynes W M. CRC handbook of chemistry and physics[M]. '
            'CRC press, 2016.', indent_chars=0)
    rb.para('[3] Jochems R, Dekker H, Mosselman C, Somsen G. The use of the '
            'LKB 8721-3 vaporization calorimeter to measure enthalpies of '
            'sublimation[J]. J. Chem. Thermodyn., 1982, 14 (4): 395–398.',
            indent_chars=0)
    rb.para("[4] Atkins P W, De Paula J, Keeler J. Atkins' physical chemistry"
            '[M]. Oxford university press, 2023.', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 单支液体
def _direction(m):
    s = m.get('series') or []
    if len(s) >= 2 and s[-1][0] < s[0][0]:
        return '降压'
    return '升压'


def _atm_table(rb, m, no):
    atm = m['atm']
    rows = []
    for i, (p, t) in enumerate(atm):
        rows.append([str(i + 1), k(p, 2), k(t, 2), k(t + 273.15, 2)])
    if len(atm) > 1:
        p_avg = float(np.mean([r[0] for r in atm]))
        t_avg = float(np.mean([r[1] for r in atm]))
        rows.append(['平均', k(p_avg, 2), k(t_avg, 2), k(t_avg + 273.15, 2)])
    rb.caption('表%d  大气压下%s的沸点测定' % (no, m['name']))
    rb.table(['组别', 'p_{0} / kPa', 'T / ℃', 'T / K'], rows,
             widths_cm=[2.2, 3.2, 3.2, 3.2], keep_together=True)


def _series_table(rb, m, no):
    rows = []
    for i, (p, t) in enumerate(m['series']):
        rows.append([str(i + 1), k(p, 2), k(t, 2), k(t + 273.15, 2)])
    rb.caption('表%d  %s的温度、压力原始数据' % (no, m['name']))
    rb.table(['编号', 'p / kPa', 'T / ℃', 'T / K'], rows,
             widths_cm=[2.2, 3.2, 3.2, 3.2], keep_together=False)


def _final_table(rb, m, no):
    rows = []
    for i, r in enumerate(m['fit']['points']):
        rows.append([str(i + 1), '%.4f' % r['lnp'],
                     '%.4f×10^{-3}' % (r['x'] * 1.0e3)])
    rb.caption('表%d  %s的最终数据' % (no, m['name']))
    rb.table(['编号', HDR_LNPP, '1/T / K^{-1}'], rows,
             widths_cm=[2.2, 4.4, 4.4], keep_together=False)


def _sec_liquid(rb, m, p1, idx, tbls, figs, pngs):
    f = m['fit']
    name = m['name']
    atm_n = len(m['atm'])
    n_total = len(f['points'])
    direction = _direction(m)

    rb.heading('3.%d %s' % (idx, m['section']), 2)
    # ---- 3.x.1 原始数据
    rb.heading('3.%d.1 原始数据记录' % idx, 3)
    atm_txt = ('（平行测定 %d 次，取平均参与拟合）' % atm_n) if atm_n > 1 else ''
    rb.para([
        '大气压下%s的沸点数据如表%d所示%s，%s过程中%s的温度、压力原始数据'
        '如表%d所示。为后续计算方便，将温度换算为开尔文温度：'
        % (name, tbls[0], atm_txt, direction, name, tbls[1]),
    ], keep_next=True)
    rb.equation(r'\frac{T}{\mathrm{K}}=\frac{T}{°\mathrm{C}}+273.15')
    if m['atm']:
        _atm_table(rb, m, tbls[0])
    _series_table(rb, m, tbls[1])

    # ---- 3.x.2 光滑曲线
    rb.heading('3.%d.2 蒸气压-温度光滑曲线' % idx, 3)
    src = ('表%d和表%d' % (tbls[0], tbls[1])) if m['atm'] \
        else ('表%d' % tbls[1])
    rb.para('根据%s的 %d 个数据点，拟合出%s的蒸气压-温度光滑曲线如图%d所示。'
            % (src, n_total, name, figs[0]))
    rb.figure(pngs[0], caption='图%d  %s的蒸气压-温度光滑曲线' % (figs[0], name),
              width_cm=11.5)

    # ---- 3.x.3 克氏拟合
    rb.heading('3.%d.3 克拉贝龙-克劳修斯方程的拟合' % idx, 3)
    rb.para('对数据的定量分析基于克拉贝龙-克劳修斯方程。根据该方程，'
            '压力和温度存在如下关系：', keep_next=True)
    rb.equation(r'\ln\frac{p}{p^{⊖}}=-\frac{\Delta_{vap}H_{m}}{R}'
                r'\cdot\frac{1}{T}+C')
    rb.para([
        '其中 ', ('t', 'p^{⊖}', ITALIC), ' 是为了消除量纲加入的，取 ',
        ('t', 'p^{⊖}', ITALIC), ' = 100 kPa。据此对 ',
    ] + SEG_LNPP + [
        '–', ('t', '1/T', ITALIC),
        ' 作线性回归。将表%d与表%d的数据合并，处理后的结果如表%d所示，'
        '其中数据按 ' % (tbls[0] if m['atm'] else tbls[1], tbls[1], tbls[2]),
        ('t', '1/T', ITALIC), ' 从小到大排布。',
    ])
    _final_table(rb, m, tbls[2])
    rb.para('表%d的线性拟合结果如图%d所示。' % (tbls[2], figs[1]))
    rb.figure(pngs[1], caption='图%d  %s的 ln(p/p^{⊖})–1/T 拟合直线'
              % (figs[1], name), width_cm=11.0)
    rb.para('曲线的拟合结果如下：', keep_next=True)
    rb.equation(r'\ln\frac{p}{p^{⊖}}=-(%s\pm%s)\times10^{3}'
                r'\times\frac{1}{T}+(%s\pm%s)'
                % (val(f['A'] / 1e3, f['sigma_A'] / 1e3),
                   unc(f['sigma_A'] / 1e3), val(f['B'], f['sigma_B']),
                   unc(f['sigma_B'])))
    rb.para(['线性相关系数 ', ('t', 'R^{2}', ITALIC), ' = %s。' % k(f['r2'], 5)])

    # ---- 3.x.4 热力学量
    rb.heading('3.%d.4 热力学量及其不确定度的计算' % idx, 3)
    _sec_thermo(rb, m, f, p1, idx)

    # ---- 复算（只有水且常压沸点偏高时才有意义）
    if m['key'] == 'water' and m.get('shift') and m['rel_tb_p'] > 0:
        _sec_shift(rb, m, idx)


def _sec_thermo(rb, m, f, p1, idx):
    """3.x.4.1 常压沸点 / 3.x.4.2 摩尔蒸发焓 / 3.x.4.3 摩尔蒸发熵。"""
    vA = val(f['A'] / 1e3, f['sigma_A'] / 1e3)
    uA = unc(f['sigma_A'] / 1e3)
    vB = val(f['B'], f['sigma_B'])
    uB = unc(f['sigma_B'])

    rb.heading('3.%d.4.1 常压沸点（%.1f kPa）' % (idx, p1), 4)
    rb.para(['在 ', ('t', 'p_{1}', ITALIC), ' = %.1f kPa 下，对于方程：' % p1],
            keep_next=True)
    rb.equation(r'\ln\frac{p}{p^{⊖}}=-A\times\frac{1}{T}+B')
    rb.para(['其中 ', ('t', 'A', ITALIC), ' = (%s ± %s)×10^{3}，' % (vA, uA),
             ('t', 'B', ITALIC), ' = %s ± %s。' % (vB, uB)], keep_next=True)
    rb.para('常压沸点的公式及结果为：', keep_next=True)
    rb.equation(r'T_{b}=\frac{A}{B-\ln(p_{1}/p^{⊖})}=%s\ K'
                % val(f['tb'], f['sigma_tb']))
    rb.para('不确定度的公式及结果为：', keep_next=True)
    rb.equation(r'\sigma_{T_{b}}=\sqrt{(\frac{\sigma_{A}}{B-\ln(p_{1}/p^{⊖})})^{2}'
                r'+(\frac{A\sigma_{B}}{(B-\ln(p_{1}/p^{⊖}))^{2}})^{2}}=%s\ K'
                % unc(f['sigma_tb']))
    rb.para(['综上，常压沸点的结果为 ', ('t', 'T_{b}', ITALIC), ' = (%s) K。'
             % pm(f['tb'], f['sigma_tb'])])

    rb.heading('3.%d.4.2 摩尔蒸发焓' % idx, 4)
    rb.para('将拟合结果对比克拉贝龙-克劳修斯方程，可得出：', keep_next=True)
    rb.equation(r'-\frac{\Delta_{vap}H_{m}}{R}=-(%s\pm%s)\times10^{3}\ K'
                % (vA, uA))
    rb.para('故摩尔蒸发焓为：', keep_next=True)
    rb.equation(r'\Delta_{vap}H_{m}=(%s\pm%s)\times10^{3}\times8.314'
                r'\times10^{-3}\ kJ\cdot mol^{-1}'
                r'=(%s\pm%s)\ kJ\cdot mol^{-1}'
                % (vA, uA, val(f['dh_kJ'], f['sigma_dh_kJ']),
                   unc(f['sigma_dh_kJ'])))

    rb.heading('3.%d.4.3 摩尔蒸发熵' % idx, 4)
    rb.para('常压沸点及摩尔蒸发焓已求出，摩尔蒸发熵的公式及结果为：', keep_next=True)
    rb.equation(r'\Delta_{vap}S_{m}=\frac{\Delta_{vap}H_{m}}{T_{b}}'
                r'=\frac{%s\times10^{3}}{%s}=%s\ J\cdot mol^{-1}\cdot K^{-1}'
                % (val(f['dh_kJ'], f['sigma_dh_kJ']),
                   val(f['tb'], f['sigma_tb']),
                   val(f['ds'], f['sigma_ds'])))
    rb.para('其不确定度的公式及结果为：', keep_next=True)
    rb.equation(r'\sigma_{\Delta_{vap}S_{m}}=\sqrt{(\frac{\sigma_{\Delta_{vap}H_{m}}}'
                r'{T_{b}})^{2}+(\frac{\Delta_{vap}H_{m}\sigma_{T_{b}}}{T_{b}^{2}})^{2}}'
                r'=%s\ J\cdot mol^{-1}\cdot K^{-1}'
                % unc(f['sigma_ds']))
    rb.para(['综上，常压下摩尔蒸发熵的结果为 ',
             ('t', 'Δ_{vap}S_{m}', ITALIC), ' = (%s) J·mol^{-1}·K^{-1}。'
             % pm(f['ds'], f['sigma_ds'])])


def _sec_shift(rb, m, idx):
    """水：假设整体温度偏高 Δt ℃ 后重新拟合的对照（参考报告 4.1.2 的思路，
    属于代入计算，故放在 3.1.4 末尾，4.1.2 只引用其结论）。"""
    shift = m['shift']
    f = shift['fit']
    dlt = shift['shift']
    vA = val(f['A'] / 1e3, f['sigma_A'] / 1e3)
    uA = unc(f['sigma_A'] / 1e3)
    vB = val(f['B'], f['sigma_B'])
    uB = unc(f['sigma_B'])
    rb.heading('3.%d.4.4 温度整体偏高 %.1f ℃ 时的复算' % (idx, dlt), 4)
    rb.para('为了直观体现温度正偏差带来的影响，不妨假设每个数据点的温度都偏高 '
            '%.1f ℃，将每个温度减去 %.1f ℃ 重新线性回归，得到的拟合直线为：'
            % (dlt, dlt), keep_next=True)
    rb.equation(r'\ln\frac{p}{p^{⊖}}=-(%s\pm%s)\times10^{3}'
                r'\times\frac{1}{T}+(%s\pm%s)' % (vA, uA, vB, uB))
    rb.para('故摩尔蒸发焓为：', keep_next=True)
    rb.equation(r'\Delta_{vap}H_{m}=(%s\pm%s)\times10^{3}\times8.314'
                r'\times10^{-3}\ kJ\cdot mol^{-1}'
                r'=(%s\pm%s)\ kJ\cdot mol^{-1}'
                % (vA, uA, val(f['dh_kJ'], f['sigma_dh_kJ']),
                   unc(f['sigma_dh_kJ'])))


# ---------------------------------------------------------------- 4 误差分析
def _sec_error(rb, m, p1, idx):
    f = m['fit']
    name = m['name']
    lit = m['lit']
    lit_tb = smart(lit['tb'])
    lit_dh = smart(lit['dh'])
    tb_p = val(f['tb'], f['sigma_tb'])
    dh_p = val(f['dh_kJ'], f['sigma_dh_kJ'])

    rb.heading('4.%d %s的误差分析' % (idx, name), 2)
    rb.heading('4.%d.1 常压沸点（%.1f kPa）' % (idx, p1), 3)
    rb.para(['%s的常压沸点为 %s K，测定结果为 ' % (name, lit_tb),
             ('t', 'T_{b}', ITALIC), ' = (%s) K，' % pm(f['tb'], f['sigma_tb']),
             '则测定结果的相对误差为：'], keep_next=True)
    rb.equation(r'E_{r}(T_{b})=\frac{%s-%s}{%s}\times100\%%=%s\%%'
                % (tb_p, lit_tb, lit_tb, signed_pct(m['rel_tb_p'])[:-1]))
    rb.para('说明测定结果与真值符合较好。不确定度的计算过程表明其主要来自'
            '拟合直线斜率和截距的误差，与实验仪器和操作的关系较小。')
    if m['rel_tb_p'] > 0.2:
        atm_txt = ''
        if m.get('atm_avg'):
            atm_txt = ('大气压下的沸点（完全由实验直接测得）为 %s K，同样存在'
                       '正偏差，说明该偏差来自实验本身而不是计算过程。'
                       % k(m['atm_avg']['t'] + 273.15, 2))
        rb.para('对于正的相对误差，' + atm_txt +
                '实验中液体沸腾后温度示数难以立刻稳定（过热效应），但它影响的'
                '是波动幅度而不是单向偏差；更可能的原因是温度测量系统存在固有'
                '正偏差，即探头或读数系统未校准导致的系统误差。')
        if m['key'] == 'water' and m.get('shift'):
            f2 = m['shift']['fit']
            dh2_p = val(f2['dh_kJ'], f2['sigma_dh_kJ'])
            better = abs(float(dh2_p) - lit['dh']) < abs(float(dh_p) - lit['dh'])
            rb.para(['这一系统偏差对摩尔蒸发焓的影响在 3.%d.4.4 的复算中'
                     '可以直接看到：把每个数据点的温度减去 %.1f ℃ 后，'
                     % (idx, m['shift']['shift']),
                     '摩尔蒸发焓从 (%s) 变为 (%s) kJ·mol^{-1}%s，'
                     % (pm(f['dh_kJ'], f['sigma_dh_kJ']),
                        pm(f2['dh_kJ'], f2['sigma_dh_kJ']),
                        '，与文献值更加接近' if better else ''),
                     '说明蒸发焓的正误差主要来自温度的正偏差。'])

    rb.heading('4.%d.2 摩尔蒸发焓' % idx, 3)
    if m['key'] == 'water':
        src = '查询手册^{[2]}，水在 82~100 ℃ 之间的平均摩尔蒸发焓为 %s kJ·mol^{-1}。' \
            % lit_dh
    else:
        src = '查询文献^{[3]}，环己烷在 58~80.7 ℃ 之间的平均摩尔蒸发焓为 %s kJ·mol^{-1}。' \
            % lit_dh
    rb.para([src, '则测定结果的相对误差为：'], keep_next=True)
    rb.equation(r'E_{r}(\Delta_{vap}H_{m})=\frac{%s-%s}{%s}\times100\%%=%s\%%'
                % (dh_p, lit_dh, lit_dh, signed_pct(m['rel_dh_p'])[:-1]))
    if m['rel_dh_p'] > 0 and m['key'] == 'water' and m.get('shift'):
        rb.para('该误差主要来自温度的正偏差：每个数据点温度偏高使 1/T 非线性地'
                '偏低，拟合直线斜率的绝对值偏大，蒸发焓偏高（见 3.%d.4.4 的'
                '复算）。' % idx)
    else:
        rb.para('该误差主要来自拟合过程，实验操作对误差的影响较小。')


def _sec_trouton(rb, liquids, trouton):
    rb.heading('4.3 与楚顿规则的比较分析', 2)
    rb.para(['楚顿规则表述为^{[4]}：在标准沸点下，许多非极性液体的摩尔蒸发熵'
             '近似为一个常数，', ('t', 'Δ_{vap}S_{m}', ITALIC),
             ' ≈ %d J·mol^{-1}·K^{-1}。' % int(round(trouton))])
    for m in liquids:
        f = m['fit']
        diff = m.get('ds_minus_trouton')
        good = diff is not None and abs(diff) <= 0.15 * trouton
        word = '与楚顿规则符合较好' if good else '显著偏离楚顿规则'
        rb.para(['由测定结果：%s的摩尔蒸发熵为 ' % m['name'],
                 ('t', 'Δ_{vap}S_{m}', ITALIC), ' = (%s) J·mol^{-1}·K^{-1}，%s。'
                 % (pm(f['ds'], f['sigma_ds']), word)])
    rb.para('这是符合预期的。楚顿规则的物理基础是：对于简单液体，蒸发过程可以'
            '看作分子从有一定有序度的凝聚相进入高度无序的气相，只要分子间作用力'
            '以范德华力为主，这种无序度的增加对不同分子是相近的。环己烷是典型的'
            '非极性、近似球形的分子，液相中主要存在色散力，蒸发熵仅来源于体积'
            '膨胀和平动自由度的增加，所以符合楚顿规则。反之，水分子之间存在'
            '强烈的氢键，氢键网络形成高度有序的三维结构，蒸发过程除体积膨胀外'
            '还要破坏这部分有序结构，额外的熵增使水的摩尔蒸发熵显著大于楚顿'
            '规则的经验值。')


def _sec_summary(rb, liquids, tbl_no):
    rb.heading('4.4 小结', 2)
    rb.para(['本实验分别通过动态法和静态法测定了水和环己烷在不同饱和蒸气压下的'
             '沸点，得到一系列 ', ('t', 'p', ITALIC), '–', ('t', 'T', ITALIC),
             ' 数据点。基于克拉贝龙-克劳修斯方程对 '] + SEG_LNPP + [
        '–', ('t', '1/T', ITALIC),
        ' 作线性回归，由拟合直线求得各热力学量，结果汇总于表%d。' % tbl_no])
    rows = []
    for m in liquids:
        f = m['fit']
        rows.append([
            m['name'], '(%s)' % pm(f['tb'], f['sigma_tb']),
            '(%s)' % pm(f['dh_kJ'], f['sigma_dh_kJ']),
            '(%s)' % pm(f['ds'], f['sigma_ds']),
            signed_pct(m['rel_dh_p']),
        ])
    rb.caption('表%d  水和环己烷的热力学量汇总' % tbl_no)
    rb.table(['液体', 'T_{b} / K', 'Δ_{vap}H_{m} / (kJ·mol^{-1})',
              'Δ_{vap}S_{m} / (J·mol^{-1}·K^{-1})', '蒸发焓相对偏差'],
             rows, widths_cm=[1.6, 3.0, 3.7, 4.2, 2.9], keep_together=True)
    rb.para('其中环己烷的各热力学量与文献值符合较好；水的常压沸点与蒸发焓存在'
            '系统性正偏差，主要来自温度测量系统的固有误差。环己烷的摩尔蒸发熵'
            '与楚顿规则符合较好，水则因氢键网络而显著偏高。')
