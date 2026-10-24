# -*- coding: utf-8 -*-
"""磁化率测定 —— 绘图模块。

生成实验报告所需的图表：
1. 各样品摩尔磁化率柱状图
2. 分子磁矩对比图
"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 中文字体设置
rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei']
rcParams['axes.unicode_minus'] = False


def plot_molar_susceptibility(chart_data, save_path, title='各样品摩尔磁化率对比'):
    """绘制摩尔磁化率柱状图。

    Parameters
    ----------
    chart_data : list
        图表数据，每项包含 name, chi_m, mu, n
    save_path : str
        图片保存路径
    title : str
        图标题
    """
    if not chart_data:
        return

    names = [d['name'] for d in chart_data]
    chi_m_values = [d['chi_m'] * 1e6 for d in chart_data]  # 转换为 10⁻⁶ m³·mol⁻¹

    fig, ax = plt.subplots(figsize=(8, 6))

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
    bars = ax.bar(names, chi_m_values, color=colors[:len(names)])

    ax.set_xlabel('样品', fontsize=12)
    ax.set_ylabel('摩尔磁化率 χ_m / (10⁻⁶ m³·mol⁻¹)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')

    # 在柱子上方添加数值标签
    for bar, val in zip(bars, chi_m_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.2f}',
                ha='center', va='bottom', fontsize=10)

    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(save_path, dpi=600, bbox_inches='tight')
    plt.close()


def plot_magnetic_moment(chart_data, save_path, title='各样品分子磁矩对比'):
    """绘制分子磁矩柱状图。

    Parameters
    ----------
    chart_data : list
        图表数据
    save_path : str
        图片保存路径
    title : str
        图标题
    """
    if not chart_data:
        return

    # 过滤掉 mu 为 None 的数据点
    valid_data = [d for d in chart_data if d.get('mu') is not None]
    if not valid_data:
        return

    names = [d['name'] for d in valid_data]
    mu_values = [d['mu'] for d in valid_data]

    fig, ax = plt.subplots(figsize=(8, 6))

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
    bars = ax.bar(names, mu_values, color=colors[:len(names)])

    ax.set_xlabel('样品', fontsize=12)
    ax.set_ylabel('分子磁矩 μ / μ_B', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')

    # 在柱子上方添加数值标签
    for bar, val in zip(bars, mu_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.3f}',
                ha='center', va='bottom', fontsize=10)

    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(save_path, dpi=600, bbox_inches='tight')
    plt.close()


def plot_unpaired_electrons(chart_data, save_path, title='各样品未成对电子数'):
    """绘制未成对电子数柱状图。

    Parameters
    ----------
    chart_data : list
        图表数据
    save_path : str
        图片保存路径
    title : str
        图标题
    """
    if not chart_data:
        return

    # 过滤掉 n 为 None 的数据点
    valid_data = [d for d in chart_data if d.get('n') is not None]
    if not valid_data:
        return

    names = [d['name'] for d in valid_data]
    n_values = [d['n'] for d in valid_data]

    fig, ax = plt.subplots(figsize=(8, 6))

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
    bars = ax.bar(names, n_values, color=colors[:len(names)])

    ax.set_xlabel('样品', fontsize=12)
    ax.set_ylabel('未成对电子数 n', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')

    # 在柱子上方添加数值标签
    for bar, val in zip(bars, n_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.2f}',
                ha='center', va='bottom', fontsize=10)

    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(save_path, dpi=600, bbox_inches='tight')
    plt.close()


def generate_all_plots(chart_data, save_dir):
    """生成全部图表。

    Parameters
    ----------
    chart_data : list
        图表数据
    save_dir : str
        保存目录

    Returns
    -------
    dict
        各图表的文件路径
    """
    os.makedirs(save_dir, exist_ok=True)

    paths = {}

    # 摩尔磁化率柱状图
    paths['chi_m'] = os.path.join(save_dir, 'chi_m_comparison.png')
    plot_molar_susceptibility(chart_data, paths['chi_m'])

    # 分子磁矩柱状图
    paths['mu'] = os.path.join(save_dir, 'magnetic_moment.png')
    plot_magnetic_moment(chart_data, paths['mu'])

    # 未成对电子数柱状图
    paths['n'] = os.path.join(save_dir, 'unpaired_electrons.png')
    plot_unpaired_electrons(chart_data, paths['n'])

    return paths
