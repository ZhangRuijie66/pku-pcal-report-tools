# -*- coding: utf-8 -*-
"""把表面吸附的分析结果导出成 xlsx / csv 数据表。

xlsx：多工作表——说明 / 结果 / 最大气泡法 / 吊片法 / 零点与纯水 / 浓度修正；
csv ：单张长表，两种方法的原始读数与 γ 摊在同一组列里，方便直接透视、排序。

导出只读，不回写 data/表面吸附数据.json（报告导出才会回写，见 SKILL §21）。
"""
from __future__ import annotations

import csv
import math
import os

AXIS_LABEL = {'lg': 'lg c', 'ln': 'ln c'}


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(v, nd=4):
    """普通数值：保留 nd 位小数；NaN/None → 空串（Excel 里留白，不造假数据）。"""
    if not _isnum(v):
        return ''
    return round(float(v), nd)


def _sci(v, digits=6):
    """小量（Γ∞ 量级 1e-6）：保留 6 位有效数字，以浮点写进单元格。"""
    if not _isnum(v):
        return ''
    return float('%.*e' % (digits - 1, v))


def _pm(x, u, n=1):
    """x ± u，按不确定度首位有效数字定位（与报告 pm() 同口径，不依赖 docxkit）。"""
    if not _isnum(x):
        return ''
    if not _isnum(u) or u == 0:
        return '%.*g' % (n + 2, x)
    import decimal
    exp = decimal.Decimal(repr(abs(u))).adjusted()
    q = decimal.Decimal(1).scaleb(exp - (n - 1))
    xx = decimal.Decimal(repr(x)).quantize(q, rounding=decimal.ROUND_HALF_EVEN)
    uu = decimal.Decimal(repr(u)).quantize(q, rounding=decimal.ROUND_HALF_EVEN)
    dec = max(0, -q.as_tuple().exponent)
    return '%.*f ± %.*f' % (dec, xx, dec, uu)


def _fit_text(m, axis):
    f = m.get('fit')
    if not f:
        return ''
    fn = 'lg' if axis == 'lg' else 'ln'
    return ('γ = (%s) %s c + (%s)'
            % (_pm(f['slope'] * 1e3, f['sigma_slope'] * 1e3), fn,
               _pm(f['intercept'] * 1e3, f['sigma_intercept'] * 1e3)))


def _side_values(stats, n=3):
    vals = []
    raw = (stats or {}).get('values')
    if raw is not None:                       # numpy 数组不能用 or 判断真假
        vals = [float(v) for v in list(raw)[:n]]
    return vals + [''] * (n - len(vals))


