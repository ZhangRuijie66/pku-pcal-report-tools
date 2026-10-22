# -*- coding: utf-8 -*-
"""紫外可见吸收光谱实验 —— 参数模型与一次完整计算。

界面、自检、报告生成都只跟这里的 :class:`Analysis` 打交道：
换参数就重建一个 Analysis 并 ``run()`` 一次，得到全部结果。
"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import uv

# 默认数据目录（换机器后可在界面上改，改完「存为默认」）
DEFAULT_DATA_DIR = r'D:\北大\课程\26秋大三上\物理化学实验\3 紫外光谱搭建\数据'


def default_config():
    return {
        # ---- 封面
        'student_name': '',
        'student_id': '',
        'group': '',
        'group_no': '',
        'date': '2026/10/14 & 10/21',
        'room_temp_1': 22.0,
        'room_temp_2': 19.1,
        'pressure_1': 101.5,
        'pressure_2': 101.8,
        # ---- 数据与处理
        'data_dir': DEFAULT_DATA_DIR,
        'smooth_window': uv.DEFAULT_SMOOTH,
        # 杂散光校正：'auto' = 只对 A3 浓度系列启用（这批数据的测量条件决定的），
        # 'off' = 全部不扣，'manual' = 全部按 stray 比例扣
        'stray_mode': 'off',
        'stray': uv.DEFAULT_STRAY,
        'stray_a3': 0.33,
        'path_cm': uv.PATH_LENGTH_CM,
        'anchor_pad': 80,
        'voigt_peaks': 'auto',   # Voigt 分峰个数：'auto' / 1 / 2
        # ---- 选用哪一次测量：分子 / 浓度系列 / Beer 拟合浓度
        'molecule_default': dict(uv.MOLECULE_DEFAULT),
        'conc_pick': dict(uv.CONC_PICK_DEFAULT),
        'beer_concs': list(uv.BEER_CONC_DEFAULT),
        # ---- 一维势箱
        'box_a': 6,          # B 组外推时采用的 a
        'box_n_B1': 22,      # B1 的 π 电子数
        'box_n_B2': 6,       # B2 的 π 电子数
        'gcalc': {},         # 高斯计算（TD-DFT）读取结果，运行时填充
        'gcalc_dir': '',     # 高斯计算工具目录（留空 = ..\高斯计算工具）
        'gcalc_logs_dir': '',  # TD-DFT 日志目录（留空 = 数据目录\..\calculation\gjf\logs）
    }


# 只有这些字段会被保存到 settings.json（与具体数据文件无关的偏好）
PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp_1', 'room_temp_2', 'pressure_1', 'pressure_2',
    'data_dir', 'smooth_window', 'stray', 'stray_mode', 'stray_a3',
    'path_cm', 'anchor_pad', 'voigt_peaks',
    'molecule_default', 'conc_pick', 'beer_concs', 'box_a', 'box_n_B1', 'box_n_B2',
    'gcalc_dir', 'gcalc_logs_dir',
)


def merge_saved(cfg, saved):
    if not saved:
        return cfg
    for k, v in saved.items():
        if k in PERSIST_KEYS and v is not None:
            if k == 'molecule_default' and isinstance(v, dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def default_config_with_saved(saved):
    return merge_saved(default_config(), saved)


def _num(v, default=0.0):
    try:
        if v in (None, ''):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _valid_picks(picks, candidates, defaults):
    """只接受候选清单里的 key，其余退回默认。"""
    out = dict(defaults)
    for slot, key in (picks or {}).items():
        cand = candidates.get(slot)
        if cand and key in cand:
            out[slot] = key
    return out


class Analysis:
    """一次完整的实验数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.samples = {}
        self.cals = {}
        self.beer = None
        self.box = None
        self.molecule_table = []
        self.warnings = []
        self.spectra = {}

    # ------------------------------------------------------------ 主流程
    def run(self, spectra=None):
        """spectra: {相对路径: load_spectrum 结果}，不给则按 data_dir 现读。"""
        cfg = self.cfg
        data_dir = cfg.get('data_dir') or DEFAULT_DATA_DIR
        self.spectra = spectra or {}
        self.warnings = []

        # 1) 三次标定
        for c in uv.CALIBRATIONS:
            path = os.path.join(data_dir, c['file'])
            spec = self._spec(path)
            cal = uv.calibrate(spec, prior=c['prior'])
            cal = dict(cal)
            cal.update(key=c['key'], label=c['label'], short=c['short'],
                       day=c['day'], file=c['file'], path=path, spec=spec)
            cal['lam_lo'] = cal['a'] * 1 + cal['b']
            cal['lam_hi'] = cal['a'] * len(spec['index']) + cal['b']
            self.cals[c['key']] = cal
            if cal.get('fallback'):
                self.warnings.append('标定 %s 自动寻峰失败，退回先验系数' % c['short'])

        # 2) 逐条样品谱
        cal_by_key = self.cals
        for s in uv.SAMPLES:
            mol = uv.MOLECULES[s['mol']]
            sp = self._spec(os.path.join(data_dir, s['sample']))
            bp = self._spec(os.path.join(data_dir, s['blank']))
            cal = cal_by_key[s['cal']]
            stray = self._stray_for(s)
            cur = uv.absorbance_curve(sp, bp, cal,
                                      smooth_window=int(_num(cfg.get('smooth_window'), 9)),
                                      stray=stray)
            band = tuple(mol['band'])
            anchors = uv.default_anchors(band, pad=_num(cfg.get('anchor_pad'), 80))
            k, b, A_corr = uv.baseline_line(cur['lam'], cur['A_smooth'], anchors)
            k0, b0, A_corr_plain = uv.baseline_line(cur['lam'], cur['A_smooth_plain'],
                                                    anchors)
            # Voigt 分峰拟合（分峰个数可配置；失败时退回简单寻峰）
            n_peaks = cfg.get('voigt_peaks', 'auto')
            if n_peaks not in (None, '', 'auto'):
                try:
                    n_peaks = int(n_peaks)
                except (TypeError, ValueError):
                    n_peaks = 'auto'
            vf = uv.voigt_fit(cur['lam'], A_corr, band, n_peaks=n_peaks)
            if vf:
                peak = dict(lam=vf['lam_max'], A=vf['A_max'], index=-1, voigt=True)
            else:
                peak = uv.find_peak(cur['lam'], A_corr, band)
                peak['voigt'] = False
            if stray == 0:
                vf_obs = vf
            else:
                vf_obs = uv.voigt_fit(cur['lam'], A_corr_plain, band, n_peaks=n_peaks)
            if vf_obs:
                peak_obs = dict(lam=vf_obs['lam_max'], A=vf_obs['A_max'],
                                index=-1, voigt=True)
            else:
                peak_obs = uv.find_peak(cur['lam'], A_corr_plain, band)
                peak_obs['voigt'] = False
            eps = uv.molar_extinction(peak['A'], s['conc'], _num(cfg.get('path_cm'), 1.0))
            self.samples[s['key']] = dict(
                s, mol_key=s['mol'], mol_name=mol['name'], short=mol['short'],
                band=band, anchors=anchors, baseline=(k, b), stray=stray,
                lam=cur['lam'], A_raw=cur['A_raw'], A_smooth=cur['A_smooth'],
                A_raw_plain=cur['A_raw_plain'], A_smooth_plain=cur['A_smooth_plain'],
                A_corr=A_corr, A_corr_plain=A_corr_plain,
                voigt=vf, voigt_obs=vf_obs,
                peak=peak, peak_obs=peak_obs, eps=eps,
                cal_label=cal['short'])

        # 3) 测量选择：浓度系列 + 其余分子
        picks_mol = _valid_picks(cfg.get('molecule_default'),
                                 uv.MOLECULE_CANDIDATES, uv.MOLECULE_DEFAULT)
        picks_conc = _valid_picks(cfg.get('conc_pick'),
                                  uv.CONC_CANDIDATES, uv.CONC_PICK_DEFAULT)
        self.picks_mol = picks_mol
        self.picks_conc = picks_conc
        self.conc_items = [self.samples[picks_conc[uv.conc_label(c)]]
                           for c in uv.CONC_VALUES
                           if picks_conc.get(uv.conc_label(c)) in self.samples]

        self.molecule_table = []
        for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
            key = picks_mol.get(code) or uv.MOLECULE_DEFAULT.get(code)
            it = self.samples.get(key)
            if it is None:
                self.warnings.append('分子 %s 选用的测量（%s）不存在' % (code, key))
                continue
            self.molecule_table.append(dict(
                code=code, name=uv.MOLECULES[code]['name'], key=key,
                conc=it['conc'], lam=it['peak']['lam'], A=it['peak']['A'],
                eps=it['eps'], source=it['source'], group=uv.MOLECULES[code]['group']))

        # 4) Beer-Lambert 拟合（A3 浓度系列）：只用线性区的点拟合，
        #    但图里要画出全部浓度点（含饱和区的 20 / 50 μmol·L⁻¹）
        beer_concs = cfg.get('beer_concs')
        if not beer_concs:
            beer_concs = list(uv.BEER_CONC_DEFAULT)
        beer_concs = [float(c) for c in beer_concs]
        self.beer_concs = beer_concs
        fit_keys = [picks_conc.get(uv.conc_label(c)) for c in uv.CONC_VALUES
                    if c in beer_concs]
        pts = [self.samples[k] for k in fit_keys if k in self.samples]
        pts = [p for p in pts if np.isfinite(p['peak']['A'])]
        pts.sort(key=lambda p: p['conc'])
        self.beer = dict(points=[dict(key=p['key'], conc=p['conc'],
                                      lam=p['peak']['lam'], A=p['peak']['A']) for p in pts])
        all_pts = []
        for it in self.conc_items:
            A_corr = it['peak']['A'] if it['peak'].get('voigt') else None
            all_pts.append(dict(key=it['key'], conc=it['conc'],
                                lam_obs=it['peak_obs']['lam'],
                                A_obs=it['peak_obs']['A'],
                                lam_corr=it['peak']['lam'], A_corr=A_corr,
                                is_fit=(it['key'] in fit_keys)))
        self.beer['all'] = all_pts
        if len(pts) >= 2:
            fit = uv.line_fit([p['conc'] for p in pts], [p['peak']['A'] for p in pts])
            fit['eps'] = fit['k'] / (1e-6 * _num(cfg.get('path_cm'), 1.0)) if np.isfinite(fit['k']) else float('nan')
            self.beer['fit'] = fit
            self.beer['x_linear'] = [0.0, max(p['conc'] for p in pts)]
        else:
            self.beer['fit'] = None
            self.beer['x_linear'] = [0.0, 0.0]

        # 5) 一维势箱
        lam = {row['code']: row['lam'] for row in self.molecule_table}
        a_rows = uv.particle_in_box(lam)
        self.box = dict(a_rows=a_rows, lambdas=lam)
        a_use = int(_num(cfg.get('box_a'), 6))
        row = next((r for r in a_rows if r['a'] == a_use), None)
        self.box['a_used'] = a_use
        self.box['x_used'] = row['x'] if row else float('nan')
        b_rows = []
        if row and np.isfinite(row['x']):
            x = row['x']
            for code, n in (('B1', int(_num(cfg.get('box_n_B1'), 22))),
                            ('B2', int(_num(cfg.get('box_n_B2'), 6)))):
                units = uv.MOLECULES[code]['i']
                l_lo, l_hi = uv.box_length(x, units)
                b_rows.append(dict(
                    code=code, units=units, L_lo=l_lo, L_hi=l_hi, n=n,
                    lam_lo=uv.box_lambda(l_lo, n), lam_hi=uv.box_lambda(l_hi, n),
                    exp=lam.get(code)))
        self.box['b_rows'] = b_rows
        return self

    # ------------------------------------------------------------ 读取缓存
    def _stray_for(self, s):
        """该条谱采用的杂散光比例（占入射光强的比例）。"""
        mode = self.cfg.get('stray_mode') or 'auto'
        if mode == 'off':
            return 0.0
        if mode == 'manual':
            return _num(self.cfg.get('stray'), 0.0)
        # auto：A3 浓度系列这一批测量杂散光最大，其余按 0
        if s['mol'] == 'A3' and s.get('kind', '').startswith('conc'):
            return _num(self.cfg.get('stray_a3'), 0.0)
        return 0.0

    def _spec(self, path):
        if path not in self.spectra:
            self.spectra[path] = uv.load_spectrum(path)
        return self.spectra[path]

    # ------------------------------------------------------------ 便捷访问
    def sample(self, key):
        return self.samples.get(key)

    def molecules(self, group=None):
        rows = self.molecule_table
        if group:
            rows = [r for r in rows if r['group'] == group]
        return rows
