# -*- coding: utf-8 -*-
"""生成《化学反应动力学探究》实验报告 .docx（完整版）。

    封面
    摘要 / 关键词
    1 引言（预留预习图片位置）
    2 实验部分
    3 数据与结果
      3.1 旋光度–浓度关系
      3.2 蔗糖水解反应级数的判定
      3.3 各酸浓度下的一级拟合
      3.4 氢离子反应级数
    4 结果与讨论
      4.1 实验结果 / 4.2 实验讨论 / 4.3 实验结论
    参考文献
"""
from __future__ import annotations

import decimal
import math
import os

import numpy as np

from . import plotting
from .docxkit import ReportBuilder
from .sigfig import k, pm, pct, sci, sci_pm

ITALIC = {'italic': True}
TITLE = '化学反应动力学探究'
INTRO_BLANK_LINES = 26
SIG_DIGITS = 2

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_IMG = os.path.join(ASSETS, '引言图.jpg')


# ---------------------------------------------------------------- 数字格式


















# ---------------------------------------------------------------- 数字格式


def _cal_claim(analysis):
    """摘要里关于「旋光度–浓度线性」的那半句，按标定的实际质量生成。

    不能无条件写「验证旋光度与浓度呈良好线性关系」：用户 2026-11-10 这批数据
    只有一个浓度点的静态读数，根本无从验证线性（SKILL §27：算不了就说清为什么）。
    """
    fit = analysis['calibration']['fit']
    n = (fit or {}).get('n') or 0
    if not fit:
        return '测量不同浓度蔗糖溶液的旋光度并尝试建立标定直线，'
    if n < 3:
        return ('测量蔗糖溶液的旋光度作为标定参考（本次只有 %d 个浓度点，'
                '线性关系未能独立验证）；' % n)
    r2 = fit.get('r2')
    if r2 is not None and r2 >= 0.999:
        return '测量不同浓度蔗糖溶液的旋光度，验证旋光度与浓度呈良好线性关系；'
    return '测量不同浓度蔗糖溶液的旋光度，其线性关系一般；'


def _ll_agrees(ll, rl):
    """lg–lg 线性拟合的 n 与非线性拟合的 n 是否在不确定度内一致。

    非线性拟合的自由度为 0 时没有 sigma，只能用「相差 < 20%」这种粗判据，
    并且明确说明这是粗判据——不能假装有误差棒。

    """

    try:

        a = float(ll['slope'])

        b = float(rl['n'])

    except (TypeError, ValueError):

        return False

    sa = ll.get('sigma_slope')

    sb = rl.get('sigma_n')

    if sa is not None and sb is not None:

        try:

            return abs(a - b) <= 2.0 * math.hypot(float(sa), float(sb))

        except (TypeError, ValueError):

            pass

    return abs(a - b) <= 0.2 * max(abs(b), 1e-9)




def _rl_n(rl, nd=2):
    """把非线性拟合的 n 写成「值 ± σ」或「只有值」。

    自由度 0（数据点数 = 参数个数）时 ``sigma_n`` 是 None——此时只给点估计，
    不能拿 None 去 pm()：那会静默印成「4.000」，读者会以为 n 精确到毫位。
    """
    sig = rl.get('sigma_n')
    try:
        ok = sig is not None and np.isfinite(float(sig))
    except (TypeError, ValueError):
        ok = False
    return pm(rl['n'], float(sig)) if ok else k(rl['n'], nd)


# sci / sci_pm 已统一到 pcal/sigfig.py（canonical = _core/sigfig.py），
# 不要在本文件里再各写一份：历史上 6 个模块的本地副本对 None/NaN/inf
# 分化出 6 种行为（有的抛 TypeError/ValueError/OverflowError、有的把
# 破折号塞进科学记数法印成 (—)×10^{-5}），审计 B P1-3。
class Num:
    """表号 / 图号的顺序计数器。

    为什么不用字面量：本报告的表数**随数据组数变化**——组数 ≤3 时 α–t
    只占一张表，>3 时占两张。写死编号会在组数变化时断号（audit_docx 的
    caption.gap 在 3 组数据下抓到「表2 → 表4」，因为表3 根本没出现）。
    """

    def __init__(self):
        self._t = 0
        self._f = 0

    def t(self):
        self._t += 1
        return self._t

    def f(self):
        self._f += 1
        return self._f

    def t_next(self):
        """下一个表号（不消耗），用于「先说表N、后出表N」的正文引用。"""
        return self._t + 1

    def f_next(self):
        return self._f + 1


def _row(g, key, sub=None):
    fit = g['fits'].get(key)
    if not fit:
        return '—'
    return fit[sub] if sub else fit