# ---------------------------------------------------------------- 表结构
def _sheet_info(an):
    cfg = an.get('config') or {}
    b = an['bubble']
    hi = b.get('height') or {}
    mode = hi.get('mode') or 'both'
    mode_txt = {'both': '两侧都读', 'left': '只读左侧', 'right': '只读右侧'}.get(mode, mode)
    rows = [['实验', cfg.get('report_title') or '溶液表面吸附的测定'],
            ['姓名', cfg.get('student_name') or ''],
            ['学号', cfg.get('student_id') or ''],
            ['组别 / 组号', '%s / %s' % (cfg.get('group') or '', cfg.get('group_no') or '')],
            ['实验日期', cfg.get('date') or ''],
            ['气泡法温度 /℃', _num(b['temperature'], 2)],
            ['γ_w /(mN·m⁻¹)', _num(b['gamma_water'], 3)],
            ['单次读数 σ_h /cm', _num(b['sigma_read'], 3)],
            ['液柱读数方式', mode_txt],
            ['两臂高度总和 S /cm', _num(hi.get('sum'), 3)],
            ['S 的来源', {'manual': '手填', 'estimated': '由两侧读数估计'}.get(
                hi.get('source'), '未使用')],
            ['零点差 Δh₀ /cm', _num(b['zero']['dh'], 4)],
            ['纯水 Δh_w /cm', _num(b['water']['dh'], 4)],
            ['压力计零点', '扣除' if b.get('zero_correction') else '不扣除'],
            ['作图横轴', AXIS_LABEL.get(an.get('axis'), an.get('axis') or '')],
            ['导出时间', __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')]]
    return '说明', ['项目', '值'], rows


def _sheet_result(an):
    axis = an.get('axis') or 'lg'
    rows = []
    for m in (an['bubble'], an['plate']):
        rows.append([m['label'], _num(m['temperature'], 2),
                     _num(m.get('gamma_water'), 3), _fit_text(m, axis),
                     _num((m.get('fit') or {}).get('r2'), 5),
                     (m.get('fit') or {}).get('n', ''),
                     _sci(m['gamma_inf']), _sci(m['sigma_gamma_inf']),
                     _num(m['q'], 5), _num(m['sigma_q'], 5)])
    headers = ['方法', 'T /℃', 'γ_w /(mN·m⁻¹)\n（仅气泡法用）', '拟合式（γ /(mN·m⁻¹)）', 'R²',
               '拟合点数', 'Γ∞ /(mol·m⁻²)', 'σ(Γ∞)', 'q /nm²', 'σ(q)']
    cmp_ = an.get('comparison') or {}
    if cmp_:
        rows.append([])
        rows.append(['两法对比', 'ΔΓ∞ /(mol·m⁻²)', _sci(cmp_.get('d_gamma')), '',
                     'Γ∞ 相对偏差 /%', _num(cmp_.get('rel_gamma'), 2)])
        rows.append(['', 'Δq /nm²', _num(cmp_.get('d_q'), 5), '',
                     'q 相对偏差 /%', _num(cmp_.get('rel_q'), 2)])
    return '结果', headers, rows


def _sheet_bubble(an):
    b = an['bubble']
    headers = ['c /(mol·dm⁻³)', 'h_l1 /cm', 'h_l2 /cm', 'h_l3 /cm',
               'h_r1 /cm', 'h_r2 /cm', 'h_r3 /cm',
               'h_l 均值 /cm', 'h_r 均值 /cm', 'Δh /cm', 'σ(Δh) /cm',
               'γ /(mN·m⁻¹)', 'σ(γ) /(mN·m⁻¹)', '参与拟合', 'h_r 来源']
    rows = []
    for r in b['rows']:
        rows.append([_num(r['c'], 6)]
                    + [_num(v, 3) for v in _side_values(r['left'])]
                    + [_num(v, 3) for v in _side_values(r['right'])]
                    + [_num(r['left']['mean'], 3), _num(r['right']['mean'], 3),
                       _num(r['dh'], 3), _num(r['sigma_dh'], 4),
                       _num(r['gamma'], 2), _num(r['sigma_gamma'], 2),
                       '是' if r['fit'] else '否',
                       '按 S 换算' if r.get('derived') else '实测'])
    return '最大气泡法', headers, rows


def _sheet_trio(an):
    b = an['bubble']
    headers = ['项目', 'h_l1 /cm', 'h_l2 /cm', 'h_l3 /cm',
               'h_r1 /cm', 'h_r2 /cm', 'h_r3 /cm',
               'h_l 均值 /cm', 'h_r 均值 /cm', 'Δh /cm', 'σ(Δh) /cm']
    rows = []
    for label, key, dh in (('压力计零点', 'zero', 'dh'), ('纯水', 'water', 'dh')):
        obj = b[key]
        rows.append([label]
                    + [_num(v, 3) for v in _side_values(obj['left'])]
                    + [_num(v, 3) for v in _side_values(obj['right'])]
                    + [_num(obj['left']['mean'], 3), _num(obj['right']['mean'], 3),
                       _num(obj[dh], 3), _num(obj['sigma_dh'], 4)])
    return '零点与纯水', headers, rows


def _sheet_plate(an):
    p = an['plate']
    headers = ['c /(mol·dm⁻³)', 'γ1 /(mN·m⁻¹)', 'γ2 /(mN·m⁻¹)', 'γ3 /(mN·m⁻¹)',
               'γ 均值 /(mN·m⁻¹)', 'σ(γ)', '参与拟合']
    rows = []
    for r in p['rows']:
        rows.append([_num(r['c'], 6)]
                    + [_num(v, 2) for v in _side_values(r['stats'])]
                    + [_num(r['gamma'], 2), _num(r['sigma_gamma'], 3),
                       '是' if r['fit'] else '否'])
    return '吊片法', headers, rows


def _sheet_qc(an):
    axis = an.get('axis') or 'lg'
    headers = ['方法', 'c /(mol·dm⁻³)', '%s' % AXIS_LABEL.get(axis, axis),
               'q_c /nm²', 'σ(q_c) /nm²', '相对偏差 /%']
    rows = []
    for m in (an['bubble'], an['plate']):
        for r in m.get('qc_rows') or []:
            x = math.log10(r['c']) if axis == 'lg' else math.log(r['c'])
            rows.append([m['label'], _num(r['c'], 6), _num(x, 5),
                         _num(r.get('qc'), 4), _num(r.get('sigma'), 4),
                         _num(r.get('rel'), 2)])
    return '浓度修正', headers, rows


def tables(an):
    """→ [(sheet 名, 表头, 行)]，顺序即工作表顺序。"""
    return [_sheet_info(an), _sheet_result(an), _sheet_bubble(an),
            _sheet_plate(an), _sheet_trio(an), _sheet_qc(an)]


# ---------------------------------------------------------------- 写文件
_XLSX_WIDTH = {}


def _style_sheet(ws, headers, widths=None):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin = Side(style='thin', color='D0D5DD')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill('solid', fgColor='F2F4F7')
    for j, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=j)
        cell.font = Font(bold=True, size=10.5)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal='center', vertical='center',
                                   wrap_text=True)
        cell.border = border
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row,
                            max_col=len(headers)):
        for cell in row:
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = border
    for j, h in enumerate(headers, start=1):
        width = max(9, min(22, len(str(h)) * 1.9))
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = width
    ws.freeze_panes = 'A2'
    ws.row_dimensions[1].height = 30


