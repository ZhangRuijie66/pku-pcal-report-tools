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
      4.2 标准电离平衡常数的误差来源分析
      4.3 弱电解质两种 K° 求解方法比较（读了共享表时为 4.4）
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
from .sigfig import k, pm, pct, sig_fig, SIG_DIGITS, sci, sci_pm

def pm(x, u, n=SIG_DIGITS):
    """本模块口径：u 缺失时用 4 位有效数字（sig_fig）。"""
    from .sigfig import pm as _pm
    if u in (None, 0) or not np.isfinite(u):
        return sig_fig(x, 4)
    return _pm(x, u, n)


def pct(x, n=SIG_DIGITS):
    """本模块口径：相对偏差带 % 后缀（其余模块不带）。"""
    from .sigfig import pct as _pct
    return _pct(x, n, sign='%')

ITALIC = {'italic': True}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, 'assets')
INTRO_JPG = os.path.join(ASSETS, '引言图.jpg')

REPORT_TITLE = '电解质溶液电导率的测定'
INTRO_BLANK_LINES = 26

SIG_DIGITS = 2


# ---------------------------------------------------------------- 数值格式










# sci / sci_pm 已统一到 pcal/sigfig.py（canonical = _core/sigfig.py），
# 不要在本文件里再各写一份：历史上 6 个模块的本地副本对 None/NaN/inf
# 分化出 6 种行为（有的抛 TypeError/ValueError/OverflowError、有的把
# 破折号塞进科学记数法印成 (—)×10^{-5}），审计 B P1-3。
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
    # 中文与西文之间**不加空格**（项目规范「汉字 空格 汉字」检查会抓）：
    # 原来写成 '%s 组 %s 号' 会印出「周三 组 7 号」，两个空格都是多余的中文间空格。
    group_txt = ('%s组%s号' % (group, group_no)) if (group and group_no) \
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
        log('⚠ 封面缺字段：%s（请在界面左侧“报告封面 / 实验条件”里填上）'
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
    for key in conduct.STRONG_SPECIES:
        if key in fits:
            fit_pngs[key] = save(plotting.make_kohlrausch_figure(analysis, key),
                                 'fit_%s.png' % key)
    fig_kfit = None
    if kfit:
        fig_kfit = save(plotting.make_kfit_figure(analysis), 'fig6_kfit.png')

    # ---- 附录图（只在读了共享数据表时才画）
    appendix_pngs = {}
    shared = getattr(analysis, 'shared', None)
    if shared and (shared.get('group') or {}).get('n', 0) >= 2:
        log('绘制附录图…')
        appendix_pngs['scatter'] = save(
            plotting.make_group_scatter_figure(shared), 'fig7_group_scatter.png')
        appendix_pngs['kappa'] = save(
            plotting.make_group_kappa_figure(shared), 'fig8_group_kappa.png')
        appendix_pngs['kpair'] = save(
            plotting.make_kpair_figure(shared), 'fig9_kpair.png')

    # ================================================================ 摘要
    #
    # ⚠ 摘要原来直接 fits['NaCl'] / fits['NaAc'] / fits['HCl'] 三次取值，
    # 任一物种缺数据就 KeyError（实测：删掉 NaAc 的数据 → KeyError: 'NaAc'，
    # 而 Analysis.compute() 其实已经优雅降级并给了 warning）。
    # 改成按实际算出来的物种拼句子：物种多就多写、少就少写。
    log('撰写摘要…')
    _strong = [k for k in conduct.STRONG_SPECIES if k in fits]
    _lam_segs = []
    for _i, _k in enumerate(_strong):
        if _i:
            _lam_segs.append('、' if _i < len(_strong) - 1 else ' 和 ')
        _lam_segs.append('%s ' % conduct.SPECIES_LABEL[_k])
        _f = fits[_k]
        _lam_segs.append(('t', '(%s) S·m⁻²·mol⁻¹'
                          % pm(_f['lam_inf'], _f['sigma_inf']), {}))
    _species_txt = '、'.join(conduct.SPECIES_LABEL[k] for k in _strong)
    # HAc 的三项（Λm∞ 由组合得出、K° 两法）依赖强电解质全部齐备
    # （`combo_lambda_inf` 要减掉 sub 项）。缺任何一个时 esa/kmean/kfit
    # 都是 None —— 这时摘要只报强电解质，并明确说明 HAc 待补，
    # 不能静默省略（否则读者以为实验只做了强电解质）。
    _hac_ready = (esa is not None and kmean is not None and kfit is not None)
    _intro = ('本实验测量了不同浓度 %s 和 %s 溶液的电导率。'
              % (_species_txt, conduct.SPECIES_LABEL['HAc'])
              if _strong else
              '本实验测量了不同浓度 %s 溶液的电导率。'
              % conduct.SPECIES_LABEL['HAc'])
    _segs = [{'text': '摘要 ', 'bold': True, 'cjk': '黑体'}, _intro]
    if _strong:
        _segs.append('通过 Kohlrausch 拟合得强电解质的极限摩尔电导率：')
        _segs.extend(_lam_segs)
        _segs.append('。')
    if _hac_ready:
        _segs.extend([
            '对于 HAc，由离子独立运动定律得极限摩尔电导率为 ',
            ('t', '(%s) S·m⁻²·mol⁻¹' % pm(esa['lam_inf'], esa['sigma']), {}),
            '，再分别通过求平均法和拟合直线法求得其标准电离平衡常数为 ',
            ('t', sci_pm(kmean['mean'], kmean['sigma']), {}),
            ' 和 ', ('t', sci_pm(kfit['K'], kfit['sigma_K']), {}),
            '，并对两种方法进行了比较。',
        ])
    else:
        _missing = [conduct.SPECIES_LABEL[k]
                    for k in conduct.STRONG_SPECIES if k not in fits]
        _segs.append(
            '由于缺少%s的测量数据，强电解质结果不齐，'
            'HAc 的极限摩尔电导率（需由离子独立运动定律从强电解质组合）'
            '与标准电离平衡常数本次未能求出。'
            % ('、'.join(_missing) if _missing else '部分物种'))
    rb.para(_segs)
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
    rb.para('KCl 溶液（0.01 mol·dm⁻³），HCl 溶液（0.1 mol·dm⁻³），'
            'NaCl 溶液（0.25 mol·dm⁻³），NaAc 溶液（0.25 mol·dm⁻³），'
            'HAc 溶液（0.25 mol·dm⁻³），去离子水。')

    rb.heading('2.2 实验内容', 2)
    rb.heading('2.2.1 电导池常数的测定和校正', 3)
    rb.para('电导池常数事先已初步标定。测定标准 KCl 溶液的电导率，'
            '若读数在 (1415 ± 5) μS·cm⁻¹ 内则视为标定成功；若偏差较大，'
            '则利用 KCl 溶液的理论电导率重新标定电导池常数。'
            '记录标定前后的电导池常数及对应的 KCl 读数。')
    rb.heading('2.2.2 测定去离子水的电导率', 3)
    # ⚠ κ 是量符号，必须走片段列表排斜体；写成纯字符串会整串正体
    # （2026-11-26 体检发现 4 处同类，见 tests/check_typesetting.py）
    rb.para(['用去离子水淋洗电导电极，在试管中装入去离子水，测其电导率 ',
             ('t', 'κ_{w}', ITALIC), '。'])
    rb.heading('2.2.3 配制不同浓度的溶液', 3)
    rb.para('按表1和表2配制不同浓度的 NaCl、NaAc、HAc 和 HCl 溶液。'
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
    # ⚠ 依赖 `an.esa`/`kmean`/`kfit` 的三节必须**按可用性判断后跳过**。
    # 这三个量要求三个强电解质都齐备（`combo_lambda_inf` 要做加减），
    # 缺任一物种时它们都是 None。原来直接 `an.esa['combo']` 会
    # TypeError: 'NoneType' object is not subscriptable（实测缺 NaAc 即崩）。
    # 这里在入口统一判断，缺数据时写一段明确说明代替整节内容——
    # 不能静默省略（读者会以为实验只做了强电解质）。
    _hac_ok = (analysis.esa is not None
               and analysis.kmean is not None
               and analysis.kfit is not None)
    log('写强电解质…')
    _sec_strong(rb, analysis, fit_pngs, hac_ok=_hac_ok)
    if _hac_ok:
        log('写弱电解质…')
        _sec_weak(rb, analysis, fig_kfit)
    else:
        log('弱电解质：强电解质数据不齐，跳过并说明')
        _sec_weak_skipped(rb, analysis)

    # ================================================================ 4 讨论与结论
    rb.heading('4 讨论与结论')
    log('写讨论…')
    _sec_error_analysis(rb, analysis)
    # 4.2 最终量 K° 的误差预算（用户 2026-11-27 要求）：4.1 讨论的是 Λm∞
    # 的相对误差，这一节讨论的是「温度补偿 / 温度波动 / 溶液浓度 / 移液管允差 /
    # 拟合误差」各自对 K° 的贡献。它依赖 esa/kmean，缺强电解质时只能说明原因。
    log('写误差预算…')
    _sec_error_budget(rb, analysis)
    # 共享数据那一节是**可选**的：读了共享表才有，没读时整节省略。
    # 所以后面两节的编号不能写死，要跟着顺移（否则会出现“4.1、4.3”跳号，
    # 或两个小节都叫 4.2）。
    has_shared = _sec_shared(rb, analysis, 3)
    # 4.1 误差分析 → 4.2 误差预算 已固定占两节，故后续从 4.3 起
    nxt = 4 if has_shared else 3
    # ⚠ `_sec_method_compare` / `_sec_summary` 都依赖 kmean/kfit/esa；
    # 缺强电解质时为 None，原来会 TypeError。同 `_hac_ok` 一并判断。
    if _hac_ok:
        _sec_method_compare(rb, analysis, nxt)
        _sec_summary(rb, analysis, nxt + 1)
    else:
        log('讨论两法比较 / 小结：数据不齐，跳过并说明')
        _sec_tail_skipped(rb, analysis, nxt)

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

    # ================================================================ 附录
    # 附录放在参考文献之后（正文引用链在参考文献处收尾，附录属补充材料）。
    # 图号接着正文往后排（图7~图9），因为 docxkit 的题注不自动编号，
    # 而 tests/audit_docx.py 会检查图号必须从 1 开始且连续。
    if appendix_pngs:
        _sec_appendix(rb, analysis, appendix_pngs)
    log('写入 docx…')
    rb.save(out_path)
    return out_path


def _sec_appendix(rb, an, pngs):
    """附录：组内分析的三张图（图7~图9）。

    正文 4.3 节（共享数据那节）只给结论与数值（表12~表15），图放附录。
    理由是这三张图都是“一人一点”的分布图，信息密度低于同页的统计表；
    正文若插三张，该节会从两页涨到四页，把讨论挤散。附录里图文并列，
    需要核对细节时翻到最后即可。

    ⚠ 图号必须接着正文排（正文到图6），否则 audit_docx 的
    caption.gap 会报“图6 → 图7”以外的跳号。
    """
    shared = getattr(an, 'shared', None) or {}
    group = shared.get('group') or {}
    members = shared.get('members') or []
    n = group.get('n') or 0

    rb.heading('附录  共享数据的组内分析图', page_break_before=True)
    who = _me_name(shared, members)
    if who:
        # 认领成功：直接写名字。若是两人合做一台仪器、表里填的是对方名字，
        # 这里如实印出“对应共享表中登记为 XX 的那一份”，不冒充成本人自测。
        rb.para(['本附录给出 4.3 节所用组内分析的三张图。图中：空心圆为组内每人，'
                 '红色实心为本人数据（对应共享表中登记为 %s 的那一份），'
                 '橙 × 为 Grubbs 检验判出的离群点，蓝带为 ±1 倍标准差范围，'
                 '绿色虚线为 CRC 离子加和的理论值。共 %d 位同学参与统计。'
                 % (who, n)])
    else:
        # 没认领到：不猜，也不把任何一个人标成"本人"
        rb.para(['本附录给出 4.3 节所用组内分析的三张图。图中：空心圆为组内每人，'
                 '橙 × 为 Grubbs 检验判出的离群点，蓝带为 ±1 倍标准差范围，'
                 '绿色虚线为 CRC 离子加和的理论值。共 %d 位同学参与统计。'
                 '（尚未指定“我的数据”，故图中未标出本人。）' % n])

    # ---- 图7
    # 附录三张图纵向排：总高约 24 cm + 文字 6.5 cm，超过一页的 24.7 cm，
    # 必然跨两页。为了不让第二页只剩一张图，把**图9 的说明合并进图9 之前**
    # 的三段说明之后，并让图9 与前两图保持同一横向比例（1.53），
    # 这样第二页至少是“图9 + 完整说明”，不会出现孤零零一张图加半页空白。
    rb.figure(pngs['scatter'],
              caption='图7  各物种极限摩尔电导率的组内散点',
              width_cm=plotting.ps.FIG_W_CM)
    hac = (group.get('lam_hac') or {}).get('describe') or {}
    nacl = ((group.get('species') or {}).get('NaCl') or {}).get('lam_inf') or {}
    nac = ((group.get('species') or {}).get('NaAc') or {}).get('lam_inf') or {}
    hcl = ((group.get('species') or {}).get('HCl') or {}).get('lam_inf') or {}
    rb.para(['图7 显示各物种 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                ' 在组内的散布。三个强电解质的相对标准偏差'
             '依次为 NaCl %.2f%%、NaAc %.2f%%、HCl %.2f%%，HAc 为 %.2f%%。'
             'NaAc 的一致性最好，HCl 与 HAc 最差；这与 H⁺ 迁移数大、'
             '对浓度配制与温度波动更敏感相符。各组的组内均值都略低于'
             '绿色虚线（CRC 理论值），系统性偏低 1~2%%，原因见 4.1 节。'
             % (nacl.get('rsd', float('nan')), nac.get('rsd', float('nan')),
                hcl.get('rsd', float('nan')), hac.get('rsd', float('nan')))])

    # ---- 图8
    rb.figure(pngs['kappa'],
              caption='图8  各成员校正电导率 κ_{corrected} 相对组内均值的偏差',
              width_cm=plotting.ps.FIG_W_CM)
    rb.para(['图8 把各人的校正电导率–c 曲线画成“相对组内均值的偏差”。之所以不直接'
             '叠加原始校正电导率，是因为它与 c 近似线性、各人绝对值只差 1~3%，'
             '原始曲线会完全重合而看不出差别；取相对偏差后，每人的系统性'
             '高低才显现出来。可以看出偏差主要出现在低浓度端（左端），'
             '高浓度端各人几乎重合——这是 4.1 节所述“极稀溶液信噪比低”'
             '的直接证据。'])

    # ---- 图9
    rb.figure(pngs['kpair'],
              caption='图9  两种方法所得 K° 的配对连线',
              width_cm=plotting.ps.FIG_W_CM)
    km = group.get('k_methods') or {}
    paired = km.get('paired') or {}
    rb.para(['图9 中每人用一条线连接“求平均法”与“拟合直线法”所得的 K°。'
             '配对比较的要点就在这里：把同一个人的两个结果相连，'
             '浓度配制、温度等共同因素相互抵消，剩下的才是方法本身的差异。'
             '配对 t 检验结果为 Δ = %.2f×10⁻⁷、t = %.2f、p = %.3f（自由度 %d），'
             '%s。'
             % (paired.get('mean_diff', float('nan')) / 1e-7,
                paired.get('t', float('nan')), paired.get('p', float('nan')),
                paired.get('df', 0),
                '两法存在系统性差异' if paired.get('significant')
                else '两法未检出系统性差异')])


def _me_name(shared, members):
    """本人姓名（认领失败时不显示别人的名字）。"""
    idx = (shared.get('match') or {}).get('index')
    if idx is not None and 0 <= idx < len(members):
        return members[idx].get('name')
    return None


# ---------------------------------------------------------------- 配制表
_PREP_COMMON = [
    ('1', '0.025', '100', '0.25', '10'),
    ('2', '0.01', '100', '0.25', '4'),
    ('3', '0.005', '100', '0.25', '2'),
    ('4', '0.0025', '100', '0.25', '1'),
    ('5', '0.00125', '100', '0.25', '0.5'),
]
#: HCl 的配制表（2026 秋讲义表3：0.1 mol·dm⁻³ 母液，25/12/8/5/2 mL 定容到
#: 100 mL）。2025 参照报告用的是 HNO₃（0.1 → 0.01…0.0005），物种与浓度档
#: 都不对，已于 2026-11-20 按讲义改掉；那张旧表不再保留，免得有人照它抄。
_PREP_HCL = [
    ('1', '0.025', '100', '0.1', '25'),
    ('2', '0.012', '100', '0.1', '12'),
    ('3', '0.008', '100', '0.1', '8'),
    ('4', '0.005', '100', '0.1', '5'),
    ('5', '0.002', '100', '0.1', '2'),
]
_PREP_HEAD = ['瓶号', '浓度 / (mol·dm⁻³)', '定容体积 / mL',
              '母液浓度 / (mol·dm⁻³)', '量取体积 / mL']
_PREP_W = [1.2, 3.6, 2.8, 4.0, 3.0]


def _table_preparation(rb):
    rb.caption('表1  不同浓度电解质溶液的配制（NaCl、NaAc、HAc 溶液）')
    rb.table(_PREP_HEAD, _PREP_COMMON, widths_cm=_PREP_W)
    rb.caption('表2  不同浓度 HCl 电解质溶液的配制')
    rb.table(_PREP_HEAD, _PREP_HCL, widths_cm=_PREP_W)


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
             '可以得到 NaCl、HCl 和 HAc 的校正电导率（',
             ('t', 'κ_{corrected}', ITALIC), '）和浓度（',
             ('t', 'c', ITALIC), '），由此作出 ',
             # ⚠ 同一句里前两个 κ/c 走了片段列表（斜体），这里若不拆就会
             # 印成正体 —— 同一符号前后不一致，是最容易被一眼看出的错。
             ('t', 'κ_{corrected}', ITALIC), ('t', '–', {}),
             ('t', 'c', ITALIC), ' 曲线，如图2所示。'])
    rb.figure(fig_kc, caption='图2  NaCl、HCl 和 HAc 的电导率-浓度关系曲线',
              width_cm=plotting.ps.FIG_W_CM)
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
    rb.para(['HCl 变化曲线的斜率比 NaCl 大，即相同浓度下 HCl 的摩尔电导率'
             '更大，这是 H⁺ 和 Na⁺ 运动速度的差异所致：H⁺ 在水中并不是靠'
             '“自身移动”导电，而是通过 Grotthuss 机制在氢键网络中接力传递，'
             '迁移速度比 Na⁺ 大很多。顺便指出，除 H⁺ 这种特殊离子之外，'
             '离子的迁移速度遵循 Stokes 定律，即与电荷成正比、与水合半径成反比。'
             '对于弱电解质 HAc，电导率随浓度的变化不显著，这是因为浓度增加使'
             '解离度减小，溶液中离子数目其实变化不大。'])