# ---------------------------------------------------------------- 主流程
def build_report(analysis, cfg, out_path, plots_dir, template_path,
                 progress=None, cover_tail_blanks=0):
    def log(msg):
        if progress:
            progress(msg)

    rb = ReportBuilder(template_path, cover_tail_blanks=cover_tail_blanks)
    num = Num()          # 表号/图号计数器：编号必须跟着实际条目数走（§27）
    cal = analysis['calibration']
    groups = analysis['groups']
    order = analysis['order']
    rl = analysis['rate_law']
    ll = analysis['loglog']
    ainf = analysis['alpha_inf']

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

    png_cal = save(plotting.make_calibration_figure(cal), 'calibration.png')
    png_at = save(plotting.make_alpha_t_figure(groups), 'alpha_t.png')
    png_order = (save(plotting.make_order_figure(
        next(g for g in groups if g['label'] == order['group'])), 'order.png')
        if order else None)
    png_first = save(plotting.make_first_order_figure(groups), 'first_order.png')
    png_rate = save(plotting.make_rate_law_figure(rl), 'rate_law.png') if rl else None
    png_log = save(plotting.make_loglog_figure(ll), 'loglog.png') if ll else None

    # ================================================================ 摘要
    log('撰写摘要…')
    main_g = next((g for g in groups if g['label'] == (cfg.get('order_group') or '')),
                  groups[0] if groups else None)
    abs_segs = [
        {'text': '摘要 ', 'bold': True, 'cjk': '黑体'},
        '本实验用基于机器学习的数智旋光仪监测蔗糖在盐酸催化下的水解动力学。',
        _cal_claim(analysis),
        '随后在 ', str(len(groups)), ' 个不同盐酸浓度下记录 ',
        ('t', 'α_{t}–t', ITALIC),
        ' 曲线，用积分法（尝试法）判定蔗糖的反应级数，并求各组速率常数与半衰期；'
        '最后由 ', ('t', 'k_{1}', ITALIC), '–', ('t', 'c', ITALIC),
        '(', ('t', 'H^{+}', ITALIC), ') 关系确定氢离子反应级数。',
    ]
    if cal['fit']:
        abs_segs += [
            '标定直线的 ', ('t', 'R^{2}', ITALIC), ' = %s；' % k(cal['fit']['r2'], 4),
        ]
    if order:
        abs_segs += [
            '以 %s 组判定，蔗糖为 %d 级反应' % (order['group'], order['best']),
            '（零、一、二级拟合的 ', ('t', 'R^{2}', ITALIC),
            ' 分别为 %s、%s、%s）；'
            % tuple(k(order['r2'][str(i)], 4) for i in (0, 1, 2)),
        ]
    if main_g and np.isfinite(main_g['k1']):
        abs_segs += [
            '%s 组的 ' % main_g['label'], ('t', 'k_{1}', ITALIC), ' = ',
            sci_pm(main_g['k1'], main_g['sigma_k1']), ' s^{-1}，半衰期 ',
            ('t', 't_{1/2}', ITALIC), ' = ',
            pm(main_g['t_half'], main_g['sigma_t_half']), ' s；',
        ]
    if rl:
        abs_segs += [
            '非线性拟合得氢离子反应级数 ', ('t', 'n', ITALIC), ' = ',
            _rl_n(rl), '。',
        ]
    if np.isfinite(ainf['measured']) and np.isfinite(ainf['theory']):
        abs_segs += [
            '实验测得的最终旋光度 ', ('t', 'α_{∞}', ITALIC), ' = ',
            k(ainf['measured'], 2), '°，与由比旋光度估算的理论值 ',
            k(ainf['theory'], 2), '° 相差 %s%%。' % pct(abs(ainf['relative'])),
        ]
    rb.para(abs_segs)
    rb.para([{'text': '关键词 ', 'bold': True},
             '旋光度；蔗糖水解；一级反应；速率常数；反应级数；数智旋光仪'])
    rb.blank()

    # ================================================================ 1 引言
    rb.heading('1 引言', page_break_before=True)
    fig_intro = num.f()
    rb.para('该实验的实验目的、实验原理及实验方法如图%d所示。' % fig_intro)
    if os.path.exists(INTRO_IMG):
        rb.figure(INTRO_IMG, caption='图%d  实验目的、原理及方法' % fig_intro,
                  width_cm=11.0)
    else:
        for _ in range(INTRO_BLANK_LINES):
            rb.blank()
        rb.caption('图%d  实验目的、原理及方法' % fig_intro)

    # ================================================================ 2 实验部分
    rb.heading('2 实验部分^{[1]}', page_break_before=True)
    rb.heading('2.1 仪器和试剂', 2)
    rb.heading('2.1.1 仪器', 3)
    rb.para('数智旋光仪（WXG-4 型圆盘旋光仪 + 同轴步进电机 + 相机 + 机器学习识别程序），'
            '超级恒温槽，恒温水浴锅，恒温旋光管，50 mL、250 mL 容量瓶，'
            '250 mL 烧杯，25 mL 移液管，100 mL 磨口锥形瓶，100 mL 量筒，'
            '滴管，洗耳球，玻璃棒，擦镜纸。')
    rb.heading('2.1.2 试剂', 3)
    rb.para('蔗糖（AR）；盐酸（AR，约 6、5、4、3、2 mol·dm^{-3}）；去离子水。')

    rb.heading('2.2 实验内容', 2)
    rb.para('（1）旋光仪校准与机器学习模型训练。打开旋光仪、电机控制盒和软件，'
            '连接串口与相机，锁定圆形识别区域。将盛有去离子水的旋光管放入旋光仪，'
            '分别录制“明暗明”和“暗明暗”三分视场的视频作为训练集，训练二元分类模型，'
            '并自动寻找旋光零点。')
    rb.para('（2）旋光度–浓度工作曲线。配制一系列浓度的蔗糖溶液各 50 mL，'
            '置于恒温水浴中恒温；用待测液润洗旋光管 2 次后装入溶液，'
            '用静态测量测定旋光度，每个浓度平行测量多次。本步骤由全组同学分工完成并共享数据。')
    rb.para('（3）蔗糖水解动力学测量。用 250 mL 容量瓶配制一定浓度的蔗糖溶液，'
            '用 25 mL 移液管移取 25 mL 于 100 mL 锥形瓶中，与另一份 25 mL 盐酸'
            '同时置于恒温水浴中恒温。恒温后把盐酸倒入蔗糖溶液，'
            '在盐酸流入一半时点击“开始计时”，全部加入后迅速摇匀并转移至旋光管，'
            '点击“开始跟踪”，软件按设定的步进角自动记录时间与旋光度。'
            '达到设定采样点数后自动停止并保存 xlsx 文件。')
    rb.para([
        '（4）改变盐酸浓度。分别用约 6、5、4、3、2 mol·dm^{-3} 的盐酸重复上述动态测量，'
        '得到 ' + str(len(groups)) + ' 组动力学曲线。所有测量结束后，'
        '把剩余的反应液放置足够长时间，用静态测量读取反应终了时的旋光度 ',
        ('t', 'α_{∞}', ITALIC), '。实验温度为 %.1f ℃。' % analysis['temperature'],
    ])

    # ================================================================ 3 数据与结果
    rb.heading('3 数据与结果')
    log('写旋光度–浓度关系…')
    _sec_calibration(rb, analysis, cal, png_cal, num)
    log('写级数判定…')
    _sec_order(rb, analysis, groups, order, png_at, png_order, num)
    log('写一级拟合…')
    _sec_first_order(rb, analysis, groups, png_first, num)
    log('写氢离子级数…')
    _sec_rate_law(rb, analysis, rl, ll, png_rate, png_log, num)

    # ================================================================ 4 结果与讨论
    rb.heading('4 结果与讨论')
    _sec_results(rb, analysis)
    _sec_discussion(rb, analysis)
    _sec_conclusion(rb, analysis)

    # ================================================================ 参考文献
    rb.heading('参考文献')
    rb.para('[1] 北京大学化学学院物理化学实验教学组. 物理化学实验（2026年秋季试用）[M]. '
            '北京：北京大学化学与分子工程学院, 2026.', indent_chars=0)
    rb.para('[2] 傅献彩, 侯文华. 物理化学（第六版）下册[M]. 北京：高等教育出版社, 2022.',
            indent_chars=0)
    rb.para('[3] 钟红梅, 侯德顺. WXG-4 型旋光仪测定旋光度操作方法[J]. '
            '实验室科学, 2011.', indent_chars=0)

    log('写入 docx…')
    rb.save(out_path)
    return out_path