def write_xlsx(path, an):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, headers, rows in tables(an):
        ws = wb.create_sheet(title=name[:31])
        ws.append(headers)
        for r in rows:
            ws.append(r)
        _style_sheet(ws, headers)
        if name == '结果':                     # Γ∞ 用科学计数显示
            for row in ws.iter_rows(min_row=2, max_col=len(headers)):
                for col in (7, 8):
                    cell = row[col - 1]
                    if isinstance(cell.value, float) and abs(cell.value) < 1e-4:
                        cell.number_format = '0.000E+00'
        elif name == '说明':
            ws.column_dimensions['A'].width = 22
            ws.column_dimensions['B'].width = 28
    wb.save(path)
    return path


CSV_BASE = ['方法', 'c /(mol·dm⁻³)', '%s', 'h_l 均值 /cm', 'h_r 均值 /cm',
            'Δh /cm', 'σ(Δh) /cm', 'γ /(mN·m⁻¹)', 'σ(γ) /(mN·m⁻¹)',
            '参与拟合', '备注']


def write_csv(path, an):
    """两种方法摊成一张长表：h_* 列对吊片法留空，方便在 Excel 里筛选/透视。"""
    axis = an.get('axis') or 'lg'
    headers = [h % AXIS_LABEL.get(axis, 'lg c') if '%s' in h else h for h in CSV_BASE]
    with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for r in an['bubble']['rows']:
            x = math.log10(r['c']) if axis == 'lg' else math.log(r['c'])
            w.writerow(['最大气泡法', _num(r['c'], 6), _num(x, 5),
                        _num(r['left']['mean'], 3), _num(r['right']['mean'], 3),
                        _num(r['dh'], 3), _num(r['sigma_dh'], 4),
                        _num(r['gamma'], 2), _num(r['sigma_gamma'], 2),
                        '是' if r['fit'] else '否',
                        'h_r 按 S 换算' if r.get('derived') else ''])
        for r in an['plate']['rows']:
            x = math.log10(r['c']) if axis == 'lg' else math.log(r['c'])
            w.writerow(['吊片法', _num(r['c'], 6), _num(x, 5), '', '', '', '',
                        _num(r['gamma'], 2), _num(r['sigma_gamma'], 2),
                        '是' if r['fit'] else '否', ''])
    return path


def write(an, path, fmt):
    fmt = (fmt or 'xlsx').lower()
    if fmt == 'csv':
        return write_csv(path, an)
    return write_xlsx(path, an)


def suggest_path(out_dir, stem, fmt='xlsx'):
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, '%s-数据.%s' % (stem, 'csv' if fmt == 'csv' else 'xlsx'))
