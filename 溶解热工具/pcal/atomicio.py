# -*- coding: utf-8 -*-
"""原子写盘 + 坏文件留证：所有"写用户数据"的地方都该走这里。

为什么需要这个模块
------------------
原来的写法到处都是：

    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)

`open(..., 'w')` **先把文件截断成 0 字节**，然后才轮到 `json.dump`。
只要序列化中途抛异常（数据里混进 numpy 标量、set、自定义对象，或者磁盘写满），
文件就被留在"半截 JSON"的状态——用户的实验读数直接没了，而且没有任何备份。

正确顺序是「先在内存里序列化成功，再整体替换」：

    text = json.dumps(data, ...)      # 失败就在这里抛，原文件一个字节都没动
    write tmp; os.replace(tmp, path)  # os.replace 在同一分区上是原子的

`_core/updater.py` 早就用了这套（`os.replace`），只是用户数据路径没跟上。

另外两个配套动作：

* `quarantine()`：读到坏 JSON 时不要 `except: pass` 然后拿默认值覆盖回去，
  应该把坏文件改名成 `*.corrupt-<时间戳>` 留证，再报错/回落。用户至少还能
  把文件捞回来手工修。
* `read_json()`：读失败时区分"不存在"（正常，返回默认）和"存在但坏了"
  （必须让调用方知道），不要混为一谈。
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import tempfile
import time

__all__ = [
    'AtomicWriteError', 'atomic_write_text', 'atomic_write_bytes',
    'atomic_write_json', 'quarantine', 'read_json', 'CorruptFileError',
]


class AtomicWriteError(OSError):
    """写盘失败（磁盘满、只读、被占用等），原文件保持不变。"""


class CorruptFileError(ValueError):
    """文件存在但不是合法 JSON。"""

    def __init__(self, path, original):
        self.path = path
        self.original = original
        super().__init__('%s 不是合法 JSON：%s' % (path, original))


def _tmp_in_same_dir(path):
    """在目标文件**同目录**建临时文件。

    必须同目录，否则 os.replace 会跨分区，退化成"复制+删除"、失去原子性。
    """
    d = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.~write-', suffix='.tmp', dir=d)
    return fd, tmp


def atomic_write_bytes(path, data):
    """把 bytes 原子地写到 path。失败时原文件不变，临时文件被清掉。"""
    fd, tmp = _tmp_in_same_dir(path)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write_text(path, text, encoding='utf-8', newline=''):
    """把 str 原子地写到 path（换行不做转换，保持内容逐字节可控）。"""
    if newline != '':
        text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', newline)
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path, data, encoding='utf-8', **dumps_kwargs):
    """原子地写 JSON。

    **先在内存里 dumps 成功，才碰磁盘**——这是与旧写法的唯一区别，
    也正是"序列化抛异常把文件截断成空"那个 bug 的根因。
    """
    kwargs = {'ensure_ascii': False, 'indent': 2}
    kwargs.update(dumps_kwargs)
    text = json.dumps(data, **kwargs)      # 失败在这里抛，原文件完好
    return atomic_write_text(path, text, encoding=encoding)


def quarantine(path, reason='corrupt'):
    """把坏文件改名留证，返回新路径（文件不存在则返回 None）。

    命名形如 `电导率数据.json.corrupt-20261108-213015`，用户能一眼找到并捞回来。
    """
    if not path or not os.path.isfile(path):
        return None
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = '%s.%s-%s' % (path, reason, stamp)
    n = 1
    while os.path.exists(target):
        target = '%s.%s-%s-%d' % (path, reason, stamp, n)
        n += 1
    try:
        os.replace(path, target)
    except OSError:
        try:
            shutil.move(path, target)
        except OSError as exc:
            raise AtomicWriteError('无法把坏文件改名留证：%s' % exc) from exc
    return target


def read_json(path, default=None):
    """读 JSON，区分「不存在」与「存在但坏了」。

    * 文件不存在 → 返回 default（正常情形，调用方拿默认值即可）
    * 文件存在但不是合法 JSON → 抛 CorruptFileError，**绝不当成 default**
      （旧代码 `except (OSError, ValueError): pass` 是静默覆盖的入口）
    """
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (ValueError, UnicodeDecodeError) as exc:
        raise CorruptFileError(path, exc) from exc
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return default
        raise
