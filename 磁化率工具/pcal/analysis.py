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
    })

    # 莫尔盐
    table_data.append({
        'name': '莫尔盐',
        'm_zero': results['mohr_salt']['m_zero'],
        'm_field': results['mohr_salt']['m_field'],
        'delta_m': results['mohr_salt']['delta_m'],
        'delta_m_corrected': results['mohr_salt']['delta_m_corrected'],
        'm_net': results['mohr_salt']['m_net'],
    })

    # 各样品
    for name, sample in results['samples'].items():
        table_data.append({
            'name': name,
            'm_zero': sample['m_zero'] if 'm_zero' in sample else sample['m_sample'],
            'm_field': sample['m_field'] if 'm_field' in sample else None,
            'delta_m': sample['delta_m'],
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