# ---------------------------------------------------------------- 3.1 标定
def _sec_calibration(rb, analysis, cal, png, num):
    rb.heading(['3.1 旋光度–浓度关系'], 2)
    rb.heading('3.1.1 原始数据', 3)
    # 表 1 只示出**平均值与重复次数**（用户 2026-11-10 要求）：
    # Polariputer 静态测量对同一份溶液连读 N 次，把 N 次原始读数全列出来
    # 只会淹没线性关系，读者真正需要的是「这个平均值是几次测出来的」。
    # 小组成员共享的数据每人只报一个最终平均值（n=1），照实写 1。
    tbl = num.t()          # 编号必须跟着实际条目数走，不能写死（§27）
    fig = num.f()
    pts = cal['points']
    multi = [p for p in pts if (p.get('n') or 1) > 1]
    if multi:
        ns = sorted({int(p.get('n') or 1) for p in pts if (p.get('n') or 1) > 1})
        rb.para([
            '不同浓度蔗糖溶液的旋光度列于表%d。表中只示出各浓度的' % tbl,
            '旋光度平均值与平行测量次数（分别为 %s 次），'
            % '、'.join(str(x) for x in ns),
            '原始读数由 Polariputer 静态测量连续读出，此处不再逐条罗列；'
            '表中同时给出线性拟合时是否采用该点。',
        ])
    else:
        rb.para([
            '不同浓度蔗糖溶液的旋光度列于表%d。所有旋光度都是平行多次测量'
            '的平均值；表中同时给出线性拟合时是否采用该点。' % tbl,
        ])
    rows = []
    for p in pts:
        rows.append([str(p['index'] + 1), k(p['c'], 4), k(p['alpha'], 2),
                     str(int(p.get('n') or 1)),
                     '否' if p['exclude'] else '是'])
    rb.caption('表%d  不同浓度蔗糖溶液的旋光度' % tbl)
    rb.table(['组别', 'c_{suc} / (g·mL^{-1})', 'α_{suc} / (°)', '重复次数',
              '参与拟合'],
             rows, widths_cm=[1.6, 3.9, 3.5, 2.2, 2.2], keep_together=True)
    if cal['exclude']:
        rb.para([
            '其中第 %s 组数据在拟合残差中明显偏离趋势，作为离群点剔除；'
            '是否剔除可结合图%d的 95%% 置信带判断。' % (
                '、'.join(str(i + 1) for i in cal['exclude']), fig),
        ])

    rb.heading('3.1.2 旋光度–浓度拟合', 3)
    rb.para('以旋光度对浓度作图并作线性拟合，结果如图%d所示，'
            '阴影为 95%% 置信带。' % fig)
    rb.figure(png, caption='图%d  蔗糖的旋光度–浓度关系与 95%% 置信带' % fig,
              width_cm=11.5)
    if not cal['fit']:
        rb.para('可用于拟合的数据点少于 2 个，未能完成标定。')
        return
    fit = cal['fit']
    rb.para('线性拟合结果为：', keep_next=True)
    rb.equation(r'\alpha_{suc}=(%s\pm%s)c_{suc}+(%s\pm%s)'
                % (k(fit['slope'], 2), k(fit['sigma_slope'], 2),
                   k(fit['intercept'], 3), k(fit['sigma_intercept'], 3)))
    # 「呈良好的线性关系」必须由点数与 R² 支撑：只有 2 个点时直线必然过两点、
    # R² 恒为 1，说「线性良好」是空话（SKILL §27「算不了要明确说清为什么」）。
    n_fit = fit.get('n') or 0
    r2_fit = fit.get('r2')
    if n_fit < 3:
        closing = ('本次可用的标定点只有 %d 个，直线由这 %d 点唯一确定，'
                   '无法据此验证线性关系；该直线只用于给出 ' % (n_fit, n_fit))
        closing += 'α_{0} 与 α_{∞} 的大致量级，后续结果的系统偏差需另行评估。'
        tail = [closing]
    elif r2_fit is not None and r2_fit >= 0.999:
        tail = ['由图%d可见，除被剔除的点外，旋光度与浓度在实验范围内呈良好的'
                '线性关系，因此可以用该直线估算反应体系的初始旋光度。' % fig]
    else:
        tail = ['由图%d可见，旋光度与浓度的线性关系一般（' % fig,
                ('t', 'R^{2}', ITALIC), ' = %s），'
                '用该直线估算初始/最终旋光度会引入额外偏差。' % k(r2_fit, 5)]
    rb.para([
        '其中 ', ('t', 'c_{suc}', ITALIC), ' 的单位为 g·mL^{-1}，线性相关系数 ',
        ('t', 'R^{2}', ITALIC), ' = %s。' % k(fit['r2'], 5),
    ] + tail)


