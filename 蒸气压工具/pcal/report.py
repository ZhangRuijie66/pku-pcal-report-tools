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
from .sigfig import k, val, unc, pm, pct

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


def smart(x, nd=2):
    """按精度打印并去掉末尾多余的 0：353.90 → '353.9'，373.15 → '373.15'。"""
    s = '%.*f' % (nd, float(x))
    return s.rstrip('0').rstrip('.') if '.' in s else s


















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

    # ---- 图/表编号：按**文档里出现的先后**逐张分配，缺一张就不占号
    # 每支液体的表依次是：大气压沸点（没有就不印）→ 原始数据 →（未参与拟合的
    # 读数，没有就不印）→ 最终数据。写死「每支 3 张」会在少一张时跳号，
    # 而 audit_docx 要求表号从 1 开始连续。
    tbl_no, fig_no = {}, {}
    n_tbl, n_fig = 0, 1
    for m in liquids:
        slots = {}
        if m.get('atm'):
            n_tbl += 1
            slots['atm'] = n_tbl
        n_tbl += 1
        slots['series'] = n_tbl
        if m.get('rejected'):
            n_tbl += 1
            slots['drop'] = n_tbl
        n_tbl += 1
        slots['final'] = n_tbl
        tbl_no[m['key']] = slots
        fig_no[m['key']] = (n_fig + 1, n_fig + 2)
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


def _rejected_note(rb, m, tbl_no):
    """把「采集软件记了 N 行、表里只有 M 点」这件事交代清楚。

    采集软件是连续记录 + 按 Hold 取点的（见《饱和蒸气压实验在线采集操作说明》）：
    抽真空检漏、液体还没沸腾、结束通大气前后记下的读数，都不是气液平衡数据。
    判据是「平衡点必在同一条 ln(p/p⊖)–1/T 直线上」，偏离多少写在表里。

    没有这些行时**什么也不写**，不要凭空添一段话。
    ``tbl_no`` 是这张新表自己的编号（由 build_report 按实际内容分配）。
    """
    dropped = m.get('rejected') or []
    if not dropped or not tbl_no:
        return
    rb.para('原始记录中另有 %d 个读数没有进入上述数据表：这些点与其余数据不在'
            '同一条 ln(p/p⊖)–1/T 直线上，是抽真空检漏、液体尚未沸腾或结束通大气'
            '前后记录的，不构成气液平衡数据，故未参与拟合。逐行说明见表%d。'
            % (len(dropped), tbl_no))
    rows = []
    for i, r in enumerate(dropped):
        resid = '—' if r.get('resid') is None else '%.2f' % r['resid']
        rows.append([str(i + 1), k(r['p'], 2), k(r['t'], 2), resid])
    rb.caption('表%d  %s未参与拟合的读数' % (tbl_no, m['name']))
    rb.table(['编号', 'p / kPa', 't / ℃', '偏离平衡线 / ln p'],
             rows, widths_cm=[2.0, 3.2, 3.2, 4.6], keep_together=True)


