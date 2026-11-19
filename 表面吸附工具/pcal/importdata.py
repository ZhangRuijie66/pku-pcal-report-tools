# -*- coding: utf-8 -*-
"""把导出的数据表（.xlsx / .csv）重新读回界面与计算内核。

与 `exportdata.py` 严格成对：导出是「分析结果 → 表」，这里是「表 → 原始读数 + 配置」。
用途是「上个星期导出的数据表，今天想改一个读数」「换台电脑继续做报告」
「把别人的数据表直接读进来重算」——不用再手工把 20 多个读数敲一遍。

三条设计口径（照 SKILL §27 的「数量鲁棒性」清单）：

1. **列数不写死**：`h_l1…h_ln` / `γ1…γn` 的 n 从**表头里的数字**读出来，
   平行次数是 1 次还是 6 次都照常读回，配置里的 repeat_n 也跟着回填；
2. **只认导出格式，不认识就报错**：表头对不上就抛出带「认识哪些列名」的错误，
   绝不「差不多就填」——静默填错的数据比缺数据难发现得多；
3. **换算值不当实测**：导出表里由 S 换算出来的一侧（`h_r 来源 = 按 S 换算`）
   读回来时**按读数方式置空**，让内核照同样的方式重新换算；否则 σ(Δh) 会从
   「只读一侧」（灵敏度 2 倍）退化成「两侧实测」，报告里的不确定度会平白变小。

可移植性：不出现任何本机绝对路径；xlsx 走 openpyxl（读字节流，不落临时文件），
csv 用 utf-8-sig / gbk 依次尝试解码。
"""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata

#: 导出时的工作表名（顺序即 exportdata.tables 的顺序）
SHEET_INFO = '说明'
SHEET_RESULT = '结果'
SHEET_BUBBLE = '最大气泡法'
SHEET_PLATE = '吊片法'
SHEET_TRIO = '零点与纯水'

MODE_TEXT = {'两侧都读': 'both', '只读左侧': 'left', '只读右侧': 'right'}
ZERO_TEXT = {'扣除': True, '不扣除': False}


class ImportDataError(ValueError):
    """数据表读不了（格式不对/缺表/缺列），消息要能直接给用户看。"""


# ---------------------------------------------------------------- 小工具
def _norm(text):
    """表头/键名的归一化形式：全角转半角、去空白、去掉单位说明后的比较基准。"""
    s = unicodedata.normalize('NFKC', str(text if text is not None else ''))
    s = s.replace('（', '(').replace('）', ')').replace('％', '%')
    s = s.replace('\\n', ' ')
    s = re.sub(r'\s+', '', s)
    return s.lower()


def _head_key(text):
    """表头的主键：`γ_w /(mN·m⁻¹)` → `γ_w`（单位写法变了也不影响识别）。"""
    s = _norm(text)
    return s.split('/')[0]


def _text(v):
    if v is None:
        return ''
    if isinstance(v, float) and not math.isfinite(v):
        return ''
    return str(v).strip()