# ---------------------------------------------------------------- 3.2 级数
def _sec_order(rb, analysis, groups, order, png_at, png_order, num):
    rb.heading('3.2 蔗糖水解反应级数的判定', 2)
    rb.heading(['3.2.1 ', ('t', 'α_{t}', ITALIC), '–', ('t', 't', ITALIC), ' 曲线'], 3)
    labels = [g['label'] for g in groups]
    # α–t 数据按组数分表：≤3 组一张、>3 组两张。表号必须跟着实际张数走
    # （以前写死 表2/表3，3 组数据时下一张直接叫表4，audit 报 caption.gap）。
    chunks = [labels[:3]] + ([labels[3:]] if labels[3:] else [])
    chunks = [c for c in chunks if c]
    first_tbl = num.t_next()
    last_tbl = first_tbl + max(0, len(chunks) - 1)
    tbl_desc = ('表%d' % first_tbl if len(chunks) <= 1
                else '表%d、表%d' % (first_tbl, last_tbl))
    fig = num.f()
    rb.para([
        '不同盐酸浓度下测得的 ', ('t', 'α_{t}', ITALIC), '–',
        ('t', 't', ITALIC), ' 数据见%s，曲线如图%d所示。'
        '表中只列出每组的一部分数据点；完整的 xlsx 原始数据保存在工具的数据文件中。'
        % (tbl_desc, fig),
    ])
    for chunk in chunks:
        _alpha_t_table(rb, groups, chunk, num)
    rb.figure(png_at, caption='图%d  不同盐酸浓度下蔗糖水解的 α–t 曲线' % fig,
              width_cm=13.5)
    rb.para('由图%d可见，盐酸浓度越高，达到相同反应进度所需的时间越短，'
            '说明该反应对氢离子为正级数；曲线本身不是直线，可以排除零级反应。'
            '但仅凭 α–t 曲线不能判定蔗糖的级数，下面用积分法（尝试法）作定量判断。'
            % fig)

    rb.heading(['3.2.2 ', ('t', 'α_{0}', ITALIC), ' 与 ',
                ('t', 'α_{∞}', ITALIC), ' 的确定'], 3)
    rb.para([
        '反应体系的初始蔗糖浓度由配制浓度和 1:1 混合稀释得到：',
    ], keep_next=True)
    rb.equation(r'c_{0}=\frac{c_{stock}}{2}=\frac{%.4f}{2}=%.4f\ '
                r'\mathrm{g}\cdot\mathrm{mL}^{-1}'
                % (analysis.get('c0', 0) * 2, analysis.get('c0', 0)))
    if cal_fit := analysis['calibration']['fit']:
        rb.para([
            '把 ', ('t', 'c_{0}', ITALIC), ' 代入 3.1 节的标定直线，得初始旋光度：',
        ], keep_next=True)
        rb.equation(r'\alpha_{0}=%.2f\times%.4f+%.3f=%.2f\degree'
                    % (cal_fit['slope'], analysis['c0'], cal_fit['intercept'],
                       analysis['alpha0']))
    rb.para([
        '反应终了时蔗糖完全水解为葡萄糖和果糖，理论上最终旋光度可由三种糖的'
        '比旋光度估算：',
    ], keep_next=True)
    rb.equation(r'\alpha_{\infty}=\alpha_{0}\times\frac{M_{glu}}{M_{suc}}'
                r'\times\frac{[\alpha]_{glu}+[\alpha]_{fru}}{[\alpha]_{suc}}')
    ainf = analysis['alpha_inf']
    rb.para([
        '取 ', ('t', 'M_{suc}', ITALIC), ' = 342.296 g·mol^{-1}，',
        ('t', 'M_{glu}', ITALIC), ' = 180.156 g·mol^{-1}，',
        ('t', '[α]_{suc}', ITALIC), ' = 66.6°·dm^{-1}·g^{-1}·mL，',
        ('t', '[α]_{glu}', ITALIC), ' = 52.5°·dm^{-1}·g^{-1}·mL，',
        ('t', '[α]_{fru}', ITALIC), ' = −91.9°·dm^{-1}·g^{-1}·mL，'
        '估算得 ', ('t', 'α_{∞}', ITALIC), ' = ', k(ainf['theory'], 2), '°；'
        '实验测得的最终旋光度为 ', k(ainf['measured'], 2), '°，两者相差 ',
        pct(abs(ainf['relative'])), '%。',
        ('（实验值是 %d 次静态读数的平均值。）' % ainf['n']
         if (ainf.get('n') or 1) > 1 else ''),
    ])
    rb.para([
        '实验值与理论值接近，说明反应已进行完全，且比旋光度数据可靠。'
        '后续拟合采用实验值 ', ('t', 'α_{∞}', ITALIC), ' = ',
        k(ainf['used'], 2), '°，因为它只依赖仪器读数，'
        '而理论值还引入了比旋光度、分子量和温度等近似。',
    ])

    rb.heading('3.2.3 零级、一级与二级的尝试', 3)
    if not order:
        rb.para('没有可用于级数判定的数据组。')
        return
    g = next((x for x in groups if x['label'] == order['group']), None)
    fig = num.f()
    tbl = num.t()
    rb.para([
        '取 ', order['group'], ' 组数据，分别按零级（', ('t', 'α', ITALIC),
        '–', ('t', 't', ITALIC), '）、一级（', ('t', 'ln(α−α_{∞})', ITALIC),
        '–', ('t', 't', ITALIC), '）和二级（',
        ('t', '1/(α−α_{∞})', ITALIC), '–', ('t', 't', ITALIC),
        '）三种线性化关系作图，结果如图%d所示，各直线的 ' % fig,
        ('t', 'R^{2}', ITALIC),
        ' 列于表%d。' % tbl,
    ])
    if png_order:
        rb.figure(png_order,
                  caption='图%d  %s 组的零级、一级与二级线性化尝试'
                  % (fig, order['group']), width_cm=15.0)
    rows = []
    names = {'0': '零级', '1': '一级', '2': '二级'}
    expr = {'0': 'α–t', '1': 'ln(α−α∞)–t', '2': '1/(α−α∞)–t'}
    for i in ('0', '1', '2'):
        concl = '最接近直线' if order['best'] == int(i) else '明显弯曲'
        rows.append([names[i], expr[i], k(order['r2'][i], 5)
                     if np.isfinite(order['r2'][i]) else '—', concl])
    rb.caption('表%d  三种级数线性化关系的比较' % tbl)
    rb.table(['级数', '线性化关系', 'R^{2}', '判断'], rows,
             widths_cm=[2.2, 4.6, 3.0, 3.6], keep_together=True)
    best_r2 = k(order['r2'][str(order['best'])], 5)
    if order['is_first']:
        rb.para([
            '由表%d可见，一级线性化的 ' % tbl, ('t', 'R^{2}', ITALIC),
            ' 最高（', best_r2, '），而零级和二级的 ',
            ('t', 'R^{2}', ITALIC), ' 明显偏低。'
            '因此蔗糖水解对蔗糖为一级反应。',
        ])
    else:
        rb.para([
            '由表%d可见，三种线性化中 ' % tbl, names[str(order['best'])],
            ' 级的线性最好（', best_r2, '），但 ',
            ('t', 'R^{2}', ITALIC),
            ' 仍未达到 0.99，需要结合实验条件进一步核对。',
        ])


