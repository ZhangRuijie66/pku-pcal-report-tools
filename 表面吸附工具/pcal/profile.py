# -*- coding: utf-8 -*-
"""全工具共用的个人档案 / 年度数据目录。

profile.json 放在实验根目录（与各工具目录同级），由入口页维护：

    {
      "student_name": "测试同学",
      "student_id": "2300000000",
      "group": "3",
      "group_no": "8",
      "data_dirs": {
        "燃烧热工具": "D:\\...\\1 燃烧热",
        ...
      }
    }

各模块的 load_settings() 会调用 merge_saved()：档案里的姓名/学号/组别/组号
和个人数据目录优先于本地 settings.json，这样换学年只要在入口页改一次。
没有 profile.json 时完全退回原来的行为。
"""
from __future__ import annotations

import json
import os

PERSONAL_KEYS = ('student_name', 'student_id', 'group', 'group_no')


def _layout():
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.basename(here) == '_core':
        return parent, ''
    return os.path.dirname(parent), os.path.basename(parent)


def repo_root():
    # 同步后在 <工具>/pcal/profile.py；canonical 在 _core/profile.py
    return _layout()[0]


def tool_dir_name():
    return _layout()[1]


def profile_path():
    return os.environ.get(
        'PCAL_PROFILE', os.path.join(repo_root(), 'profile.json'))


def load():
    try:
        with open(profile_path(), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def merge_saved(saved):
    """把档案合并进 settings.json 读出的字典；档案值优先。"""
    out = dict(saved or {})
    prof = load()
    for key in PERSONAL_KEYS:
        value = prof.get(key)
        if value not in (None, ''):
            out[key] = value
    dirs = prof.get('data_dirs')
    if isinstance(dirs, dict):
        path = dirs.get(tool_dir_name())
        if isinstance(path, str) and path.strip():
            out['data_dir'] = path.strip()
    return out