def _sec_liquid(rb, m, p1, idx, tbls, figs, pngs):
    """``tbls`` 是 {atm/series/drop/final: 表号}，缺的那几张键不存在。"""
    f = m['fit']
    name = m['name']
    atm_n = len(m['atm'])
    n_total = len(f['points'])
    direction = _direction(m)
    t_atm = tbls.get('atm')
    t_series = tbls['series']
    t_drop = tbls.get('drop')
    t_final = tbls['final']

    rb.heading('3.%d %s' % (idx, m['section']), 2)
    # ---- 3.x.1 原始数据
    rb.heading('3.%d.1 原始数据记录' % idx, 3)
    atm_txt = ('（平行测定 %d 次，取平均参与拟合）' % atm_n) if atm_n > 1 else ''
    if t_atm:
        lead = ['大气压下%s的沸点数据如表%d所示%s，%s过程中%s的温度、压力原始数据'
                '如表%d所示。' % (name, t_atm, atm_txt, direction, name, t_series)]
    else:
        lead = ['%s过程中%s的温度、压力原始数据如表%d所示（本次没有单独记录'
                '大气压下的沸点读数）。' % (direction, name, t_series)]
    rb.para(lead + ['为后续计算方便，将温度换算为开尔文温度：'], keep_next=True)
    rb.equation(r'\frac{T}{\mathrm{K}}=\frac{T}{°\mathrm{C}}+273.15')
    if t_atm:
        _atm_table(rb, m, t_atm)
    _series_table(rb, m, t_series)
    _rejected_note(rb, m, t_drop)

    # ---- 3.x.2 光滑曲线
    rb.heading('3.%d.2 蒸气压-温度光滑曲线' % idx, 3)
    src = ('表%d和表%d' % (t_atm, t_series)) if t_atm else ('表%d' % t_series)
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
    merge_txt = ('将表%d与表%d的数据合并' % (t_atm, t_series)) if t_atm \
        else ('将表%d的数据' % t_series)
    rb.para([
        '其中 ', ('t', 'p^{⊖}', ITALIC), ' 是为了消除量纲加入的，取 ',
        ('t', 'p^{⊖}', ITALIC), ' = 100 kPa。据此对 ',
    ] + SEG_LNPP + [
        '–', ('t', '1/T', ITALIC),
        ' 作线性回归。%s，处理后的结果如表%d所示，其中数据按 '
        % (merge_txt, t_final),
        ('t', '1/T', ITALIC), ' 从小到大排布。',
    ])
    _final_table(rb, m, t_final)
    rb.para('表%d的线性拟合结果如图%d所示。' % (t_final, figs[1]))
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
    # ⚠ 旧式是纯平方和 (σ_A/d)² + (Aσ_B/d²)²，把 A、B 当独立量。但 A、B 出自同一次
    # 最小二乘，相关系数 0.99987（水）/0.99981（环己烷），协方差项与两个平方项同量级
    # 且符号为负，漏掉它会把 σ_Tb 印成 3.2359 K（真值 0.0662 K，40 万次 MC 确认），
    # 即报告里「374.179 ± 3.236 K」这种一眼假的结果。必须印含协方差的完整式。
    rb.equation(r'\sigma_{T_{b}}=\sqrt{\left(\frac{\partial T_{b}}{\partial A}'
                r'\sigma_{A}\right)^{2}+\left(\frac{\partial T_{b}}{\partial B}'
                r'\sigma_{B}\right)^{2}+2\frac{\partial T_{b}}{\partial A}'
                r'\frac{\partial T_{b}}{\partial B}\mathrm{Cov}(A,B)}=%s\ K'
                % unc(f['sigma_tb']))
    rb.para(['其中 ', ('t', '∂T_{b}/∂A', ITALIC), ' = 1/[', ('t', 'B', ITALIC),
             ' − ln(', ('t', 'p', ITALIC), '_{1}/', ('t', 'p', ITALIC),
             '^{⊖})]，', ('t', '∂T_{b}/∂B', ITALIC), ' = −',
             ('t', 'A', ITALIC), '/[', ('t', 'B', ITALIC), ' − ln(',
             ('t', 'p', ITALIC), '_{1}/', ('t', 'p', ITALIC), '^{⊖})]^{2}。',
             ('t', 'A', ITALIC), ' 与 ', ('t', 'B', ITALIC),
             ' 由同一批数据点拟合得到、高度负相关，故必须保留协方差项；'
             '若按独立量做平方和，', ('t', 'σ_{T_{b}}', ITALIC),
             ' 会被高估近 50 倍，结果失去意义。'])
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
    # ⚠ Δ_vapS_m = ΔH/Tb = (A·R)/(A/d) = R·d（d = B − ln(p1/p⊖)），与 A **严格无关**：
    # ∂ΔS/∂A = 0。旧式 sqrt((σ_ΔH/Tb)² + (ΔH·σ_Tb/Tb²)²) 把 Tb = A/d 当成与 A
    # 独立的量，等于把同一个 A 的误差算了两遍，代入得 1.16 而真值 0.68（印出来
    # 和算出来差 70%）。正确式只有 R·σ_B。
    rb.equation(r'\sigma_{\Delta_{vap}S_{m}}=R\,\sigma_{B}'
                r'=%s\ J\cdot mol^{-1}\cdot K^{-1}'
                % unc(f['sigma_ds']))
    rb.para(['由于 ', ('t', 'Δ_{vap}S_{m}', ITALIC), ' = ',
             ('t', 'R', ITALIC), '(', ('t', 'B', ITALIC), ' − ln(',
             ('t', 'p', ITALIC), '_{1}/', ('t', 'p', ITALIC), '^{⊖})) 与 ',
             ('t', 'A', ITALIC), ' 无关，', ('t', 'σ_{Δ_{vap}S_{m}}', ITALIC),
             ' 只由 ', ('t', 'B', ITALIC), ' 的标准误传播。'])
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
    # ⚠ 这里原来无条件写「说明测定结果与真值符合较好」，只有
    # `if m['rel_tb_p'] > 0.2` 才补一段说明 —— **只判正值**。
    # 实测环己烷 rel = −0.207%（353.166 vs 353.9），绝对值已超 0.2%，
    # 但条件为假 → 整段误差说明被跳过，报告一边印出 −0.21% 的误差
    # 一边说「符合较好」，且对它没有任何解释（而水的 +0.28% 有一整段）。
    #
    # 改成：先按 |rel| 分档给判断，再按**实际方向**给说明。
    _rel = float(m['rel_tb_p'])
    _abs_rel = abs(_rel)
    _dir = '正' if _rel > 0 else '负'
    #: 认为「符合较好」的阈值（%）——与下面分支用的同一个值
    _TOL = 0.2

    if _abs_rel <= _TOL:
        _verdict = ('说明测定结果与真值符合较好'
                    '（相对误差 %s 在 %.1f%% 以内）。'
                    % (signed_pct(_rel), _TOL))
    else:
        _verdict = ('测定结果与真值的相对误差为 %s，偏%s，'
                    '超出 %.1f%% 的容差，需要说明来源。'
                    % (signed_pct(_rel), _dir, _TOL))
    rb.para(_verdict + '不确定度的计算过程表明其主要来自拟合直线斜率和截距'
                       '的误差，与实验仪器和操作的关系较小。')

    if _abs_rel > _TOL:
        atm_txt = ''
        if m.get('atm_avg'):
            atm_txt = ('大气压下的沸点（完全由实验直接测得）为 %s K，同样存在'
                       '%s偏差，说明该偏差来自实验本身而不是计算过程。'
                       % (k(m['atm_avg']['t'] + 273.15, 2), _dir))
        # 温度偏差方向的物理解释：正偏差来自探头/读数未校准；
        # 负偏差通常来自沸腾滞后或探头响应不足（示数追不上真实沸点）。
        if _rel > 0:
            _mech = ('实验中液体沸腾后温度示数难以立刻稳定（过热效应），'
                     '但它影响的是波动幅度而不是单向偏差；'
                     '更可能的原因是温度测量系统存在固有正偏差，'
                     '即探头或读数系统未校准导致的系统误差。')
        else:
            _mech = ('更可能是温度示数偏低：沸腾刚建立时探头尚未跟上体系'
                     '温度（响应滞后），或读数时液体已停止剧烈沸腾、'
                     '局部温度回落；也可能是探头校准偏低。'
                     '这类偏差方向与正偏差相反，同样属于系统误差。')
        rb.para('对于%s的相对误差，' % _dir + atm_txt + _mech)
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
                     '说明蒸发焓%s误差主要来自温度的%s偏差。' % (_dir, _dir)])

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
    rb.caption('表%d  %s的热力学量汇总'
               % (tbl_no, '、'.join(m['name'] for m in liquids)))
    rb.table(['液体', 'T_{b} / K', 'Δ_{vap}H_{m} / (kJ·mol^{-1})',
              'Δ_{vap}S_{m} / (J·mol^{-1}·K^{-1})', '蒸发焓相对偏差'],
             rows, widths_cm=[1.6, 3.0, 3.7, 4.2, 2.9], keep_together=True)

    # ⚠ 这里原来是一整段**纯字符串**：
    #     「其中环己烷的各热力学量与文献值符合较好；水的常压沸点与蒸发焓存在
    #       系统性正偏差……环己烷的摩尔蒸发熵与楚顿规则符合较好，水则因氢键
    #       网络而显著偏高。」
    # 三个判断全是写死的：换数据（比如某次水的偏差很小、或扩展成三种液体）
    # 这句话立刻自相矛盾。现在改成**按实测偏差分档生成**，
    # 并且「显著偏高」也用实际偏差判断，不再预设水的行为。
    _by_key = {m['key']: m for m in liquids}
    _verdicts = []
    for m in liquids:
        _f = m['fit']
        _rdh = abs(float(m['rel_dh_p']))
        _tab = abs(float(m['rel_tb_p']))
        # 判据：蒸发焓与沸点的相对偏差都在 1% 以内算「符合较好」
        if _rdh <= 1.0 and _tab <= 1.0:
            _v = '%s的热力学量与文献值符合较好（蒸发焓偏差 %s）' % (
                m['name'], signed_pct(m['rel_dh_p']))
        else:
            _bits = []
            if _tab > 1.0:
                _bits.append('常压沸点偏差 %s' % signed_pct(m['rel_tb_p']))
            if _rdh > 1.0:
                _bits.append('蒸发焓偏差 %s' % signed_pct(m['rel_dh_p']))
            _v = '%s存在偏差（%s）' % (m['name'], '、'.join(_bits))
        _verdicts.append(_v)

    # 楚顿规则：|ΔvapSm − 88| / 88 的偏差分档
    _ent = []
    for m in liquids:
        _ds = float(m['fit']['ds'])
        _dev = abs(_ds - 88.0) / 88.0 * 100
        if _dev <= 5:
            _ent.append('%s的摩尔蒸发熵与楚顿规则符合较好（偏差 %.1f%%）'
                        % (m['name'], _dev))
        else:
            _ent.append('%s的摩尔蒸发熵偏离楚顿规则 %.0f%%'
                        % (m['name'], _dev))
    rb.para('；'.join(_verdicts) + '。' + '；'.join(_ent) + '。')

    # 偏差来源只在确实存在较大偏差时才写，且按实际方向说。
    #
    # ⚠ 方向要按**蒸发焓**判，不能用沸点的方向：两者可以不同向。
    # 实测环己烷沸点 −0.21%（负）、蒸发焓 +1.1%（正），
    # 若按沸点方向写就会得到「蒸发焓负偏差」的自相矛盾（踩过一次）。
    _bad = [m for m in liquids
            if abs(float(m['rel_dh_p'])) > 1.0 or abs(float(m['rel_tb_p'])) > 1.0]
    if _bad:
        _dh_dirs = set('正' if float(m['rel_dh_p']) > 0 else '负' for m in _bad)
        _dh_txt = _dh_dirs.pop() if len(_dh_dirs) == 1 else '正负不定'
        rb.para('上述偏差（%s）主要来自温度测量系统的固有偏差'
                '（蒸发焓呈%s偏差），属于本实验的系统误差。'
                % ('、'.join(m['name'] for m in _bad), _dh_txt))
    if any(m['key'] == 'water' for m in liquids):
        rb.para('水的摩尔蒸发熵相对其他液体更偏离楚顿规则，原因是水分子之间存在'
                '强烈氢键，氢键网络形成高度有序的三维结构，蒸发时除体积膨胀外'
                '还要破坏这部分有序结构，额外的熵增使水的蒸发熵明显增大。')