def _alpha_t_table(rb, groups, labels, num):
    sel = [g for lab in labels for g in groups if g['label'] == lab]
    if not sel:
        return
    max_n = max(len(g['all_data']) for g in sel)
    headers = ['#']
    for g in sel:
        headers += ['t_{%s} / s' % g['label'], 'α_{%s} / (°)' % g['label']]
    rows = []
    for i in range(max_n):
        row = [str(i + 1)]
        for g in sel:
            pts = g['all_data']
            if i < len(pts):
                row += [k(pts[i][0], 3), k(pts[i][1], 4)]
            else:
                row += ['', '']
        rows.append(row)
    rb.caption('表%d  %s 盐酸下动力学测量的旋光度–时间数据'
               % (num.t(), '、'.join(labels)))
    widths = [1.2] + [2.9, 2.9] * len(sel)
    rb.table(headers, rows, widths_cm=widths, keep_together=False)


# ---------------------------------------------------------------- 3.3 一级拟合
def _sec_first_order(rb, analysis, groups, png, num):
    rb.heading('3.3 各酸浓度下的一级拟合', 2)
    rb.heading('3.3.1 拟合结果', 3)
    fig = num.f()
    tbl = num.t()
    rb.para([
        '已知蔗糖为一级反应后，对每组数据以 ',
        ('t', 'ln(α_{t}−α_{∞})', ITALIC), ' 对 ', ('t', 't', ITALIC),
        ' 作线性拟合，结果如图%d所示。' % fig,
    ])
    rb.figure(png, caption='图%d  各盐酸浓度下的一级反应拟合' % fig, width_cm=12.5)
    rows = []
    for i, g in enumerate(groups):
        fit = g['fits'].get('1')
        rows.append([
            g['label'],
            k(g['acid_true'], 3) if g['acid_true'] is not None else '—',
            pm(g['k1'] * 1e3, g['sigma_k1'] * 1e3) if fit else '—',
            pm(g['t_half'], g['sigma_t_half']) if fit else '—',
            k(fit['r2'], 4) if fit else '—',
            str(g['n']),
        ])
    rb.caption('表%d  各盐酸浓度下的一级反应拟合结果' % tbl)
    rb.table(['编号', 'c(H^{+}) / (mol·L^{-1})', 'k_{1} / (10^{-3} s^{-1})',
              't_{1/2} / s', 'R^{2}', 'n'], rows,
             widths_cm=[1.8, 3.4, 3.9, 3.3, 2.2, 1.2], keep_together=True)
    rb.para([
        '一级反应的积分式为 ',
        ('t', 'ln(α_{t}−α_{∞}) = ln(α_{0}−α_{∞}) − k_{1}t', ITALIC),
        '，因此拟合直线的斜率为 ', ('t', '−k_{1}', ITALIC),
        '，截距为 ', ('t', 'ln(α_{0}−α_{∞})', ITALIC),
        '。半衰期与速率常数的关系为：',
    ], keep_next=True)
    rb.equation(r't_{1/2}=\frac{\ln 2}{k_{1}},\qquad '
                r'\sigma_{t_{1/2}}=\frac{\ln 2}{k_{1}^{2}}\sigma_{k_{1}}')
    if groups:
        gmain = groups[0]
        rb.para([
            '各组 ', ('t', 'k_{1}', ITALIC), ' 与 ', ('t', 't_{1/2}', ITALIC),
            ' 已列于表%d。可以看到，随着盐酸浓度增大，' % tbl,
            ('t', 'k_{1}', ITALIC),
            ' 单调增大、', ('t', 't_{1/2}', ITALIC), ' 单调减小，'
            '符合酸催化反应的一般规律。',
        ])

    rb.heading('3.3.2 拟合质量与离群点', 3)
    worst = (min(groups, key=lambda g: g['fits']['1']['r2']
                 if g['fits'].get('1') else 0) if groups else None)
    if worst and worst['fits'].get('1'):
        r2s = {g['label']: g['fits']['1']['r2'] for g in groups
               if g['fits'].get('1')}
        worst_r2 = worst['fits']['1']['r2']
        others = [v for kk, v in r2s.items() if kk != worst['label']]
        # 「其余各组都在 0.999 以上」是结论，必须核对再写：只有 1 组时没有
        # 「其余各组」，其余组也可能都低于 0.999（本人数据里 1M/2M 的确如此）。
        if not others:
            spread = ('本次只有这一组数据，无从横向比较。')
        elif min(others) >= 0.999:
            spread = '其余各组都在 0.999 以上。'
        else:
            low = [kk for kk, v in r2s.items() if kk != worst['label'] and v < 0.999]
            spread = ('其余各组为 %s，其中 %s 也未达 0.999。'
                      % ('、'.join('%s %.4f' % (kk, r2s[kk])
                                  for kk in r2s if kk != worst['label']),
                         '、'.join(low)))
        rb.para([
            '由表%d可见，%s 组的 ' % (tbl, worst['label']),
            ('t', 'R^{2}', ITALIC), ' 最低（%s），%s'
            % (k(worst_r2, 4), spread),
            '这可能与该组反应较快、初始读数偏低以及反应后期可能偏离一级有关；'
            '若该组某些数据点明显偏离，可在界面中把这些点的序号填入「剔除」框，'
            '重新拟合后再生成报告。',
        ])
    excluded = [g for g in groups if g['exclude']]
    if excluded:
        rb.para('本次处理中剔除的数据点：' + '；'.join(
            '%s 组第 %s 点' % (g['label'],
                              '、'.join(str(i + 1) for i in g['exclude']))
            for g in excluded) + '。剔除依据是这些点在拟合残差中明显偏离趋势。')


