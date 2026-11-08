# -*- coding: utf-8 -*-
"""磁化率测定 —— 分析流程。

将计算内核的结果组织成报告所需的结构。
"""
import os
from . import magnetic


def run_analysis(data_dict):
    """运行完整的数据分析流程。

    Parameters
    ----------
    data_dict : dict
        实验数据

    Returns
    -------
    dict
        分析结果，包含表格数据、图表数据等
    """
    results = magnetic.process_all(data_dict)

    # 组织表格数据
    table_data = []

    # 空管
    table_data.append({
        'name': '空管',
        'm_zero': results['tube']['m_zero'],
        'm_field': results['tube']['m_field'],
        'delta_m': results['tube']['delta_m'],
        'delta_m_gross': results['tube']['delta_m'],
    })

    # 莫尔盐
    table_data.append({
        'name': '莫尔盐',
        'm_zero': results['mohr_salt']['m_zero'],
        'm_field': results['mohr_salt']['m_field'],
        'delta_m': results['mohr_salt']['delta_m'],
        'delta_m_gross': results['mohr_salt']['delta_m'],
        'delta_m_corrected': results['mohr_salt']['delta_m_corrected'],
        'm_net': results['mohr_salt']['m_net'],
    })

    # 各样品
    #
    # ⚠ 口径：表 1 必须整张表都用**毛重**（含样品管），否则同一张表里空管/莫尔盐
    # 是毛重、样品是净质量，两种口径混排，读者用 m − m₀ 一减就对不上 Δm。
    # `process_sample` 只回传净质量 m_sample（= 毛重 − 空管），拿不到毛重；
    # 毛重就在原始数据 data_dict[name] 里，直接从那里取，不去改计算内核。
    for name, sample in results['samples'].items():
        raw = data_dict.get(name) or {}
        m_zero = raw.get('m_zero')
        m_field = raw.get('m_field')
        # 毛重质量变化 Δm = m − m₀（扣空管之前的值，也就是参照报告的 Δm_I）
        delta_m_gross = (m_field - m_zero) if (m_zero is not None
                                              and m_field is not None) else None
        table_data.append({
            'name': name,
            'm_zero': m_zero,
            'm_field': m_field,
            'delta_m_gross': delta_m_gross,
            # delta_m 保留「扣空管后」的口径：它是 χ 公式里真正用到的量
            'delta_m': sample['delta_m'],
            'm_sample': sample['m_sample'],
            'chi_mass': sample['chi_mass'],
            'chi_m': sample['chi_m'],
            'mu': sample['mu'],
            'n': sample['n'],
        })

    # 图表数据（柱状图：各样品的摩尔磁化率）
    chart_data = []
    for name, sample in results['samples'].items():
        if sample['chi_m'] is not None:
            chart_data.append({
                'name': name,
                'chi_m': sample['chi_m'],
                'mu': sample['mu'],
                'n': sample['n'],
            })

    return {
        'temperature_C': results['temperature_C'],
        'temperature_K': results['temperature_K'],
        'chi_std': results['chi_std'],
        'table': table_data,
        'chart': chart_data,
        'samples': results['samples'],
    }


def format_results(results):
    """格式化结果为字符串（用于界面显示）。

    Parameters
    ----------
    results : dict
        分析结果

    Returns
    -------
    str
        格式化的字符串
    """
    lines = []
    lines.append(f"温度: {results['temperature_C']:.1f}°C = {results['temperature_K']:.2f} K")
    lines.append(f"莫尔盐比磁化率: {results['chi_std']:.3e} m³·kg⁻¹")
    lines.append("")

    for name, sample in results['samples'].items():
        lines.append(f"{name}:")
        lines.append(f"  比磁化率 χ: {sample['chi_mass']:.3e} m³·kg⁻¹")
        if sample['chi_m'] is not None:
            lines.append(f"  摩尔磁化率 χ_m: {sample['chi_m']:.3e} m³·mol⁻¹")
            if sample['mu'] is not None:
                lines.append(f"  分子磁矩 μ: {sample['mu']:.3f} μ_B")
            else:
                lines.append("  分子磁矩 μ: —（反磁性）")
            if sample['n'] is not None:
                lines.append(f"  未成对电子数 n: {sample['n']:.2f}")
            else:
                lines.append("  未成对电子数 n: 0（反磁性）")
        lines.append("")

    return "\n".join(lines)