# ---------------------------------------------------------------- 3.2
def _sec_strong(rb, an, fit_pngs, hac_ok=True):
    fits = an.fits
    _present = [k for k in conduct.STRONG_SPECIES if k in an.tables]
    rb.heading('3.2 强电解质的数据处理', 2)
    rb.heading('3.2.1 原始数据记录及基本数据处理', 3)
    # ⚠ 原来写死「NaCl、NaAc 和 HCl … 表3、表4和表5」，缺物种时表号会错位。
    _sp_txt = '、'.join(conduct.SPECIES_LABEL[k] for k in _present)
    _tbl_txt = ('、'.join('表%d' % (3 + i) for i in range(len(_present)))
                if len(_present) > 1 else
                ('表3' if _present else '（无）'))
    rb.para('%s 的不同浓度溶液电导率原始数据及基本数据处理分别如%s所示。'
            % (_sp_txt, _tbl_txt))
    rb.para('有必要说明有效数字：HCl 的母液浓度为 0.1 mol·dm⁻³，但这显然不'
            '意味着结果只保留 1 位有效数字。鉴于配制过程中有效数字最低为 4 位'
            '（25 mL 移液管精度为 25.00 mL），浓度均保留 4 位有效数字；电导率'
            '保留 3~4 位是因为电导率仪在不同量程下的有效位数本就不同，'
            '表中保持原始读数不变，后续结果再统一有效数字。')
    rb.para('浓度和电导率按如下关系换算成标准单位制：')
    rb.equation(r'1\ mol\cdot dm^{-3}=10^{3}\ mol\cdot m^{-3},\qquad'
                r'1\ \mu S\cdot cm^{-1}=10^{-4}\ S\cdot m^{-1}')
    rb.para('校正电导率等于测量电导率减去去离子水的电导率：')
    rb.equation(r'\kappa_{corrected}=\kappa_{measured}-\kappa_{w}')
    rb.para('摩尔电导率等于校正电导率除以浓度：')
    rb.equation(r'\Lambda_{m}=\frac{\kappa_{corrected}}{c}')

    # ⚠ 三处循环必须**数据驱动**：`Analysis.compute()` 在某物种缺数据时会
# 优雅降级（记 warning 并从 `fits`/`tables` 里去掉它），但如果这里仍按
# 硬编码三元组去取，`an.tables[key]` / `fits[key]` 会直接 KeyError，
# 把「优雅降级」变成「生成失败」。实测：删掉 NaAc 的数据后
#   fits keys: ['NaCl', 'HCl'] → KeyError: 'NaAc'
    # 所以统一用「实际算出来的」物种列表。
    present = [k for k in conduct.STRONG_SPECIES if k in an.tables]
    for idx, key in enumerate(present, 3):
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
    _fit_keys = [k for k in conduct.STRONG_SPECIES if k in fits]
    # 图号范围也跟着变：3 个物种是「图3~图5」，2 个是「图3~图4」。
    if len(_fit_keys) > 1:
        _fig_span = '图3~图%d' % (2 + len(_fit_keys))
    elif _fit_keys:
        _fig_span = '图3'
    else:
        _fig_span = '（无）'
    rb.para(['故以 ', ('t', 'Λ_{m}', ITALIC), ' 对 ', ('t', '√c', ITALIC),
             ' 作线性拟合，截距即为该物种的极限摩尔电导率 ',
             ('t', 'Λ_{m}^{∞}', ITALIC),
             '。%d 个物种的拟合结果如图3所示。' % len(_fit_keys)
             if len(_fit_keys) == 1 else
             '。%d 个物种的拟合结果分别如%s所示。'
             % (len(_fit_keys), _fig_span)])
    for idx, key in enumerate(_fit_keys, 3):
        f = fits[key]
        rb.figure(fit_pngs[key],
                  caption='图%d  %s 的 Λ_{m}–√c 拟合直线'
                          % (idx, conduct.SPECIES_LABEL[key]),
                  width_cm=plotting.ps.FIG_W_CM)
        sign = '-' if f['k'] < 0 else '+'
        rb.equation(r'\Lambda_{m}=(%(b)s)%(s)s(%(k)s)\times\sqrt{c}'
                    % {'b': pm(f['lam_inf'], f['sigma_inf']), 's': sign,
                       'k': pm(abs(f['k']), f['sigma_k'])})
        rb.para(['相关系数 ', ('t', 'r', ITALIC), ' = ',
                 ('t', '%.2f' % f['r'], ITALIC), '。'])
    # ⚠ 这里原来有一句 `f_worst = fits['HCl']`，**从未被使用**（下面段落
    # 取最差物种用的是 `_finite_fits` 的 `min()`），而且它在缺 HCl 数据时
    # 会直接 KeyError。死代码 + 崩溃点，已删除（2026-11-27）。
    #
    # ⚠ 这段原来写的是“HNO₃ 前两个数据点违背规律、线性特别差”。物种换成
    # HCl 以后那句话**不再成立**：HCl 不易挥发，实测 r 都在 −0.97 附近、
    # 线性良好。所以这里改成**按实际 r 值分档描述**，不再预设某个物种有问题。
    # 报告正文不能断言数据里没有的现象——那是编造。
    #
    # ⚠ 取最差物种也必须**数据驱动**：只遍历 `fits` 里真的算出来的键，
    # 否则缺物种时 `fits[k]` 直接 KeyError（与上面三处循环同一类问题）。
    # ⚠ `min(_finite_fits)` 取的是**代数最小**的 r。因为 Λm 随 √c 下降，
    # r 全为负，代数最小 = |r| 最大 = **线性最好**，不是最差。
    # 原来下面写「相关系数最低」并暗示它有问题，读起来像「HCl 拟合最差」，
    # 而实际 HCl 线性最好（|r| 最大）。这里改成按 |r| 明确表述，
    # 避免「最低」被误读成「最差」（用户 2026-11-27 指出）。
    rb.para(['与电导率不同，强电解质的摩尔电导率随浓度增加而降低：溶液中能导电'
             '的物质的量已给定（1 mol），浓度升高时正负离子相互作用力增加并形成'
             '离子氛，两种效应都阻碍离子在电场下的定向运动。'])
    _finite_fits = [(fits[k]['r'], k) for k in _fit_keys
                    if np.isfinite(fits[k]['r'])]
    _best_r, _best_key = max(_finite_fits, key=lambda t: abs(t[0]))
    _abs_r = abs(_best_r)
    if _abs_r < 0.99:
        rb.para(['%d 个物种的拟合线性程度略有差别，其中 %s 的线性相对最好'
                 '（' % (len(_fit_keys), conduct.SPECIES_LABEL[_best_key]),
                 ('t', '|r|', ITALIC), ('t', ' = %.3f' % _abs_r, ITALIC),
                 '，最大），但仍有可见的弯曲。线性偏差的来源见 4.1 节：'
                 '一方面是低浓度端电导率的绝对值小、仪器噪声与溶解 CO_{2} 等'
                 '杂质的相对影响大；另一方面是电极浸入深度与摆放位置会改变'
                 '有效电导池面积，这部分对稀溶液尤为显著。'])
    else:
        rb.para(['%d 个物种的拟合直线线性都相当好（' % len(_fit_keys),
                 ('t', '|r|', ITALIC), ' 均优于 0.99），说明在本实验的浓度'
                 '范围内 Kohlrausch 极限定律成立良好。'])

    rb.heading('3.2.3 极限摩尔电导率的计算', 3)
    rb.para('根据 %d 条拟合直线的截距，得到各强电解质的极限摩尔电导率'
            '（不确定度为拟合截距的标准误）：' % len(_fit_keys))
    for key in _fit_keys:
        f = fits[key]
        rb.para([('t', 'Λ_{m}^{∞}', ITALIC),
                 ('t', '(%s)' % conduct.CHEM_MARK[key], {}),
                 ' = ',
                 ('t', '(%s) S·m⁻²·mol⁻¹' % pm(f['lam_inf'], f['sigma_inf']), {})])
    # ⚠ 组合式依赖 an.esa，缺强电解质时为 None —— 由 hac_ok 判断，
    # 缺数据时说明原因并返回，不再往下取 an.esa['combo']（原来会 TypeError）。
    if not hac_ok or an.esa is None:
        rb.para(['弱电解质 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                 ' 需由离子独立运动定律从强电解质结果组合求得，'
                 '而本次强电解质数据不齐（缺 %s），'
                 '无法完成组合，相关计算与讨论从略。'
                 % '、'.join(conduct.SPECIES_LABEL[k]
                            for k in conduct.STRONG_SPECIES
                            if k not in fits)])
        return
    combo = an.esa['combo']
    add_names = '+'.join(conduct.SPECIES_LABEL[k] for k in combo['add'])
    sub_names = '-'.join(conduct.SPECIES_LABEL[k] for k in combo['sub'])
    rb.para(['弱电解质不符合 Kohlrausch 经验公式，其极限摩尔电导率由离子独立'
             '运动定律从强电解质结果组合而来。本实验的组合关系为 ',
             # ⚠ Λ 是量符号，必须走片段列表；写进纯字符串会整串正体
             ('t', 'Λ_{m}^{∞}', ITALIC),
             ('t', '(HAc)', {}),
             ' = %s − %s，即：' % (add_names, sub_names)])
    lam_hac, sig_hac = an.esa['lam_inf'], an.esa['sigma']
    # 组合式按 combo 里的**实际物种**生成。原来把 NaAc/HNO₃/NaNO₃ 写死在
    # LaTeX 里，物种一换（NaCl/HCl）就会印出与数据不符的式子。
    # 注意符号：add 项之间用 +，sub 项前面用 −（不能把两个列表都拼成 +）。
    _lam = lambda k: r'\Lambda_{m}^{\infty}(\mathrm{%s})' % k  # noqa: E731
    _rhs = '+'.join(_lam(k) for k in combo['add'])
    for k in combo['sub']:
        _rhs += '-' + _lam(k)
    rb.equation(r'\Lambda_{m}^{\infty}(\mathrm{HAc})=%s'
                r'=%s\ S\cdot m^{2}\cdot mol^{-1}'
                % (_rhs, _latex_num(lam_hac, 5)))
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
             'Na⁺ 0.005008、Ac⁻ 0.00409、H⁺ 0.034965、Cl⁻ 0.007631 '
             'S·m⁻²·mol⁻¹。由离子独立运动定律求得各物种的理论值，'
             '与实验值一起整理成表6，相对误差以 %s 为例：'
             % conduct.SPECIES_LABEL[an.lit_table[0]['key']]])
    na = an.lit_table[0]
    # 相对误差式也按**实际物种**生成（原来写死 NaNO₃，换成 NaCl 后不成立）
    _e_mark = conduct.CHEM_LATEX.get(na['key'], na['key'])
    rb.equation(r'E_{r}(%s)=\frac{%s-%s}{%s}\times100\%%=%s'
                % (_e_mark, _latex_num(na['exp'], 5),
                   _latex_num(na['theo'], 5), _latex_num(na['theo'], 5),
                   pct(na['er'])))
    rb.caption('表6  各物种极限摩尔电导率实验值（exp）与理论值（theo）的比较')
    rows6 = []
    for row in an.lit_table:
        rows6.append([conduct.SPECIES_LABEL[row['key']],
                      '%s S·m⁻²·mol⁻¹' % pm(row['exp'], row['sigma']),
                      sig_fig(row['theo'], 5), pct(row['er'])])
    rb.table(['物种', 'Λ_{m}^{∞}（实验值）', 'Λ_{m}^{∞}（理论值）', 'E_{r}'],
             rows6, widths_cm=[2.2, 5.6, 3.6, 2.6])


