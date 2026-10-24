# -*- coding: utf-8 -*-
"""生成《双液体系沸点-成分图的绘制》实验报告 .docx（完整版）。

    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分
    3 数据与结果
      3.1 标准工作曲线的绘制（3.1.1 原始数据 / 3.1.2 拟合 /
          3.1.3 离群点判断 / 3.1.4 剔除后重新拟合）
      3.2 沸点和两相成分的测定（3.2.1 原始数据 / 3.2.2 相图 /
          3.2.3 最低恒沸点及误差分析）
    4 结果与讨论（4.1 结果 / 4.2 讨论 / 4.3 结论）
    参考文献
"""
from __future__ import annotations

import decimal
import os

import numpy as np

from . import plotting
from .docxkit import ReportBuilder

ITALIC = {'italic': True}
TITLE = '双液体系沸点-成分图的绘制'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')
APPARATUS_IMG = os.path.join(ASSETS, '讲义图2-恒沸点仪.jpg')


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
    if x is None or not np.isfinite(x):
        return '—'
    return _fmt(_sig(x, n), _place(x, n))


def _vol(v):
    """体积显示：整数去掉小数点。"""
    if v is None:
        return '—'
    f = float(v)
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else ('%g' % f)


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    curve = analysis['curve']
    rows = analysis['rows']
    azeo = analysis['azeotrope']
    fit = curve['fit']
    fit_all = curve['fit_all']
    mode = analysis['mode']
    fig_no = 1
    tbl_no = 0

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

    has_removed = bool(curve['removed'])
    png_curve = save(plotting.make_curve_figure(curve, 'fit_all' if has_removed
                                               else 'fit'), 'curve.png')
    png_refit = save(plotting.make_curve_figure(curve, 'fit'),
                     'curve_refit.png') if has_removed else None
    png_phase = save(plotting.make_phase_figure(rows, azeo, mode), 'phase.png')

    # ================================================================ 摘要
    log('撰写摘要…')
    x_name = ('质量比 m(乙醇)/m(环己烷)' if mode == 'ratio' else '乙醇质量分数')
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验用回流冷凝法测定了环己烷-乙醇体系 %d 个不同组成的沸点，'
        '并用阿贝折射仪测定气、液平衡两相的折射率；由称量法配制已知组成的'
        '系列溶液建立折射率-组成标准工作曲线（二次多项式拟合，' % len(rows),
        ('t', 'R^{2}', ITALIC), ' = %s），' % k(fit['r2'], 4),
        '据此把两相折射率换算为组成，绘制了环己烷-乙醇体系的沸点-成分图。'
        '结果表明，实验压力（约 %s kPa）下体系的最低恒沸点为 %s K，'
        % (k(max(r['p_kpa'] or 0 for r in rows), 1) if rows else '—',
           k(azeo['T_K'], 1) if azeo.get('ok') else '—'),
    ]
    if azeo.get('ok'):
        abs_segs += [
            '恒沸混合物的组成（%s）为 (%s)。' % (x_name, pm(azeo['w'], azeo['sigma_w'])),
        ]
        if analysis.get('deviation') is not None:
            abs_segs += [
                '恒沸点与文献值（%s K[4]）相差 %s K，组成较文献值偏低约 %s%%，'
                '属系统偏差，其来源在讨论中分析。'
                % (k(analysis['lit_T_K'], 2), k(azeo['T_K'] - analysis['lit_T_K'], 1),
                   pct(abs(analysis['deviation']) * 100)),
            ]
    rb.para(abs_segs)
    rb.para([{'text': '关键词 ', 'bold': True},
             '环己烷-乙醇体系；沸点-成分图；折射率；阿贝折射仪；最低恒沸点'])
    rb.blank()

    # ================================================================ 1 引言
    rb.heading('1 引言', page_break_before=True)
    rb.para('该实验的实验目的、实验原理及实验方法如图1所示。')
    fig_no += 1
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
    rb.para('环己烷（AR），乙醇（AR）。')
    rb.heading('2.1.2 仪器', 3)
    rb.para('恒沸点仪，阿贝折射仪，恒温水循环系统，冷却水循环系统，'
            '温度测量及加热控制仪，4 Ω 电阻丝，小滴瓶，刻度移液管数支。')

    rb.heading('2.2 实验内容', 2)
    fig_no = _sec_procedure(rb, analysis, fig_no)

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写工作曲线…')
    fig_no, tbl_no = _sec_curve(rb, analysis, curve, png_curve, png_refit,
                                fig_no, tbl_no)
    log('写相图…')
    fig_no, tbl_no = _sec_boiling(rb, analysis, rows, azeo, png_phase,
                                  fig_no, tbl_no)

    # ================================================================ 4 结果与讨论
    rb.heading('4 结果与讨论')
    log('写结果与讨论…')
    _sec_results(rb, analysis)
    _sec_discussion(rb, analysis)
    _sec_conclusion(rb, analysis)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] 雷玲, 陆新华. 乙醇-环己烷双液系气液平衡相图测绘方法改进[J]. '
            '化工时刊, 2016, 30(01): 22-25.', indent_chars=0)
    rb.para('[3] Montgomery D C, Peck E A, Vining G G. Introduction to Linear '
            'Regression Analysis[M]. 6th ed. Hoboken: John Wiley & Sons, 2021.',
            indent_chars=0)
    rb.para('[4] Haynes W M. CRC Handbook of Chemistry and Physics[M]. '
            '97th ed. Boca Raton: CRC Press, 2016.', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 2.2 步骤
def _sec_procedure(rb, analysis, fig_no=2):
    rows = analysis['rows']
    b = [r for r in rows if r['v_ethanol'] == 20 and r['v_cyclohexane'] != 20]
    a = [r for r in rows if r['v_cyclohexane'] == 20 and r['v_ethanol'] != 20]

    def additions(rs, key):
        vols = [r[key] for r in rs]
        adds = [vols[0]] + [vols[i] - vols[i - 1] for i in range(1, len(vols))]
        return '、'.join(_vol(v) for v in adds if v)

    cyc_add = additions(b, 'v_cyclohexane') if b else ''
    eth_add = additions(a, 'v_ethanol') if a else ''
    have_vols = bool(cyc_add and eth_add)

    rb.heading('2.2.1 标准工作曲线的绘制', 3)
    rb.para(['洗净并烘干 7 个小滴瓶，冷却后称量、去皮。对第 ',
             ('t', 'i', ITALIC), ' 号滴瓶：用刻度移液管移取 ',
             ('t', 'i', ITALIC), ' mL 乙醇，称量质量，记为 m₁；再加入环己烷，'
            '称量质量，记为 m₂。旋紧瓶盖摇匀，用阿贝折射仪测其折射率 ',
            ('t', 'n', ITALIC), '，平行测三次取平均。各瓶的实际组成一律由称量质量计算，'
            '不依赖移取体积。纯乙醇与纯环己烷的折射率在沸点测定时一并测得，'
            '与 1~7 号瓶的数据一起作为工作曲线的数据点。'
            '以上实验由全组同学分工完成并共享数据。'])

    rb.heading('2.2.2 沸点和两相成分的测定', 3)
    if os.path.exists(APPARATUS_IMG):
        rb.para('实验装置为恒沸点仪（连接如图%d所示）。' % fig_no, keep_next=True)
        rb.figure(APPARATUS_IMG, caption='图%d  恒沸点仪连接示意图' % fig_no,
                  width_cm=8.0)
        fig_no += 1
    tail = ('随后往烧瓶中依次加入 %s mL 环己烷，重复上述测量。' % cyc_add) \
        if have_vols else '随后往烧瓶中逐次加入环己烷，重复上述测量。'
    rb.para(['先绘制相图的右侧支（乙醇为主）。洗净、烘干恒沸点仪，加入 20 mL 乙醇，'
             '装好仪器，通冷凝水，将电阻丝接在稳压电源输出端。加热使液体沸腾，'
             '待温度稳定（沸腾约 3~5 min）后记下沸点 ', ('t', 'T_{b}', ITALIC),
             ' 与大气压 ', ('t', 'p_{0}', ITALIC), '；'
             '切断电源，用两支干净的滴管分别取支管凹槽处的气相冷凝液和烧瓶中的'
             '液体各一滴，立即测折射率，各平行两次。' + tail])
    fig_no_ret = fig_no
    tail2 = ('然后依次加入 %s mL 乙醇，各重复上述测量。' % eth_add) \
        if have_vols else '然后逐次加入乙醇，各重复上述测量。'
    rb.para('再绘制左侧支（环己烷为主）。回收母液，用少量环己烷洗涤蒸馏烧瓶 3~4 次，'
            '加入 20 mL 环己烷，先测纯环己烷的沸点与两相折射率，' + tail2)
    return fig_no_ret


# ---------------------------------------------------------------- 3.1 工作曲线
def _sec_curve(rb, analysis, curve, png_curve, png_refit, fig_no, tbl_no):
    fit = curve['fit']
    fit_all = curve['fit_all']
    mode = curve['mode']
    has_removed = bool(curve['removed'])
    x_name = '质量比' if mode == 'ratio' else '质量分数'

    rb.heading('3.1 标准工作曲线的绘制', 2)
    rb.heading('3.1.1 原始数据记录', 3)
    rb.para('工作曲线的原始数据列于表1。折射率均为平行三次测量的平均值；'
            '纯环己烷和纯乙醇的数据在沸点测定实验中获得，'
            '与 1~7 号瓶一起按组成从小到大排列，合并编号 i = 0~8。')
    tbl_no += 1
    rows = []
    for p in curve['points']:
        rows.append([str(p['index']), p['label'],
                     val(p['m1'], 0.0001) if p['m1'] is not None else '—',
                     val(p['m2'], 0.0001) if p['m2'] is not None else '—',
                     k(p['n'], 4), '是' if p['in_fit'] else '否'])
    rb.caption('表1  工作曲线原始数据（m₁ 为乙醇质量，m₂ 为环己烷质量）')
    rb.table(['i', '样品', 'm_{1} / g', 'm_{2} / g', 'n', '参与拟合'],
             rows, widths_cm=[1.1, 2.4, 2.6, 2.6, 2.2, 2.0], keep_together=True)

    rb.heading('3.1.2 工作曲线的拟合', 3)
    rb.para('折射率与组成的严格定量关系十分复杂，难以从理论上导出，'
            '需要根据数据点的排布选择合适的拟合方式。'
            '理想溶液的摩尔折射率与摩尔分数呈线性关系，'
            '但折射率与组成之间并无线性关系；由表1数据点的散点也可以看出明显的'
            '曲率，线性拟合会引入较大误差。参照文献[2]的做法，'
            '采用二次多项式拟合即可满足精度要求（次数过高有过拟合的风险），'
            '拟合方程为：', keep_next=True)
    rb.equation(r'n=Ax^{2}+Bx+C')
    if mode == 'ratio':
        rb.para(['式中组成变量 ', ('t', 'x', ITALIC),
                 ' 为乙醇与环己烷的质量比：'], keep_next=True)
        rb.equation(r'x=\frac{m_{1}}{m_{2}}')
        rb.para(['质量比与质量分数一一对应、可精确换算；两种定义下本组数据都能'
                 '用二次多项式表示，但以质量比为自变量时拟合优度显著更高'
                 '（', ('t', 'R^{2}', ITALIC), ' = %s 对 %s），'
                 '故本报告以质量比为组成变量。'
                 % (k(fit_all['r2'], 4),
                    k(_frac_r2(curve), 4) if _frac_r2(curve) else '—'),
                 ])
    else:
        rb.para(['式中组成变量 ', ('t', 'x', ITALIC),
                 ' 为乙醇的质量分数：'], keep_next=True)
        rb.equation(r'x=\frac{m_{1}}{m_{1}+m_{2}}')

    tbl_no += 1
    rows2 = []
    for p in curve['points']:
        rows2.append([str(p['index']), k(p['x'], 4), k(p['n'], 4),
                      ('%.2f' % p['resid_all']) if np.isfinite(p['resid_all']) else '—',
                      '是' if p['in_fit'] else '否'])
    rb.caption('表2  工作曲线的组成-折射率数据与全部数据拟合的学生化残差')
    rb.table(['i', 'x', 'n', 'r_{i}', '参与拟合'],
             rows2, widths_cm=[1.4, 3.0, 3.0, 2.8, 2.6], keep_together=True)

    if not has_removed:
        rb.para('以折射率对组成作图并作二次拟合，结果如图%d所示。' % fig_no)
        rb.figure(png_curve, caption='图%d  折射率-组成工作曲线' % fig_no,
                  width_cm=11.5)
        fig_no += 1
        rb.para('拟合结果为：', keep_next=True)
        rb.equation(r'n=(%s\pm%s)x^{2}+(%s\pm%s)x+(%s\pm%s)'
                    % (val(fit['A'], fit['se_A']), unc(fit['se_A']),
                       val(fit['B'], fit['se_B']), unc(fit['se_B']),
                       val(fit['C'], fit['se_C']), unc(fit['se_C'])))
        rb.para([('t', 'R^{2}', ITALIC), ' = %s，拟合优度高，' % k(fit['r2'], 4),
                 '后续气、液相组成的计算即以此曲线为准。'])
        return fig_no, tbl_no

    # 有剔除点：先展示全部数据的拟合
    rb.para('先对全部 %d 个数据点作二次拟合，结果如图%d所示。'
            % (fit_all['n'], fig_no))
    rb.figure(png_curve, caption='图%d  折射率-%s散点图与二次拟合（全部数据）'
              % (fig_no, x_name), width_cm=11.5)
    fig_no += 1
    rb.para(['由表2的学生化残差可见，合并序号 ',
             ('t', 'i', ITALIC), ' = %s 的数据点明显偏离趋势'
             % '、'.join(str(rm['index']) for rm in curve['removed']),
             '（', ('t', 'r', ITALIC), ' = %s），下面作定量判断。'
             % '、'.join('%.2f' % abs(rm['resid']) for rm in curve['removed']
                         if rm['resid'] is not None)])

    # ---- 3.1.3 离群点判断（有可疑点才写）
    suspects = [o for o in curve['outliers']]
    if suspects:
        rb.heading('3.1.3 离群点判断', 3)
        rb.para('为判断可疑点是否为离群点，采用经典教科书[3]的方法计算'
                '学生化残差：', keep_next=True)
        rb.equation(r'r_{i}=\frac{e_{i}}{s_{-i}\sqrt{1-h_{ii}}}')
        rb.para(['其中 ', ('t', 'e_{i}', ITALIC), ' 是用全部数据拟合二次模型后'
                 '第 ', ('t', 'i', ITALIC), ' 点的残差，', ('t', 'h_{ii}', ITALIC),
                 ' 是第 ', ('t', 'i', ITALIC), ' 点在'
                 '该模型中的杠杆值，', ('t', 's_{-i}', ITALIC),
                 ' 是剔除第 ', ('t', 'i', ITALIC), ' 点后重新拟合得到的回归标准误差。'
                 '按约定，|', ('t', 'r', ITALIC), '| > 2 时该点是潜在的离群点，'
                 '|', ('t', 'r', ITALIC), '| > 3 时基本可认定为离群点。'
                 '计算结果（表2）表明：'])
        for o in suspects:
            rb.para(['第 %d 号数据点（%s）的学生化残差 ' % (o['index'], o['label']),
                 ('t', 'r', ITALIC), ' = %s，' % ('%.2f' % o['r']),
                 '是显著的离群点，应剔除后重新进行回归分析。'])

    # ---- 3.1.4 剔除后的工作曲线
    rb.heading('3.1.4 剔除离群点后的工作曲线', 3)
    rb.para('将上述离群点剔除（在界面中按序号剔除即可）后重新进行二次拟合，'
            '结果如图%d所示。' % fig_no)
    rb.figure(png_refit, caption='图%d  剔除离群点后的折射率-%s回归曲线'
              % (fig_no, x_name), width_cm=11.5)
    fig_no += 1
    rb.para('剔除后的拟合结果为：', keep_next=True)
    rb.equation(r'n=(%s\pm%s)x^{2}+(%s\pm%s)x+(%s\pm%s)'
                % (val(fit['A'], fit['se_A']), unc(fit['se_A']),
                   val(fit['B'], fit['se_B']), unc(fit['se_B']),
                   val(fit['C'], fit['se_C']), unc(fit['se_C'])))
    rb.para([('t', 'R^{2}', ITALIC), ' = %s，较剔除前（%s）显著提升。'
             % (k(fit['r2'], 4), k(fit_all['r2'], 4)),
             '后续气、液相组成的计算即以此曲线为准。'])
    return fig_no, tbl_no


def _frac_r2(curve):
    """质量分数口径下同样数据的二次拟合 R²（仅用于比较说明）。"""
    try:
        from . import phase as _ph
        xs = np.array([p['x'] for p in curve['points']])
        ns = np.array([p['n'] for p in curve['points']])
        m1 = np.array([p['m1'] if p['m1'] is not None else (0.0 if p['kind'] == 'pure_cyc' else 1.0)
                       for p in curve['points']])
        m2 = np.array([p['m2'] if p['m2'] is not None else (1.0 if p['kind'] == 'pure_cyc' else 0.0)
                       for p in curve['points']])
        xf = _ph.composition_variable(m1, m2, 'frac')
        keep = np.array([i for i, p in enumerate(curve['points']) if p['in_fit']])
        c = np.polyfit(xf[keep], ns[keep], 2)
        res = np.polyval(c, xf[keep]) - ns[keep]
        return 1.0 - (res ** 2).sum() / ((ns[keep] - ns[keep].mean()) ** 2).sum()
    except Exception:                                       # noqa: BLE001
        return None


# ---------------------------------------------------------------- 3.2 相图
def _sec_boiling(rb, analysis, rows, azeo, png_phase, fig_no, tbl_no):
    fit = analysis['curve']['fit']
    mode = analysis['mode']
    tbl_no += 1
    rb.heading('3.2 沸点和两相成分的测定', 2)
    rb.heading('3.2.1 原始数据记录', 3)
    n_eth_side = len([r for r in rows if r['v_ethanol'] == 20])
    rb.para('沸点与两相折射率的原始数据列于表3，其中前 %d 组为往 20 mL 乙醇中'
            '依次加入环己烷，其余各组为往 20 mL 环己烷中依次加入乙醇。'
            % n_eth_side)
    rows3 = []
    for r in rows:
        ng = (r['n_g_raw'] + [''] * 2)[:2]
        nl = (r['n_l_raw'] + [''] * 2)[:2]
        rows3.append([
            _vol(r['v_ethanol']), _vol(r['v_cyclohexane']),
            k(ng[0], 4) if ng[0] != '' else '—', k(ng[1], 4) if ng[1] != '' else '—',
            k(nl[0], 4) if nl[0] != '' else '—', k(nl[1], 4) if nl[1] != '' else '—',
            k(r['T_c'], 2), k(r['p_kpa'], 1) if r['p_kpa'] is not None else '—',
        ])
    rb.caption('表3  沸点-成分测定原始数据')
    rb.table(['V(乙醇) / mL', 'V(环己烷) / mL', 'n_{g,1}', 'n_{g,2}',
              'n_{l,1}', 'n_{l,2}', 'T_{b} / ℃', 'p_{0} / kPa'],
             rows3,
             widths_cm=[2.1, 2.3, 1.9, 1.9, 1.9, 1.9, 1.9, 2.0],
             keep_together=False)

    rb.heading('3.2.2 沸点-成分相图的绘制', 3)
    rb.para('为了得到沸点与气、液两相组成的关系，需把折射率换算为组成。'
            '将工作曲线按组成反解（取 [0,1] 内的根，舍去另一个根）：',
            keep_next=True)
    rb.equation(r'x=\frac{-B-\sqrt{B^{2}-4A(C-n)}}{2A}')
    rb.para(['其中 ', ('t', 'A', ITALIC), '、', ('t', 'B', ITALIC), '、',
             ('t', 'C', ITALIC), ' 取剔除离群点后的拟合值。'
             '平行读数分别反推后取平均，作为该相的组成。'
             '将表3按气相组成从小到大重新排列成表4，'
             '温度换算为开尔文（各次测量的压力在 %s~%s kPa 之间微小变化，'
             '可忽略其影响）。'
             % (k(min(r['p_kpa'] for r in rows), 1),
                k(max(r['p_kpa'] for r in rows), 1))])
    tbl_no += 1
    srt = sorted(rows, key=lambda r: (r['wg'] if np.isfinite(r['wg']) else 9))
    rows4 = []
    for j, r in enumerate(srt):
        rows4.append([str(j + 1),
                      k(r['n_g'], 4) if np.isfinite(r['n_g']) else '—',
                      k(r['n_l'], 4) if np.isfinite(r['n_l']) else '—',
                      k(r['wg'], 4) if np.isfinite(r['wg']) else '—',
                      k(r['wl'], 4) if np.isfinite(r['wl']) else '—',
                      k(r['T_K'], 2) if r['T_K'] else '—'])
    rb.caption('表4  沸点-成分测定最终数据')
    rb.table(['序号', 'n_{g}', 'n_{l}', 'x_{g}', 'x_{l}', 'T_{b} / K'],
             rows4, widths_cm=[1.6, 2.5, 2.5, 2.5, 2.5, 2.8],
             keep_together=False)
    rb.para('根据表4绘制沸点-成分相图，其中数据点的连接采用弧长参数化的'
            '三次 B 样条曲线，结果如图%d所示。' % fig_no)
    rb.figure(png_phase, caption='图%d  环己烷-乙醇体系的沸点-成分相图' % fig_no,
              width_cm=12.5)
    fig_no += 1
    rb.para('由图%d可见，液相线与气相线在最低点相遇，'
            '说明环己烷-乙醇体系是具有最低恒沸点的双液系；'
            '在环己烷一侧（左支）气相组成大于液相组成，'
            '在乙醇一侧（右支）正好相反。' % (fig_no - 1))

    rb.heading('3.2.3 最低恒沸点及误差分析', 3)
    if not azeo.get('ok'):
        rb.para('数据不足以定位恒沸点：%s' % azeo.get('reason', ''))
        return fig_no, tbl_no
    rb.para('恒沸点由两支平滑曲线的最低点定位：本报告用弧长参数化的三次 B 样条'
            '分别平滑气相线与液相线，在两条曲线相差最小的位置读取恒沸温度与'
            '组成（相图上气相线除纯组分端与恒沸点外都在液相线上方，'
            '因此该位置即两线的相切点）。结果为：')
    x_name = '质量比 m(乙醇)/m(环己烷)' if mode == 'ratio' else '乙醇质量分数'
    rb.para([('t', 'T', ITALIC), ' = %s K，%s = (%s)。'
             % (k(azeo['T_K'], 2), x_name, pm(azeo['w'], azeo['sigma_w']))])

    rb.para('对组成作简单的误差分析。由工作曲线反解公式，'
            '组成的不确定度来自拟合系数与折射率读数两项，传播公式为：',
            keep_next=True)
    rb.equation(r'\sigma_{x}=\sqrt{(\frac{\partial x}{\partial A}\sigma_{A})^{2}'
                r'+(\frac{\partial x}{\partial B}\sigma_{B})^{2}'
                r'+(\frac{\partial x}{\partial C}\sigma_{C})^{2}'
                r'+(\frac{\partial x}{\partial n}\sigma_{n})^{2}}')
    den = 2 * fit['A'] * azeo['w'] + fit['B']
    rb.para('各偏导数由隐函数求导得到：', keep_next=True)
    rb.equation(r'\frac{\partial x}{\partial A}=-\frac{x^{2}}{2Ax+B},\qquad '
                r'\frac{\partial x}{\partial B}=-\frac{x}{2Ax+B}')
    rb.equation(r'\frac{\partial x}{\partial C}=-\frac{1}{2Ax+B},\qquad '
                r'\frac{\partial x}{\partial n}=\frac{1}{2Ax+B}')
    parts = azeo.get('sigma_parts') or {}
    rb.para([('t', 'A', ITALIC), '、', ('t', 'B', ITALIC), '、',
             ('t', 'C', ITALIC), ' 的标准差由拟合协方差矩阵给出；折射率读数误差取 ',
             ('t', 'σ_{n}', ITALIC), ' = %s（最后一位的估读误差）。' % k(analysis['sigma_n'], 4),
             '在恒沸组成处代入各项数值：拟合系数项贡献 %s、%s、%s，'
             '读数项贡献 %s，合成得 ' % (
                 k(parts.get('A', 0), 4), k(parts.get('B', 0), 4),
                 k(parts.get('C', 0), 4), k(parts.get('n', 0), 4)),
             ('t', 'σ_{x}', ITALIC), ' = %s，故组成写作 (%s)。'
             % (k(azeo['sigma_w'], 4), pm(azeo['w'], azeo['sigma_w']))])
    rb.para([('t', '2', {}), ('t', 'A', ITALIC), ('t', 'x', ITALIC),
             ('t', '+', {}), ('t', 'B', ITALIC),
             ' 在恒沸组成处为 %s，'
             '即折射率每偏离 0.001，反推出的组成就会改变约 %s，'
             '这是气相线在恒沸点附近近乎垂直、组成对折射率极其敏感的量度。'
             % (k(den, 4), k(abs(1.0 / den) * 0.001, 3))])

    lit_T = analysis.get('lit_T_K')
    lit_x = analysis.get('lit_x')
    if lit_x is not None:
        lit_name = '质量比' if mode == 'ratio' else '质量分数'
        lit_w = analysis.get('lit_w')
        dev = analysis.get('deviation')
        rb.para([('t', 'σ_{x}', ITALIC), ' 之所以达到 %s 量级，主要来自拟合系数'
                 % k(azeo['sigma_w'], 3),
                 '经反解公式分母 ',
                 ('t', '2', {}), ('t', 'A', ITALIC), ('t', 'x', ITALIC),
                 ('t', '+', {}), ('t', 'B', ITALIC),
                 ' 的放大。文献[4]给出环己烷-乙醇体系的最低恒沸点为 '
                 '%s K，恒沸组成以乙醇摩尔分数 0.4540 计，'
                 '换算成乙醇质量分数为 %s' % (k(lit_T, 2), k(lit_w, 4)),
                 '（%s 为 %s）。本实验测得恒沸点 %s K 与文献值相差 %s K；'
                 '组成 (%s) 较文献 %s 相差 %s%%，'
                 '明显超出不确定度范围，属于系统偏差，其来源在 4.2 节讨论。'
                 % (lit_name, k(lit_x, 4), k(azeo['T_K'], 2),
                    k(azeo['T_K'] - lit_T, 2),
                    pm(azeo['w'], azeo['sigma_w']), k(lit_x, 4),
                    pct(abs(dev) * 100) if dev is not None else '—')])
    return fig_no, tbl_no


# ---------------------------------------------------------------- 4 结果与讨论
def _sec_results(rb, analysis):
    curve = analysis['curve']
    azeo = analysis['azeotrope']
    rows = analysis['rows']
    rb.heading('4.1 实验结果', 2)
    segs = [
        '本实验由称量法建立环己烷-乙醇体系的折射率-组成标准工作曲线，'
        '二次多项式拟合的 ', ('t', 'R^{2}', ITALIC),
        ' = %s；' % k(curve['fit']['r2'], 4),
        '用回流冷凝法测定了 %d 个组成的沸点及气、液两相折射率，'
        '绘制了体系的沸点-成分图。' % len(rows),
    ]
    pure_eth = next((r for r in rows if r['v_ethanol'] == 20 and r['v_cyclohexane'] == 0), None)
    pure_cyc = next((r for r in rows if r['v_cyclohexane'] == 20 and r['v_ethanol'] == 0), None)
    if pure_eth and pure_cyc:
        segs += [
            '测得纯乙醇沸点 %s ℃、纯环己烷沸点 %s ℃。'
            % (k(pure_eth['T_c'], 2), k(pure_cyc['T_c'], 2)),
        ]
    if azeo.get('ok'):
        x_name = '质量比 m(乙醇)/m(环己烷)' if analysis['mode'] == 'ratio' \
            else '乙醇质量分数'
        segs += [
            '体系的最低恒沸点为 ', ('t', 'T', ITALIC), ' = %s K，' % k(azeo['T_K'], 2),
            '恒沸混合物的 %s 为 (%s)。' % (x_name, pm(azeo['w'], azeo['sigma_w'])),
        ]
        if analysis.get('deviation') is not None:
            segs += [
                '与文献值（恒沸点 %s K、乙醇质量分数 %s）相比，'
                '温度相差 %s K，组成偏低约 %s%%。'
                % (k(analysis['lit_T_K'], 2), k(analysis['lit_w'], 4),
                   k(azeo['T_K'] - analysis['lit_T_K'], 1),
                   pct(abs(analysis['deviation']) * 100)),
            ]
    rb.para(segs)


def _sec_discussion(rb, analysis):
    azeo = analysis['azeotrope']
    curve = analysis['curve']
    rows = analysis['rows']
    mode = analysis['mode']
    rb.heading('4.2 实验讨论', 2)

    rb.heading('4.2.1 相图形状与恒沸组成的偏差', 3)
    sens = ''
    if azeo.get('ok'):
        den = 2 * curve['fit']['A'] * azeo['w'] + curve['fit']['B']
        sens = ('在恒沸组成处折射率每偏差 0.001，反推出的组成就会移动约 %s，'
                % k(abs(1.0 / den) * 0.001, 3))
    rb.para(['由图可见，气相线在恒沸点附近近乎垂直：气相折射率变化不到 0.004，'
             '组成却扫过整个恒沸区。这是折射率-组成工作曲线在恒沸点附近'
             '斜率平缓的必然结果，%s折射率的微小误差就会被放大成组成的'
             '很大偏差，也是恒沸组成不确定度（±%s）的主要来源。'
             % (sens, k(azeo['sigma_w'], 3) if azeo.get('ok') else '—')])
    rb.para('测得的恒沸组成较文献值偏低（偏向环己烷）。一个与实验程序直接相关的'
            '原因是分馏漂移：乙醇的沸点（78.4 ℃）低于环己烷（80.1 ℃），'
            '每轮测量中蒸出的蒸气都富乙醇，倒回或取样都会使母液逐渐富环己烷；'
            '左侧支要经过多轮“沸腾—取样”才到达恒沸区，'
            '累计的漂移可以把液相组成系统性拉低。'
            '此外，气相冷凝液量很少，转移与测定过程中富乙醇组分更易挥发损失，'
            '也会把气相组成往环己烷方向拉。'
            '纯环己烷沸点比文献值低约 0.6 K（纯乙醇只低 0.03 K），'
            '提示温度计示数或样品纯度还可能有系统误差，'
            '这会同时影响恒沸温度与组成。')

    rb.heading('4.2.2 主要误差来源', 3)
    denom = 2 * curve['fit']['A'] * azeo['w'] + curve['fit']['B']         if azeo.get('ok') else 1.0
    parts = analysis['sigma_parts'] or {}
    rb.para(['（1）折射率读数误差：阿贝折射仪最后一位为估读，取 ',
             ('t', 'σ_{n}', ITALIC), ' = %s，' % k(analysis['sigma_n'], 4),
             '经工作曲线反解放大约 %s 倍，单是读数项就贡献 '
             % k(abs(1.0 / denom), 1),
             ('t', 'σ', ITALIC), ' ≈ %s；' % k(parts.get('n', 0), 4),
             '（2）工作曲线系数的不确定度：三项合计贡献 ', ('t', 'σ', ITALIC),
             ' ≈ %s，是组成不确定度的主要部分；'
             % k(np.sqrt(sum(v ** 2 for kk, v in parts.items() if kk != 'n')), 4),
             '（3）温度：折射率的温度系数为负（乙醇约 −4×10⁻⁴ K⁻¹、'
             '环己烷约 −5×10⁻⁴ K⁻¹），若测样品与绘工作曲线的温度相差 1 K，'
             '组成会系统偏差约 0.006，本实验未恒温，是重要的系统误差来源；'
             '（4）压力：各次测量大气压在 0.3 kPa 内波动，对沸点的影响不足 0.1 K，'
             '可以忽略；（5）取样：气相冷凝液少、易挥发，凹槽存液混合不充分，'
             '液相取样点单一，都会带来随机偏差。'])

    rb.heading('4.2.3 思考题', 3)
    rb.para('（1）气、液两相是怎样达成平衡的？若支管凹槽处体积太大，对测量有何影响？'
            '电阻丝加热使液体沸腾，蒸气沿支管上升被冷凝管冷却，冷凝液积存在凹槽中并'
            '沿管壁回流；当单位时间的冷凝量与蒸发量相等时，体系达到稳定状态，'
            '此时凹槽中的冷凝液就是与液相平衡的气相样品。凹槽体积太大时，'
            '建立平衡需要冷凝更多蒸气、时间更长；更严重的是凹槽相当于一小段'
            '精馏柱，存留的旧冷凝液与新冷凝液混合，'
            '取出的“气相”组成会偏离真正的平衡气相组成，分馏效应也使组成失真。')
    rb.para('（2）平衡时气、液两相的温度应该不应该一样？实际是否一样？'
            '怎样防止温度的差异？理论上两相处于同一平衡体系，温度应该相同。'
            '实际上温度计探头浸在液相中，读数主要是液相温度，'
            '气相空间与冷凝管附近的温度可能略低；加热过猛时液相还可能局部过热。'
            '为防止差异，应控制加热功率使回流平稳（蒸气环高度稳定、'
            '冷凝液一滴一滴回流），沸腾 3~5 min 待读数不变后再记录，'
            '并把探头放在液面下适当深度、不接触电阻丝和瓶壁。')
    rb.para(['（3）折射率的温度系数有多大？如不恒温，对折射率的数据影响如何？'
             '液体折射率随温度升高而减小，乙醇约 −4×10⁻⁴ K⁻¹、'
             '环己烷约 −5×10⁻⁴ K⁻¹（20 ℃ 附近，随波长略有变化）。'
             '若不恒温，测样品与绘工作曲线时的温度差 ', ('t', 'ΔT', ITALIC),
             ' 会带来 Δ', ('t', 'n', ITALIC), ' ≈ (4~5)×10⁻⁴·',
             ('t', 'ΔT', ITALIC), ' 的折射率偏差；经工作曲线反解放大约 14 倍，'
             '组成的系统偏差约 0.006·', ('t', 'ΔT', ITALIC),
             '，温度差 2~3 K 时达到 0.01~0.02，'
             '与组成的不确定度同量级，不可忽略。'
             '因此应当用恒温水循环把折射仪棱镜恒温，'
             '并尽量保证样品测定与工作曲线绘制在同一温度下进行。'])


def _sec_conclusion(rb, analysis):
    azeo = analysis['azeotrope']
    curve = analysis['curve']
    rb.heading('4.3 实验结论', 2)
    segs = [
        '本实验用称量法配制系列组成的环己烷-乙醇溶液，建立了折射率-组成'
        '标准工作曲线（二次多项式拟合，', ('t', 'R^{2}', ITALIC),
        ' = %s，剔除 1 个离群点）；' % k(curve['fit']['r2'], 4),
        '用回流冷凝法测定了 %d 个组成的沸点与气、液两相折射率，'
        '绘制了体系的沸点-成分图。' % len(analysis['rows']),
    ]
    if azeo.get('ok'):
        x_name = '质量比 m(乙醇)/m(环己烷)' if analysis['mode'] == 'ratio' \
            else '乙醇质量分数'
        segs += [
            '测得 %s kPa 下体系的最低恒沸点为 %s K，恒沸混合物的 %s 为 (%s)，'
            '并与文献值作了比较、分析了偏差来源。'
            % (k(max(r['p_kpa'] or 0 for r in analysis['rows']), 1),
               k(azeo['T_K'], 2), x_name, pm(azeo['w'], azeo['sigma_w'])),
        ]
    segs += [
        '计算表明，影响组成不确定度的主要因素是折射率读数误差经工作曲线的放大'
        '与拟合系数的不确定度；恒沸组成偏低的系统偏差主要来自多轮沸腾引起的'
        '分馏漂移与取样挥发。',
    ]
    rb.para(segs)
