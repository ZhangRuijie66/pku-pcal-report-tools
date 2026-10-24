# -*- coding: utf-8 -*-
"""报告工作区快照：把“这份报告是用什么数据和参数生成的”留在报告旁边。

导出时在报告同目录写 workspace.json，内容包括：
  · 本次界面的完整输入（config / rounds / 手工录入的数据）
  · 引用到的数据文件路径、大小、SHA256
  · 数据目录的文件清单（只记名字/大小/时间，不哈希整目录）
  · 模板路径与 SHA256
  · 工具版本、canonical 核心版本、Python 与关键依赖版本

它不是报告归档，不复制原始数据；只提供可追溯性和“载入上次工作区”的依据。
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import sys
import time

CORE_VERSION = '1.0.0'
SCHEMA = 1

FILE_EXTS = {'.csv', '.txt', '.json', '.xlsx', '.xls', '.xlsm', '.png',
             '.jpg', '.jpeg'}
MAX_HASH_BYTES = 50 * 1024 * 1024
MAX_DIR_ENTRIES = 200


def sha256_file(path):
    h = hashlib.sha256()
    size = 0
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _hash_or_none(path):
    try:
        if os.path.getsize(path) > MAX_HASH_BYTES:
            return None, os.path.getsize(path), '文件超过 50 MB，未计算哈希'
        digest, size = sha256_file(path)
        return digest, size, ''
    except OSError as exc:
        return None, None, str(exc)


def package_versions():
    out = {}
    for dist in ('numpy', 'scipy', 'matplotlib', 'python-docx', 'openpyxl'):
        try:
            out[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            out[dist] = None
    return out


def core_files():
    here = os.path.dirname(os.path.abspath(__file__))
    out = {}
    for name in ('__init__.py', 'omml.py', 'docxkit.py', 'workspace.py'):
        path = os.path.join(here, name)
        if not os.path.exists(path):
            continue
        digest, size, err = _hash_or_none(path)
        out[name] = {'sha256': digest, 'size': size, 'error': err}
    return out


def tool_version():
    try:
        pkg = importlib.import_module(__package__ or 'pcal')
        return str(getattr(pkg, '__version__', '') or '')
    except Exception:                                # noqa: BLE001
        return ''


def _iter_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield value


def _resolve_path(value, base_dirs):
    value = (value or '').strip().strip('"')
    if not value or len(value) > 4096:
        return None
    if os.path.isabs(value):
        return os.path.normpath(value) if os.path.exists(value) else None
    for base in base_dirs:
        if not base:
            continue
        cand = os.path.normpath(os.path.join(base, value))
        if os.path.exists(cand):
            return cand
    if os.path.exists(value):
        return os.path.normpath(os.path.abspath(value))
    return None


def collect_inputs(payload, config, extra=None):
    """扫描 payload/config/extra 里的字符串，找出存在的文件与目录。"""
    base_dirs = []
    for source in (config, payload, extra):
        if isinstance(source, dict):
            for key in ('data_dir', 'default_dir', 'data_path', 'work_dir'):
                if isinstance(source.get(key), str):
                    base_dirs.append(source[key])
    base_dirs = [d for d in base_dirs if os.path.isdir(d)]

    files, dirs, seen = {}, {}, set()
    for source in (payload, config, extra):
        for value in _iter_strings(source):
            path = _resolve_path(value, base_dirs)
            if not path:
                continue
            real = os.path.abspath(path)
            if real in seen:
                continue
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext not in FILE_EXTS:
                    continue
                seen.add(real)
                digest, size, err = _hash_or_none(path)
                files[real] = {
                    'path': real, 'size': size, 'sha256': digest,
                    'mtime': time.strftime('%Y-%m-%d %H:%M:%S',
                                           time.localtime(os.path.getmtime(path))),
                    'error': err,
                }
            elif os.path.isdir(path):
                seen.add(real)
                entries = []
                try:
                    names = sorted(os.listdir(path))[:MAX_DIR_ENTRIES]
                except OSError as exc:
                    entries = [{'error': str(exc)}]
                    names = []
                for name in names:
                    full = os.path.join(path, name)
                    try:
                        entries.append({
                            'name': name,
                            'size': os.path.getsize(full) if os.path.isfile(full) else None,
                            'mtime': time.strftime(
                                '%Y-%m-%d %H:%M:%S',
                                time.localtime(os.path.getmtime(full))),
                        })
                    except OSError:
                        entries.append({'name': name})
                dirs[real] = {'path': real, 'entries': entries}
    return list(files.values()), list(dirs.values())


def template_info(template_path):
    if not template_path or not os.path.exists(template_path):
        return {'path': template_path or '', 'missing': True,
                'sha256': None, 'size': None}
    digest, size, err = _hash_or_none(template_path)
    return {'path': os.path.abspath(template_path), 'missing': False,
            'sha256': digest, 'size': size, 'error': err}


def snapshot(payload, config, tool, template_path, extra=None):
    files, dirs = collect_inputs(payload, config, extra)
    return {
        'schema': SCHEMA,
        'tool': tool,
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'tool_version': tool_version(),
        'core': {'version': CORE_VERSION, 'files': core_files()},
        'environment': {
            'python': sys.version.split()[0],
            'platform': platform.platform(),
            'packages': package_versions(),
        },
        'template': template_info(template_path),
        'config': config,
        'payload': payload,
        'files': files,
        'data_dirs': dirs,
        'extra': extra or {},
    }


def save(out_dir, payload, config, tool, template_path, extra=None):
    data = snapshot(payload, config, tool, template_path, extra)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'workspace.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    return path


def load(out_dir):
    path = os.path.join(out_dir, 'workspace.json')
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)
