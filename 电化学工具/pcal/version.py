# -*- coding: utf-8 -*-
"""整套物化实验报告工具的版本号 —— 唯一真源。

类比光谱可视化分析工具（SpectraLab）的 `gui_config.APP_VERSION`：
窗口标题、入口页、更新检查、打包脚本都从这里取版本，不许各处硬编码。

发版流程（见仓库根 `make_release.py` 与 README「版本号与自动更新」）：

    1. `python make_release.py patch --notes "..." --type 修复 --apply`
    2. 它改本文件的 APP_VERSION / RELEASE_DATE、写 更新日志/CHANGELOG_vX_Y_Z.md、
       跑 `_core/sync_core.py --apply` 把本文件同步进 11 个工具的 pcal/、
       跑全量测试、然后 commit + tag vX.Y.Z + push。

编号规则（用户 2026-11-06 定稿，与光谱工具一致）：
  · 三段式 X.Y.Z，第三段只装**递增序号**（.1、.2、.3…），修复类别用文字写进
    CHANGELOG 首段的「类型：」，不编进版本号；
  · MAJOR = 破坏性变更（目录结构、报告输出布局、settings.json 键名）；
  · MINOR = 用户可感知的新功能（新实验模块、新导出通道、自动更新本身）；
  · 不允许跳号，未发布过的号不使用。
"""
from __future__ import annotations

import re

APP_NAME = '物化实验报告工具'
APP_VERSION = '1.1.0'
RELEASE_DATE = '2026-11-09'

# 更新源（用户 2026-11-06 确认：认 git tag，不看 main 的最新提交）
REPO_SLUG = 'ZhangRuijie66/pku-pcal-report-tools'
DEFAULT_BRANCH = 'main'
GITHUB_API = 'https://api.github.com'
CODELOAD = 'https://codeload.github.com'
REPO_URL = 'https://github.com/' + REPO_SLUG

# 更新日志目录（相对安装根目录）
CHANGELOG_DIR = '更新日志'

_VERSION_RE = re.compile(r'^\s*[vV]?\s*(\d+)\.(\d+)\.(\d+)\s*$')


def version_tuple(text):
    """'v1.0.10' / '1.0.10' -> (1, 0, 10)；解析不了返回 None。"""
    if text is None:
        return None
    m = _VERSION_RE.match(str(text))
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def normalize(text):
    """'v1.0.0' -> '1.0.0'；解析不了原样返回（去空白）。"""
    parts = version_tuple(text)
    if parts is None:
        return str(text or '').strip()
    return '%d.%d.%d' % parts


def is_newer(candidate, current):
    """candidate 是否比 current 新。无法解析的一律视为「不是更新」。"""
    a, b = version_tuple(candidate), version_tuple(current)
    if a is None or b is None:
        return False
    return a > b


def tag_for(version):
    """'1.0.0' -> 'v1.0.0'。"""
    return 'v' + normalize(version)


def changelog_filename(version):
    """'1.0.0' -> 'CHANGELOG_v1_0_0.md'（下划线格式，避免 4.10 与 4.1 混淆）。"""
    parts = version_tuple(version) or (0, 0, 0)
    return 'CHANGELOG_v%d_%d_%d.md' % parts


def changelog_relpath(version):
    return CHANGELOG_DIR + '/' + changelog_filename(version)


def bump(version, kind='patch'):
    """按 patch/minor/major 算下一个版本号（patch 纯递增 +1）。"""
    major, minor, patch = version_tuple(version) or (0, 0, 0)
    kind = (kind or 'patch').lower()
    if kind == 'major':
        return '%d.0.0' % (major + 1)
    if kind == 'minor':
        return '%d.%d.0' % (major, minor + 1)
    if kind != 'patch':
        raise ValueError('未知的发版类型：%s' % kind)
    return '%d.%d.%d' % (major, minor, patch + 1)


def summary():
    """给入口页 / 网页 / 打包脚本用的一小份版本信息。"""
    return {
        'name': APP_NAME,
        'version': APP_VERSION,
        'release_date': RELEASE_DATE,
        'repo': REPO_SLUG,
        'repo_url': REPO_URL,
        'tag': tag_for(APP_VERSION),
        'changelog': changelog_relpath(APP_VERSION),
    }