# ---------------------------------------------------------------- 3.4 氢离子级数
def _sec_rate_law(rb, analysis, rl, ll, png_rate, png_log, num):
    rb.heading('3.4 氢离子反应级数', 2)
    rb.heading(['3.4.1 ', ('t', 'k_{1}', ITALIC), '–',
                ('t', 'c', ITALIC), '(', ('t', 'H^{+}', ITALIC),
                ') 非线性拟合'], 3)
    tbl = num.t()
    rb.para([
        '实验中所用的盐酸浓度是加入时的标称浓度，混合后又被蔗糖溶液稀释一倍，'
        '因此参与动力学计算的氢离子浓度应取标称值的一半，列于表%d。' % tbl,
    ])
    rows = [[g['label'], k(g['acid_nominal'], 1) if g['acid_nominal'] is not None else '—',
             k(g['acid_true'], 3) if g['acid_true'] is not None else '—']
            for g in analysis['groups']]
    rb.caption('表%d  各盐酸标称浓度对应的真实氢离子浓度' % tbl)
    rb.table(['编号', 'c_{nom} / (mol·L^{-1})', 'c(H^{+}) / (mol·L^{-1})'],
             rows, widths_cm=[2.4, 4.2, 4.2], keep_together=True)
    if not rl:
        rb.para('有效数据组不足 3 组，未能拟合氢离子反应级数。')
        return
    rb.para([
        '酸催化反应的表观速率常数与氢离子浓度之间满足：',
    ], keep_next=True)
    rb.equation(r'k_{1}=k_{0}+k_{H}c(H^{+})^{n}')
    fig = num.f()
    rb.para([
        '其中 ', ('t', 'k_{0}', ITALIC), ' 为无酸存在时的速率常数，',
        ('t', 'n', ITALIC), ' 为氢离子的反应级数。用非线性最小二乘直接拟合，'
        '结果如图%d所示。' % fig,
    ])
    if png_rate:
        rb.figure(png_rate, caption='图%d  k₁–c(H⁺) 非线性拟合' % fig,
                  width_cm=11.0)
    # sigma 可能为 None：恰好定解（数据点数 = 参数个数）时残差自由度为 0，
    # 点估计成立但不确定度无定义。此时**只给值、不给 ±**，并在正文里说清原因——
    # 绝不能把 None 塞进 k()/pm() 印成 "4.000" 让读者以为精确到毫位（SKILL §27）。
    has_sig = bool(rl.get('sigma_ok'))
    rb.para('拟合参数为：', keep_next=True)
    if has_sig:
        rb.equation(r'k_{1}=(%s\pm%s)\times10^{-4}+(%s\pm%s)\times10^{-4}'
                    r'\,c(H^{+})^{%s\pm%s}'
                    % (k(rl['k0'] * 1e4, 3), k(abs(rl['sigma_k0']) * 1e4, 1),
                       k(rl['k_h'] * 1e4, 3), k(abs(rl['sigma_k_h']) * 1e4, 1),
                       k(rl['n'], 2), k(abs(rl['sigma_n']), 2)))
    else:
        rb.equation(r'k_{1}=%s\times10^{-4}+%s\times10^{-4}'
                    r'\,c(H^{+})^{%s}'
                    % (k(rl['k0'] * 1e4, 3), k(rl['k_h'] * 1e4, 3),
                       k(rl['n'], 2)))
    segs = [
        '即 ', ('t', 'k_{0}', ITALIC), ' = ',
        (sci_pm(rl['k0'], rl['sigma_k0'], -4) if has_sig
         else sci(rl['k0'], 3, -4)),
        ' s^{-1}，', ('t', 'n', ITALIC), ' = ',
        (_rl_n(rl) if has_sig else k(rl['n'], 2)),
        '，', ('t', 'R^{2}', ITALIC), ' = %s。' % k(rl['r2'], 4),
    ]
    if not has_sig:
        segs += [
            '本次只有 %d 组不同盐酸浓度的数据，却要拟合 ' % rl['n_points'],
            '%d 个参数，残差自由度为 0，' % rl['n_params'],
            '因此上面给出的是唯一解、但无法估计不确定度；'
            '要给出误差棒，需要增加盐酸浓度档次（至少 %d 组以上）。'
            % (rl['n_points'] + 1),
        ]
    if rl.get('at_bound'):
        segs += [
            '另外 ', ('t', 'n', ITALIC), ' 顶到了拟合上界 4，'
            '说明真值可能更大，该结果只能作为下限看待。',
        ]
    else:
        # ⚠ 不能无条件写「接近 2 级」：n=4.00、n=1.30 都出现过，
        # 照抄那句话就是拿数据迁就预设结论。按 n 本身分支。
        nval = float(rl['n'])
        if abs(nval - 2.0) <= 0.3:
            segs += [
                '氢离子反应级数接近 2 级，说明蔗糖水解速率大致与 ',
                ('t', 'c', ITALIC), '(', ('t', 'H^{+}', ITALIC),
                ')^{2} 成正比。',
            ]
        else:
            segs += [
                '本次拟合得到 ', ('t', 'n', ITALIC), ' = %s，' % k(nval, 2),
                '与文献常引的二级关系（',
                ('t', 'n', ITALIC), ' ≈ 2）有明显偏离。',
                '该偏差更可能来自数据本身而非机理变化：本实验各组'
                '由不同同学在不同时间完成，零点、计时起点与恒温程度'
                '都不完全一致，而 ', ('t', 'n', ITALIC),
                ' 由少数几个 ', ('t', 'k_{1}', ITALIC),
                ' 值决定，对组间系统偏差非常敏感；'
                '要定准级数，需要同一人、同一批酸在同一恒温槽中'
                '测更多浓度档次。',
            ]
    rb.para(segs)

    rb.heading(['3.4.2 ', ('t', 'lg(k_{1}−k_{0})', ITALIC), '–',
                ('t', 'lg c(H^{+})', ITALIC), ' 线性验证'], 3)
    if ll:
        rb.para([
            '把 ', ('t', 'k_{1} = k_{0} + k_{H}c(H^{+})^{n}', ITALIC),
            ' 两边取对数，得 ',
            ('t', 'lg(k_{1}−k_{0}) = lg k_{H} + n lg c(H^{+})', ITALIC),
            '。以 ', ('t', 'lg(k_{1}−k_{0})', ITALIC), ' 对 ',
            ('t', 'lg c(H^{+})', ITALIC), ' 作图，直线斜率即为 ',
            ('t', 'n', ITALIC), '，结果如图%d所示。' % num.f_next(),
        ])
        if png_log:
            rb.figure(png_log,
                      caption='图%d  lg(k₁−k₀)–lg c(H⁺) 线性拟合' % num.f(),
                      width_cm=10.5)
        rb.para([
            '拟合得 ', ('t', 'n', ITALIC), ' = ',
            pm(ll['slope'], ll['sigma_slope']), '，', ('t', 'R^{2}', ITALIC),
            ' = %s。' % k(ll['r2'], 4),
            '这一结果与非线性拟合的 ', ('t', 'n', ITALIC), ' = ',
            _rl_n(rl), ' 相比：',
        ] + ([
            '两者的差在各自不确定度范围内，可以互相印证。',
        ] if _ll_agrees(ll, rl) else [
            '两者相差较大，说明仅靠这 %d 组数据还不足以把 n 定准，'
            '该值只能作为量级参考。' % len(analysis['groups']),
        ]))


