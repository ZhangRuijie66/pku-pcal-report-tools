# -*- coding: utf-8 -*-
"""配置模型：把界面上的输入整理成一次计算 / 出报告所需的完整参数。"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import dissolution as ds

# ---------------------------------------------------------------- 溶质预设
# Mr 取 IUPAC 2016 原子量计算值，与课程软件内置的默认式量一致。
SUBSTANCES = {
    'kno3': {
        'label': '硝酸钾 KNO3', 'tex_label': r'KNO_{3}',
        'Mr': 101.102,
        'dissolution_note': '硝酸钾溶于水为吸热过程，$Q_s$ 随 $n_0$ 增大而增大。',
        'solubility': '20 ℃ 时约 31.6 g/100 g 水、40 ℃ 时约 63.9 g/100 g 水。',
    },
    'kcl': {
        'label': '氯化钾 KCl', 'tex_label': r'KCl',
        'Mr': 74.551,
        'dissolution_note': '氯化钾溶于水为吸热过程。',
        'solubility': '20 ℃ 时约 34.0 g/100 g 水。',
    },
    'nh4no3': {
        'label': '硝酸铵 NH4NO3', 'tex_label': r'NH_{4}NO_{3}',
        'Mr': 80.043,
        'dissolution_note': '硝酸铵溶于水为显著吸热过程。',
        'solubility': '20 ℃ 时约 190 g/100 g 水。',
    },
    'nacl': {
        'label': '氯化钠 NaCl', 'tex_label': r'NaCl',
        'Mr': 58.443,
        'dissolution_note': '氯化钠溶于水热效应很小。',
        'solubility': '20 ℃ 时约 36.0 g/100 g 水。',
    },
    'custom': {
        'label': '自定义', 'tex_label': '待测溶质', 'Mr': None,
        'dissolution_note': '', 'solubility': '',
    },
}


def default_config():
    return {
        # 报告封面
        'student_name': '', 'student_id': '', 'group': '', 'group_no': '',
        'date': '', 'pressure_kPa': None,
        # 实验条件
        'water_volume_mL': 500.0,
        # 温度用摄氏度输入（沿用实验记录的写法），计算时内部换算成 K。
        # None -> 取数据文件头里的 room_temperature(K)
        'temperature_C': None,
        'force_temperature': False,     # True -> 全部轮次都用界面上的室温
        'water_density': None,          # None -> 按温度查表
        'water_capacity': None,
        'solute': 'kno3',
        'solute_molarmass': None,       # None -> 取预设值 / 数据文件头
        # 手册值：25 ℃ 下硝酸钾的无限稀释积分溶解热（kJ/mol），用于结果误差分析
        'literature_Qs0': 34.89,
        # 不确定度：各量的标准差（沿用本课程报告一贯的口径，见 dissolution.py 顶部注释）
        'sigma_current': ds.SIGMA_CURRENT,        # A
        'sigma_resistance': ds.SIGMA_RESISTANCE,  # Ω
        'sigma_time': ds.SIGMA_TIME,              # s
        'sigma_dt': ds.SIGMA_DT,                  # K
        'e_balance': ds.E_BALANCE,                # g（称量）
        # 自动寻点
        'point_source': 'file',         # 'file' 用课程软件 dissolution.csv 里记的取点；'auto' 自动寻点
        'win_seconds': 32.0,
        'lead_seconds': 6.0,
        'lag_seconds': 10.0,
        'dx': ds.DX,
        # 上次用过的数据文件夹（换机器/换目录后也能记住，省得每次重找）
        'data_dir': None,
        # 各轮次
        'rounds': [],
    }


# 会被记住（写进设置文件、下次打开自动填回）的字段。
PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'pressure_kPa', 'water_volume_mL', 'temperature_C',
    'water_density', 'water_capacity', 'solute', 'solute_molarmass',
    'literature_Qs0',
    'sigma_current', 'sigma_resistance', 'sigma_time', 'sigma_dt', 'e_balance',
    'point_source', 'force_temperature', 'data_dir',
)


def default_config_with_saved(saved):
    cfg = default_config()
    if not saved:
        return cfg
    for k in PERSIST_KEYS:
        if k in saved and saved[k] not in (None, ''):
            cfg[k] = saved[k]
    if saved.get('temperature_C') is None and saved.get('temperature_K') is not None:
        cfg['temperature_C'] = round(float(saved['temperature_K']) - 273.15, 2)
    return cfg


def default_round(index):
    return {
        'index': index,
        'enabled': True,
        'name': '第%d轮' % index,
        'file': None,
        'params': {},
        'points': None,          # [Start1, End1, Start2, End2, Start3, End3]
        'solute_mass': None,
        'note': '',
    }


def setpoint_to_kelvin(celsius_or_none):
    if celsius_or_none is None or celsius_or_none == '':
        return None
    return float(celsius_or_none) + 273.15


def _num(v, default=None):
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Analysis:
    """一次完整的溶解热数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config)
        self.rounds = []
        self.fit = None            # 积分溶解热的经验方程拟合
        self.diff = None           # 各浓度下的积分 / 微分热
        self.sigma_dT = ds.sigma_dT()
        self.sigma_m = ds.sigma_mass()

    # ------------------------------------------------------------ 计算
    def run(self, loaders):
        """
        loaders: dict filename -> DissolutionData
        返回 self.rounds（含每轮两次雷诺校正与溶解热）。
        """
        cfg = self.cfg
        if not cfg['rounds']:
            raise ValueError('还没有任何一轮数据。')

        T = setpoint_to_kelvin(_num(cfg.get('temperature_C')))
        rho_cfg = _num(cfg.get('water_density'))
        cw_cfg = _num(cfg.get('water_capacity'))
        V_cfg = _num(cfg.get('water_volume_mL'), 500.0)
        e_b = _num(cfg.get('e_balance'), ds.E_BALANCE)
        s_I = _num(cfg.get('sigma_current'), ds.SIGMA_CURRENT)
        s_R = _num(cfg.get('sigma_resistance'), ds.SIGMA_RESISTANCE)
        s_tt = _num(cfg.get('sigma_time'), ds.SIGMA_TIME)
        s_dT = _num(cfg.get('sigma_dt'), ds.SIGMA_DT)
        sub = SUBSTANCES.get(cfg.get('solute') or 'kno3', SUBSTANCES['custom'])
        Mr_cfg = _num(cfg.get('solute_molarmass')) or sub.get('Mr')

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

            V = _num(params.get('water_volume(mL)')) or V_cfg
            Ti = None
            temp_source = ''
            if cfg.get('force_temperature') and T is not None:
                Ti, temp_source = T, '界面统一室温'
            if Ti is None:
                Ti = _num(params.get('room_temperature(K)'))
                if Ti is not None:
                    temp_source = '数据文件中的室温'
            if Ti is None:
                Ti = T if T is not None else 298.15
                temp_source = '界面室温' if T is not None else '默认 298.15 K'
            rho = rho_cfg if rho_cfg else ds.wp.water_density(Ti)
            cw = cw_cfg if cw_cfg else ds.wp.water_capacity(Ti)

            Mr = _num(params.get('solute_molarmass(g/mol)')) or Mr_cfg or 0.0
            m_solute = _num(r.get('solute_mass'))
            if m_solute is None:
                m_solute = _num(params.get('solute_mass(g)'))
            current = _num(params.get('current(A)'), 0.0)
            R1 = _num(params.get('R1(Omega)'), 0.0)
            R2 = _num(params.get('R2(Omega)'), 0.0)
            t1 = _num(params.get('t1(s)'))
            t2 = _num(params.get('t2(s)'))

            points = r.get('points')
            is_auto = False
            auto_points = None
            auto_note = ''
            if not points or len(points) != 6:
                auto_points = ds.find_start_end_point(
                    data.csv, t1, t2,
                    win_seconds=_num(cfg.get('win_seconds'), 32.0),
                    lead_seconds=_num(cfg.get('lead_seconds'), 6.0),
                    lag_seconds=_num(cfg.get('lag_seconds'), 10.0))
                points = auto_points
                is_auto = True
                auto_note = '自动寻点（按曲线平台自动识别）'
            points = [int(p) for p in points]

            reyn1 = ds.reynolds(data.csv, *points[0:4], dx=_num(cfg.get('dx'), ds.DX))
            reyn2 = ds.reynolds(data.csv, *points[2:6], dx=_num(cfg.get('dx'), ds.DX))
            f1 = ds.fit_info(data.csv, points[0], points[1])
            f2 = ds.fit_info(data.csv, points[2], points[3])
            f3 = ds.fit_info(data.csv, points[4], points[5])

            dT_diss = abs(reyn1['signed_dT'])     # 溶解使温度下降
            dT_heat = abs(reyn2['signed_dT'])     # 通电使温度回升
            res = ds.calc_round_dissolution(current, R1, R2, t1, t2,
                                            dT_diss, dT_heat)
            rel = ds.sigma_Q(current, R1, R2, t1, t2, dT_diss, dT_heat,
                             sigma_I=s_I, sigma_R=s_R,
                             sigma_t=s_tt, sigma_dT_=s_dT)
            terms = ds.sigma_terms(current, R1, R2, t1, t2, dT_diss, dT_heat,
                                   sigma_I=s_I, sigma_R=s_R,
                                   sigma_t=s_tt, sigma_dT_=s_dT)

            rounds.append({
                'index': i + 1,
                'name': r.get('name') or ('第%d轮' % (i + 1)),
                'note': r.get('note', ''),
                'data': data,
                'params': params,
                'points': points,
                'is_auto': is_auto,
                'auto_points': auto_points,
                'auto_note': auto_note,
                'reynolds_diss': reyn1,
                'reynolds_heat': reyn2,
                'fit1': f1, 'fit2': f2, 'fit3': f3,
                'temperature': Ti,
                'temperature_source': temp_source,
                'water_volume': V,
                'water_density': rho,
                'water_capacity': cw,
                'current': current, 'R1': R1, 'R2': R2, 't1': t1, 't2': t2,
                'Mr': Mr,
                'solute_mass': m_solute,
                'dT_diss': dT_diss,
                'dT_heat': dT_heat,
                'Q_elec': res['Q_elec'],
                'Q': res['Q'],
                'R_heat': res['R'],
                't_heat': res['t_heat'],
                'sigma_Q_rel': rel,
                'sigma_Q': abs(res['Q']) * rel,
                'sigma_terms': terms,
                'software_Q_kJ': r.get('ref_Q_kJ'),
            })

        if not rounds:
            raise ValueError('没有可用的数据轮次。')

        # ---- 积分溶解热与经验方程拟合
        rows = [{'solute_mass': it['solute_mass'],
                 'solute_molar_mass': it['Mr'],
                 'Q': it['Q']} for it in rounds]
        base = rounds[0]
        fit = ds.fit_integral_heat(rows, base['water_density'],
                                   base['water_volume'])
        self.fit = fit

        # ---- 逐轮累积量与不确定度
        n1 = fit['n1']
        s_V = ds.E_VOLUME / ds.SQRT3
        s_rho = ds.E_WATER_DENSITY / ds.SQRT3
        s_n1 = n1 * float(np.sqrt((s_V / base['water_volume']) ** 2
                                  + (s_rho / base['water_density']) ** 2))
        s_m = e_b / ds.SQRT3
        sum_sqQ = 0.0
        sum_m2 = 0.0
        for i, it in enumerate(rounds):
            it['cum_m2'] = float(fit['cum_m2'][i])
            it['cum_Q'] = float(fit['cum_Q'][i])
            it['n0'] = float(fit['n0'][i])
            it['Qs'] = float(fit['Qs'][i])
            sum_sqQ += it['sigma_Q'] ** 2
            it['sigma_cum_Q'] = float(np.sqrt(sum_sqQ))
            sum_m2 += it['solute_mass']
            it['sum_n2'] = sum_m2 / it['Mr'] if it['Mr'] else float('nan')
            it['sigma_sum_n2'] = float(np.sqrt(i + 1) * s_m / it['Mr']) if it['Mr'] else float('nan')
            rel_n0 = float(np.sqrt((s_n1 / n1) ** 2
                                   + (it['sigma_sum_n2'] / it['sum_n2']) ** 2)) if it['Mr'] else float('nan')
            it['sigma_n0'] = it['n0'] * rel_n0
            rel_Qs = float(np.sqrt((it['sigma_cum_Q'] / abs(it['cum_Q'])) ** 2
                                   + (it['sigma_sum_n2'] / it['sum_n2']) ** 2)) if it['Mr'] else float('nan')
            it['sigma_Qs'] = abs(it['Qs']) * rel_Qs
            # 与本课程报告一贯的写法一致：σ_Qs 由 σ_Q 直接除以溶质的物质的量
            if it['Mr']:
                it['sigma_Qs_simple'] = it['sigma_cum_Q'] / it['sum_n2']

        # 经验方程给出的各浓度热效应
        self.diff = ds.differential_heats(fit['Qs0'], fit['a'])

        self.rounds = rounds
        self.sigma_n1 = float(s_n1)
        self.sigma_m_single = float(s_m)
        self.sigma_dT = float(s_dT)
        self.sigma_current = s_I
        self.sigma_resistance = s_R
        self.sigma_time = s_tt
        self.sigma_balance = e_b
        self.e_balance = e_b
        return rounds

    # ------------------------------------------------------------ 便捷量
    @property
    def names(self):
        return [it['name'] for it in self.rounds]

    @property
    def Qs0(self):
        return self.fit['Qs0'] if self.fit else None

    @property
    def a(self):
        return self.fit['a'] if self.fit else None

    def half_concentration(self):
        """经验方程里 Qs 达到 Qs0/2 时的 n0（= 1/a），用来解释参数 a 的物理意义。"""
        if not self.fit or not self.fit['a']:
            return None
        return 1.0 / self.fit['a']
