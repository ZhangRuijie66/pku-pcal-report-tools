# -*- coding: utf-8 -*-
"""配置模型：把界面上的输入整理成一次计算/出报告所需的完整参数。"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import combustion as cb

# ---------------------------------------------------------------- 样品预设
# main=B: 待测样品主成分（用于燃烧方程式与分子量）；cal: 标准物质
SUBSTANCES = {
    'sucrose': {
        'label': '蔗糖 C12H22O11', 'tex_label': '蔗糖 C_{12}H_{22}O_{11}',
        'formula': 'C12H22O11', 'Mr': 342.296,
        'equation': r'C_{12}H_{22}O_{11}(s)+12O_{2}(g)=12CO_{2}(g)+11H_{2}O(l)',
        'dn': 0.0,
        'literature_kJ_per_mol': 5643.0,
        'literature_note': '蔗糖标准摩尔燃烧焓约 −5643 kJ·mol⁻¹（CRC Handbook）',
    },
    'glucose': {
        'label': '葡萄糖 C6H12O6', 'tex_label': '葡萄糖 C_{6}H_{12}O_{6}',
        'formula': 'C6H12O6', 'Mr': 180.156,
        'equation': r'C_{6}H_{12}O_{6}(s)+6O_{2}(g)=6CO_{2}(g)+6H_{2}O(l)',
        'dn': 0.0,
        'literature_kJ_per_mol': 2801.0,
        'literature_note': '葡萄糖标准摩尔燃烧焓约 −2801 kJ·mol⁻¹（CRC Handbook）',
    },
    'fructose': {
        'label': '果糖 C6H12O6', 'tex_label': '果糖 C_{6}H_{12}O_{6}',
        'formula': 'C6H12O6', 'Mr': 180.156,
        'equation': r'C_{6}H_{12}O_{6}(s)+6O_{2}(g)=6CO_{2}(g)+6H_{2}O(l)',
        'dn': 0.0,
        'literature_kJ_per_mol': 2812.0,
        'literature_note': '果糖标准摩尔燃烧焓约 −2812 kJ·mol⁻¹（CRC Handbook）',
    },
    'lard': {
        'label': '奶片（糖/脂肪/蛋白混合物）', 'tex_label': '奶片（糖/脂肪/蛋白混合物）',
        'formula': None, 'Mr': None,
        'equation': None, 'dn': None,
        'literature_kJ_per_mol': None, 'literature_note': '',
    },
    'custom': {
        'label': '自定义', 'tex_label': '自定义', 'formula': None, 'Mr': None,
        'equation': None, 'dn': None,
        'literature_kJ_per_mol': None, 'literature_note': '',
    },
}


def default_config():
    return {
        # 报告封面
        'student_name': '', 'student_id': '', 'group': '', 'group_no': '',
        'date': '', 'pressure_kPa': None,
        # 实验条件
        'water_volume_mL': 3000.0,
        # 温度用摄氏度输入（沿用实验记录的写法），计算时内部换算成 K。
        # None -> 取数据文件头里的 room_temperature(K)
        'temperature_C': None,
        'force_temperature': False,     # True -> 全部轮次都用界面上的室温
        'water_density': None,          # None -> 按温度查表
        'water_capacity': None,
        'cotton_heat': cb.Q_COTTON,
        'nickel_heat': cb.Q_NICKEL,
        'benzoic_enthalpy': cb.BENZOIC_ENTHALPY,
        # 不确定度
        'e_balance': 0.0002,
        'e_temperature': 0.002,
        # 舍入
        'round_constant_to': 1,
        'round_qv_to': 1,
        # 自动寻点
        # std_limit=0.02：课程软件 main.py 内置的是 0.005，但对本套“升温缓慢、
        # 基线有漂移”的数据，0.005 会把基线漂移误判成平台结束，把拟合区间放到
        # 正在上升的曲线上；0.02 才能取到真正平直的两段平台。
        'std_limit': 0.02,
        'time_lower_limit': 30.0,
        'time_upper_limit': 40.0,
        'dx': 0.1,
        'point_prefer': 'software',   # 'software' 复刻课程软件；'rise' 升温段法；'anchor' 锚点法
        # 上次用过的数据文件夹（换机器/换目录后也能记住，省得每次重找）
        'data_dir': None,
        # 各轮次
        'rounds': [],
    }


# 会被记住（写进设置文件、下次打开自动填回）的字段。
# 只保存“每次实验都要重新填、且与具体数据文件无关”的内容。
PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'pressure_kPa', 'water_volume_mL', 'temperature_C',
    'water_density', 'water_capacity',
    'cotton_heat', 'nickel_heat', 'benzoic_enthalpy',
    'e_balance', 'e_temperature', 'std_limit', 'point_prefer',
    'force_temperature', 'data_dir',
)


def default_config_with_saved(saved):
    """出厂默认值叠加设置文件里记住的字段。"""
    cfg = default_config()
    if not saved:
        return cfg
    for k in PERSIST_KEYS:
        if k in saved and saved[k] not in (None, ''):
            cfg[k] = saved[k]
    # 兼容早期只写了 temperature_K 的设置文件
    if saved.get('temperature_C') is None and saved.get('temperature_K') is not None:
        cfg['temperature_C'] = round(float(saved['temperature_K']) - 273.15, 2)
    return cfg


def setpoint_to_kelvin(celsius_or_none):
    """摄氏 -> 开尔文；None 原样返回。"""
    if celsius_or_none is None or celsius_or_none == '':
        return None
    return float(celsius_or_none) + 273.15


def default_round(index):
    return {
        'index': index,
        'enabled': True,
        'role': 'sample',            # 'standard' | 'sample'
        'name': '样品%d' % index,
        'substance': 'sucrose',
        'file': None,
        'params': {},
        'points': None,              # [Start1, End1, Start2, End2]
        'sample_mass': None,         # 覆盖用；None 表示按 可燃物+棉线 - 棉线 计算
        'note': '',
    }


def _num(v, default=None):
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Analysis:
    """一次完整的燃烧热数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config)
        self.datasets = {}          # key -> CombustionData
        self.rounds = []            # 结果字典列表
        self.standard = None
        self.W = None               # 量热计常数 J/K
        self.sigma_W = None
        self.per_round_state = {}

    # ------------------------------------------------------------ 载入
    def load(self, sources):
        """sources: {key: (按需) 由服务器读入的 csv 文本}"""
        keyed = {}
        for r in self.cfg['rounds']:
            f = r.get('file')
            if not f:
                continue
            keyed[f] = None
        return keyed

    # ------------------------------------------------------------ 计算
    def run(self, loaders):
        """
        loaders: dict filename -> CombustionData
        返回 self.rounds（含每轮的雷诺校正、拟合、能量项）
        """
        cfg = self.cfg
        n = len(cfg['rounds'])
        if n < 2:
            raise ValueError('至少需要两轮数据：一轮标准物质（苯甲酸）+ 一轮待测样品。')

        std_i = next((i for i, r in enumerate(cfg['rounds'])
                      if r.get('enabled', True) and r.get('role') == 'standard'), None)
        if std_i is None:
            raise ValueError('请把其中一轮标记为“标准物质（苯甲酸）”，用于标定量热计常数。')
        self.std_index = std_i

        # 界面上的温度是摄氏度；内部一律用 K
        T = setpoint_to_kelvin(_num(cfg.get('temperature_C')))
        if T is None:
            T = _num(cfg.get('temperature_K'))      # 兼容旧配置
        rho = _num(cfg.get('water_density'))
        cw = _num(cfg.get('water_capacity'))
        V = _num(cfg.get('water_volume_mL'), 3000.0)
        cotton_heat = _num(cfg.get('cotton_heat'), cb.Q_COTTON)
        nickel_heat = _num(cfg.get('nickel_heat'), cb.Q_NICKEL)
        benzoic_enthalpy = _num(cfg.get('benzoic_enthalpy'), cb.BENZOIC_ENTHALPY)
        e_b = _num(cfg.get('e_balance'), 0.0002)
        e_t = _num(cfg.get('e_temperature'), 0.002)
        sigma_dT = 2.0 * e_t / cb.SQRT3
        sigma_m_diff = np.sqrt(2.0) * e_b / cb.SQRT3
        sigma_m_single = e_b / cb.SQRT3

        rounds = []
        for i, r in enumerate(cfg['rounds']):
            if not r.get('enabled', True):
                continue
            key = r.get('file')
            data = loaders.get(key)
            if data is None:
                raise ValueError('第 %d 轮数据文件未载入：%s' % (i + 1, key))
            params = dict(data.params)
            params.update(r.get('params') or {})
            # 允许界面覆盖文件头里的参数
            vol = _num(params.get('water_volume(mL)'))
            water_volume = vol if vol else V
            # 温度来源：界面统一温度 > 数据文件头里的室温 > 默认 298.15 K
            temp_source = ''
            Ti = None
            if cfg.get('force_temperature') and T is not None:
                Ti = T
                temp_source = '界面统一室温'
            if Ti is None:
                Ti = _num(params.get('room_temperature(K)'))
                if Ti is not None:
                    temp_source = '数据文件中的室温'
            if Ti is None:
                Ti = T if T is not None else 298.15
                temp_source = '界面室温' if T is not None else '默认 298.15 K'
            rho_i = rho if rho else cb.wp.water_density(Ti)
            cw_i = cw if cw else cb.wp.water_capacity(Ti)
            cotton = _num(params.get('cotton_mass(g)'), 0.0)
            combustible = _num(params.get('combustible_mass(g)'), 0.0)
            nickel_before = _num(params.get('Nickel_before_mass(g)'), 0.0)
            nickel_after = _num(params.get('Nickel_after_mass(g)'), 0.0)

            points = r.get('points')
            auto = False
            auto_method = ''
            auto_warning = ''
            if not points or len(points) != 4:
                auto_points, auto_method, auto_warning = cb.find_start_end_point_ex(
                    data.csv, _num(cfg.get('time_lower_limit'), 30.0),
                    _num(cfg.get('time_upper_limit'), 40.0),
                    _num(cfg.get('std_limit'), 0.02),
                    prefer=cfg.get('point_prefer') or 'software')
                points = auto_points
                auto = True
            else:
                auto_points = list(points)
            points = [int(p) for p in points]
            reyn = cb.reynolds(data.csv, *points, dx=_num(cfg.get('dx'), 0.1))
            f1 = cb.fit_info(data.csv, points[0], points[1])
            f2 = cb.fit_info(data.csv, points[2], points[3])
            f1.update(start=points[0], end=points[1])
            f2.update(start=points[2], end=points[3])

            m_sam = _num(r.get('sample_mass'))
            if m_sam is None:
                m_sam = combustible - cotton

            item = {
                'index': i + 1,
                'name': r.get('name') or ('第%d轮' % (i + 1)),
                'role': r.get('role', 'sample'),
                'substance': r.get('substance', 'sucrose'),
                'note': r.get('note', ''),
                'data': data,
                'params': params,
                'points': points,
                'is_auto': auto,
                'auto_points': auto_points,
                'auto_method': auto_method,
                'auto_warning': auto_warning,
                'reynolds': reyn,
                'fit1': f1,
                'fit2': f2,
                'temperature': Ti,
                'temperature_source': temp_source,
                'water_volume': water_volume,
                'water_density': rho_i,
                'water_capacity': cw_i,
                'cotton_mass': cotton,
                'combustible_mass': combustible,
                'nickel_before': nickel_before,
                'nickel_after': nickel_after,
                'nickel_loss': nickel_before - nickel_after,
                'sample_mass': m_sam,
                'dT': reyn['dT'],
                'cotton_heat': cotton_heat,
                'nickel_heat': nickel_heat,
            }
            item['Q_cotton'] = cotton * cotton_heat
            item['Q_nickel'] = (nickel_before - nickel_after) * nickel_heat
            item['sum_q'] = item['Q_cotton'] + item['Q_nickel']
            item['D_Cw'] = water_volume * rho_i * cw_i
            rounds.append(item)

        # ---- 标准物质轮：量热计常数
        std = next((x for x in rounds if x['role'] == 'standard'), None)
        if std is None:
            raise ValueError('请把其中一轮标记为“标准物质（苯甲酸）”，用于标定量热计常数。')
        Qv_ben = cb.benzoic_qv_per_gram(std['temperature'], benzoic_enthalpy)
        W = (-(Qv_ben * std['sample_mass'] + std['sum_q']) / std['dT']) - std['D_Cw']
        sigma_sumq = float(np.sqrt((nickel_heat * sigma_m_diff) ** 2
                                   + (cotton_heat * sigma_m_single) ** 2))
        numerator = Qv_ben * std['sample_mass'] + std['sum_q']
        sigma_W = float(np.sqrt((Qv_ben * sigma_m_diff / std['dT']) ** 2
                                + (sigma_sumq / std['dT']) ** 2
                                + (numerator * sigma_dT / std['dT'] ** 2) ** 2))
        std.update({
            'Qv_benzoic': Qv_ben,
            'W': W,
            'sigma_W': sigma_W,
        })

        # ---- 样品轮：燃烧热
        for it in rounds:
            if it['role'] != 'standard':
                Qv = ((W + it['D_Cw']) * it['dT'] + it['sum_q']) / it['sample_mass']
                total_heat = (W + it['D_Cw']) * it['dT'] + it['sum_q']
                sigma = float(np.sqrt(
                    (it['dT'] * sigma_W / it['sample_mass']) ** 2
                    + ((W + it['D_Cw']) * sigma_dT / it['sample_mass']) ** 2
                    + (sigma_sumq / it['sample_mass']) ** 2
                    + (total_heat * sigma_m_diff / it['sample_mass'] ** 2) ** 2))
                it['Qv_per_gram'] = Qv
                it['sigma_Qv_per_gram'] = sigma
            else:
                it['Qv_per_gram'] = None
                it['sigma_Qv_per_gram'] = None

        self.rounds = rounds
        self.standard = std
        self.W = W
        self.sigma_W = sigma_W
        self.sigma_dT = sigma_dT
        self.sigma_sumq = sigma_sumq
        self.sigma_m_diff = sigma_m_diff
        self.sigma_m_single = sigma_m_single
        self.Qv_benzoic = Qv_ben
        return rounds

    # ------------------------------------------------------------ 摩尔燃烧热
    def molar(self, item):
        sub = SUBSTANCES.get(item['substance'], SUBSTANCES['custom'])
        Mr = sub.get('Mr')
        Qv_g = item.get('Qv_per_gram')
        if not Mr or Qv_g is None:
            return None
        s_g = item.get('sigma_Qv_per_gram')
        Qp_mol = Qv_g * Mr / 1000.0          # kJ/mol
        s_mol = (s_g * Mr / 1000.0) if s_g is not None else None
        return {
            'Mr': Mr, 'Qp_kJ_per_mol': Qp_mol, 'sigma_kJ_per_mol': s_mol,
            'Qp_J_per_g': Qv_g, 'sigma_J_per_g': s_g,
            'literature': sub.get('literature_kJ_per_mol'),
            'literature_note': sub.get('literature_note', ''),
            'error_percent': (abs(Qp_mol - sub['literature_kJ_per_mol'])
                              / abs(sub['literature_kJ_per_mol']) * 100.0)
            if sub.get('literature_kJ_per_mol') else None,
        }
