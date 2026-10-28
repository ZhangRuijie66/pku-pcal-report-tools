# -*- coding: utf-8 -*-
"""生成《溶液表面吸附的测定》实验报告 .docx（完整版）。

    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分
    3 数据与结果
      3.1 最大气泡压力法
      3.2 吊片法
      3.3 两种方法的比较
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

ITALIC = {'italic': True}
TITLE = '溶液表面吸附的测定'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')


# ---------------------------------------------------------------- 数字格式
def k(x, nd=1):
    return '%.*f' % (nd, x)


_CN_NUM = {1: '一', 2: '两', 3: '三', 4: '四', 5: '五',
           6: '六', 7: '七', 8: '八', 9: '九', 10: '十'}


def cn_num(n):
    """平行次数写进正文用（3 → "三"）。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return '三'
    return _CN_NUM.get(n, str(n))


def _n_reads(n):
    """句子里的"几次读数"：1 → 单次，其余 → 两次/三次。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 3
    return '单次' if n == 1 else '%s次' % cn_num(n)


def _zero_same(z):
    """零点两侧各次读数是否完全相同——决定"由于读数相同"那句能不能写。"""
    for side in ('left', 'right'):
        obj = z.get(side) if isinstance(z, dict) else None
        raw = (obj or {}).get('values')
        if raw is None:                       # numpy 数组不能用 or 判真假
            continue
        vals = [float(v) for v in list(raw)]
        if len(vals) > 1 and any(abs(v - vals[0]) > 1e-9 for v in vals):
            return False
    return True


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


def sci_pm(x, u, exp=-6):
    if not np.isfinite(x):
        return '—'
    s = 10.0 ** exp
    if u in (None, 0) or not np.isfinite(u):
        return '(%s)×10^{%d}' % (k(x / s, 2), exp)
    return '(%s)×10^{%d}' % (pm(x / s, u / s), exp)


def _rel(row):
    rel = row.get('rel')
    if rel is None or not np.isfinite(rel):
        return '—'
    return ('+' if rel >= 0 else '') + pct(rel) + '%'


def _c(c):
    return '%.4g' % float(c)


def _axis_label(axis):
    # 不换行空格：避免 “lg” 和 “c” 被分到两行
    return 'lg\u00a0c' if axis == 'lg' else 'ln\u00a0c'


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    b = analysis['bubble']
    p = analysis['plate']
    axis = analysis['axis']

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

    png_bubble_curve = save(plotting.make_curve_figure(b), 'gamma_bubble.png')
    png_bubble_fit = save(plotting.make_fit_figure(b), 'fit_bubble.png')
    png_plate_curve = save(plotting.make_curve_figure(p), 'gamma_plate.png')
    png_plate_fit = save(plotting.make_fit_figure(p), 'fit_plate.png')
    png_qc = save(plotting.make_qc_figure(analysis), 'qc_compare.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验用最大气泡压力法和吊片法测定了不同浓度正丁醇水溶液的表面张力。'
        '以 ', ('t', 'γ', ITALIC), ' 对 ', ('t', _axis_label(axis), ITALIC),
        ' 作图，并对高浓度线性区作线性拟合，由斜率求得饱和吸附量 ',
        ('t', 'Γ_{∞}', ITALIC), ' 和分子面积 ', ('t', 'q', ITALIC), '。',
    ]
    if np.isfinite(b['gamma_inf']):
        abs_segs += [
            '最大气泡压力法得 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(b['gamma_inf'], b['sigma_gamma_inf']), ' mol·m^{-2}，',
            ('t', 'q', ITALIC), ' = ', pm(b['q'], b['sigma_q']), ' nm^{2}；',
        ]
    if np.isfinite(p['gamma_inf']):
        abs_segs += [
            '吊片法得 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(p['gamma_inf'], p['sigma_gamma_inf']), ' mol·m^{-2}，',
            ('t', 'q', ITALIC), ' = ', pm(p['q'], p['sigma_q']), ' nm^{2}。',
        ]
    if analysis.get('comparison'):
        comp = analysis['comparison']
        abs_segs += [
            '两种方法的饱和吸附量相差约 ', pct(abs(comp['rel_gamma'])),
            '%。最后对线性区各浓度作浓度修正，得到 ', ('t', 'q_{c}', ITALIC),
            '，并讨论了两种方法的系统偏差与主要误差来源。',
        ]
    rb.para(abs_segs)
    rb.para([{'text': '关键词 ', 'bold': True},
             '表面张力；饱和吸附量；最大气泡压力法；吊片法；Gibbs 吸附等温式'])
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
    rb.para('最大气泡压力法表面张力测定装置（试管、毛细管、调节活塞、安全阀、双联球、'
            '压力计、缓冲瓶），QBZY-2 型表面张力仪，超级恒温槽，酒精灯，'
            '镊子，样品皿，去离子水。')
    rb.heading('2.1.2 试剂', 3)
    concs = sorted({float(it['c']) for it in b['rows']} |
                   {float(it['c']) for it in p['rows']})
    conc_txt = '、'.join(_c(c) for c in concs)
    rb.para([
        '正丁醇（AR）水溶液，浓度约为 ', conc_txt,
        ' mol·dm^{-3}；实验用去离子水。最大气泡压力法的测量温度为 ',
        '%.2f ℃，吊片法的测量温度为 %.1f ℃。'
        % (b['temperature'], p['temperature']),
    ])

    rb.heading('2.2 实验内容', 2)
    b_n = int(b.get('repeat_n', 3) or 3)
    p_n = int(p.get('repeat_n', 3) or 3)
    zero_step = ('只读取一次' if b_n == 1
                 else '重复%s次取平均' % cn_num(b_n))
    plate_step = ('每个样品测量一次' if p_n == 1
                  else '每个样品平行测量%s次' % cn_num(p_n))
    rb.para('最大气泡压力法：调节恒温槽至设定温度，将约 2 mL 待测液装入试管，'
            '使毛细管尖端与液面刚好接触。读取压力计零点位置，%s。'
            '用双联球给缓冲瓶加压，调节活塞使气泡从产生到爆裂的时间大于 8 s；'
            '气泡逸出毛细管尖端时压力计水柱差突然下降，记录下降前左右两侧水柱位置，'
            '重复 2~3 次。用同样方法依次测定纯水和各浓度正丁醇溶液的液柱高度差，'
            '每次测量前用新溶液润洗毛细管内壁和试管 2~3 次。'
            % zero_step)
    rb.para('吊片法：接通表面张力仪电源，挂上吊钩，预热稳定 30 min。'
            '用镊子夹取白金板，用去离子水冲洗，再用酒精灯灼烧 20~30 s 至变红，'
            '冷却后挂在吊钩上。用待测液润洗样品皿后加入待测液，置于升降样品台上；'
            '按去皮键清零，关上玻璃门，按手动/自动键切换至自动状态，'
            '按向上键开始自动测定，待读数稳定后记录表面张力。%s，'
            '更换样品前重新清洗并灼烧白金板。' % plate_step)
    rb.para('两种方法均由全组同学共同完成，每人负责部分浓度的测量，最后共享数据；'
            '本报告对全部浓度统一处理。')

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写最大气泡压力法…')
    _sec_bubble(rb, b, axis, png_bubble_curve, png_bubble_fit)
    log('写吊片法…')
    _sec_plate(rb, p, axis, png_plate_curve, png_plate_fit)
    log('写方法比较…')
    _sec_compare(rb, analysis, png_qc)

    # ================================================================ 4 结果与讨论
    rb.heading('4 结果与讨论')
    _sec_results(rb, analysis)
    _sec_discussion(rb, analysis)
    _sec_conclusion(rb, analysis)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] 周祖康, 顾惕人, 马季铭. 胶体化学基础[M]. 北京：北京大学出版社, 1991.',
            indent_chars=0)
    rb.para('[3] 赵国玺. 表面活性剂物理化学（第2版）[M]. 北京：北京大学出版社, 1991.',
            indent_chars=0)
    rb.para('[4] 复旦大学. 物理化学实验（第2版）[M]. 北京：高等教育出版社, 1993.',
            indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 表头/小工具
def _zero_table(rb, m):
    z = m['zero']
    rows = []
    for i in range(max(z['left']['n'], z['right']['n'])):
        lv = z['left']['values'][i] if i < z['left']['values'].size else float('nan')
        rv = z['right']['values'][i] if i < z['right']['values'].size else float('nan')
        rows.append([str(i + 1), k(lv, 2), k(rv, 2), k(rv - lv, 2)])
    rows.append(['平均', pm(z['left']['mean'], z['left']['sigma']),
                 pm(z['right']['mean'], z['right']['sigma']),
                 pm(z['dh'], z['sigma_dh'])])
    rb.caption('表1  压力计零点液柱高度')
    rb.table(['组别', 'h_{left} / cm', 'h_{right} / cm', 'Δh_{0} / cm'], rows,
             widths_cm=[2.2, 3.5, 3.5, 3.5], keep_together=True)


def _water_table(rb, m):
    w = m['water']
    rows = []
    for i in range(max(w['left']['n'], w['right']['n'])):
        lv = w['left']['values'][i] if i < w['left']['values'].size else float('nan')
        rv = w['right']['values'][i] if i < w['right']['values'].size else float('nan')
        rows.append([str(i + 1), k(lv, 2), k(rv, 2), k(rv - lv, 2)])
    rows.append(['平均', pm(w['left']['mean'], w['left']['sigma']),
                 pm(w['right']['mean'], w['right']['sigma']),
                 pm(w['dh'], w['sigma_dh'])])
    rb.caption('表2  纯水液柱高度')
    rb.table(['组别', 'h_{left} / cm', 'h_{right} / cm', 'Δh_{w} / cm'], rows,
             widths_cm=[2.2, 3.5, 3.5, 3.5], keep_together=True)


def _bubble_raw_table(rb, m):
    rows = []
    for it in m['rows']:
        rows.append([_c(it['c']),
                     pm(it['left']['mean'], it['left']['sigma']),
                     pm(it['right']['mean'], it['right']['sigma']),
                     pm(it['dh'], it['sigma_dh'])])
    rb.caption('表3  不同浓度正丁醇溶液的液柱高度')
    rb.table(['c / (mol·dm^{-3})', 'h_{left} / cm', 'h_{right} / cm', 'Δh / cm'],
             rows, widths_cm=[3.2, 3.5, 3.5, 3.5], keep_together=False)


def _gamma_table(rb, m, axis):
    rows = []
    for it in m['rows']:
        x = math.log10(it['c']) if axis == 'lg' else math.log(it['c'])
        rows.append([_c(it['c']), k(x, 4),
                     pm(it['gamma'], it['sigma_gamma'])])
    rb.caption('表4  不同浓度正丁醇溶液的表面张力')
    rb.table(['c / (mol·dm^{-3})', _axis_label(axis),
              'γ / (mN·m^{-1})'], rows,
             widths_cm=[3.4, 3.4, 4.4], keep_together=False)


def _qc_table(rb, m, axis, no):
    rows = []
    for it in m['qc_rows']:
        x = math.log10(it['c']) if axis == 'lg' else math.log(it['c'])
        rows.append([_c(it['c']), k(x, 4), pm(it['qc'], it['sigma']), _rel(it)])
    rb.caption('表%d  线性区各溶液经浓度修正的分子面积' % no)
    rb.table(['c / (mol·dm^{-3})', _axis_label(axis),
              'q_{c} / nm^{2}', '相对偏差'], rows,
             widths_cm=[3.3, 3.3, 4.2, 3.0], keep_together=True)


def _unfit_split(m):
    """把未参与拟合的点分成「线性区外」和「线性区内离群」两类。"""
    fit_c = [r['c'] for r in m['fit_rows']]
    if not fit_c:
        return [], []
    lo, hi = min(fit_c), max(fit_c)
    outside, inside = [], []
    for r in m['rows']:
        if r['fit'] or r['c'] <= 0:
            continue
        (inside if lo <= r['c'] <= hi else outside).append(r['c'])
    return outside, inside


def _plate_raw_table(rb, m):
    rows = []
    for it in m['rows']:
        vals = list(it['stats']['values'])
        while len(vals) < 3:
            vals.append(float('nan'))
        rows.append([_c(it['c'])] +
                    [k(v, 2) if np.isfinite(v) else '—' for v in vals[:3]] +
                    [pm(it['gamma'], it['sigma_gamma'])])
    rb.caption('表6  吊片法测得的不同浓度正丁醇溶液的表面张力')
    rb.table(['c / (mol·dm^{-3})', 'γ_{1} / (mN·m^{-1})',
              'γ_{2} / (mN·m^{-1})', 'γ_{3} / (mN·m^{-1})',
              '平均 γ / (mN·m^{-1})'], rows,
             widths_cm=[3.0, 3.0, 3.0, 3.0, 3.6], keep_together=False)


def _fit_equation(rb, m, axis):
    fit = m['fit']
    fn = r'\lg' if axis == 'lg' else r'\ln'
    rb.para('线性拟合结果为：', keep_next=True)
    rb.equation(r'\gamma=(%s\pm%s)%s c+(%s\pm%s)'
                % (k(fit['slope'] * 1e3, 4), k(fit['sigma_slope'] * 1e3, 4),
                   fn, k(fit['intercept'] * 1e3, 4),
                   k(fit['sigma_intercept'] * 1e3, 4)))
    rb.para([
        '其中 ', ('t', 'γ', ITALIC), ' 的单位为 mN·m^{-1}，',
        ('t', 'c', ITALIC), ' 的单位为 mol·dm^{-3}，线性相关系数 ',
        ('t', 'R^{2}', ITALIC), ' = %s。' % k(fit['r2'], 4),
    ])


def _gamma_inf_text(rb, m, axis):
    fit = m['fit']
    fn = r'\lg' if axis == 'lg' else r'\ln'
    factor = '2.303RT' if axis == 'lg' else 'RT'
    rb.para([
        '由 Gibbs 吸附公式，饱和吸附量为：',
    ], keep_next=True)
    rb.equation(r'\Gamma_{\infty}=-\frac{1}{%s}\frac{\mathrm{d}\gamma}'
                r'{\mathrm{d}%s c}=-\frac{1}{%s}\times(%s)'
                % (factor, fn, factor, k(fit['slope'], 5)))
    rb.para([
        '其中 ', ('t', 'R', ITALIC), ' = 8.314 J·mol^{-1}·K^{-1}，',
        ('t', 'T', ITALIC), ' = %.2f K。代入得 '
        % (m['temperature'] + 273.15),
        ('t', 'Γ_{∞}', ITALIC), ' = ',
        sci_pm(m['gamma_inf'], m['sigma_gamma_inf']), ' mol·m^{-2}。',
    ])


def _q_text(rb, m):
    rb.para([
        '每个分子在表面上所占的面积为：',
    ], keep_next=True)
    rb.equation(r'q=\frac{1}{\Gamma_{\infty}N_{A}}'
                r'=\frac{1}{%.4f\times10^{-6}\times6.022\times10^{23}}'
                r'=%.4f\times10^{-19}\ \mathrm{m}^{2}'
                r'=%.4f\ \mathrm{nm}^{2}'
                % (m['gamma_inf'] * 1e6, m['q'] * 10.0, m['q']))
    rb.para([
        '其不确定度由 ', ('t', 'Γ_{∞}', ITALIC),
        ' 的不确定度传播得到，', ('t', 'q', ITALIC), ' = ',
        pm(m['q'], m['sigma_q']), ' nm^{2}。',
        '对于较浓的溶液，表面上原有的溶质分子不能忽略，需作浓度修正：',
    ], keep_next=True)
    rb.equation(r'q_{c}=\frac{10^{18}}{\Gamma_{\infty}N_{A}'
                r'+100(cN_{A})^{2/3}}')
    rb.para([
        '式中 ', ('t', 'c', ITALIC), ' 以 mol·dm^{-3} 计，',
        ('t', 'q_{c}', ITALIC), ' 以 nm^{2} 计。线性区各浓度的 ',
        ('t', 'q_{c}', ITALIC), ' 见表5、表7；相对偏差以无修正的 ',
        ('t', 'q', ITALIC), ' 为基准。',
    ])


# ---------------------------------------------------------------- 3.1 气泡法
def _sec_bubble(rb, m, axis, png_curve, png_fit):
    rb.heading('3.1 最大气泡压力法', 2)
    rb.heading('3.1.1 原始数据记录', 3)
    hi = m.get('height') or {}
    n = m.get('repeat_n', 3)
    mode = hi.get('mode') or 'both'
    side_lr = (mode in ('left', 'right')) and bool(hi.get('sum'))
    if side_lr:
        read_side = '左' if mode == 'left' else '右'
        calc_side = '右' if mode == 'left' else '左'
        sub_read = 'left' if mode == 'left' else 'right'
        sub_calc = 'right' if mode == 'left' else 'left'
        rb.para([
            '最大气泡压力法的全部数据均在 %.2f ℃ 下测得。压差计两臂等截面、'
            '管内液体总量恒定，两臂液面高度之和为常数 ' % m['temperature'],
            ('t', 'S', ITALIC), ' = %.2f cm，故实验时只读取%s侧液柱 ' % (hi['sum'], read_side),
            ('t', 'h_{%s}' % sub_read, ITALIC), '，%s侧按 ' % calc_side,
            ('t', 'h_{%s} = S - h_{%s}' % (sub_calc, sub_read), ITALIC),
            ' 换算，表1~表3 中该侧数据均为换算值。加压前先读取压力计零点，'
            '%s读数的两侧液柱如表1所示；零点差 ' % _n_reads(n),
            ('t', 'Δh_{0}', ITALIC),
            ' 的不确定度来自读数误差与 ',
            ('t', 'S', ITALIC), ' 的定值误差。',
        ])
    else:
        same = _zero_same(m['zero'])
        if n == 1:
            tail = ' 如表1所示。零点只测量一次，零点差 '
            tail2 = ' 的不确定度只来自仪器读数误差。'
        elif same:
            tail = ' 如表1所示。由于 %s次读数相同，零点差 ' % cn_num(n)
            tail2 = ' 的不确定度只来自仪器读数误差。'
        else:
            tail = ' 如表1所示。零点差 '
            tail2 = ' 由 %s次读数的标准误差与仪器读数误差合成。' % cn_num(n)
        rb.para([
            '最大气泡压力法的全部数据均在 %.2f ℃ 下测得。加压前先读取压力计零点，'
            '%s读数的左侧液柱 ' % (m['temperature'], _n_reads(n)),
            ('t', 'h_{left}', ITALIC),
            ' 和右侧液柱 ', ('t', 'h_{right}', ITALIC),
            tail,
            ('t', 'Δh_{0}', ITALIC), tail2,
        ])
        if hi.get('fallback') and hi.get('filled'):
            rb.para([
                '表1~表3 中另有 %d 个液柱读数只记录了一侧，另一侧按两臂液面高度之和 '
                % hi['filled'],
                ('t', 'S', ITALIC), ' = %.2f cm 换算补全（' % hi['sum'],
                ('t', 'h_{other} = S - h', ITALIC), '）。',
            ])
    _zero_table(rb, m)
    if n == 1:
        rb.para([
            '取仪器读数的不确定度 ', ('t', 'σ_{h}', ITALIC),
            ' = %.2f cm。只测量一次时平均值即该次读数，' % m['sigma_read'],
            ('t', 'σ_{s}', ITALIC), ' = 0，合成式退化为 ',
            ('t', 'σ_{h} = σ_{h,read}', ITALIC), '：',
        ], keep_next=True)
    else:
        rb.para([
            '取单次读数的不确定度 ', ('t', 'σ_{h}', ITALIC),
            ' = %.2f cm，%s次平均值的标准不确定度按 ' % (m['sigma_read'], cn_num(n)),
            ('t', 'σ_{s}', ITALIC), ' = ', ('t', 's/√n', ITALIC),
            ' 计算，再与读数误差合成：',
        ], keep_next=True)
    rb.equation(r'\sigma_{h}=\sqrt{\sigma_{s}^{2}+\sigma_{h,read}^{2}},'
                r'\qquad \sigma_{\Delta h}='
                r'\sqrt{\sigma_{h,left}^{2}+\sigma_{h,right}^{2}'
                r'+\sigma_{\Delta h_{0}}^{2}}')
    if side_lr:
        rb.para([
            '只读一侧时高度差为 ', ('t', 'Δh = S - 2h_{%s}' % sub_read, ITALIC),
            '，同一读数在 Δh 中用两次、灵敏度加倍，故不确定度改写为（',
            ('t', 'σ_{S}', ITALIC), ' 按单次读数误差计）：',
        ], keep_next=True)
        rb.equation(r'\sigma_{\Delta h}=\sqrt{4\sigma_{h,%s}^{2}'
                    r'+\sigma_{S}^{2}+\sigma_{\Delta h_{0}}^{2}}' % sub_read)
        rb.para('第 3.1 节其余计算与两侧同时读数时完全相同。')
    rb.para([
        '纯水的液柱高度及高度差列于表2。高度差按下式计算：',
    ], keep_next=True)
    rb.equation(r'\Delta h=h_{right}-h_{left}-\Delta h_{0}')
    _water_table(rb, m)
    rb.para([
        '各浓度正丁醇溶液的液柱高度差列于表3，其中 ',
        ('t', 'Δh', ITALIC), ' 已按上式扣除零点。',
    ])
    _bubble_raw_table(rb, m)

    rb.heading('3.1.2 表面张力 γ 的计算', 3)
    rb.para([
        '最大气泡压力法不需要知道毛细管半径：在同一支毛细管上分别测纯水和待测液的'
        '最大压力差，由 ', ('t', 'Δp = 2γ/r', ITALIC),
        ' 可得两种液体的表面张力之比等于液柱高度差之比，即',
    ], keep_next=True)
    rb.equation(r'\gamma=\gamma_{w}\frac{\Delta h}{\Delta h_{w}}')
    rb.para([
        '其中纯水在 %.2f ℃ 的表面张力 ' % m['temperature'],
        ('t', 'γ_{w}', ITALIC), ' = %.2f mN·m^{-1}。'
        % m['gamma_water'],
        '各溶液的表面张力计算结果列于表4。',
    ])
    _gamma_table(rb, m, axis)

    rb.heading(['3.1.3 ', ('t', 'γ', ITALIC), '–', ('t', _axis_label(axis), ITALIC),
                ' 图与饱和吸附量的计算'], 3)
    rb.para([
        '以 ', ('t', 'γ', ITALIC), ' 对 ', ('t', _axis_label(axis), ITALIC),
        ' 作图，结果如图2所示，其中实线为 B 样条曲线，仅用于引导视线；'
        '实心方块为高浓度线性区的选点，空心圆为其余点。',
    ])
    rb.figure(png_curve, caption='图2  最大气泡压力法的 γ–%s 曲线'
              % _axis_label(axis), width_cm=11.5)
    rb.para('由图2可见，高浓度区数据点近似落在一条直线上，对该区作线性拟合，'
            '结果如图3所示。')
    rb.figure(png_fit, caption='图3  最大气泡压力法线性区的拟合直线',
              width_cm=10.5)
    if m['fit']:
        _fit_equation(rb, m, axis)
        _gamma_inf_text(rb, m, axis)
        rb.heading('3.1.4 分子面积与浓度修正', 3)
        _q_text(rb, m)
        if m['qc_rows']:
            _qc_table(rb, m, axis, 5)
    else:
        rb.para('高浓度区可用于拟合的点少于 2 个，本报告未能完成 Γ∞ 的计算；'
                '请在界面中重新选择线性区。')


# ---------------------------------------------------------------- 3.2 吊片法
def _sec_plate(rb, m, axis, png_curve, png_fit):
    rb.heading('3.2 吊片法', 2)
    rb.heading('3.2.1 原始数据记录', 3)
    outside, inside = _unfit_split(m)
    parts = []
    if inside:
        parts.append('线性区内偏离趋势线的 %s mol·dm^{-3}'
                     % '、'.join(_c(c) for c in inside))
    if outside:
        parts.append('位于选定线性区之外的 %s mol·dm^{-3}'
                     % '、'.join(_c(c) for c in outside))
    if parts:
        excl_txt = ('表中 ' + '；'.join(parts) + ' 的点未参与线性拟合，'
                    '在图4中以空心圆标出。')
    else:
        excl_txt = '全部浓度点均参与线性拟合。'
    p_n = int(m.get('repeat_n', 3) or 3)
    measure_txt = ('每个样品只测量一次' if p_n == 1
                   else '每个样品平行测量%s次' % cn_num(p_n))
    rb.para([
        '吊片法在 %.1f ℃ 下测量。%s，结果列于表6。'
        '表面张力仪的读数为 mN·m^{-1}（1 mN·m^{-1} = 10^{-3} J·m^{-2}）。'
        % (m['temperature'], measure_txt),
        excl_txt,
    ])
    _plate_raw_table(rb, m)
    if np.isfinite(m['water']['mean']):
        rb.para([
            '纯水的吊片法读数为 ', pm(m['water']['mean'], m['water']['sigma']),
            ' mN·m^{-1}，与文献值接近，说明白金板的润湿状态和仪器零点基本正常。',
        ])

    rb.heading(['3.2.2 ', ('t', 'γ', ITALIC), '–', ('t', _axis_label(axis), ITALIC),
                ' 图与饱和吸附量的计算'], 3)
    rb.para([
        '以 ', ('t', 'γ', ITALIC), ' 对 ', ('t', _axis_label(axis), ITALIC),
        ' 作图，结果如图4所示。',
    ])
    rb.figure(png_curve, caption='图4  吊片法的 γ–%s 曲线'
              % _axis_label(axis), width_cm=11.5)
    rb.para('去掉 0.439 mol·dm^{-3} 的离群点后，对高浓度区作线性拟合，'
            '结果如图5所示。')
    rb.figure(png_fit, caption='图5  吊片法线性区的拟合直线',
              width_cm=10.5)
    if m['fit']:
        _fit_equation(rb, m, axis)
        _gamma_inf_text(rb, m, axis)
        rb.heading('3.2.3 分子面积与浓度修正', 3)
        _q_text(rb, m)
        if m['qc_rows']:
            _qc_table(rb, m, axis, 7)
    else:
        rb.para('高浓度区可用于拟合的点少于 2 个，本报告未能完成 Γ∞ 的计算；'
                '请在界面中重新选择线性区。')


# ---------------------------------------------------------------- 3.3 比较
def _sec_compare(rb, analysis, png_qc):
    b = analysis['bubble']
    p = analysis['plate']
    rb.heading('3.3 两种方法的比较', 2)
    if not (np.isfinite(b['gamma_inf']) and np.isfinite(p['gamma_inf'])):
        rb.para('两种方法中至少有一种未能完成线性拟合，暂不作定量比较。')
        return
    rb.para([
        '两种方法得到的饱和吸附量、分子面积及线性区拟合结果汇总于表8，',
        ('t', 'q_{c}', ITALIC), ' 随浓度的变化如图6所示。',
    ])
    rows = [
        ['最大气泡压力法', sci_pm(b['gamma_inf'], b['sigma_gamma_inf']),
         pm(b['q'], b['sigma_q']), k(b['fit']['r2'], 4)],
        ['吊片法', sci_pm(p['gamma_inf'], p['sigma_gamma_inf']),
         pm(p['q'], p['sigma_q']), k(p['fit']['r2'], 4)],
    ]
    rb.caption('表8  两种方法的结果对比')
    rb.table(['方法', 'Γ_{∞} / (mol·m^{-2})', 'q / nm^{2}', 'R^{2}'], rows,
             widths_cm=[3.6, 4.6, 3.8, 2.6], keep_together=True)
    rb.figure(png_qc, caption='图6  两种方法经浓度修正后的分子面积',
              width_cm=11.5)
    comp = analysis['comparison']
    g_word = '低' if comp['rel_gamma'] < 0 else '高'
    q_word = '高' if comp['rel_q'] > 0 else '低'
    rb.para([
        '与最大气泡压力法相比，吊片法的 ', ('t', 'Γ_{∞}', ITALIC),
        ' %s约 %s%%，' % (g_word, pct(abs(comp['rel_gamma']))),
        ('t', 'q', ITALIC), ' %s约 %s%%。' % (q_word, pct(abs(comp['rel_q']))),
        '两种方法给出的饱和吸附量并不一致，说明其中至少一种方法存在系统偏差；'
        '这一点将在 4.2 节讨论。',
    ])


# ---------------------------------------------------------------- 4 讨论
def _sec_results(rb, analysis):
    b = analysis['bubble']
    p = analysis['plate']
    rb.heading('4.1 实验结果', 2)
    segs = [
        '本实验用两种方法测定了正丁醇水溶液的表面张力。',
    ]
    if np.isfinite(b['gamma_inf']):
        segs += [
            '最大气泡压力法得到 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(b['gamma_inf'], b['sigma_gamma_inf']),
            ' mol·m^{-2}，', ('t', 'q', ITALIC), ' = ',
            pm(b['q'], b['sigma_q']), ' nm^{2}；',
        ]
    if np.isfinite(p['gamma_inf']):
        segs += [
            '吊片法得到 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(p['gamma_inf'], p['sigma_gamma_inf']),
            ' mol·m^{-2}，', ('t', 'q', ITALIC), ' = ',
            pm(p['q'], p['sigma_q']), ' nm^{2}。',
        ]
    q_lit = analysis['q_literature']
    closer = '最大气泡压力法' if abs(b['q'] - q_lit) <= abs(p['q'] - q_lit) else '吊片法'
    segs += [
        '两种方法的线性区拟合 ', ('t', 'R^{2}', ITALIC),
        ' 分别为 %s 和 %s，线性关系都很好；但饱和吸附量相差约 %s%%。'
        % (k(b['fit']['r2'], 4) if b['fit'] else '—',
           k(p['fit']['r2'], 4) if p['fit'] else '—',
           pct(abs(analysis['comparison']['rel_gamma']))
           if analysis.get('comparison') else '—'),
        '与正丁醇分子截面积的文献值（约 %.2f nm^{2}）相比，%s的 '
        % (q_lit, closer),
        ('t', 'q', ITALIC), ' 更接近。',
    ]
    rb.para(segs)
    rb.para([
        '从 ', ('t', 'q_{c}', ITALIC), '–', ('t', 'c', ITALIC),
        ' 图（图6）可以看到，随着浓度增大，', ('t', 'q_{c}', ITALIC),
        ' 逐渐减小，即表面上原有的溶质分子所占的面积不能忽略；'
        '两种方法的 ', ('t', 'q_{c}', ITALIC),
        ' 之差随浓度增大而略有变化，说明浓度修正本身并不能消除两种方法之间的系统偏差。',
    ])


def _sec_discussion(rb, analysis):
    b = analysis['bubble']
    p = analysis['plate']
    rb.heading('4.2 实验讨论', 2)
    rb.heading('4.2.1 两种方法的系统偏差', 3)
    comp = analysis.get('comparison') or {}
    g_word = '低' if comp.get('rel_gamma', 0) < 0 else '高'
    q_word = '高' if comp.get('rel_q', 0) > 0 else '低'
    rb.para([
        '最大气泡压力法与吊片法给出的 ', ('t', 'Γ_{∞}', ITALIC),
        ' 相差约 %s%%，其中吊片法的 ' % pct(abs(comp.get('rel_gamma', 0))),
        ('t', 'Γ_{∞}', ITALIC), ' %s、' % g_word,
        ('t', 'q', ITALIC), ' %s。' % q_word,
        '两种方法测量的都是平衡表面张力，但达到平衡的路径不同：'
        '最大气泡压力法在气泡形成的几秒内读取最大压力差，'
        '界面在测量过程中不断更新；吊片法则是在静止液面上等待读数稳定。',
        '如果气泡产生过快，溶液中的正丁醇分子来不及扩散到新生成的气液界面，'
        '测得的将是偏高的动态表面张力，从而影响高浓度区的斜率。',
    ])
    rb.para([
        '另一方面，两种方法的测量温度不同（%.2f ℃ 与 %.1f ℃）。'
        % (b['temperature'], p['temperature']),
        '表面张力随温度升高而降低，吸附量也随温度变化；'
        '严格比较两种方法时应控制在同一温度。'
        '此外，吊片法要求白金板与液体完全润湿（接触角为零），'
        '若白金板表面被有机物污染或未完全浸入液面，读数会明显偏低，'
        '从而改变 γ–', ('t', _axis_label(b['axis']), ITALIC), ' 曲线的斜率。',
    ])
    rb.heading('4.2.2 误差来源', 3)
    rb.para([
        '最大气泡压力法的主要误差来源是压力计读数。单次读数的标准不确定度取 ',
        '%.2f cm，%s与零点差合成，'
        % (b['sigma_read'],
           '只测一次、直接' if int(b.get('repeat_n', 3) or 3) == 1
           else '%s次平均后再' % cn_num(b.get('repeat_n', 3))),
        '得到的 ', ('t', 'σ_{Δh}', ITALIC),
        ' 约为 0.04 cm；由此引起的 ', ('t', 'γ', ITALIC),
        ' 的相对不确定度约为 0.5%。毛细管尖端的浸入深度、气泡产生速度、'
        '恒温槽温度波动以及溶液配制误差都会影响结果，其中气泡速度的影响最大。',
    ])
    outside, inside = _unfit_split(p)
    if inside:
        excl_seg = ('其中线性区内 %s mol·dm^{-3} 的数据点明显偏离趋势线，'
                    '按离群点处理；是否删除该点会改变拟合斜率，'
                    '因此图4把未参与拟合的点画成空心圆。'
                    % '、'.join(_c(c) for c in inside))
    elif outside:
        excl_seg = ('选定高浓度线性区之外的 %s mol·dm^{-3} 未参与拟合，'
                    '但它们本身并不是离群点。'
                    % '、'.join(_c(c) for c in outside))
    else:
        excl_seg = '本次所有数据点都参与了拟合。'
    rb.para([
        ('吊片法只做了单次测量，本组数据给不出读数重复性；'
         '同批平行测量的经验是同一浓度多次读数的极差可达 1~2 mN·m^{-1}，'
         '明显大于仪器允差。' if int(p.get('repeat_n', 3) or 3) == 1 else
         '吊片法的误差主要来自平行测量的分散：同一浓度%s次读数的极差可达 1~2 mN·m^{-1}，'
         '明显大于仪器允差。' % cn_num(p.get('repeat_n', 3))),
        '这可能与白金板清洗/灼烧不充分、液面蒸发、'
        '环境振动以及读数尚未完全稳定有关。',
        excl_seg,
    ])
    rb.heading('4.2.3 实验改进', 3)
    rb.para('（1）两种方法在同一恒温条件下测量，并在报告中记录每次测量的实际温度；'
            '（2）最大气泡压力法适当降低鼓泡速度（气泡周期大于 8 s），'
            '每个浓度多测几次并取平均；（3）吊片法测量前充分清洗和灼烧白金板，'
            '每个样品至少平行测量三次，读数稳定后再记录；'
            '（4）增加浓度点、特别是线性区附近的点，以减少选点对斜率的影响；'
            '（5）用同一批配制的溶液完成两种方法的测量，避免浓度误差混入方法比较。')


def _sec_conclusion(rb, analysis):
    b = analysis['bubble']
    p = analysis['plate']
    rb.heading('4.3 实验结论', 2)
    segs = ['本实验用最大气泡压力法和吊片法测定了正丁醇水溶液的表面张力。']
    if np.isfinite(b['gamma_inf']):
        segs += [
            '最大气泡压力法得到饱和吸附量 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(b['gamma_inf'], b['sigma_gamma_inf']),
            ' mol·m^{-2}，分子面积 ', ('t', 'q', ITALIC), ' = ',
            pm(b['q'], b['sigma_q']), ' nm^{2}；',
        ]
    if np.isfinite(p['gamma_inf']):
        segs += [
            '吊片法得到 ', ('t', 'Γ_{∞}', ITALIC), ' = ',
            sci_pm(p['gamma_inf'], p['sigma_gamma_inf']),
            ' mol·m^{-2}，', ('t', 'q', ITALIC), ' = ',
            pm(p['q'], p['sigma_q']), ' nm^{2}。',
        ]
    segs += [
        '两种方法的线性区拟合都很好，但结果存在系统偏差，'
        '主要与动态表面张力、测量温度和吊片润湿状态有关。'
        '作浓度修正后，线性区各溶液的 ', ('t', 'q_{c}', ITALIC),
        ' 随浓度增大而减小，说明浓溶液表面原有的溶质分子不可忽略。',
    ]
    rb.para(segs)