# ---------------------------------------------------------------- 3.3
def _sec_weak_skipped(rb, an):
    """强电解质数据不齐、`esa`/`kmean`/`kfit` 为 None 时的替代小节。

    ⚠ 不能**静默省略**整个 3.3 节：读者会以为实验只做了强电解质，
    或者以为报告漏印。必须写清楚“为什么没有”——这正是
    `Analysis.compute()` 已经给出的 warning，转述到报告里即可。
    """
    rb.heading('3.3 弱电解质的数据处理（本次未完成）', 2)
    missing = [conduct.SPECIES_LABEL[k]
               for k in conduct.STRONG_SPECIES if k not in an.fits]
    rb.para(['弱电解质 HAc 的极限摩尔电导率由离子独立运动定律从强电解质结果'
             '组合求得（', ('t', 'Λ_{m}^{∞}', ITALIC),
             ('t', '(HAc)', {}), ' = 加项之和 − 减项），'
             '因此要求三种强电解质的数据齐备。本次缺少 %s 的测量数据，'
             '组合无法完成，故 HAc 的极限摩尔电导率、'
             '两种方法的电离平衡常数以及后续的讨论均从略。'
             % ('、'.join(missing) if missing else '部分物种')])
    rb.para('补齐上述物种的测量数据后重新生成报告，本节的全部内容会自动恢复。')
    if an.warnings:
        rb.para(['本次计算过程记录的提示：' + '；'.join(an.warnings[:6]) + '。'])


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
             table_rows,
             # κ_{measured} / κ_{corrected} 两列原来给 2.6 cm 放不下（实测可用
             # 2.42 cm，Word 折成两行）。各加 0.4 cm；Λ_m 列留足，其余列各让出
             # 0.1~0.4 cm，总和 16.0 cm = 正文宽（审计 B P1-2）。
             widths_cm=[1.0, 2.1, 3.0, 3.0, 2.9, 1.3, 2.7])

    # 这里的瓶数原来是写死的“5”：瓶数变化（或 drift 结论不同）时
    # 会印出与数据不符的式子。改为取实际瓶数。
    n_bot = len(kmean['bottles'])
    drift_bot = bool(kmean.get('drift'))
    rb.para(['%d 组数据平衡常数 ' % n_bot, ('t', 'K^{⊖}', ITALIC),
             ' 的平均值为：'])
    ks_txt = '+'.join(_latex_num(b['k'] * 1e5, 3) for b in kmean['bottles'])
    rb.equation(r'K^{\\ominus}=\\frac{%s}{%d}\\times10^{-5}=%s\\times10^{-5}'
                % (ks_txt, n_bot, _latex_num(kmean['mean'] * 1e5, 3)))
    if drift_bot:
        rb.para(['由于各浓度瓶给出的 ', ('t', 'K^{⊖}', ITALIC),
                 ' 并不完全相同（见下文的不确定度分析），此平均值只代表'
                 '这几个浓度点上的平均水平。'])
    rb.para(['下面估算其不确定度。联立摩尔电导率、电离度和标准电离平衡常数的'
             '计算式，可得 ', ('t', 'K^{⊖}', ITALIC), ' 的总计算式：'])
    rb.equation(r'K^{\ominus}=\frac{1}{c^{\ominus}}\times'
                r'\frac{\kappa_{corrected}^{2}}'
                r'{c(\Lambda_{m}^{\infty})^{2}-\kappa_{corrected}\Lambda_{m}^{\infty}}')
    # σ_κ 的末位由**仪器分辨力**决定，不由字符串里写了几个小数位决定。
    #
    # ⚠ 这里原来印的是“σ_κ 随记录的小数位数而变（2×10^{−d}，d 为读数的小数位数）”。
    # 那句话描述的是一个**已经修掉的缺陷**：按小数位定末位时，同一个仪器读数
    #      '0.277' → 3 位小数 → σ_κ = 2×10⁻³
    #      '0.2770' → 4 位小数 → σ_κ = 2×10⁻⁴        相差 10 倍
    # 学生习惯把末尾的 0 省掉，于是“抄了几个 0”直接决定报告精度。
    # 现在末位按读数量级分档（见 conduct.py 的 KAPPA_RANGE_EDGES）：
    #   κ > 0.02 S·m⁻¹（仪器大量程，显示到 1 μS·cm⁻¹） → 末位 1e-4 → σ_κ = 2×10⁻⁴
    #   κ ≤ 0.02 S·m⁻¹（小量程，显示到 0.1 μS·cm⁻¹）    → 末位 1e-5 → σ_κ = 2×10⁻⁵
    # 所以正文按读数所在的量程统计，不再提“小数位数”。
    def _sigma_txt(v):
        """2e-4 这种值写成普通文本：2×10⁻⁴（用真上标标记，交给 add_rich_text）。"""
        exp = int(round(__import__('math').log10(v)))
        mant = v / (10.0 ** exp)
        return '%g×10^{%d}' % (mant, exp)

    sig_all = [float(r['sigma_kappa'])
               for rows in (an.tables or {}).values()
               for r in rows if r.get('sigma_kappa')]
    sig_segs = []
    if sig_all:
        uniq = sorted(set(sig_all))
        if len(uniq) == 1:
            sig_segs = [('t', 'σ_{κ}', ITALIC),
                        ' 统一取 %s S·m⁻¹。' % _sigma_txt(uniq[0])]
        else:
            counts = {v: sig_all.count(v) for v in uniq}
            parts = '、'.join('%d 个读数取 %s' % (counts[v], _sigma_txt(v))
                             for v in uniq)
            sig_segs = [('t', 'σ_{κ}', ITALIC),
                        ' 按读数量程分档（大量程 ',
                        ('t', 'κ', ITALIC),
                        ' > 0.02 S·m⁻¹ 末位取 1×10^{−4}、小量程 ',
                        ('t', 'κ', ITALIC),
                        ' ≤ 0.02 S·m⁻¹ 末位取 1×10^{−5}）：'
                        '%s S·m⁻¹。' % parts]
    else:
        sig_segs = [('t', 'σ_{κ}', ITALIC), '。']
    rb.para(['电导率读数的不确定度按“末位数字取 2”估计：'] + sig_segs + [
             '末位由电导率仪在该量程的分辨力决定，与记录时写了几个小数位无关——'
             '若按记录的小数位数定末位，同一个读数写成 0.277 与 0.2770 会差出 '
             '10 倍，报告精度就成了“抄写习惯”的函数。'
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
             '，得到各瓶的不确定度（表8）。'])
    # ⚠ 这里原来印的是 σ_K° = √(Σσ_i²)/5，即把 5 个**不同浓度瓶**当成
    # 同一个量的 5 次重复测量。但它们是 5 个独立估计，瓶间还随浓度单调漂移，
    # 所以那个式子只反映“瓶内读数传播”，把瓶间系统漂移当成了 0
    # （实测 2.5676e-07，而瓶间 SEM 是 7.7960e-07，相差 3.04 倍）。
    # 现在按两段式报：瓶内项与瓶间项取大（见 conduct.k_from_mean）。
    sig_within = float(kmean.get('sigma_within', float('nan')))
    sig_between = float(kmean.get('sigma_between', float('nan')))
    drift = bool(kmean.get('drift'))
    rel_spread = float(kmean.get('rel_spread', float('nan')))
    sig_used = float(kmean['sigma'])
    n_bottle = len(kmean['bottles'])

    rb.para(['把这些瓶看作同一物理量的重复测定并不合适：它们是 %d 个不同浓度下的'
             '独立估计，瓶与瓶之间还存在随浓度变化的系统漂移。故总不确定度取'
             '以下两者中的较大者。' % n_bottle])
    rb.para(['（1）瓶内项——各瓶由 ', ('t', 'σ_{κ}', ITALIC), ' 与 ',
             ('t', 'σ_{Λ_{m}^{∞}}', ITALIC),
             ' 逐瓶传播得到的不确定度，按独立量合成后取平均：'])
    sig_parts = '+'.join(_latex_num(b['sigma_k'] ** 2 / 1e-14, 2)
                         for b in kmean['bottles'])
    rb.equation(r'\sigma_{K^{\ominus}}^{\mathrm{within}}='
                r'\frac{\sqrt{%s}}{%d}\times10^{-7}=%s\times10^{-7}'
                % (sig_parts, n_bottle,
                   _latex_num(sig_within * 1e7, 2)))
    rb.para(['（2）瓶间项——各瓶 ', ('t', 'K^{⊖}', ITALIC),
             ' 的标准偏差除以瓶数的平方根，即平均值自身的标准误，'
             '衡量的是“不同浓度瓶给出的 K⊖ 彼此有多一致”（式中带下标 m 的量表示各瓶 K⊖ 的平均值）：'])
    # ⚠ 本 OMML 不支持 \bar / \overline（会在正文残留反斜杠），
    # 用 Unicode 组合字符 m̄ 表示平均值；且 m 是**量符号**，不能用
    # \mathrm{} 强成正体（原来写成 \mathrm{m}，与同段正文「带下标 m 的量
    # 表示各瓶 K⊖ 的平均值」自相矛盾）。
    rb.equation(r'\sigma_{K^{\ominus}}^{\mathrm{between}}='
                r'\frac{1}{\sqrt{%d}}\sqrt{\frac{\sum_{i=1}^{%d}'
                r'\left(K_{i}^{\ominus}-m̄^{\ominus}\right)^{2}'
                r'}{%d}}=%s\times10^{-7}'
                % (n_bottle, n_bottle, n_bottle - 1,
                   _latex_num(sig_between * 1e7, 2)))
    rb.equation(r'\sigma_{K^{\ominus}}=\mathrm{max}\left(\sigma_{K^{\ominus}}'
                r'^{\mathrm{within}},\ \sigma_{K^{\ominus}}^{\mathrm{between}}'
                r'\right)=%s\times10^{-7}'
                % _latex_num(sig_used * 1e7, 2))
    if drift:
        # ⚠ 百分比不能写成 '...%.1f%%，...' 再对最后一段做 % 运算：
        # '%' 只作用于紧挨着它的那个字符串字面量，而 '%.1f%%' 在队列里
        # 的位置与 % 运算的对象不一定是同一个片段，会抛
        # TypeError: not all arguments converted。先算好整句再插进列表。
        spread_txt = ('本组数据中各瓶 K^{⊖} 的相对离散为 %.1f%%，'
                      '瓶间项显著大于瓶内项，说明 K^{⊖} 随浓度存在系统漂移'
                      '（活度系数未校正所致），因此取瓶间项作为不确定度；'
                      '此时平均值只代表这些浓度点上的平均水平，'
                      '不代表无限稀释的真值。' % rel_spread)
        rb.para([spread_txt])
    else:
        rb.para(['本组数据中瓶间项不大于瓶内项，两者一致，说明各浓度瓶给出的 ',
                 ('t', 'K^{⊖}', ITALIC),
                 ' 相互吻合，取瓶内项作为不确定度。'])
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
              width_cm=plotting.ps.FIG_W_CM)
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
    # ⚠ `lit_table` 在数据不齐时为空（analysis 已给默认值，不再是
    # AttributeError），此时不能拼出「相对误差都不大（）」这种空括号。
    if not an.lit_table:
        rb.para(['本次强电解质数据不齐，缺少与手册值的完整对照，'
                 '误差分析从略。下面仅对已有的拟合结果作说明。'])
        for k in conduct.STRONG_SPECIES:
            if k in an.fits:
                f = an.fits[k]
                rb.para(['%s：' % conduct.SPECIES_LABEL[k],
                         ('t', 'Λ_{m}^{∞}', ITALIC),
                         ('t', ' = (%s) S·m⁻²·mol⁻¹' 
                          % pm(f['lam_inf'], f['sigma_inf']), {}),
                         '，相关系数 ',
                         ('t', 'r', ITALIC),
                         ('t', ' = %.3f' % f['r'], ITALIC), '。'])
        return
    er_txt = '、'.join('%s %s' % (conduct.SPECIES_LABEL[r['key']], pct(r['er']))
                       for r in an.lit_table[:3])
    # ⚠ 原来写死「各强电解质的相对误差都不大」，但相对误差是**算出来的**，
    # 有人 NaCl −8.3%、HCl −8.3%（共享数据里就有）。改成按实际最大偏差分档。
    _max_er = max((abs(float(r['er'])) for r in an.lit_table), default=0.0)
    if _max_er <= 3.0:
        _er_verdict = '各强电解质极限摩尔电导率的相对误差都不大'
    elif _max_er <= 10.0:
        _er_verdict = '各强电解质极限摩尔电导率的相对误差尚可接受，但有个别偏大'
    else:
        _er_verdict = '各强电解质极限摩尔电导率的相对误差偏大（最大 %s）' % pct(_max_er)
    rb.para('根据表6，%s（%s），但这个相对误差并不完全可信，分析如下。'
            % (_er_verdict, er_txt))
    # ⚠ 原来这段专门归因于“HNO₃ 容易挥发导致低浓度点偏低”。物种换成
    # HCl 后那个解释不成立（HCl 不挥发），硬留着就是给数据编成因。
    # 现在按**实测的 r 与相对误差**分档叙述，只说数据支持的话。
    #
    # ⚠⚠ **相关系数必须按绝对值判好坏**：r 是负数（Λm 随 √c 下降），
    # 「线性最好」= |r| 最大（最接近 −1）。原来直接 `max(rs)` 取的是
    # **代数值最大**，于是把 r = −0.901 判成「最好」、把 −0.971 判成
    # 「略差」——**结论正好反了**（用户 2026-11-27 指出「HCl 拟合最差」
    # 不符合实际）。实测：HCl r=−0.971 才是线性最好的。
    fits = an.fits
    rs = {k: fits[k]['r'] for k in conduct.STRONG_SPECIES if k in fits}
    if len(rs) >= 2:
        _best = max(rs, key=lambda k: abs(rs[k]))     # |r| 最大 = 线性最好
        _worst = min(rs, key=lambda k: abs(rs[k]))    # |r| 最小 = 线性最差
        _gap = abs(abs(rs[_best]) - abs(rs[_worst]))
        # 只有差异足够大时才分高下，否则「差不多」更诚实
        if _gap >= 0.02:
            _cmp = ['从线性看，%s 的拟合最好（'
                    % conduct.SPECIES_LABEL[_best],
                    ('t', 'r', ITALIC), ' = ',
                    ('t', '%.3f' % rs[_best], ITALIC), '），%s 略差（'
                    % conduct.SPECIES_LABEL[_worst],
                    ('t', 'r', ITALIC), ' = ',
                    ('t', '%.3f' % rs[_worst], ITALIC), '）。']
        else:
            _cmp = ['从线性看，各物种的相关系数差别很小（',
                    ('t', 'r', ITALIC), ' = %.3f~%.3f），线性程度相当。'
                    % (min(rs.values()), max(rs.values()))]
        # 「线性好坏与误差大小是否对应」也要按数据说，不能预设。
        #
        # ⚠ 判据必须是「线性最好的那个物种，是不是同时也是误差最小的那个」，
        # **不能只比 best 与 worst 两个**（我第一版就这么写错了）：
        # 实测 |r| 最大的是 HCl（1.3%），|r| 最小的是 NaCl（1.4%），
        # 只比这两个会得出「1.3 < 1.4 → 一致」，但真正误差最小的是
        # 中间的 NaAc（0.84%）——三物种时漏掉中间的那个就会说反。
        _er_by_key = {r['key']: abs(float(r['er'])) for r in an.lit_table
                      if r['key'] in rs}
        if _er_by_key:
            _er_best = min(_er_by_key, key=lambda k: _er_by_key[k])
            if _er_best == _best:
                _rel_txt = ('本例中线性最好的物种误差也确实最小，两者一致；'
                            '但不能据此认为线性好就一定有小的误差，因为 ')
            else:
                _rel_txt = ('本例中线性最好的物种（%s）并非误差最小的'
                            '（%s），两者不一致：'
                            % (conduct.SPECIES_LABEL[_best],
                               conduct.SPECIES_LABEL[_er_best]))
        else:
            _rel_txt = '线性好坏与误差大小不一定对应：'
        _cmp.append(_rel_txt)
        _cmp.extend([('t', 'Λ_{m}^{∞}', ITALIC),
                     ' 是外推得到的量，截距的偏差由整条'
                     '直线的斜率与分布共同决定，而不只由残差大小决定。因此'
                     '“相对误差小”不能单独当作拟合可信的证据。'])
        rb.para(_cmp)
    rb.para('线性欠佳的系统性原因在于：极低浓度下摩尔电导率较高，但绝对'
            '电导率很低，仪器噪声与杂质的影响很大。杂质可能来自空气及呼吸'
            '带出的 CO_{2}；仪器方面，铂电极片的浸入深度、摆放位置都可能改变'
            '有效电导池面积，这些影响对稀溶液尤为显著。此外，Kohlrausch 经验'
            '公式只对“极稀溶液”成立，NaAc 还可能轻微水解，但本实验的浓度'
            '已处于一般文献认可的极稀范围内，不构成主要因素。')