def _num(v):
    """表里的一个数 → float；空/破折号/文字 → None（不是 0，避免造数）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    s = _text(v).replace('−', '-').replace('—', '').replace('–', '').strip()
    if not s:
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def _yes(raw):
    """'是' / '否' / True / 1 → bool。"""
    if isinstance(raw, bool):
        return raw
    s = _text(raw)
    return s in ('是', '√', 'Y', 'y', 'true', 'True', 'TRUE', '1')


def _decode(raw):
    for enc in ('utf-8-sig', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


def _fmt_of(name, raw):
    low = str(name or '').lower()
    if low.endswith(('.xlsx', '.xlsm', '.xls')):
        return 'xlsx'
    if low.endswith('.csv'):
        return 'csv'
    if raw[:2] == b'PK':                     # 没后缀但内容是 zip → xlsx
        return 'xlsx'
    return 'csv' if low.endswith(('.txt', '.tsv')) else 'xlsx'


# ---------------------------------------------------------------- 读 xlsx
def _read_xlsx(raw):
    """→ {sheet 名: [[单元格, …], …]}；只用只读模式，不写临时文件。"""
    try:
        import openpyxl
    except ImportError as exc:                       # pragma: no cover
        raise ImportDataError('读取 .xlsx 需要 openpyxl：%s' % exc)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True,
                                    data_only=True)
    except Exception as exc:                         # noqa: BLE001
        raise ImportDataError('这个文件不是有效的 xlsx（%s）' % exc)
    grids = {}
    try:
        for ws in wb.worksheets:
            grid = []
            for row in ws.iter_rows(values_only=True):
                grid.append(list(row))
            grids[str(ws.title).strip()] = grid
    finally:
        wb.close()
    if not grids:
        raise ImportDataError('工作簿里没有任何工作表')
    return grids


def _find_sheet(grids, want):
    key = _norm(want)
    for name, grid in grids.items():
        if _norm(name) == key:
            return grid
    return None


def _guess_sheets(grids):
    """没有工作表名（被改名）时按表头内容认，返回 {角色: grid}。"""
    out = {}
    for grid in grids.values():
        if not grid:
            continue
        head = [_norm(c) for c in (grid[0] or [])]
        joined = '|'.join(head)
        if not joined:
            continue
        is_trio = any(h.startswith('项目') for h in head)
        has_h = bool(re.search(r'h_l\d', joined) or re.search(r'h_r\d', joined))
        has_g = bool(re.search(r'γ\d', joined))
        if is_trio and 'h_l' in joined.replace('|', ''):
            out.setdefault('trio', grid)
        elif has_h and not is_trio:
            out.setdefault('bubble', grid)
        elif has_g and not has_h:
            out.setdefault('plate', grid)
    return out


# ---------------------------------------------------------------- 表头解析
def _column_roles(headers):
    """表头 → 列角色。

    → dict(c=idx, left=[(序号, idx)], right=[…], gamma=[(序号, idx)],
           fit=idx, derived=idx, label=idx)
    序号取表头里的数字（h_l1 → 1），**这就是平行次数**，不写死 3。
    """
    roles = {'c': None, 'left': [], 'right': [], 'gamma': [],
             'fit': None, 'derived': None, 'label': None}
    for j, raw in enumerate(headers):
        # ⚠ 必须用 _head_key（先去掉 `/单位` 再比）：导出表头是
        #   `h_l1 /cm`、`γ1 /(mN·m⁻¹)`，用 _norm 的话整串带着单位，正则匹配不上。
        key = _head_key(raw)
        if not key:
            continue
        m = re.match(r'^h_?l(\d+)$', key)
        if m:
            roles['left'].append((int(m.group(1)), j))
            continue
        m = re.match(r'^h_?r(\d+)$', key)
        if m:
            roles['right'].append((int(m.group(1)), j))
            continue
        m = re.match(r'^γ(\d+)$', key)
        if m:
            roles['gamma'].append((int(m.group(1)), j))
            continue
        if key == 'c' or key.startswith('浓度'):
            roles['c'] = j
            continue
        if key.startswith('参与拟合') or key == 'fit':
            roles['fit'] = j
            continue
        if key.endswith('来源') or key == 'derived':
            roles['derived'] = j
            continue
        if key.startswith('项目'):
            roles['label'] = j
    for name in ('left', 'right', 'gamma'):
        roles[name].sort()
    return roles


def _pick(grid, role_name):
    if not grid:
        return None
    return grid


# ---------------------------------------------------------------- 各表解析
def _parse_info(grid):
    """说明表（项目 / 值）→ (config 片段, data 片段)。

    两边的归属必须分清：
      · config：封面字段 + 处理参数（analysis.default_config 里的键）；
      · data  ：温度、γ_w、σ、吊片法纯水读数（默认数据里的键）。
    放错边不会报错，只是**静默不生效**（_coerce 按白名单过滤 config），
    界面上温度、γ_w 还是旧值 —— 这类偏差最难发现。
    """
    cfg, data_patch, info_extra, raw = {}, {}, {}, {}
    for row in grid or []:
        if len(row) < 2:
            continue
        key = _head_key(row[0])
        if not key or key == '项目':
            continue
        val = row[1]
        raw[key] = val
    # ---- 封面与实验条件
    if _text(raw.get('实验')):
        cfg['report_title'] = _text(raw['实验'])
    for key, name in (('姓名', 'student_name'), ('学号', 'student_id'),
                      ('实验日期', 'date')):
        if _text(raw.get(key)):
            cfg[name] = _text(raw[key])
    group_txt = _text(raw.get('组别/组号', raw.get('组别')))
    if group_txt:
        parts = [p.strip() for p in group_txt.split('/')]
        if len(parts) >= 2:
            if parts[0]:
                cfg['group'] = parts[0]
            if parts[1]:
                cfg['group_no'] = parts[1]
        else:
            cfg['group'] = group_txt
    # ---- 数值条件：⚠ 温度/γ_w/σ 属于 **data** 不是 config
    #   （analysis.default_config() 里没有这些键，放 cfg 会被 server._coerce
    #   整条丢掉，界面上就还是旧温度）。所以这里写进 data_patch。
    for key, name in (('气泡法温度', 'temperature_bubble'),
                      ('吊片法温度', 'temperature_plate'),
                      ('γ_w', 'gamma_water'),
                      ('单次读数σ_h', 'sigma_read'),
                      ('吊片法单次读数σ_γ', 'sigma_plate')):
        val = _num(raw.get(key))
        if val is not None:
            data_patch[name] = val
    # 纯水（吊片法）逐次读数，用 / 分隔；缺了就让调用方沿用当前值
    water = []
    for piece in re.split(r'[/、,;]', _text(raw.get('纯水γ(吊片法)'))):
        v = _num(piece)
        if v is not None:
            water.append(v)
    if water:
        data_patch['water_plate'] = water
    # ---- 读数方式 / 零点 / 横轴
    mode_txt = _text(raw.get('液柱读数方式'))
    if mode_txt in MODE_TEXT:
        cfg['height_mode'] = MODE_TEXT[mode_txt]
    zero_txt = _text(raw.get('压力计零点'))
    if zero_txt in ZERO_TEXT:
        cfg['zero_correction'] = ZERO_TEXT[zero_txt]
    axis_txt = _text(raw.get('作图横轴'))
    if 'ln' in axis_txt.lower():
        cfg['conc_axis'] = 'ln'
    elif 'lg' in axis_txt.lower():
        cfg['conc_axis'] = 'lg'
    # ---- 两臂高度总和 S：手填才固化，自动估计的留 0 让内核重新估
    s_val = _num(raw.get('两臂高度总和s'))
    s_src = _text(raw.get('s的来源'))
    # height_sum 是 config 项（见 analysis.default_config），只给 info 留痕
    info_extra['height_sum'] = s_val
    info_extra['height_sum_source'] = s_src
    if s_val is not None:
        if '手填' in s_src:
            cfg['height_sum'] = s_val
        elif cfg.get('height_mode') in ('left', 'right'):
            # 只读一侧时必须给 S，否则整表 Δh 算不出来
            cfg['height_sum'] = s_val
        else:
            cfg['height_sum'] = 0.0
    return cfg, data_patch, info_extra


def _parse_result(grid, data_patch):
    """结果表 → 两种方法各自的温度（说明表里可能没有这两行）。

    温度是 **data** 项：写进 data_patch，说明表里已有的优先（setdefault 语义，
    由调用方先填 parsed 再调本函数保证）。
    """
    headers = [c for c in (grid[0] if grid else [])]
    key_t = None
    for j, h in enumerate(headers):
        if _head_key(h).startswith('t'):
            s = _norm(h)
            if s.startswith('t/'):
                key_t = j
                break
    if key_t is None:
        return
    for row in grid[1:]:
        label = _text(row[0]) if row else ''
        val = _num(row[key_t]) if key_t < len(row) else None
        if val is None:
            continue
        if '气泡' in label:
            data_patch.setdefault('temperature_bubble', val)
        elif '吊片' in label:
            data_patch.setdefault('temperature_plate', val)


def _side_values(row, cols):
    out = []
    for _, j in cols:
        out.append(_num(row[j]) if j < len(row) else None)
    return out


def _trim(values):
    """去掉尾部的空值（Excel 里末尾留白不该变成一个 None 读数）。"""
    vals = list(values)
    while vals and vals[-1] is None:
        vals.pop()
    return vals


def _parse_bubble(grid, mode, warnings):
    """最大气泡法表 → data['bubble'] 行。"""
    if not grid:
        return []
    headers = grid[0]
    roles = _column_roles(headers)
    if roles['c'] is None or (not roles['left'] and not roles['right']):
        raise ImportDataError(
            '「%s」表里找不到 c 列或 h_l/h_r 列；表头是：%s'
            % (SHEET_BUBBLE, '、'.join(_text(h) for h in headers if _text(h))))
    rows = []
    for raw in grid[1:]:
        if not raw or all(v in (None, '') for v in raw):
            continue
        c = _num(raw[roles['c']]) if roles['c'] < len(raw) else None
        if c is None:
            continue
        left = _trim(_side_values(raw, roles['left']))
        right = _trim(_side_values(raw, roles['right']))
        derived = (_yes(raw[roles['derived']])
                   if roles['derived'] is not None
                   and roles['derived'] < len(raw) else False)
        fit = (_yes(raw[roles['fit']])
               if roles['fit'] is not None and roles['fit'] < len(raw)
               else False)
        # 换算值不当实测：只读一侧时把换算出来的那一侧清掉，
        # 让内核照同样的方式重新换算（否则 σ 会按两侧实测算）。
        if mode == 'left':
            right = []
        elif mode == 'right':
            left = []
        elif derived and left and right:
            warnings.append(
                'c = %g 那一行导出时只有一侧的读数，另一侧是按 S 换算的；'
                '两侧都读模式下无法判断哪侧是实测值，已原样保留'
                '（Δh 不变，但 σ(Δh) 会比原来略小）' % c)
        rows.append({'c': c, 'left': left, 'right': right, 'fit': fit})
    return rows


def _parse_plate(grid):
    """吊片法表 → data['plate'] 行。"""
    if not grid:
        return []
    headers = grid[0]
    roles = _column_roles(headers)
    if roles['c'] is None or not roles['gamma']:
        raise ImportDataError(
            '「%s」表里找不到 c 列或 γ 列；表头是：%s'
            % (SHEET_PLATE, '、'.join(_text(h) for h in headers if _text(h))))
    rows = []
    for raw in grid[1:]:
        if not raw or all(v in (None, '') for v in raw):
            continue
        c = _num(raw[roles['c']]) if roles['c'] < len(raw) else None
        if c is None:
            continue
        gamma = _trim(_side_values(raw, roles['gamma']))
        fit = (_yes(raw[roles['fit']])
               if roles['fit'] is not None and roles['fit'] < len(raw)
               else False)
        rows.append({'c': c, 'gamma': gamma, 'fit': fit})
    return rows


def _parse_trio(grid, mode, warnings):
    """零点与纯水表 → (data['zero'], data['water_bubble'])。"""
    if not grid:
        return None, None
    headers = grid[0]
    roles = _column_roles(headers)
    label_col = roles['label'] if roles['label'] is not None else 0
    out = {}
    for raw in grid[1:]:
        if not raw:
            continue
        label = _text(raw[label_col]) if label_col < len(raw) else ''
        if not label:
            continue
        left = _trim(_side_values(raw, roles['left']))
        right = _trim(_side_values(raw, roles['right']))
        if mode == 'left':
            right = []
        elif mode == 'right':
            left = []
        if '零点' in label:
            out['zero'] = {'left': left, 'right': right}
        elif '纯水' in label:
            if any(v is not None for v in left) or \
                    any(v is not None for v in right):
                out['water_bubble'] = {'left': left, 'right': right}
    if 'zero' not in out and warnings is not None:
        warnings.append('数据表里没有「压力计零点」这一行，零点差将按 0 处理')
    return out.get('zero'), out.get('water_bubble')


# ---------------------------------------------------------------- csv 长表
CSV_REQUIRED = ('方法', 'c')


def _read_csv(raw, base_data, warnings):
    """导出得到的 csv：两种方法摊在一张长表里（只有均值列）。

    只能还原到「每个点 1 次读数」——原始平行读数已经被平均掉了，
    这一点必须在 warnings 里说清楚，否则用户会以为不确定度还算得对。
    """
    text = _decode(raw)
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r and any(str(c).strip() for c in r)]
    if not rows:
        raise ImportDataError('csv 是空的')
    head = [_head_key(c) for c in rows[0]]
    if not any(h.startswith('方法') for h in head):
        raise ImportDataError(
            '这张 csv 不像本工具导出的数据表（首行没有「方法」列）：%s'
            % '、'.join(_text(c) for c in rows[0][:6]))
    col = {}
    for j, h in enumerate(head):
        if h.startswith('方法'):
            col['method'] = j
        elif h == 'c' or h.startswith('浓度'):
            col['c'] = j
        elif h.startswith('h_l均值'):
            col['hl'] = j
        elif h.startswith('h_r均值'):
            col['hr'] = j
        elif h.startswith('γ均值') or h == 'γ':
            col['gamma'] = j
        elif h.startswith('参与拟合'):
            col['fit'] = j
    if 'c' not in col:
        raise ImportDataError('csv 首行里找不到「c」列')
    bubble, plate = [], []
    for r in rows[1:]:
        get = lambda k: (_num(r[col[k]]) if k in col and col[k] < len(r) else None)
        c = get('c')
        if c is None:
            continue
        fit = _yes(r[col['fit']]) if 'fit' in col and col['fit'] < len(r) else False
        label = _text(r[col['method']]) if 'method' in col and col['method'] < len(r) else ''
        if '吊片' in label:
            g = get('gamma')
            plate.append({'c': c, 'gamma': [_trim([g])[0]] if g is not None else [],
                          'fit': fit})
        else:
            hl, hr = get('hl'), get('hr')
            bubble.append({'c': c,
                           'left': [hl] if hl is not None else [],
                           'right': [hr] if hr is not None else [],
                           'fit': fit})
    if not bubble and not plate:
        raise ImportDataError('csv 里没有读到任何数据行')
    warnings.append('csv 只有平均值列：导入后每个浓度点按「1 次读数」处理，'
                    'σ 会比导出时大；需要保留平行读数请改用 .xlsx 数据表回读')
    data = dict(base_data or {})
    cfg = {}
    if bubble:
        data['bubble'] = bubble
        cfg['repeat_n_bubble'] = 1
    if plate:
        data['plate'] = plate
        cfg['repeat_n_plate'] = 1
    return data, cfg, {'sheets': [], 'format': 'csv',
                       'counts': {'bubble': len(bubble), 'plate': len(plate)},
                       'repeat': {'bubble': 1, 'plate': 1},
                       'axis': None, 'height_mode': None}


# ---------------------------------------------------------------- 对外接口
def read(name, raw, base_data=None):
    """把一份数据表读成 (data, config, info)。

    参数
    ----
    name : 文件名（用来判 xlsx / csv；没有后缀时看内容头）
    raw  : 文件字节
    base_data : 当前界面里的数据；表里没有的项（如吊片法纯水读数）
                沿用这里的值，不静默清空。

    → dict(data=…, config=…, info=…, warnings=[…])
    """
    if not raw:
        raise ImportDataError('文件是空的：%s' % (name or '(未命名)'))
    fmt = _fmt_of(name, raw)
    warnings = []
    data = dict(base_data or {})

    if fmt == 'csv':
        data, cfg, info = _read_csv(raw, data, warnings)
        return dict(data=data, config=cfg, info=info, warnings=warnings)

    grids = _read_xlsx(raw)
    info_grid = _find_sheet(grids, SHEET_INFO)
    result_grid = _find_sheet(grids, SHEET_RESULT)
    bubble_grid = _find_sheet(grids, SHEET_BUBBLE)
    plate_grid = _find_sheet(grids, SHEET_PLATE)
    trio_grid = _find_sheet(grids, SHEET_TRIO)

    # 工作表名对不上时按表头内容逐个辨认。
    # ⚠ 必须**逐表**判断：只改了一两个名字（比如把「最大气泡法」改成 Sheet1，
    #   「零点与纯水」还是原名）时，三表全缺的条件不成立，逐表猜才补得上。
    if bubble_grid is None or plate_grid is None or trio_grid is None:
        guess = _guess_sheets(grids)
        guessed = []
        if bubble_grid is None and guess.get('bubble') is not None:
            bubble_grid = guess['bubble']
            guessed.append(SHEET_BUBBLE)
        if plate_grid is None and guess.get('plate') is not None:
            plate_grid = guess['plate']
            guessed.append(SHEET_PLATE)
        if trio_grid is None and guess.get('trio') is not None:
            trio_grid = guess['trio']
            guessed.append(SHEET_TRIO)
        if guessed:
            warnings.append('有工作表被改名，已按表头内容辨认：%s'
                            % '、'.join(guessed))
        if bubble_grid is None and plate_grid is None and trio_grid is None:
            raise ImportDataError(
                '这个工作簿里找不到「%s」「%s」或「%s」表（现有工作表：%s）。'
                '请用本工具导出的「数据表 .xlsx」回读，或先把原始读数'
                '按「导入类型」逐个导入。'
                % (SHEET_BUBBLE, SHEET_PLATE, SHEET_TRIO,
                   '、'.join(grids.keys())))

    cfg = {}
    parsed = {}
    info_extra = {}
    if info_grid is not None:
        info_cfg, parsed, info_extra = _parse_info(info_grid)
        cfg.update(info_cfg)
    if result_grid is not None:
        # 说明表里已有的温度优先（_parse_result 用 setdefault）；缺了才用结果表补
        _parse_result(result_grid, parsed)

    mode = cfg.get('height_mode')
    if mode is None:
        mode = 'both'
        if trio_grid is not None or bubble_grid is not None:
            warnings.append('说明表里没写「液柱读数方式」，按「两侧都读」处理')

    # 说明表里的 data 片段（温度/γ_w/σ/纯水读数）。表里没有的项沿用 base_data，
    # 绝不静默清空——旧版导出的表本来就没有这几行。
    for key, val in parsed.items():
        data[key] = val
    if 'water_plate' not in parsed and not data.get('water_plate'):
        warnings.append('数据表里没有吊片法纯水读数（旧版导出），报告里'
                        '「纯水 γ（吊片法）」会沿用当前界面的值')

    if bubble_grid is not None:
        data['bubble'] = _parse_bubble(bubble_grid, mode, warnings)
    if plate_grid is not None:
        data['plate'] = _parse_plate(plate_grid)
    zero, water = _parse_trio(trio_grid, mode, warnings)
    if zero:
        data['zero'] = zero
    if water:
        data['water_bubble'] = water

    # 平行次数由表头的最大序号决定（1~6 之外不写进配置，交给内核按数据推）
    def _repeat(rows, side_key, extra=()):
        n = 0
        for r in rows or []:
            n = max(n, len([v for v in (r.get(side_key) or []) if v is not None]))
        for obj in extra:
            if isinstance(obj, dict):
                n = max(n, len([v for v in (obj.get(side_key) or [])
                                if v is not None]))
        return n

    nb = _repeat(data.get('bubble'), 'left', (data.get('zero'),
                                              data.get('water_bubble')))
    np_ = _repeat(data.get('plate'), 'gamma')
    if 1 <= nb <= 6:
        cfg['repeat_n_bubble'] = nb
    if 1 <= np_ <= 6:
        cfg['repeat_n_plate'] = np_

    info = dict(
        sheets=[n for n in (SHEET_INFO, SHEET_RESULT, SHEET_BUBBLE,
                            SHEET_PLATE, SHEET_TRIO) if _find_sheet(grids, n)],
        format='xlsx',
        counts={'bubble': len(data.get('bubble') or []),
                'plate': len(data.get('plate') or [])},
        repeat={'bubble': nb, 'plate': np_},
        axis=cfg.get('conc_axis'),
        height_mode=mode,
        height_sum=cfg.get('height_sum'),
    )
    if not data.get('bubble') and not data.get('plate'):
        raise ImportDataError('数据表里没有读到任何浓度点（%s/%s 两表都是空的）'
                              % (SHEET_BUBBLE, SHEET_PLATE))
    return dict(data=data, config=cfg, info=info, warnings=warnings)


def read_path(path, base_data=None):
    """文件路径版本（服务端从数据目录读文件时用）。"""
    import os
    with open(path, 'rb') as fh:
        raw = fh.read()
    return read(os.path.basename(path), raw, base_data)
