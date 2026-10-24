# -*- coding: utf-8 -*-
"""磁化率测定 —— 计算内核。

古埃磁天平法测定固体物质的磁化率，计算摩尔磁化率，并估算未成对电子数。

实验原理
--------
1. 莫尔盐标定：χ_莫 = 9500×10⁻⁹/(T+1) × 4π (m³·kg⁻¹)
2. 样品摩尔磁化率：χ_m = χ_标 × m_标 × (Δm_样-Δm_空)/(Δm_标-Δm_空) × M_样/m_样
3. 分子磁矩：μ = 797.7 × √(χ_m × T) (μ_B)
4. 未成对电子数：n = √(797.7² × χ_m × T + 1) - 1

数据格式
--------
JSON 格式，包含空管、莫尔盐标样、CuSO₄·5H₂O、K₄Fe(CN)₆·3H₂O 及未知样的
称量数据（不同励磁电流下的质量）。
"""
import json
import math
import os

# 物理常数
MU_0 = 4 * math.pi * 1e-7  # 真空磁导率 N·A⁻²
N_A = 6.02214076e23        # 阿伏伽德罗常数 mol⁻¹
K_B = 1.380649e-23         # 玻尔兹曼常数 J·K⁻¹
MU_B = 9.274078e-24        # 玻尔磁子 J·T⁻¹

# 标准样品（莫尔盐）的磁化率公式系数
MOHR_SALT_COEFF = 9500e-9 * 4 * math.pi  # m³·kg⁻¹·K

# 物质的摩尔质量 (g·mol⁻¹)
MOLAR_MASS = {
    '莫尔盐': 392.14,      # (NH₄)₂Fe(SO₄)₂·6H₂O
    '硫酸铜': 249.68,      # CuSO₄·5H₂O
    '亚铁氰化钾': 422.39,  # K₄Fe(CN)₆·3H₂O
    '未知样': 0,            # 由用户输入
}


def mohr_salt_susceptibility(T_K):
    """计算莫尔盐的比磁化率 (m³·kg⁻¹)。

    公式：χ = 9500×10⁻⁹/(T+1) × 4π

    Parameters
    ----------
    T_K : float
        热力学温度 (K)

    Returns
    -------
    float
        比磁化率 (m³·kg⁻¹)
    """
    return MOHR_SALT_COEFF / (T_K + 1)


def mass_magnetic_susceptibility(chi_std, m_std, delta_m_sample, delta_m_std, m_sample):
    """计算样品的比磁化率 (m³·kg⁻¹)。

    公式：χ_样 = χ_标 × m_标 × (Δm_样-Δm_空)/(Δm_标-Δm_空) / m_样

    Parameters
    ----------
    chi_std : float
        标准样品的比磁化率 (m³·kg⁻¹)
    m_std : float
        标准样品的质量 (g)
    delta_m_sample : float
        样品在磁场中的质量变化 (g)
    delta_m_std : float
        标准样品在磁场中的质量变化 (g)
    m_sample : float
        样品的质量 (g)

    Returns
    -------
    float
        样品的比磁化率 (m³·kg⁻¹)
    """
    return chi_std * m_std * delta_m_sample / (delta_m_std * m_sample)


def molar_magnetic_susceptibility(chi_mass, M):
    """计算摩尔磁化率 (m³·mol⁻¹)。

    公式：χ_m = χ × M

    Parameters
    ----------
    chi_mass : float
        比磁化率 (m³·kg⁻¹)
    M : float
        摩尔质量 (g·mol⁻¹)

    Returns
    -------
    float
        摩尔磁化率 (m³·mol⁻¹)
    """
    return chi_mass * M * 1e-3  # g→kg


def magnetic_moment(chi_m, T_K):
    """计算分子磁矩 (μ_B)。

    公式：μ = 797.7 × √(χ_m × T) (μ_B)

    Parameters
    ----------
    chi_m : float
        摩尔磁化率 (m³·mol⁻¹)
    T_K : float
        热力学温度 (K)

    Returns
    -------
    float or None
        分子磁矩 (μ_B)，若 χ_m < 0 则返回 None（反磁性物质）
    """
    if chi_m < 0:
        return None  # 反磁性物质无永久磁矩
    return 797.7 * math.sqrt(chi_m * T_K)


def unpaired_electrons(chi_m, T_K):
    """估算未成对电子数。

    公式：n = √(797.7² × χ_m × T + 1) - 1

    Parameters
    ----------
    chi_m : float
        摩尔磁化率 (m³·mol⁻¹)
    T_K : float
        热力学温度 (K)

    Returns
    -------
    float or None
        未成对电子数，若 χ_m < 0 则返回 None（反磁性物质）
    """
    if chi_m < 0:
        return None  # 反磁性物质无未成对电子
    val = 797.7**2 * chi_m * T_K + 1
    if val < 0:
        return None
    return math.sqrt(val) - 1


def delta_mass(m_zero, m_field):
    """计算磁场中的质量变化。

    Parameters
    ----------
    m_zero : float
        无磁场时的质量 (g)
    m_field : float
        有磁场时的质量 (g)

    Returns
    -------
    float
        质量变化 (g)
    """
    return m_field - m_zero