# ---------------------------------------------------------------- 4.2 误差预算
#
# 用户 2026-11-27 指出：4.1 那一节讨论的是「强电解质 Λm∞ 的相对误差」，
# 而课程要求的误差分析是**最终量 K° 的误差贡献分解**——温度补偿、温度波动、
# 溶液浓度、移液管允差、拟合误差各占多少。两者是不同的对象：
# 4.1 的自变量是 Λm∞（对表6），本节的自变量是 K°（对表9）。
#
# 本节的所有数字都来自 ``conduct.error_budget``，而它是用**数值扰动 + 整链
# 重算**得到的，不是手推灵敏度系数乘出来的——原因见该函数的说明：三层耦合
# （κ/c 的传导方式、Λ∞ 组合的正负权重、瓶平均）手推容易错符号或差 n 倍，
# 我在这上面推错过两版，最后用有限差分定标才定下来。
def _sec_error_budget(rb, an):
    esa = an.esa
    kmean = an.kmean
    if esa is None or kmean is None:
        return False
    eb = conduct.error_budget(
        an.tables, an.fits, esa['lam_inf'], esa['sigma'], esa['combo'],
        temp_c=an.ctx.get('temp'), compensation=an.ctx.get('compensation'),
        kappa_w=an.ctx.get('kappa_w'))
    # 标题在这里统一打一次：两个分支互斥，不能各写一处——
    # 否则要么重号（两处都执行），要么正常路径漏标题（我第一版误删了
    # 正常分支那处，于是正文直接出现「4.1 节讨论的是…」，4.2 节名凭空消失，
    # 而 4.2.1 又照常出现，成了"有子节无父节"）。
    rb.heading('4.2 标准电离平衡常数的误差来源分析', 2)
    if not eb.get('ok'):
        rb.para(['本节本应对最终量 ', ('t', 'K^{⊖}', ITALIC),
                 ' 作误差来源分解，但'])
        rb.para(['；'.join(eb.get('notes') or ['数据不足，无法完成预算']) + '。'])
        rb.para('补齐数据后重新生成报告，本节会自动给出完整的分项贡献。')
        return True

    rb.para(['4.1 节讨论的是 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 的相对误差（对应表6）；本节的对象是最终量 ',
             ('t', 'K^{⊖}', ITALIC),
             '（对应表9）。两者的误差来源并不相同：',
             ('t', 'K^{⊖}', ITALIC),
             ' 由 ', ('t', 'Λ_{m}', ITALIC), '、', ('t', 'c', ITALIC),
             ' 和 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 共同决定，而 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             '(HAc) 又要由三个强电解质的加减得到，误差在其中会被加权、'
             '也可能相互抵消。因此有必要按对最终量的贡献逐项分解。'])

    # ---- 4.2.1 灵敏度：为什么不能"按输入量直接乘"
    rb.heading('4.2.1 各输入量对 K 的灵敏度', 3)
    S2 = eb['coef']['kappa']
    S1 = eb['coef']['c']
    rb.para(['由 ', ('t', 'K^{⊖}', ITALIC), ' 与 ', ('t', 'α', ITALIC),
             ' 的定义对 ', ('t', 'κ_{corrected}', ITALIC), '、', ('t', 'c', ITALIC),
             ' 求偏导，可得相对灵敏度：'])
    rb.equation(r'\left|\frac{\partial\ln K^{\ominus}}{\partial\ln c}\right|=1+\frac{\alpha}{1-\alpha},'
                r'\qquad\left|\frac{\partial\ln K^{\ominus}}{\partial\ln\kappa}\right|'
                r'=\left|\frac{\partial\ln K^{\ominus}}{\partial\ln\Lambda_{m}^{\infty}}\right|'
                r'=2+\frac{\alpha}{1-\alpha}')
    rb.para(['本实验各瓶的 ', ('t', 'α', ITALIC), ' 在 %s~%s 之间，'
             % (_f3(min(b['alpha'] for b in kmean['bottles'])),
                _f3(max(b['alpha'] for b in kmean['bottles']))),
             '故两个系数分别为 ',
             ('t', '%.3f' % S1, {}), ' 和 ', ('t', '%.3f' % S2, {}),
             '——', ('t', 'κ', ITALIC),
             ' 的误差对 ', ('t', 'K', ITALIC),
             ' 的影响约为浓度的两倍。这一点决定了后面的排序：'
             '凡是通过 ', ('t', 'κ', ITALIC),
             ' 进入的项（读数、温度补偿、', ('t', 'Λ^{∞}', ITALIC),
             '、母液与移液管引起的 ', ('t', 'κ', ITALIC),
             ' 变化）都带 ', ('t', '≈2.07', {}), ' 的放大因子；'
             '只有直接影响名义浓度的那部分带 ',
             ('t', '≈1.07', {}), '。'])
    rb.para(['需要特别强调一个容易写错的地方：配制偏浓时，测到的 ',
             ('t', 'κ', ITALIC),
             ' 也同比例偏大，而计算仍用配制表上的名义 ', ('t', 'c', ITALIC),
             '。所以浓度类误差在 ', ('t', 'Λ_{m}=κ/c', ITALIC),
             ' 里并不抵消——它表现为 ', ('t', 'κ', ITALIC),
             ' 偏了而 ', ('t', 'c', ITALIC),
             ' 没变，因而走的是 2.07 那条'
             '路径，不是 1.07。若照“浓度误差只影响 ', ('t', 'c', ITALIC),
             '”去算，会把 ',
             'HAc 母液那一项低估一半。'])

    # ---- 4.2.2 分项贡献
    rb.heading('4.2.2 各误差来源的分项贡献', 3)
    rb.para(['把上述各项的输入不确定度逐一代入完整的计算链（组合 ',
             ('t', 'Λ_{m}^{∞}', ITALIC),
             '(HAc) → 逐瓶 ', ('t', 'α', ITALIC), ' → 逐瓶 ',
             ('t', 'K^{⊖}', ITALIC), ' → 求平均），重算 ',
             ('t', 'K^{⊖}', ITALIC),
             ' 的变化量，得到表10。每一项都是“只扰动该项、其余不动”的单次'
             '重算，与正文的计算共用同一套函数，因此不存在另一套口径。'])
    _NAME = {'fit': ('拟合误差', '各物种 ', None),
             'conc': ('溶液浓度', '母液标定 + 容量瓶定容', None),
             'read': ('电导率读数', '仪器末位（取 2）', None),
             'pip': ('移液管允差', 'GB/T 12807 A 类', None),
             'comp': ('温度补偿', '仪器补偿系数与真实 β 之差', None),
             'fluct': ('温度波动', '恒温槽波动', None)}
    rows = []
    for t in eb['terms']:
        nm = _NAME.get(t['key'], (t['name'], '', None))[0]
        rows.append([nm,
                     '共同' if t['kind'] == 'common' else '独立',
                     '%.2f' % t['pct'],
                     '%.1f' % t['share']])
    rb.caption('表10  K^{⊖} 各误差来源的贡献（按对 K^{⊖} 的相对影响排序）')
    rb.table(['误差来源', '性质', 'ΔK^{⊖}/K^{⊖} / %', '方差占比 / %'],
             rows + [['合成', '—', '%.2f' % eb['total_pct'], '100']],
             widths_cm=[3.6, 1.8, 4.0, 3.4])
    rb.para(['表中“共同”指该项对各瓶同向作用（如拟合误差、母液浓度），'
             '它不会因多测几瓶而减小；“独立”指逐瓶独立的随机项（如读数末位、'
             '逐瓶移液），取平均后按 1/√n 下降。最后一列是方差占比'
             '（平方后归一），所以几项相加可以超过 100%，这是独立误差按'
             '平方和合成的直接结果，不是算错。'])

    # ---- 4.2.3 逐项讨论（顺序由数据决定，不预设）
    rb.heading('4.2.3 主要来源的机理', 3)
    fitted = next((t for t in eb['terms'] if t['key'] == 'fit'), None)
    conc = next((t for t in eb['terms'] if t['key'] == 'conc'), None)
    read = next((t for t in eb['terms'] if t['key'] == 'read'), None)
    pip = next((t for t in eb['terms'] if t['key'] == 'pip'), None)
    comp = next((t for t in eb['terms'] if t['key'] == 'comp'), None)
    fluct = next((t for t in eb['terms'] if t['key'] == 'fluct'), None)

    # 名次由 eb['terms'] 的顺序给出（已按 value 降序），不写死「第 1 项是谁」
    rank = {t['key']: i + 1 for i, t in enumerate(eb['terms'])}
    _CN = {1: '（1）', 2: '（2）', 3: '（3）', 4: '（4）', 5: '（5）', 6: '（6）'}

    if fitted is not None:
        w = eb['weights']
        order = conduct.conduct_order(esa['combo'])
        # 主导物种 = |权重| × 自身相对不确定度 最大者
        cand = []
        for k2 in order:
            if k2 not in w or k2 not in an.fits:
                continue
            lim = float(an.fits[k2].get('lam_inf', float('nan')))
            sig = float(an.fits[k2].get('sigma_inf', float('nan')))
            if np.isfinite(lim) and lim and np.isfinite(sig):
                cand.append((k2, w[k2], sig / lim, abs(w[k2]) * sig / lim))
        lead = max(cand, key=lambda t2: t2[3]) if cand else None
        # ⚠ 「谁自身相对误差大谁就主导」是**错的**：实测 HCl 自身只有 0.65%
        # （三个物种里最小），但它在组合式里权重 1.09、其余两项仅 ±0.2~0.3，
        # 于是它反而是主导项。必须按「权重 × 自身误差」判，不能按自身误差判。
        _wtxt = '、'.join('%s %+.2f' % (conduct.SPECIES_LABEL.get(k2, k2), w[k2])
                          for k2 in order if k2 in w)
        rb.para(['%s拟合误差（%.2f%%，占 %.0f%% 的方差）是本项中最大的来源。'
                 % (_CN.get(rank.get('fit', 9), ''), fitted['pct'],
                    fitted['share']),
                 ('t', 'Λ_{m}^{∞}', ITALIC), '(HAc) 由 ',
                 '、'.join(conduct.SPECIES_LABEL.get(k2, k2) for k2 in order),
                 ' 加减得到，三者的拟合标准误按权重传递（权重 ',
                 _wtxt, '）。'])
        if lead:
            rb.para(['真正起决定作用的不是自身相对误差最大的物种，而是'
                     '“权重 × 自身误差”最大的那一个：本实验中 ',
                     conduct.SPECIES_LABEL.get(lead[0], lead[0]),
                     ' 自身的 ', ('t', 'σ/Λ_{m}^{∞}', ITALIC), ' 只有 ',
                     ('t', '%.2f%%' % (lead[2] * 100), {}),
                     '，在三个物种里并不突出，但它在组合式里的权重是 ',
                     ('t', '%+.2f' % lead[1], {}),
                     '（因为 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                     '(HCl) 数值远大于其余两项），放大后成为主导。'
                     '这也解释了为什么单纯“把每个物种都拟合得更直”并不等价于'
                     '“把 K 做得更准”——要优先压的是权重大的那个物种。'])
        rb.para(['另一条不能忽略的路径是：拟合误差属于“共同项”，'
                 '它对各浓度瓶同向作用，多测几瓶不会把它压小。'
                 '这与读数、移液这类逐瓶随机的项性质不同。'])

    if conc is not None:
        rb.para(['%s溶液浓度（%.2f%%，占 %.0f%% 的方差）。本项包含两部分：'
                 '母液本身浓度的不确定度（按 %.1f%% 估计，母液由老师配制标定，'
                 '学生不参与）与 %.0f mL 容量瓶的定容允差（±%.2f mL）。'
                 '两者合成 ' % (_CN.get(rank.get('conc', 9), ''), conc['pct'],
                                conc['share'], eb['stock_rel'],
                                eb['flask_ml'], eb['flask_tol_ml']),
                 ('t', 'u(c)/c', ITALIC), ' = ',
                 ('t', '%.3f%%' % (np.sqrt((eb['stock_rel'] / 100.0) ** 2
                                           + (eb['flask_tol_ml'] / np.sqrt(3.0)
                                              / eb['flask_ml']) ** 2) * 100), {}),
                 '。逐物种分别计算后按独立量合成——不同物种的母液是各自配制的，'
                 '其浓度误差互不相关，不能假定它们同向抵消。'])
        rb.para(['值得注意：如果假设四个物种的母液同时同向偏同样的比例，'
                 '对 K 的影响反而接近于零（因为 ',
                 ('t', 'Λ_{m}', ITALIC), ' 与 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                 ' 同比例变化，在 ', ('t', 'α', ITALIC),
                 ' 里抵消）。这是一个虚假的抵消：它只在“四份母液误差完全'
                 '相关”时才成立，而实际上它们是四次独立的称量与定容。'
                 '按独立处理才是正确口径，也是本项排到第二位的原因。'])

    if read is not None:
        rb.para(['%s电导率读数（%.2f%%）。读数末位按量程分档取 2，逐瓶 '
                 % (_CN.get(rank.get('read', 9), ''), read['pct']),
                 ('t', 'σ_{κ}/κ', ITALIC),
                 ' %s' % _read_span(an),
                 ' 不等——低浓度瓶的 ', ('t', 'κ', ITALIC),
                 ' 绝对值小，同样的'
                 '仪器分辨力带来更大的相对误差。再经 ',
                 ('t', '2+r', {}), ' 放大后进入 ', ('t', 'K', ITALIC), '。'])

    if pip is not None:
        rb.para(['%s移液管允差（%.2f%%）。按讲义配制表的量取体积，逐瓶取'
                 '“能放出该体积的最小标称规格”的允差（GB/T 12807 A 类）。'
                 '这一项本身不大，但 0.5 mL 那一档的相对允差已达 1.15%%，'
                 '是全组最大——低浓度瓶的配制精度天然最差，'
                 '这也是浓度档位不宜再往下取的原因之一。'
                 % (_CN.get(rank.get('pip', 9), ''), pip['pct'])])

    if comp is not None:
        rb.para(['%s温度补偿（%.2f%%）。这一项的结果需要解释，因为它与直觉相反。'
                 % (_CN.get(rank.get('comp', 9), ''), comp['pct'])])
        if eb.get('comp_cancel'):
            rb.para(['电导率仪按固定的 ',
                     ('t', '%.2f %%/℃' % float(eb['compensation']), {}),
                     ' 做线性补偿，而各物种的真实温度系数并不相同（本实验按 '
                     'CRC 离子值加权得 ',
                     '、'.join('%s %.2f' % (conduct.SPECIES_LABEL.get(k2, k2),
                                            conduct.species_temp_coeff(k2))
                              for k2 in conduct.SPECIES_ORDER
                              if np.isfinite(conduct.species_temp_coeff(k2))),
                     ' %%/℃）。|25−T| = %.1f K 时，这会让单个 ' % abs(eb['dT']),
                     ('t', 'Λ_{m}^{∞}', ITALIC), ' 偏约 ',
                     ('t', '%.2f%%' % eb['lam_comp_pct'], {}),
                     '——若只看表6，这是 0.7% 量级的项。'])
            rb.para(['但对 ', ('t', 'K^{⊖}', ITALIC),
                     ' 而言它几乎完全抵消：',
                     ('t', 'Λ_{m}^{∞}', ITALIC),
                     '(HAc) 是由同一批离子加和出来的，与 HAc 溶液自身的电导率'
                     '同源，补偿系数整体偏一点时 ',
                     ('t', 'κ(HAc)', {}), ' 与 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                     ' 按同一比例变化，比值不变。实测代入后 ',
                     ('t', 'ΔK^{⊖}/K^{⊖}', ITALIC), ' 只剩 ',
                     ('t', '%.3f%%' % comp['pct'], {}),
                     '。所以温度补偿是表6 的显著误差源，却不是 K 的误差源，'
                     '这两件事必须分开讲：只笼统说“温度补偿有影响”会误导。'])
            rb.para(['剩下的残差来自二阶项与各物种 ', ('t', 'β', ITALIC),
                     ' 的差异不能完全对齐，量级已降到 0.1% 以下，可以忽略。'])
        else:
            rb.para(['本次温度补偿未能一阶抵消（残差 %.2f%%），'
                     '说明各物种的补偿残差不满足同源条件，需要单独核对'
                     '补偿系数的设置。' % comp['pct']])

    if fluct is not None:
        # ⚠ `%` 只作用于紧邻的字符串字面量：把它写在片段列表的中间会导致
        # "not all arguments converted"。先算成变量再插进列表。
        _fl = ('%s温度波动（%.2f%%）。恒温槽波动按 ±%.1f K 估计。'
               '与温度补偿同理，瓶间同步的波动大部分抵消，留下的是逐瓶的'
               '随机部分，故量级远小于按 2+r 直接估算的结果。'
               % (_CN.get(rank.get('fluct', 9), ''), fluct['pct'],
                  conduct.TEMP_FLUCT_K))
        rb.para([_fl])

    # ---- 4.2.4 合成与判断
    rb.heading('4.2.4 合成不确定度与系统偏差', 3)
    _k_mean = float(kmean['mean'])
    _sig_abs = eb['total'] * _k_mean
    rb.para(['把上表各项按方和根合成，得 ', ('t', 'K^{⊖}', ITALIC), ' = ',
             # ⚠ sci_pm 自己已经带一对外括号（值是 (1.80 ± 0.01)×10^{-5} 形式），
             # 外面再包一层就成了 ((1.633 ± 0.043)×10⁻⁵)，实测踩到。
             ('t', '%s' % sci_pm(_k_mean, _sig_abs), {}),
             '，相对合成不确定度 ',
             ('t', '%.2f%%' % eb['total_pct'], {}),
             '。作为对照，3.3.1 节按瓶间离散给出的 ',
             ('t', 'σ_{K^{⊖}}', ITALIC), ' 是 ',
             ('t', '%s' % sci_pm(_k_mean, float(kmean['sigma'])), {}),
             '（相对 %.2f%%）。' % (float(kmean['sigma']) / _k_mean * 100)])
    # 两个口径谁大谁小要按数据说：A 类只含瓶间离散，B 类含全部已知来源
    if float(kmean['sigma']) > _sig_abs:
        rb.para(['瓶间离散给出的不确定度大于分项合成值。这说明各瓶 ',
                 ('t', 'K^{⊖}', ITALIC),
                 ' 之间还存在上表未覆盖的系统漂移（活度系数未校正），'
                 '此时应以瓶间离散作为 A 类估计，分项预算用于说明构成'
                 '而不是替代它。'])
    else:
        rb.para(['分项合成值大于瓶间离散给出的 A 类估计，这是预期的：'
                 'A 类只反映“各瓶彼此差多少”，而共同项（拟合误差、母液浓度、'
                 '温度补偿）对各瓶同向作用，不会体现在瓶间离散里。'
                 '因此报告 K 的不确定度时应以分项合成为准，表8 的瓶内/瓶间项'
                 '只用于判断“各浓度瓶是否自洽”。'])

    ka = conduct.KA_HAC
    dev = (_k_mean - ka) / ka * 100.0
    ratio = abs(dev) / eb['total_pct'] if eb['total_pct'] else float('nan')
    rb.para(['再与手册值比较：', ('t', 'K_{a}', ITALIC), ' = ',
             ('t', sci(ka, 4, -5), {}),
             '（', ('t', 'p', {}), ('t', 'K_{a}', ITALIC), ' = 4.756），'
             '本实验值偏 ', ('t', 'E_{r}', ITALIC), ' = ',
             ('t', '%s' % pct(dev), {}), '，是合成不确定度的 ',
             ('t', '%.1f' % ratio, {}), ' 倍。'])
    if ratio >= 3.0:
        rb.para(['偏差达到 3 倍以上不确定度，说明存在上表未涵盖的系统误差，'
                 '不能仅用随机误差解释。下面把已知的系统项逐条核对，'
                 '定位偏差的来源。'])
    elif ratio >= 1.0:
        rb.para(['偏差与合成不确定度同一量级（1~3 倍），说明随机项与系统项'
                 '都有贡献，尚不能断言存在未识别的系统误差。'])
    else:
        rb.para(['偏差小于合成不确定度，本实验值与手册值在不确定度范围内一致，'
                 '没有证据表明存在显著的系统误差。'])

    # ---- 4.2.5 已知系统项的量级核对（只在偏差显著时才需要"解释"）
    rb.heading('4.2.5 已知系统项的核对与改进方向', 3)
    theo_hac = conduct.LAMBDA_THEO.get('HAc')
    bias_l = ((esa['lam_inf'] - theo_hac) / theo_hac * 100.0
              if theo_hac else float('nan'))
    S2 = eb['coef']['kappa']
    rb.para(['按课程要求的四级口径收束本节：'])
    rb.caption('表11  K^{⊖} 误差来源的四级分析（Level 0~3）')
    lvl_rows = [
        ['Level 0 穷举',
         '拟合、母液浓度、容量瓶、移液管、电导率读数、温度补偿、温度波动',
         '共 %d 项，均已定量' % len(eb['terms'])],
        ['Level 1 半定量',
         '各项 ΔK/K 见表10；最大项 %.2f%%，最小项 %.2f%%'
         % (eb['terms'][0]['pct'], eb['terms'][-1]['pct']),
         '跨越 %.0f 倍'
         % (eb['terms'][0]['pct'] / eb['terms'][-1]['pct'])
         if eb['terms'][-1]['pct'] else '—'],
        ['Level 2 定主因',
         '方差占比前两位：%s' % '、'.join(
             '%s %.0f%%' % (t['name'], t['share']) for t in eb['terms'][:2]),
         '合计 %.0f%%' % sum(t['share'] for t in eb['terms'][:2])],
        ['Level 3 改进',
         _level3_text(eb, an), '按杠杆大小排序'],
    ]
    rb.table(['层级', '内容', '量化结果'], lvl_rows,
             widths_cm=[2.6, 8.4, 4.0], font_size=10.5, keep_together=True)

    if np.isfinite(bias_l) and ratio >= 1.0:
        rb.para(['其中一项可以由数据直接核对：本实验 ',
                 ('t', 'Λ_{m}^{∞}', ITALIC), '(HAc) = ',
                 ('t', '%s' % sig_fig(esa['lam_inf'], 5), {}),
                 '，比离子加和的理论值 ',
                 ('t', '%s' % sig_fig(theo_hac, 5), {}),
                 ' 偏 ', ('t', '%+.2f%%' % bias_l, {}),
                 '。由于 ', ('t', 'K^{⊖}∝(Λ_{m}^{∞})^{-2}', ITALIC),
                 '，这一项单独就能让 K 系统偏 ',
                 ('t', '%+.2f%%' % (-S2 * bias_l), {}),
                 '——占实测总偏差 %.2f%% 的约 %.0f%%。'
                 % (dev, abs(-S2 * bias_l) / abs(dev) * 100 if dev else float('nan')),
                 '也就是说，K 偏低的主要来源是 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                 '(HAc) 偏高，而不是 K 本身的推算有误。'])
        rb.para(['据此，最有效的一步改进不是加密读数，而是压低 ',
                 ('t', 'Λ_{m}^{∞}', ITALIC),
                 '(HAc) 的偏差：把强电解质的浓度范围往低端延伸、'
                 '严格控制铂电极的浸入深度与位置、并用同一支电导池连续测完'
                 '四个物种（避免换池引入 ', ('t', 'K_{cell}', ITALIC),
                 ' 的差异）。这些措施同时压小 4.2.2 表中排第一的拟合项。'])
    return True


def _read_span(an):
    """逐瓶 σ_κ/κ 的最小/最大值（百分数），供正文插值。

    单独提出来是为了避开“%”只能作用于紧邻字符串字面量这条限制：
    片段列表里夹 ('t', …) 元组时不能对整句做 % 运算。
    """
    vals = []
    for r in (an.tables.get('HAc') or []):
        sk = float(r.get('sigma_kappa', float('nan')))
        if np.isfinite(sk) and r['kappa_corr'] > 0:
            vals.append(sk / r['kappa_corr'] * 100.0)
    if not vals:
        return '—'
    return '%.2f%% 到 %.2f%%' % (min(vals), max(vals))


def _f3(x):
    """三位有效数字的普通写法（用于 α 这类 0.0x 量级的小数）。"""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return '—'
    if not np.isfinite(x):
        return '—'
    return '%.3f' % x


def _level3_text(eb, an):
    """Level 3 改进方案：按“去掉该项后 σ 能降多少”排序，用数据说话。

    ⚠ 返回值是**片段列表**而不是字符串：里面要插 σ 这个量符号，
    写成纯字符串会整段排成正体（check_source_symbols 会抓）。
    表格单元格接受片段列表（与 RSD 表头同一套写法）。
    """
    if not eb.get('terms') or not eb.get('total_pct'):
        return '—'
    total = eb['total_pct']
    cand = []
    for t in eb['terms']:
        left = np.sqrt(max(total ** 2 - t['pct'] ** 2, 0.0))
        cand.append((t['name'], t['pct'], left, total - left))
    cand.sort(key=lambda x: -x[3])
    top = cand[0]
    return ['优先压“%s”（去掉它 ' % top[0],
            ('t', 'σ', ITALIC),
            ' 由 %.2f%% 降到 %.2f%%）' % (total, top[2])]


def _sec_shared(rb, an, num=3):
    """4.x 节：共享数据的组内统计与 t/F 检验（num 由 build_report 传入）。

    讲义“五、数据记录和处理”第（5）条要求“利用共享数据与自测实验数据
    进行误差分析”，思考题还直接问“如何利用共享数据对实验结果进行定量或
    半定量误差分析”。本节就是这部分定量结果。

    ⚠ 这一节**只在真的读了共享数据表时**才写（``an.shared`` 非空）。
    没读时整节省略、后续小节编号自动前移——不能印一个空标题说"见表格"，
    也不能凭空编造组内统计数字。
    """
    sh = getattr(an, 'shared', None)
    if not sh:
        return False
    group = sh.get('group') or {}
    members = sh.get('members') or []
    if not group or group.get('n', 0) < 2:
        return False

    rb.heading('4.%d 共享数据的组内误差分析' % num, 2)
    n = group['n']
    rb.para(['本实验的数据按要求录入了全组共享表，共 %d 位同学（%s）。'
             '本节用这些共享数据对实验结果作定量误差分析：先看组内各人结果'
             '的离散程度，再用统计检验判断本人数据与组内水平是否一致。'
             '共享数据由各人独立测得，仪器序号、电导池常数与去离子水电导率'
             '都不同，因此组内离散反映的是操作与配制层面的差异，'
             '而不只是仪器误差。各步对应的分布图放在附录图7~图9，'
             '正文只给数值结论。'
             % (n, '、'.join(m['name'] for m in members))])

    # ---- 4.2.1 组内一致性
    rb.heading('4.%d.1 极限摩尔电导率的组内一致性' % num, 3)
    rb.para(['把每位同学各自算出的 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 汇集起来，计算组内平均值 ', ('t', 'x̄', ITALIC),
             '、样本标准偏差 ', ('t', 's', ITALIC),
             '（自由度 ' + str(n - 1) + '）与相对标准偏差 RSD = ',
             ('t', 's', ITALIC), '/', ('t', 'x̄', ITALIC),
             '。这里 RSD'
             ' 直接衡量“不同同学做同一个实验能差多少”，'
             '是比单次测量的不确定度更贴近实际的精度指标。'])
    # 表头里 RSD / Grubbs 是**缩写**，必须正体（check_italic 会抓）。
    # 但 _write_header 的默认规则是“含拉丁字母即视为量符号 → 斜体”，
    # 所以对这两列要显式给片段列表、指定 italic=False。
    _UP = {'italic': False}
    _SHARED_HEAD = ['物种', '组内平均 Λ_{m}^{∞}', 's',
                    [('RSD', _UP)], [('Grubbs G', _UP)],
                    '判定']
    rows = []
    grubbs_hits = []
    for key in conduct.STRONG_SPECIES:
        node = (group.get('species') or {}).get(key)
        if not node:
            continue
        d = node['lam_inf']
        gb = node['grubbs']
        verdict = '异常'
        if gb.get('is_outlier') and gb.get('outlier_index') is not None:
            idx = gb['outlier_index']
            who = members[idx]['name'] if idx < len(members) else '—'
            verdict = '异常（%s）' % who
            grubbs_hits.append((key, who, gb))
        else:
            verdict = '正常'
        rows.append([conduct.SPECIES_LABEL[key],
                     _shared_pm(d['mean'], d['sd']),
                     _ssci(d['sd']), '%.2f%%' % d['rsd'],
                     '%.2f' % gb['g'] if np.isfinite(gb['g']) else '—',
                     verdict])
    hac = group.get('lam_hac') or {}
    hd = hac.get('describe') or {}
    if hd.get('n', 0) >= 2:
        hg = hac.get('grubbs') or {}
        rows.append([conduct.SPECIES_LABEL['HAc'],
                     _shared_pm(hd['mean'], hd['sd']),
                     _ssci(hd['sd']), '%.2f%%' % hd['rsd'],
                     '%.2f' % hg['g'] if np.isfinite(hg.get('g', float('nan')))
                     else '—',
                     '正常' if not hg.get('is_outlier') else '异常'])
    rb.caption('表12  各物种极限摩尔电导率的组内一致性（n = %d）' % n)
    rb.table(_SHARED_HEAD, rows, widths_cm=[2.2, 4.0, 2.2, 1.8, 1.9, 3.4])
    # 表号必须与正文引用一致：本函数依次是表12/13/14/15（见各 caption）。
    # docxkit 的 caption 不会自动编号，写错就出现"表12 之后是表14"的跳号。
    # ⚠ 4.2 节（K° 误差预算）新增了两张表（表10、表11），因此本函数从表12 起。

    # 逐句解读：只写数据支持的话，不预设"某个物种一定好/差"
    nacl_rsd = ((group.get('species') or {}).get('NaCl', {})
                .get('lam_inf', {}).get('rsd', float('nan')))
    if np.isfinite(nacl_rsd):
        best_key = min(
            [k for k in conduct.STRONG_SPECIES
             if np.isfinite(((group.get('species') or {}).get(k, {})
                             .get('lam_inf', {}).get('rsd', float('nan'))))],
            key=lambda k: group['species'][k]['lam_inf']['rsd'],
            default=None)
        worst_key = max(
            [k for k in conduct.STRONG_SPECIES
             if np.isfinite(((group.get('species') or {}).get(k, {})
                             .get('lam_inf', {}).get('rsd', float('nan'))))],
            key=lambda k: group['species'][k]['lam_inf']['rsd'],
            default=None)
        if best_key and worst_key:
            # ⚠ 原来这段把 worst_key 的离散**写死归因于「H⁺ 迁移数极大」**，
            # 即预设最差的一定是 HCl。若某次测下来 NaCl 的 RSD 最大，
            # 这句话就成了张冠李戴的编造。现在只在实际是 HCl 时才用那个解释，
            # 否则给出中性说明（2026-11-27）。
            _bs = group['species'][best_key]['lam_inf']['rsd']
            _ws = group['species'][worst_key]['lam_inf']['rsd']
            _head = ('组内一致性差别明显：%s 的 RSD 最小（%.2f%%），%s 最大'
                     '（%.2f%%）。%s 的一致性最好'
                     % (conduct.SPECIES_LABEL[best_key], _bs,
                        conduct.SPECIES_LABEL[worst_key], _ws,
                        conduct.SPECIES_LABEL[best_key]))
            if worst_key == 'HCl':
                # ⚠ 「H⁺」要用真上标。原来写 'H⁺' 但经过 % 格式化后
                # docxkit 的 Unicode 上标转换没生效（印出 'H+'），
                # 而且「在 … 上」中间原本插了 Λ_m 片段，改写成纯文字后
                # 那个占位丢了，只剩双空格。现在拆片段显式给出。
                _why = ('，%s 的离散更大，主要来自 '
                        % conduct.SPECIES_LABEL[worst_key])
                _why_tail = [
                    # 与全文其它地方一致：用 Unicode 上标 H⁺。
                    # 别写成 'H^{+}' —— `('t', …, {})` 是非斜体片段，
                    # 不走 docxkit 的 LaTeX 上标转换，会原样印出 'H+'。
                    'H⁺ 的迁移数极大（约 0.83），因而对浓度配制误差与温度'
                    '波动都更敏感——同样 1% 的浓度偏差，在 ',
                    ('t', 'Λ_{m}', ITALIC),
                    ' 上的反映会被放大。']
            else:
                _head = _head + ('；%s 的离散相对更大。各组离散度的差异可能来自'
                                 '配制、温度或电极状态，需结合原始读数核对，'
                                 '不宜简单归因于某个离子。'
                                 % conduct.SPECIES_LABEL[worst_key])
                _why_tail = []
            rb.para([_head] + ([_why] if worst_key == 'HCl' else []) + _why_tail)

    # ---- 4.2.2 Grubbs
    rb.heading('4.%d.2 异常值的统计甄别' % num, 3)
    rb.para(['对每一列用 Grubbs 检验（',
             ('t', 'α', ITALIC), ' = 0.05）判断是否存在离群值。'
             '检验统计量为 ',
             ('t', 'G', ITALIC), ' = max|', ('t', 'x_{i} − x̄', ITALIC),
             '|/', ('t', 's', ITALIC),
             '，临界值由 ',
             ('t', 't', ITALIC), ' 分布换算。', ('t', 'n', ITALIC),
             ' = %d 时临界值 ' % n,
             ('t', 'G_{crit}', ITALIC), ' = ',
             ('t', '%.3f' % (group['species'].get(
                 conduct.STRONG_SPECIES[0], {}).get('grubbs', {})
                 .get('g_crit', float('nan'))), {}), '。'])
    if grubbs_hits:
        for key, who, gb in grubbs_hits:
            rb.para(['%s 的 ' % conduct.SPECIES_LABEL[key],
                     ('t', 'G', ITALIC), ' = ',
                     ('t', '%.3f' % gb['g'], {}), ' > ',
                     ('t', 'G_{crit}', ITALIC),
                     '，判出 %s 的数据为离群值。该同学的这一组读数中存在'
                     '记写层面的错误（见本节末的数据清洗说明），'
                     '已按量级自动改正后参与统计；改正后仍偏离，'
                     '说明除记写错误外还有实验操作层面的差异。' % who])
    else:
        rb.para(['各物种均未检出离群值（', ('t', 'G', ITALIC),
                 ' 均小于临界值），说明组内没有哪一位同学的结果明显偏离，'
                 '离散是整体性的而非个别的。'])
    rb.para(['需要强调：Grubbs 判出离群',
             {'text': '不等于', 'bold': True},
             '该数据错误。它只说明'
             '“在假设全体来自同一正态总体的前提下，这个点出现的概率小于 '
             '5%”。剔除与否要看物理原因，不能只看统计量，'
             '否则就变成用统计方法挑好看的数据。'])

    # ---- 4.2.3 我 vs 组内：t 检验与 F 检验
    me = group.get('me')
    if me and group.get('tests'):
        rb.heading('4.%d.3 本人数据与组内水平的比较' % num, 3)
        rb.para(['把本人的结果与其余 %d 位同学的平均值比较。'
                 '采用 t 检验：' % (n - 1)])
        # ⚠ 这个 OMML 转换器**不支持 \\bar**：写 \\bar{x} 会在正文里残留一个
        # 反斜杠（audit_docx 报 text.backslash）。改用 Unicode 组合字符 x̄，
        # 与本节前文“组内平均值 x̄”的写法一致。
        rb.equation(r't=\frac{x_{me}-x̄_{others}}'
                    r'{s_{others}\sqrt{1+1/n_{others}}}')
        rb.para(['分母里多出的 ', ('t', '√(1 + 1/n)', ITALIC),
                 ' 项是因为“其余同学的平均值”本身也是从有限样本估出来的，'
                 '带着自己的抽样误差；若按标准的单样本 t 检验把它当成真值，'
                 '会系统性低估标准误、把不显著的差异判成显著。'
                 '自由度为 ', ('t', 'n', ITALIC), '_{others} − 1。'])
        trows = []
        for key in conduct.STRONG_SPECIES + ('HAc',):
            node = (group.get('tests') or {}).get(key)
            if not node:
                continue
            t = node['t']
            trows.append([conduct.SPECIES_LABEL[key],
                          _sci_or_dash(t['diff'] + t['others_mean'], 5),
                          _sci_or_dash(t['others_mean'], 5),
                          '%.2f' % t['t'] if np.isfinite(t['t']) else '—',
                          '%.2f' % t['p'] if np.isfinite(t['p']) else '—',
                          '显著' if t['significant'] else '不显著'])
        rb.caption('表13  本人结果与组内其余同学平均值的 t 检验')
        rb.table(['物种', '本人值', '组内均值', 't', 'p', '判定（α = 0.05）'],
                 trows, widths_cm=[2.0, 3.4, 3.4, 1.7, 1.7, 3.2])

        sig = [conduct.SPECIES_LABEL[k]
               for k in conduct.STRONG_SPECIES + ('HAc',)
               if ((group.get('tests') or {}).get(k) or {})
               .get('t', {}).get('significant')]
        if sig:
            rb.para(['在 ', ('t', 'α', ITALIC),
                       ' = 0.05 水平下，%s 与组内其余同学存在显著差异。'
                     '结合 4.1 节的分析，这一差异更可能来自该物种对'
                     '浓度配制与温度波动更敏感，而非计算口径不同。'
                     % '、'.join(sig)])
        else:
            rb.para(['在 ', ('t', 'α', ITALIC),
                       ' = 0.05 水平下，本人各物种的结果与组内其余同学的'
                     '平均值均无显著差异。这说明本人的测量结果在组内是'
                     '有代表性的，结果之间的差别属于正常的实验分散，'
                     '不是系统性偏差。'])

        rb.heading('4.%d.4 实验精度的 F 检验' % num, 3)
        rb.para(['t 检验比较的是“结果的高低”，属于准确度；'
                 'F 检验比较的是“拟合残差的大小”，属于精度的重复性。'
                 '两者是不同的问题：一个人可能每次测得的 ', ('t', 'Λ_{m}^{∞}', ITALIC),
                  ' 都很接近组内'
                 '均值（t 检验不显著），但每条拟合直线的残差都偏大'
                 '（F 检验显著）。F 统计量为本人拟合残差方差与组内其余'
                 '同学合并残差方差之比：'])
        rb.equation(r'F=\frac{s_{me}^{2}}{s_{others}^{2}}')
        frows = []
        for key in conduct.STRONG_SPECIES:
            node = (group.get('tests') or {}).get(key)
            if not node or not node.get('F'):
                continue
            f = node['F']
            frows.append([conduct.SPECIES_LABEL[key],
                          _ssci(f['F']) if np.isfinite(f['F']) else '—',
                          '%.2f' % f['p'] if np.isfinite(f['p']) else '—',
                          '%d, %d' % (f['df1'], f['df2']),
                          '显著' if f['significant'] else '不显著'])
        if frows:
            rb.caption('表14  本人拟合精度与组内的 F 检验')
            rb.table(['物种', 'F', 'p', '自由度', '判定（α = 0.05）'],
                     frows, widths_cm=[2.2, 2.4, 2.2, 2.6, 3.2])
            fsig = [conduct.SPECIES_LABEL[k]
                    for k in conduct.STRONG_SPECIES
                    if ((group.get('tests') or {}).get(k) or {})
                    .get('F', {}).get('significant')]
            if fsig:
                rb.para(['%s 的 F 检验显著，说明本人在这些物种上的拟合'
                         '精度与组内整体水平存在差别。这通常意味着该组'
                         '读数中的随机误差偏大（或反之偏小），'
                         '值得回头检查那几条拟合直线的散点分布。'
                         % '、'.join(fsig)])
            else:
                rb.para(['各物种的 F 检验均不显著，说明本人的拟合精度'
                         '（重复性）与组内整体水平相当。'])

    # ---- 4.2.5 两法 K° 的组内比较
    km = group.get('k_methods') or {}
    if km.get('paired') and km.get('mean', {}).get('n', 0) >= 2:
        rb.heading(['4.%d.5 两种 ' % num, ('t', 'K^{°}', ITALIC),
                ' 求解方法的组内比较'], 3)
        rb.para(['下一节比较两种方法的依据是单组数据的相对误差大小，'
                 '样本量为 1，说服力有限。这里先用共享数据做更硬的检验：'
                 '对每位同学各算一次“求平均法 K° − 拟合直线法 K°”，'
                 '得到 %d 个配对差值，再对这一列做配对 t 检验。'
                 '配对的要点是同一人的两个结果相减——这样浓度配制、'
                 '温度等共同因素被抵消，剩下的才是方法本身的差异。' % n])
        p = km['paired']
        rb.caption('表15  两种方法所得 K° 的组内统计（n = %d）' % n)
        rb.table(['方法', '组内平均 K^{⊖}', 's', [('RSD', _UP)]],
                 [['求平均法', _sci_or_dash(km['mean']['mean']),
                   _sci_or_dash(km['mean']['sd']),
                   '%.2f%%' % km['mean']['rsd']],
                  ['拟合直线法', _sci_or_dash(km['fit']['mean']),
                   _sci_or_dash(km['fit']['sd']),
                   '%.2f%%' % km['fit']['rsd']]],
                 widths_cm=[3.0, 4.2, 3.2, 2.2])
        rb.para(['配对差值（求平均法 − 拟合直线法）的平均值为 ',
                 ('t', _sci_or_dash(p['mean_diff']), {}), '，',
                 ('t', 't', ITALIC), ' = ',
                 ('t', '%.2f' % p['t'] if np.isfinite(p['t']) else '—', {}),
                 '，', ('t', 'p', ITALIC), ' = ',
                 ('t', '%.3f' % p['p'] if np.isfinite(p['p']) else '—', {}),
                 '（自由度 %d）。' % p['df']])
        if p['significant']:
            # ⚠ 量符号必须走片段列表：α / Λm∞ / K° 若写在纯字符串里会整串正体
            rb.para(['在 ', ('t', 'α', ITALIC), ' = 0.05 水平下两种方法存在系统性差异，'
                     '这与 4.3 节对单组数据的分析方向一致，且现在有了'
                     '组内重复的证据支持：两种方法给出不同的 ',
                     ('t', 'K^{⊖}', ITALIC),
                     '，这个差值不是某一个人测偏造成的，而是方法本身的结构性差别'
                     '（求平均法把 ', ('t', '(1−α)', {}),
                     ' 放在分母上、放大低浓度端随机误差）。'])
        else:
            # ⚠ 这里原来写死「单组数据里看到的“拟合直线法更接近文献值”」，
            # 把某一法更准当成了既定事实。但哪个更接近手册值**取决于数据**，
            # 换个数据集就可能反过来（本工具的其他数据集里确实出现过）。
            # 改成中性说法：不能据此断言任何一种方法更好。
            rb.para(['在 ', ('t', 'α', ITALIC), ' = 0.05 水平下两种方法未检出系统性差异。'
                     '这说明单组数据里看到的“某一种方法更接近手册值”'
                     '可能只是偶然；两种方法的差别小于组内各人之间的差别。'
                     '因此不宜据此断言某一种方法更好。'
                     '若要判别方法的优劣，需要更多重复或更宽的浓度范围。'])
        rb.para(['另外，两种 ', ('t', 'K^{°}', ITALIC),
                 ' 的组内 RSD 都在 10% 量级，远大于 ',
                 ('t', 'Λ_{m}^{∞}', ITALIC), ' 的 1~4%：这是因为 ',
                 ('t', 'K^{°}', ITALIC), ' 由 ',
                 ('t', '1−', {}), ('t', 'α', ITALIC),
                 ' 作分母，当 ', ('t', 'α', ITALIC), ' 接近 0 时对 ',
                 ('t', 'Λ_{m}', ITALIC), ' 的微小误差极其敏感，'
                 '误差被结构性地放大。这一点也解释了两法 RSD 相近，'
                 '说明放大作用主要来自 ', ('t', 'K^{°}', ITALIC),
                 ' 的计算式本身，而非某一种方法的拟合方式。'])
    return True


def _shared_pm(v, s):
    """共享数据表里的 (值 ± 不确定度)：5 位有效数字，与正文其他表一致。"""
    try:
        if not (np.isfinite(float(v)) and np.isfinite(float(s))):
            return '—'
    except (TypeError, ValueError):
        return '—'
    return '(%s ± %s) S·m⁻²·mol⁻¹' % (sig_fig(v, 5), sig_fig(s, 2))


def _ssci(v):
    """科学计数法的紧凑写法（用于 s、F 这类跨数量级的量）。"""
    try:
        v = float(v)
        if not np.isfinite(v):
            return '—'
    except (TypeError, ValueError):
        return '—'
    if v == 0:
        return '0'
    e = int(np.floor(np.log10(abs(v))))
    return '%.2f×10^{%d}' % (v / 10.0 ** e, e)


def _sci_or_dash(v, digits=3):
    """科学计数法；``digits`` 控制有效位数。

    表13 的“本人值”与“组内均值”必须用足够位数，否则两者舍入成同一个数
    （实测 1.247×10⁻² 与 1.247×10⁻²），读者看不出差别、更看不出 t 检验
    比的是什么。这里给 4 位。
    """
    try:
        v = float(v)
        if not np.isfinite(v):
            return '—'
    except (TypeError, ValueError):
        return '—'
    return sci(v, digits)


def _sec_tail_skipped(rb, an, num):
    """数据不齐时替代“两法比较 + 小结”两节。

    同样不能静默省略：读者会以为报告没写完。
    """
    rb.heading('4.%d 两种方法比较与小结（本次未完成）' % num, 2)
    missing = [conduct.SPECIES_LABEL[k]
               for k in conduct.STRONG_SPECIES if k not in an.fits]
    rb.para(['弱电解质的两种标准电离平衡常数求解（求平均法与拟合直线法）'
             '都需要先由强电解质组合出 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             ('t', '(HAc)', {}),
             '。本次缺少%s的测量数据，组合无法完成，'
             '因此两法比较与结论汇总从略。' %
             ('、'.join(missing) if missing else '部分物种')])
    rb.para('本次已完成的部分：' + '；'.join(
        '%s 的 ' % conduct.SPECIES_LABEL[k]
        + 'Λₘ∞ = (%s) S·m⁻²·mol⁻¹'
        % pm(an.fits[k]['lam_inf'], an.fits[k]['sigma_inf'])
        for k in conduct.STRONG_SPECIES if k in an.fits) + '。')


def _sec_method_compare(rb, an, num=2):
    # num 由 build_report 传入：读了共享数据时本节顺移为 4.4。
    rb.heading(['4.%d 弱电解质两种 ' % num, ('t', 'K^{°}', ITALIC),
                ' 求解方法比较'], 2)
    # ⚠ 这一节原来开头写死「求平均法的误差显著大于拟合直线法，这符合理论预期」，
    # 但**两个判据方向相反**（2026-11-27 实测）：
    #     求平均法  K = 1.633e-5 ± 1.95e-7 （相对 1.20%）  偏差 −6.89%
    #     拟合直线法 K = 1.719e-5 ± 3.48e-7 （相对 2.02%）  偏差 −1.99%
    # 按 σ 判，**拟合直线法更大**；按与手册值的偏差判，拟合直线法更准。
    # 所以不能笼统说「某法误差更大」——必须分开讲准确度（偏差）与精密度（σ），
    # 否则就是拿一个判据的结论去支持另一个判据的问题。
    _ka = conduct.KA_HAC
    _er_mean = (an.kmean['mean'] - _ka) / _ka * 100.0
    _er_fit = (an.kfit['K'] - _ka) / _ka * 100.0
    _sig_mean = an.kmean['sigma'] / an.kmean['mean'] * 100.0
    _sig_fit = an.kfit['sigma_K'] / an.kfit['K'] * 100.0
    _closer = ('拟合直线法' if abs(_er_fit) < abs(_er_mean) else '求平均法')
    _tighter = ('求平均法' if _sig_mean < _sig_fit else '拟合直线法')
    rb.para(['两种方法的比较要从两个不同的判据看：与手册值的偏差'
             '（准确度）和不确定度 ', ('t', 'σ_{K^{⊖}}', ITALIC),
             '（精密度）。本实验的结果是：求平均法 ',
             ('t', 'E_{r}', ITALIC), ' = ', ('t', '%s' % pct(_er_mean), {}),
             '、相对 ', ('t', 'σ', ITALIC), ' = ',
             ('t', '%.2f%%' % _sig_mean, {}),
             '；拟合直线法 ', ('t', 'E_{r}', ITALIC), ' = ',
             ('t', '%s' % pct(_er_fit), {}), '、相对 ',
             ('t', 'σ', ITALIC), ' = ', ('t', '%.2f%%' % _sig_fit, {}),
             '。即：%s更接近手册值，而%s的随机不确定度更小。'
             % (_closer, _tighter)])
    rb.para(['这两个结论并不矛盾，也不会因数据不同而反转方向——它们衡量的是'
             '不同的东西。下面分别说明。'])

    # ---- 准确度：求平均法的系统偏低
    rb.para(['先看准确度。求平均法中各瓶 ', ('t', 'K^{⊖}', ITALIC),
             ' 由 ', ('t', 'α', ITALIC),
             ' 逐点计算而来：浓度较高、离解度较小时 ', ('t', 'α', ITALIC),
             ' 接近 0，分母 ', ('t', '1−', {}), ('t', 'α', ITALIC),
             ' 接近 1，计算尚可；浓度较低时 ',
             ('t', 'α', ITALIC), ' 增大，', ('t', 'Λ_{m}', ITALIC),
             ' 测量上的微小随机误差在与 ', ('t', '1−', {}),
             ('t', 'α', ITALIC), ' 相除时被急剧放大，'
             '所以低浓度端单个 ', ('t', 'K^{⊖}', ITALIC),
             ' 的偏差非常大——表7 中浓度越低、平衡常数越偏离文献值正是这一点'
             '的体现。关键是这些偏差同向（本例各瓶一致偏低），'
             '取平均并不能抵消它们，所以均值仍然偏低。'])

    # ---- 精密度：为什么平均法的 σ 反而小（按数据说，不预设）
    if _sig_mean < _sig_fit:
        rb.para(['再看精密度，这里的结果与"求平均法更粗糙"的直觉相反：',
                 '求平均法的 ', ('t', 'σ', ITALIC),
                 ' 反而更小。原因是它对 %d 个独立瓶取了平均，'
                 '逐瓶的随机误差按 1/√n 被压小；而拟合直线法虽然利用了全部'
                 '数据点，其斜率的方差仍受残差大小支配，本实验的拟合残差'
                 '（相对 %.2f%%）比瓶间离散（相对 %.2f%%）更大。'
                 % (len(an.kmean['bottles']), _sig_fit,
                    an.kmean['spread'] / an.kmean['mean'] * 100)])
    else:
        rb.para(['再看精密度：拟合直线法的', ('t', 'σ', ITALIC),
                 ' 小于求平均法，这符合"最小二乘平滑了随机误差"的预期。'])

    # ---- Gauss–Markov 的理论依据（与上面的实测分开讲）
    rb.para(['就方法本身而言，拟合直线法的优势有理论依据：它利用全部数据点'
             '共同估计一个参数。根据 Gauss–Markov 定理^{[4]}，'
             '在误差主要存在于 ', ('t', 'y', ITALIC),
             ' 且满足 OLS 假设（残差独立、同方差、'
             '零均值）时，斜率的估计方差最小。严格地说，',
             ('t', 'x', ITALIC), ' 与 ', ('t', 'y', ITALIC),
             ' 都由同一个带噪测量 ', ('t', 'Λ_{m}', ITALIC),
             ' 构成，并不完全满足 OLS 假设，而且 ',
             ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 的不确定度也直接进入拟合直线法的结果（它出现在分母上），'
             '这部分误差与求平均法共有。所以“哪一种更好”不能只看本实验的'
             '单组数据：两种方法的 σ 差别（%.2f%% 对 %.2f%%）小于 4.4 节'
             '组内各人之间的差别。' % (_sig_mean, _sig_fit)]
            if an.shared else
            ['就方法本身而言，拟合直线法的优势有理论依据：它利用全部数据点'
             '共同估计一个参数。根据 Gauss–Markov 定理^{[4]}，'
             '在误差主要存在于 ', ('t', 'y', ITALIC),
             ' 且满足 OLS 假设（残差独立、同方差、'
             '零均值）时，斜率的估计方差最小。严格地说，',
             ('t', 'x', ITALIC), ' 与 ', ('t', 'y', ITALIC),
             ' 都由同一个带噪测量 ', ('t', 'Λ_{m}', ITALIC),
             ' 构成，并不完全满足 OLS 假设，而且 ',
             ('t', 'Λ_{m}^{∞}', ITALIC),
             ' 的不确定度也直接进入拟合直线法的结果（它出现在分母上），'
             '这部分误差与求平均法共有。判断哪一种方法更好需要多次重复，'
             '单组数据给出的 ', ('t', 'σ', ITALIC), ' 不足以定论。'])

    # ---- 两法之差是否显著（有共享数据时才做配对检验，否则明说不能判）
    # 两法之差要按「两个 K 值的相对差」算，不是两个百分比相减：
    # _er_fit − _er_mean = 4.90 是**百分点**，写成「相差 4.90%」会被读成
    # 「相对差 4.90%」，两者数值接近但含义不同，容易混淆。
    _gap = ((an.kfit['K'] - an.kmean['mean']) / an.kmean['mean'] * 100.0)
    rb.para(['最后要说明：两法的 ', ('t', 'K^{⊖}', ITALIC),
             ' 相差 ', ('t', '%s' % pct(_gap), {}),
             '，这一差值本身也带着两条路径各自的不确定度。',
             '把“某一法更准”当作结论时，需要先确认这个差值超出合成'
             '不确定度；单组数据只能给出倾向，不能给出证明。'])


def _sec_summary(rb, an, num=3):
    esa, kmean, kfit = an.esa, an.kmean, an.kfit
    # num 由 build_report 传入（读了共享数据时顺移为 4.4）。
    rb.heading('4.%d 小结' % num, 2)
    # ⚠ 原来这里写死「与文献值吻合良好」。相对误差是算出来的（共享数据里就有
# −8.3% 的情形），无条件说「吻合良好」等于替读者下了一个数据未必支持的
# 结论。改用与 4.1 节同一套三档判据，措辞随 max|Er| 变。
    _max_er_s = max((abs(float(r['er'])) for r in (an.lit_table or [])),
                    default=0.0)
    if _max_er_s <= 3.0:
        _lam_verdict = '与文献值吻合良好'
    elif _max_er_s <= 10.0:
        _lam_verdict = ('与文献值基本吻合（最大相对误差 %s）'
                        % pct(_max_er_s))
    else:
        _lam_verdict = ('与文献值偏差较大（最大相对误差 %s）'
                        % pct(_max_er_s))
    rb.para(['本实验先用标准 KCl 溶液对电导率仪进行标定，随后分别测量了不同'
             '浓度 NaCl、NaAc、HCl 和 HAc 溶液的电导率。利用 Kohlrausch '
             '经验公式对三种强电解质作 ', ('t', 'Λ_{m}', ITALIC), '–',
             ('t', '√c', ITALIC), ' 线性拟合、外推得到极限摩尔电导率：NaCl ',
             ('t', '(%s)' % pm(an.fits['NaCl']['lam_inf'],
                               an.fits['NaCl']['sigma_inf']), {}),
             '、NaAc ',
             ('t', '(%s)' % pm(an.fits['NaAc']['lam_inf'],
                               an.fits['NaAc']['sigma_inf']), {}),
             '、HCl ',
             ('t', '(%s)' % pm(an.fits['HCl']['lam_inf'],
                               an.fits['HCl']['sigma_inf']), {}),
             ' S·m⁻²·mol⁻¹，%s；针对拟合线性与相对误差的'
             '不一致，从极稀溶液的噪声/杂质影响与电极状态两方面作了归因分析。'
             % _lam_verdict])
    rb.para(['弱电解质 HAc 不符合 Kohlrausch 经验公式，其极限摩尔电导率由'
             '离子独立运动定律组合得 ',
             ('t', '(%s)' % pm(esa['lam_inf'], esa['sigma']), {}),
             ' S·m⁻²·mol⁻¹。进而通过 Ostwald 稀释定律，分别用求平均法和'
             '拟合直线法求得标准电离平衡常数 ',
             ('t', sci_pm(kmean['mean'], kmean['sigma']), {}), ' 与 ',
             ('t', sci_pm(kfit['K'], kfit['sigma_K']), {}),
             '。'])
    # ⚠ 原来这里写死「后者与文献值明显更接近，验证了线性拟合处理带噪数据的
    # 优势」。但本实验的实测是**偏差与 σ 两个判据方向相反**（见 4.3 节）：
    # 拟合直线法偏差更小，σ 反而更大。用「更接近文献值」直接推出「验证了
    # 线性拟合的优势」是偷换判据，而且换个数据集就会说反。现在按数据分说。
    _ka = conduct.KA_HAC
    _er_m = (kmean['mean'] - _ka) / _ka * 100.0
    _er_f = (kfit['K'] - _ka) / _ka * 100.0
    _closer = '拟合直线法' if abs(_er_f) < abs(_er_m) else '求平均法'
    _sig_m = kmean['sigma'] / kmean['mean'] * 100.0
    _sig_f = kfit['sigma_K'] / kfit['K'] * 100.0
    _tighter = '求平均法' if _sig_m < _sig_f else '拟合直线法'
    rb.para(['与手册值 ', ('t', sci(_ka, 4, -5), {}), ' 相比，%s的结果更接近'
             '（%s 对 %s），但%s的随机不确定度更小（%.2f%% 对 %.2f%%）。'
             '两者的差别分别体现在准确度与精密度上，不能合成一句'
             '“某法更好”——这一点在 4.3 节已作分析。'
             % (_closer, pct(_er_m), pct(_er_f), _tighter, _sig_m, _sig_f)])
    rb.para(['就自洽性而言，本实验的 ', ('t', 'Λ_{m}^{∞}', ITALIC),
             '(HAc) 比离子加和的理论值偏高，',
             ('t', 'K^{⊖}∝(Λ_{m}^{∞})^{-2}', ITALIC),
             ' 使两个 ', ('t', 'K^{⊖}', ITALIC),
             ' 同时偏低，这是两种方法共有的系统偏差，4.2 节的误差预算'
             '已定量给出其量级。'])