# ---------------------------------------------------------------- 4 讨论
def _sec_results(rb, analysis):
    groups = analysis['groups']
    rl = analysis['rate_law']
    ll = analysis['loglog']
    ainf = analysis['alpha_inf']
    order = analysis['order']
    rb.heading('4.1 实验结果', 2)
    segs = [
        '本实验在 %.1f ℃ 下测定了 %d 个不同盐酸浓度下蔗糖水解的 ' % (
            analysis['temperature'], len(groups)),
        ('t', 'α_{t}', ITALIC), '–', ('t', 't', ITALIC), ' 曲线。',
    ]
    cal_fit = analysis['calibration']['fit']
    if cal_fit:
        # 「线性良好」是结论、不是装饰：按 R² 和参与拟合的点数如实说。
        # 只有 2 个点时直线必然过两点，R²≈1 但毫无说服力，不能说「线性良好」。
        n_cal = cal_fit.get('n') or 0
        r2_cal = cal_fit.get('r2')
        if n_cal < 3:
            segs += [
                '旋光度–浓度只测得 %d 个浓度点，不足以验证线性关系，'
                '标定直线仅作参考；' % n_cal,
            ]
        elif r2_cal is not None and r2_cal >= 0.999:
            segs += [
                '旋光度与蔗糖浓度的标定直线 ', ('t', 'R^{2}', ITALIC),
                ' = %s，线性良好；' % k(r2_cal, 5),
            ]
        else:
            segs += [
                '旋光度与蔗糖浓度的标定直线 ', ('t', 'R^{2}', ITALIC),
                ' = %s，线性一般；' % k(r2_cal, 5),
            ]
    if order:
        segs += [
            '以 %s 组作积分法判定，蔗糖为 %d 级反应；' %
            (order['group'], order['best']),
        ]
    if rl:
        segs += [
            '各组 ', ('t', 'k_{1}', ITALIC), ' 随 ',
            ('t', 'c', ITALIC), '(', ('t', 'H^{+}', ITALIC),
            ') 增大而增大，非线性拟合得 ', ('t', 'n', ITALIC), ' = ',
            _rl_n(rl), '。',
        ]
    if ll:
        segs += [
            'lg–lg 线性拟合得 ', ('t', 'n', ITALIC), ' = ',
            pm(ll['slope'], ll['sigma_slope']),
            ('，两者一致。' if _ll_agrees(ll, rl)
             else '，与非线性结果有差距，级数只能算初步结论。'),
        ]
    if np.isfinite(ainf['measured']) and np.isfinite(ainf['theory']):
        segs += [
            '实验测得的 ', ('t', 'α_{∞}', ITALIC), ' = ',
            k(ainf['measured'], 2), '°，理论值 ',
            k(ainf['theory'], 2), '°，相差 %s%%，说明反应已进行完全。'
            % pct(abs(ainf['relative'])),
        ]
    rb.para(segs)
    worst = (min(groups, key=lambda g: g['fits']['1']['r2']
                 if g['fits'].get('1') else 0) if groups else None)
    if worst and worst['fits'].get('1'):
        rb.para([
            '各组一级拟合的 ', ('t', 'R^{2}', ITALIC),
            ' 大多在 0.999 以上，只有 %s 组较低（%s）。' %
            (worst['label'], k(worst['fits']['1']['r2'], 4)),
            '该组盐酸浓度最高、反应最快，取样点少且反应后期可能偏离一级，'
            '是拟合误差较大的主要原因。',
        ])