def process_sample(data, T_K, sample_name, chi_std, m_std, delta_m_std):
    """处理单个样品的数据。

    Parameters
    ----------
    data : dict
        样品数据，包含 'm_zero' 和 'm_field' 键
    T_K : float
        温度 (K)
    sample_name : str
        样品名称
    chi_std : float
        标准样品的比磁化率 (m³·kg⁻¹)
    m_std : float
        标准样品的质量 (g)
    delta_m_std : float
        标准样品在磁场中的质量变化 (g)

    Returns
    -------
    dict
        包含 χ_mass, χ_m, μ, n 的结果字典
    """
    m_zero = data['m_zero']
    m_field = data['m_field']
    m_sample = m_zero  # 无磁场时的质量

    delta_m_sample = delta_mass(m_zero, m_field)

    chi_mass = mass_magnetic_susceptibility(
        chi_std, m_std, delta_m_sample, delta_m_std, m_sample
    )

    M = MOLAR_MASS.get(sample_name, 0)
    if M > 0:
        chi_m = molar_magnetic_susceptibility(chi_mass, M)
        mu = magnetic_moment(chi_m, T_K)
        n = unpaired_electrons(chi_m, T_K)
    else:
        chi_m = None
        mu = None
        n = None

    return {
        'name': sample_name,
        'm_sample': m_sample,
        'delta_m': delta_m_sample,
        'chi_mass': chi_mass,
        'chi_m': chi_m,
        'mu': mu,
        'n': n,
    }


def process_all(data_dict):
    """处理全部样品数据。

    Parameters
    ----------
    data_dict : dict
        完整的实验数据，包含温度、空管、各样品数据

    Returns
    -------
    dict
        包含所有计算结果的字典
    """
    T_C = data_dict['temperature_C']
    T_K = T_C + 273.15

    # 莫尔盐标样的比磁化率
    chi_std = mohr_salt_susceptibility(T_K)

    # 空管数据
    tube = data_dict['tube']
    m_tube_zero = tube['m_zero']
    m_tube_field = tube['m_field']
    delta_m_tube = delta_mass(m_tube_zero, m_tube_field)

    # 莫尔盐标样
    mohr = data_dict['mohr_salt']
    m_mohr_zero = mohr['m_zero']
    m_mohr_field = mohr['m_field']
    delta_m_mohr = delta_mass(m_mohr_zero, m_mohr_field)

    # 扣除空管后的标样质量变化
    delta_m_std = delta_m_mohr - delta_m_tube
    m_std = m_mohr_zero - m_tube_zero  # 标样的净质量

    results = {
        'temperature_C': T_C,
        'temperature_K': T_K,
        'chi_std': chi_std,
        'tube': {
            'm_zero': m_tube_zero,
            'm_field': m_tube_field,
            'delta_m': delta_m_tube,
        },
        'mohr_salt': {
            'm_zero': m_mohr_zero,
            'm_field': m_mohr_field,
            'delta_m': delta_m_mohr,
            'delta_m_corrected': delta_m_std,
            'm_net': m_std,
        },
        'samples': {},
    }

    # 处理各个样品
    for sample_name in ['硫酸铜', '亚铁氰化钾', '未知样']:
        if sample_name in data_dict:
            sample_data = data_dict[sample_name]
            result = process_sample(
                sample_data, T_K, sample_name, chi_std, m_std, delta_m_std
            )
            results['samples'][sample_name] = result

    return results


def sample_data():
    """返回示例数据（2025 年参照数据）。

    Returns
    -------
    dict
        示例实验数据
    """
    return {
        'temperature_C': 22.5,
        'tube': {
            'm_zero': 18.2345,
            'm_field': 18.2340,
        },
        'mohr_salt': {
            'm_zero': 24.5678,
            'm_field': 24.5890,
        },
        '硫酸铜': {
            'm_zero': 23.4567,
            'm_field': 23.4612,
        },
        '亚铁氰化钾': {
            'm_zero': 22.3456,
            'm_field': 22.3450,
        },
        '未知样': {
            'm_zero': 21.2345,
            'm_field': 21.2389,
        },
    }


if __name__ == '__main__':
    # 自检
    data = sample_data()
    results = process_all(data)

    print(f"温度: {results['temperature_C']}°C = {results['temperature_K']:.2f} K")
    print(f"莫尔盐比磁化率: {results['chi_std']:.3e} m³·kg⁻¹")
    print()

    for name, sample in results['samples'].items():
        print(f"{name}:")
        print(f"  质量: {sample['m_sample']:.4f} g")
        print(f"  Δm: {sample['delta_m']:.4f} g")
        print(f"  χ_mass: {sample['chi_mass']:.3e} m³·kg⁻¹")
        if sample['chi_m'] is not None:
            print(f"  χ_m: {sample['chi_m']:.3e} m³·mol⁻¹")
            print(f"  μ: {sample['mu']:.3f} μ_B")
            print(f"  n: {sample['n']:.2f}")
        print()
