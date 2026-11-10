# -*- coding: utf-8 -*-
"""把任意 Python 对象变成**合法 JSON** 可序列化的结构。

## 为什么需要它

本项目的每个模块都在 ``pcal/server.py`` 里用 ``json.dumps(...)`` 回给浏览器。
``json.dumps`` 的默认行为是把 ``float('nan')`` / ``±inf`` 写成裸
``NaN`` / ``Infinity`` / ``-Infinity`` —— **这三个都不是合法 JSON 字面量**。
浏览器端 ``await res.json()`` 会直接抛

    SyntaxError: Unexpected token 'N', "..., "sd": NaN}, "al" ... is not valid JSON

于是前端 ``boot()`` 里的 ``catch`` 把它显示成「初始化失败：…」，
**整个界面打不开**，而错误消息里只有一个 ``N`` 字符，完全指不到源头。

2026-11-10 真栽过：化学动力学模块分析内核里 ``alpha_inf['sd']`` 取到
``float('nan')``（用户没填重复次数的标准差），``/api/state`` 整包坏掉，
页面卡在「初始化失败」。11 个模块的 ``_json`` 各写各的，全都有这个隐患。

## 口径

| 输入 | 输出 | 理由 |
| --- | --- | --- |
| ``float('nan')`` / ``inf`` | ``None`` | 「没算出来」≠「算出来是 0」，前端显示「—」 |
| ``numpy`` 标量 | Python 原生类型 | ``json`` 不认 numpy 类型 |
| ``numpy.ndarray`` | ``list``（递归清洗） | 同上 |
| 其它非原生对象 | ``str(obj)`` | 兜底，绝不因序列化失败让接口 500 |

配套 ``core_json_dumps()`` 强制 ``allow_nan=False``：即使本模块漏掉某个
嵌套位置，也会**抛异常**（由 server 的 ``_error`` 回一条可读错误），
而不是悄悄吐出半截坏 JSON 让浏览器语法错。

注意 ``None`` 会保留：JSON 的 ``null`` 与「0」语义不同，不能混。
"""
from __future__ import annotations

import json
import math


def to_jsonable(obj):
    """递归把对象清洗成 ``json.dumps`` 一定能处理的纯原生结构。

    ``NaN`` / ``±inf`` → ``None``（前端显示「—」）。容器保持类型
    （dict 保持键、list 保持顺序），不丢弃任何条目。
    """
    # numpy 可选：不是所有调用方都装了；装了才做标量/数组转换
    try:
        import numpy as np
    except Exception:                                    # noqa: BLE001
        np = None

    if obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, bool):                            # bool 要在 int 之前判
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None

    if np is not None:
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            v = float(obj)
            return v if math.isfinite(v) else None
        if isinstance(obj, np.ndarray):
            return [to_jsonable(v) for v in obj.tolist()]

    if isinstance(obj, dict):
        return {to_jsonable(k) if not isinstance(k, str) else k: to_jsonable(v)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = list(obj)
        return [to_jsonable(v) for v in items]

    # 其它对象（Path、datetime、自定义类…）：退化成字符串，绝不抛
    return str(obj)


def core_json_dumps(obj, **kwargs):
    """清洗后序列化，并**禁止** NaN/Infinity 逃出去。

    额外好处：``allow_nan=False`` 让「本模块漏清洗」变成显式异常，
    便于在测试里被发现，而不是变成浏览器里一句看不懂的语法错。
    """
    kwargs.pop('allow_nan', None)
    return json.dumps(to_jsonable(obj), ensure_ascii=False, allow_nan=False,
                      **kwargs)


def json_default(obj):
    """给 ``json.dumps(default=...)`` 用的一层兜底（不含递归清洗）。

    模块里若只换 ``default=`` 而没换整体 dumps，至少 numpy 标量与数组
    能被转成原生类型；``nan`` 仍会漏——所以推荐用 :func:`core_json_dumps`。
    """
    try:
        import numpy as np
    except Exception:                                    # noqa: BLE001
        np = None
    if np is not None:
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            v = float(obj)
            return v if math.isfinite(v) else None
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    return str(obj)