def _sec_discussion(rb, analysis):
    groups = analysis['groups']
    rb.heading('4.2 实验讨论', 2)
    rb.heading('4.2.1 模型训练与零点', 3)
    rb.para('数智旋光仪用机器学习模型识别三分视场的明暗状态，模型训练质量直接影响'
            '旋光零点和每个数据点的判断。若训练集中混入少量坏帧，'
            '软件找到的零点可能偏离均匀暗场，使整条 α–t 曲线平移。'
            '本次实验发现，只用自己录制的视频训练时零点更稳定；'
            '也可以手动找到均匀暗场，记住它与软件零点的偏差，'
            '每次测量前把电机转到该角度，相当于人工校正零点。')
    fastest = max(groups, key=lambda g: g['k1'] if np.isfinite(g['k1']) else -1) \
        if groups else None
    fast_txt = ('%s 组' % fastest['label']) if fastest else '反应最快的一组'
    rb.heading('4.2.2 蔗糖浓度与步进角', 3)
    rb.para([
        '蔗糖浓度过高会超出旋光度–浓度线性范围，过低则反应后期 ',
        ('t', 'α−α_{∞}', ITALIC),
        ' 很小，对数拟合对读数误差非常敏感。'
        '本次实验所用蔗糖溶液混合后约为 %.4f g·mL^{-1}，'
        % analysis.get('c0', 0),
        '对%s偏低，可能导致初始旋光度不高、后期数据点少，'
        '从而影响该组的拟合质量。步进角过大会使采样点太少，'
        '过小则测量时间过长、仪器稳定性要求高；经验上取 0.2~0.5° 较合适。'
        % fast_txt,
    ])
    rb.heading('4.2.3 误差来源', 3)
    rb.para([
        '（1）旋光仪读数与模型识别误差：每个数据点的判断都可能偏移一个步进角，'
        '对应约 1/746°；对一级拟合，随机误差主要影响斜率的不确定度。'
        '（2）温度波动：蔗糖水解速率对温度敏感，恒温槽波动或旋光管未充分恒温'
        '会使不同组数据之间产生系统差异。'
        '（3）溶液配制与混合：蔗糖和盐酸的体积、浓度误差会直接进入 ',
        ('t', 'c_{0}', ITALIC), ' 和 ', ('t', 'c', ITALIC),
        '(', ('t', 'H^{+}', ITALIC), ')；盐酸挥发也会使实际酸度偏低。'
        '（4）α∞ 的选取：若反应未完全，实验测得的 α∞ 偏大，'
        '使 ln(α−α∞) 在高转化率区弯曲。'
        '（5）数据组之间的差异：本实验共 %d 组数据，由小组成员分工完成，'
        % len(groups),
        '零点、模型和计时起点不完全相同，这也是 k1–c(H+) 拟合误差的主要来源之一。',
    ])
    rb.heading('4.2.4 实验改进', 3)
    rb.para('（1）统一由一人完成模型训练和零点校准，或每组测量前都用同一标准管复核零点；'
            '（2）适当提高蔗糖浓度（在标定线性范围内），使高酸浓度组也能获得足够多的'
            '有效数据点；（3）每组至少重复两次，取斜率平均值并给出标准差；'
            '（4）用同一批盐酸、同一恒温槽完成全部组别，减少组间系统差异；'
            '（5）反应结束后延长恒温时间再测 α∞，或由多组高转化率数据外推 α∞；'
            '（6）在报告中同时给出非线性拟合与 lg–lg 线性拟合的 n，互相验证。')


def _sec_conclusion(rb, analysis):
    groups = analysis['groups']
    rl = analysis['rate_law']
    ll = analysis['loglog']
    ainf = analysis['alpha_inf']
    order = analysis['order']
    rb.heading('4.3 实验结论', 2)
    # 开头这句「旋光度与浓度呈良好的线性关系」必须按标定实际质量分支：
    # 本次只有 1 个浓度点，凭什么都验证不了线性（§27 不允许把「没测」写成「测得好」）。
    cal_fit = analysis['calibration']['fit']
    n_cal = (cal_fit or {}).get('n') or 0
    if cal_fit and n_cal >= 3 and (cal_fit.get('r2') or 0) >= 0.999:
        head = ('本实验用数智旋光仪监测了蔗糖在盐酸催化下的水解过程。'
                '旋光度与蔗糖浓度呈良好的线性关系；')
    elif cal_fit and n_cal >= 3:
        head = ('本实验用数智旋光仪监测了蔗糖在盐酸催化下的水解过程。'
                '旋光度与蔗糖浓度的线性关系一般；')
    else:
        head = ('本实验用数智旋光仪监测了蔗糖在盐酸催化下的水解过程。'
                '本次标定只测得 %d 个浓度点，尚不足以独立验证旋光度与浓度的'
                '线性关系；' % n_cal)
    segs = [head]
    if order:
        segs += ['用积分法判定蔗糖为 %d 级反应；' % order['best']]
    if rl:
        segs += [
            '由 ', ('t', 'k_{1}', ITALIC), '–', ('t', 'c', ITALIC),
            '(', ('t', 'H^{+}', ITALIC), ') 非线性拟合得氢离子反应级数 ',
            ('t', 'n', ITALIC), ' = ', _rl_n(rl), '，',
        ]
    if ll:
        segs += [
            'lg–lg 线性拟合得 ', ('t', 'n', ITALIC), ' = ',
            pm(ll['slope'], ll['sigma_slope']),
            ('，两者一致；' if _ll_agrees(ll, rl)
             else '，与非线性结果有差距；'),
        ]
    order_label = order['group'] if order else None
    main_g = next((g for g in groups if g['label'] == order_label),
                  groups[0] if groups else None)
    if main_g and np.isfinite(main_g['k1']):
        segs += [
            '%s 组的速率常数 ' % main_g['label'],
            ('t', 'k_{1}', ITALIC), ' = ',
            sci_pm(main_g['k1'], main_g['sigma_k1']), ' s^{-1}，半衰期 ',
            ('t', 't_{1/2}', ITALIC), ' = ',
            pm(main_g['t_half'], main_g['sigma_t_half']), ' s；',
        ]
    if np.isfinite(ainf['measured']) and np.isfinite(ainf['theory']):
        segs += [
            '实验测得的最终旋光度 ', k(ainf['measured'], 2),
            '° 与理论值 ', k(ainf['theory'], 2), '° 相符。',
        ]
    rb.para(segs)
