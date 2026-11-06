# -*- coding: utf-8 -*-
"""自动抓取更新：认 git tag、下载 codeload zip、备份后原位替换、失败自动回滚。

设计口径（用户 2026-11-06 确认）
--------------------------------
* **更新源是 tag，不是 main**：发版时 `git push` 一个 `vX.Y.Z` tag，
  这里拉 `api.github.com/repos/<slug>/tags` 找语义最大者与本地
  `_core/version.APP_VERSION` 比较。
* **只在用户点「下载并安装」时才真正替换代码**；检查可以后台做（有节流）。
* **用户数据永不覆盖**：`settings.json`、`profile.json`、各工具 `data/`、
  `实验报告输出/`、`发布/`、日志、`.git/` 全部在受保护名单里。
* **先备份后覆盖，装完自检，坏了自动还原**：备份落在
  `_core/updates/backups/<旧版本>-<时间>/`，只留最近 2 份。

对外接口见 `_tmp_update/CONTRACT.md` 的 C 节；页面侧的调用在
`物化实验报告工具/portal.py` 的 `/api/update/*`。

测试与镜像用环境变量覆盖（见 CONTRACT）：
    PCAL_UPDATE_API_BASE / PCAL_UPDATE_CODELOAD / PCAL_UPDATE_ROOT
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_FALLBACK = os.path.dirname(HERE)
if ROOT_FALLBACK not in sys.path:
    sys.path.insert(0, ROOT_FALLBACK)
try:                                     # 正常情形：以 _core 包的一部分导入
    from _core import version as _version
except ImportError:                      # 单独拷走 / 直接跑脚本时的兜底
    import version as _version           # type: ignore

APP_NAME = _version.APP_NAME
MIN_CHECK_INTERVAL = 6 * 3600            # 自动检查的节流间隔（秒）
MAX_PACKAGE_BYTES = 200 * 1024 * 1024    # 解包总量上限，防 zip 炸弹
KEEP_BACKUPS = 2
USER_AGENT = 'pcal-updater/1.0 (+%s)' % _version.REPO_URL
RAW_BASE = os.environ.get('PCAL_UPDATE_RAW') or 'https://raw.githubusercontent.com'

# ---------------------------------------------------------------- 白名单/保护名单
# 11 个实验模块目录（顺序 = 讲义实验顺序）
TOOL_DIRS = (
    '燃烧热工具', '溶解热工具', '蒸气压工具', '双液系工具', '化学动力学工具',
    '表面吸附工具', '电导率工具', '电化学工具', '偶极矩工具', '磁化率工具',
    '紫外光谱工具',
)
PORTAL_DIR = '物化实验报告工具'
TOP_DIRS = ('_core', '_tools', 'tests', PORTAL_DIR, '更新日志') + TOOL_DIRS
ROOT_FILES = (
    'README.md', 'LICENSE', 'requirements.txt',
    '启动入口.cmd', '启动入口.vbs', '停止服务.vbs', '安装依赖.cmd',
    'make_portable.py', 'make_release.py',
)
# 任意层级的目录名/文件名命中即跳过（用户数据、缓存、备份）
PROTECTED_PARTS = {
    'settings.json', 'profile.json', 'update_state.json',
    '实验报告输出', '发布', '.git', '.vscode', '.idea',
    'updates', 'backups', 'data', '__pycache__', '_test_out',
    '启动日志.log', '.dsh-ops-update-lock',
}
PROTECTED_SUFFIX = ('.pyc', '.pyo', '.bak', '.log', '.zip')
PROTECTED_PREFIX = ('~$', '$', '.~lock')

# 递归删除时绝不能碰的目录（在安装根下的相对路径）
NEVER_DELETE = ('_core/updates', '_core/backups', '实验报告输出', '发布', '.git',
                '_tools/启动日志.log')

STATE_FILE = 'update_state.json'
_CHECKS_LOCK = threading.Lock()          # 串行化联网检查
_APPLY_LOCK = threading.Lock()           # 串行化安装/回滚


class UpdateError(Exception):
    """带中文说明的更新失败；消息可直接展示给用户。"""


class NoReleaseTag(UpdateError):
    """远端还没有任何 vX.Y.Z 发版 tag —— 不是故障，是「还没发过版」。"""


# ---------------------------------------------------------------- 路径
def _env_root():
    root = (os.environ.get('PCAL_UPDATE_ROOT') or '').strip()
    return os.path.abspath(root) if root else ''


def repo_root():
    """安装根目录（…\\物理化学实验）。可用 PCAL_UPDATE_ROOT 覆盖（E2E 测试用）。"""
    return _env_root() or ROOT_FALLBACK


def state_path():
    return os.path.join(repo_root(), STATE_FILE)


def updates_dir():
    return os.path.join(repo_root(), '_core', 'updates')


def backups_dir():
    return os.path.join(updates_dir(), 'backups')


def _api_base():
    return (os.environ.get('PCAL_UPDATE_API_BASE') or _version.GITHUB_API).rstrip('/')


def _codeload_base():
    return (os.environ.get('PCAL_UPDATE_CODELOAD') or _version.CODELOAD).rstrip('/')


def _rel(path):
    try:
        return os.path.relpath(path, repo_root()).replace('\\', '/')
    except ValueError:
        return path


def _parse_version_file(path):
    """从某个 version.py 文本里抠 (APP_VERSION, RELEASE_DATE)（不 import，避免半截文件炸掉）。"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return '', ''
    ver = re.search(r'^\s*APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.M)
    date = re.search(r'^\s*RELEASE_DATE\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.M)
    return (_version.normalize(ver.group(1)) if ver else '',
            date.group(1).strip() if date else '')


def installed_version():
    """安装树上**磁盘里**的版本号。

    比对与判重必须用磁盘版本而不是当前进程 import 进来的常量：安装/回滚刚
    写完文件时，进程里的 `_core.version.APP_VERSION` 还是旧值（重启前一直如此），
    用它判断「是否更新」会判错。读不到就退回模块常量。
    """
    path = os.path.join(repo_root(), '_core', 'version.py')
    for _ in range(3):                    # 正被复制时可能读到半截，重试两次
        got, _date = _parse_version_file(path)
        if got:
            return got
        time.sleep(0.05)
    return _version.APP_VERSION


def installed_info():
    """磁盘上的 (版本号, 发版日期)；读取失败时退回模块常量。"""
    got, date = _parse_version_file(os.path.join(repo_root(), '_core', 'version.py'))
    if not got:
        return installed_version(), _version.RELEASE_DATE
    return got, (date or _version.RELEASE_DATE)



# ---------------------------------------------------------------- 状态缓存
def _empty_state():
    return {
        'current': _version.APP_VERSION,
        'latest': '',
        'tag': '',
        'checked_at': '',
        'checked_epoch': 0,
        'available': False,
        'busy': False,
        'error': '',
        'notes': '',
        'last_apply': {},
    }


def load_state():
    state = _empty_state()
    try:
        with open(state_path(), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in state})
    if not isinstance(state.get('last_apply'), dict):
        state['last_apply'] = {}
    return state


def save_state(state):
    """原子写：先写 .tmp 再 os.replace，避免半截 json 让页面报错。"""
    path = state_path()
    tmp = path + '.tmp'
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise UpdateError('无法写入更新状态文件：%s' % exc)


def _notes_url(tag):
    return '%s/blob/%s/%s' % (_version.REPO_URL, urllib.parse.quote(tag),
                              urllib.parse.quote(_version.CHANGELOG_DIR + '/'))


def tag_url(tag):
    return '%s/tree/%s' % (_version.REPO_URL, urllib.parse.quote(tag))


def notes_url(tag, version_text=None):
    """新版本的更新说明（仓库里 CHANGELOG_vX_Y_Z.md 的网页地址）。"""
    ver = version_text or _version.normalize(tag)
    parts = _version.version_tuple(ver)
    if parts is None:
        return tag_url(tag)
    name = _version.changelog_filename(ver)
    return '%s/blob/%s/%s/%s' % (_version.REPO_URL, urllib.parse.quote(tag),
                                 urllib.parse.quote(_version.CHANGELOG_DIR),
                                 urllib.parse.quote(name))


def public_status():
    """给网页/命令行看的只读状态（不联网、不写盘）。"""
    state = load_state()
    backups = list_backups()
    _cur = installed_info()
    return {
        'ok': True,
        'current': _cur[0],
        'release_date': _cur[1],
        'name': APP_NAME,
        'repo': _version.REPO_SLUG,
        'repo_url': _version.REPO_URL,
        'available': bool(state.get('available')),
        'latest': state.get('latest') or '',
        'tag': state.get('tag') or '',
        'checked_at': state.get('checked_at') or '',
        'from_cache': True,
        'busy': bool(state.get('busy')),
        'error': state.get('error') or '',
        'notes': state.get('notes') or '',
        'tag_url': tag_url(state['tag']) if state.get('tag') else '',
        'notes_url': notes_url(state['tag'], state.get('latest')) if state.get('tag') else '',
        'backups': backups,
        'can_rollback': bool(backups),
        'last_apply': state.get('last_apply') or {},
        'min_interval': MIN_CHECK_INTERVAL,
    }


# ---------------------------------------------------------------- 网络
def _fetch(url, timeout=8, accept='application/vnd.github+json'):
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': accept,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError('GitHub 接口被限流（HTTP %d），请过一会儿再试。'
                              '若开着代理，检查代理是否拦截了 api.github.com。' % exc.code)
        if exc.code == 404:
            raise UpdateError('远端仓库或该 tag 不存在（HTTP 404）：%s' % url)
        raise UpdateError('请求 GitHub 失败（HTTP %d）：%s' % (exc.code, url))
    except urllib.error.URLError as exc:
        raise UpdateError('连不上 GitHub（%s）。检查网络或代理后重试；'
                          '离线时也可以在命令行手动执行 '
                          '`_tools\\launcher.py --update`。' % (exc.reason,))
    except OSError as exc:
        raise UpdateError('网络请求出错：%s' % exc)


def latest_remote_tag(timeout=8):
    """远端语义最大的发版 tag。返回 {'version','tag','sha'}；失败抛 UpdateError。

    远端一个 `vX.Y.Z` tag 都没有时抛 `NoReleaseTag`（子类），调用方当作
    「还没有发版」而不是「网络坏了」。
    """
    slug = _version.REPO_SLUG
    url = '%s/repos/%s/tags?per_page=100' % (_api_base(), slug)
    status, raw = _fetch(url, timeout=timeout)
    try:
        items = json.loads(raw.decode('utf-8'))
    except ValueError:
        raise UpdateError('GitHub 返回的不是合法 JSON（可能被代理劫持）：%s' % url)
    if not isinstance(items, list):
        raise UpdateError('GitHub 返回格式异常：%s' % url)
    best = None
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        parts = _version.version_tuple(name)
        if parts is None:                 # 非 vX.Y.Z 的 tag 一律忽略
            continue
        if best is None or parts > best[0]:
            sha = ''
            commit = item.get('commit')
            if isinstance(commit, dict):
                sha = str(commit.get('sha') or '')
            best = (parts, name, sha)
    if best is None:
        raise NoReleaseTag('远端仓库 %s 还没有 vX.Y.Z 形式的发版 tag。'
                           % _version.REPO_SLUG)
    parts, tag, sha = best
    return {'version': '%d.%d.%d' % parts, 'tag': tag, 'sha': sha}


def _fetch_notes(tag, version_text, timeout=6):
    """尽力取新版本的 CHANGELOG 正文（取不到就当空，不影响升级）。"""
    parts = _version.version_tuple(version_text)
    if parts is None:
        return ''
    name = _version.changelog_filename(version_text)
    path = urllib.parse.quote(_version.CHANGELOG_DIR) + '/' + urllib.parse.quote(name)
    # 正文走 raw.githubusercontent（不受 API 限流影响），取不到就当没有说明
    url = '%s/%s/%s/%s' % (RAW_BASE, _version.REPO_SLUG,
                           urllib.parse.quote(tag), path)
    try:
        status, raw = _fetch(url, timeout=timeout, accept='text/plain')
    except UpdateError:
        return ''
    text = raw.decode('utf-8', errors='replace').strip()
    return text[:4000]


def check_for_update(force=False, timeout=8):
    """联网检查是否有新版本；带节流与串行锁。失败抛 UpdateError（状态里留错误）。"""
    state = load_state()
    now = time.time()
    last = float(state.get('checked_epoch') or 0)
    if (not force and last and (now - last) < MIN_CHECK_INTERVAL
            and state.get('latest')):
        status = public_status()
        status['from_cache'] = True
        return status

    if not _CHECKS_LOCK.acquire(blocking=force):
        status = public_status()
        status['error'] = '正在检查中…'
        return status
    try:
        remote = latest_remote_tag(timeout=timeout)
        current = installed_version()
        state.update({
            'current': current,
            'latest': remote['version'],
            'tag': remote['tag'],
            'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'checked_epoch': int(time.time()),
            'available': _version.is_newer(remote['version'], current),
            'error': '',
            'notes': '',
        })
        if state['available']:
            state['notes'] = _fetch_notes(remote['tag'], remote['version'])
        save_state(state)
    except UpdateError as exc:
        # 「远端还没有 tag」不是故障：当前多半是还没打过 tag 的开发版。
        message = ('远端还没有 vX.Y.Z 发版 tag（当前是开发版，等作者发版后再检查）。'
                   if isinstance(exc, NoReleaseTag) else str(exc))
        state.update({
            'current': installed_version(),
            'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'checked_epoch': int(time.time()),
            'available': False,
            'error': message,
        })
        try:
            save_state(state)
        except UpdateError:
            pass
        raise
    finally:
        _CHECKS_LOCK.release()

    status = public_status()
    status['from_cache'] = False
    return status


# ---------------------------------------------------------------- 下载 / 解包
def download_package(tag, dest_zip, progress=None, timeout=180):
    """下载 tag 的源码 zip（codeload），返回本地路径。"""
    if not tag:
        raise UpdateError('没有指定要下载的 tag')
    url = '%s/%s/zip/refs/tags/%s' % (_codeload_base(), _version.REPO_SLUG,
                                      urllib.parse.quote(tag))
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    dest_zip = os.path.abspath(dest_zip)
    os.makedirs(os.path.dirname(dest_zip) or '.', exist_ok=True)
    tmp = dest_zip + '.part'
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(tmp, 'wb') as fh:
            total = int(resp.headers.get('Content-Length') or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_PACKAGE_BYTES:
                    raise UpdateError('更新包超过 %d MB，已中止（可能是错误的响应）。'
                                      % (MAX_PACKAGE_BYTES // 1024 // 1024))
                fh.write(chunk)
                if progress:
                    try:
                        progress(got, total)
                    except Exception:      # noqa: BLE001  进度回调不许影响下载
                        pass
        if got < 1024:
            raise UpdateError('下载到的更新包只有 %d 字节，不像正常的 zip。' % got)
        with open(tmp, 'rb') as fh:
            head = fh.read(4)
        if head[:2] != b'PK':
            raise UpdateError('下载到的不是 zip 文件（可能被代理/登录页替换）：%s' % url)
        os.replace(tmp, dest_zip)
        return dest_zip
    except urllib.error.HTTPError as exc:
        raise UpdateError('下载更新包失败（HTTP %d）：%s' % (exc.code, url))
    except urllib.error.URLError as exc:
        raise UpdateError('下载更新包时网络中断（%s）：%s' % (exc.reason, url))
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _safe_members(zf):
    """过滤出安全的成员：拒绝绝对路径、`..`、符号链接与超量内容。"""
    out = []
    total = 0
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or ':' in name.split('/')[0]:
            raise UpdateError('更新包含有非法绝对路径：%s' % info.filename)
        parts = [p for p in name.split('/') if p not in ('', '.')]
        if any(p == '..' for p in parts):
            raise UpdateError('更新包含有越级路径：%s' % info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:              # 符号链接
            raise UpdateError('更新包含符号链接，已拒绝：%s' % info.filename)
        total += max(0, int(info.file_size or 0))
        if total > MAX_PACKAGE_BYTES:
            raise UpdateError('更新包解压后超过 %d MB，已中止。'
                              % (MAX_PACKAGE_BYTES // 1024 // 1024))
        out.append((info, parts))
    return out


def extract_package(zip_path, work_dir):
    """解包并返回包根目录（GitHub zip 顶层是 `<repo>-<tag>/`，这里剥掉）。"""
    work_dir = os.path.abspath(work_dir)
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError('更新包不是有效的 zip：%s' % exc)
    with zf:
        members = _safe_members(zf)
        for info, parts in members:
            if not parts:
                continue
            target = os.path.join(work_dir, *parts)
            if parts[-1] == '':
                continue
            os.makedirs(os.path.dirname(target) or work_dir, exist_ok=True)
            try:
                with zf.open(info) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            except (OSError, zipfile.BadZipFile) as exc:
                raise UpdateError('解包失败（%s）：%s' % (parts[-1], exc))
    return _locate_package_root(work_dir)


def _looks_like_root(path):
    return (os.path.isfile(os.path.join(path, '_core', 'version.py'))
            and os.path.isfile(os.path.join(path, PORTAL_DIR, 'portal.py')))


def _locate_package_root(work_dir):
    """在解出来的目录里找那一层「既有 _core/version.py 又有入口 portal.py」。"""
    if _looks_like_root(work_dir):
        return work_dir
    try:
        children = [os.path.join(work_dir, n) for n in sorted(os.listdir(work_dir))]
    except OSError as exc:
        raise UpdateError('读不出解包目录：%s' % exc)
    for child in children:
        if os.path.isdir(child) and _looks_like_root(child):
            return child
    raise UpdateError('更新包结构不对：既没有 _core/version.py，'
                      '也没有 %s/portal.py。这可能不是本工具的仓库包。' % PORTAL_DIR)


# ---------------------------------------------------------------- 白名单与保护
def _is_protected(parts):
    lowered = [p.lower() for p in parts]
    for part in parts:
        if part in PROTECTED_PARTS or part.lower() in (x.lower() for x in PROTECTED_PARTS):
            return True
        if part.startswith(PROTECTED_PREFIX):
            return True
    if lowered and any(lowered[-1].endswith(suffix) for suffix in PROTECTED_SUFFIX):
        return True
    return False


def _whitelisted(rel_parts):
    """(是否在同步白名单里, 是否为顶层文件)"""
    if not rel_parts:
        return False, False
    head = rel_parts[0]
    if head in TOP_DIRS:
        return True, False
    if len(rel_parts) == 1 and head in ROOT_FILES:
        return True, True
    return False, False


def iter_package_files(package_root):
    """遍历包内白名单文件，产出 (包内绝对路径, 相对安装根的 tuple 路径)。"""
    root = os.path.abspath(package_root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _is_protected([d]))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace('\\', '/').split('/')
            ok, _is_root_file = _whitelisted(rel)
            if not ok:
                continue
            if _is_protected(rel):
                continue
            yield full, tuple(rel)


def plan_package(package_root, expected_version=None):
    """只算计划不落盘：{'to','updated':[...],'added':[...],'total':N}。"""
    package_root = os.path.abspath(package_root)
    got = _package_version(package_root)
    want = _version.normalize(expected_version) if expected_version else got
    if _version.version_tuple(got) is None:
        raise UpdateError('更新包里的 _core/version.py 没有可识别的 APP_VERSION。')
    if expected_version and got != want:
        raise UpdateError('更新包版本不一致：期望 %s，包内是 %s。'
                          '可能下载到了错误的 tag。' % (want, got))
    root = repo_root()
    updated, added = [], []
    for _full, rel in iter_package_files(package_root):
        target = os.path.join(root, *rel)
        (updated if os.path.exists(target) else added).append('/'.join(rel))
    return {'to': got, 'updated': updated, 'added': added,
            'total': len(updated) + len(added)}


def _package_version(package_root):
    path = os.path.join(package_root, '_core', 'version.py')
    if not os.path.isfile(path):
        raise UpdateError('更新包里没有 _core/version.py')
    got, _date = _parse_version_file(path)
    if not got:
        raise UpdateError('更新包的 _core/version.py 里找不到 APP_VERSION。')
    return got


# ---------------------------------------------------------------- 备份
def _stamp():
    return time.strftime('%Y%m%d-%H%M%S')


def _backup_name(from_version, stamp):
    return '%s-%s' % (_version.normalize(from_version) or 'unknown', stamp)


def list_backups():
    base = backups_dir()
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        manifest = {}
        try:
            with open(os.path.join(path, 'manifest.json'), 'r', encoding='utf-8') as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            manifest = {}
        out.append({
            'name': name,
            'path': path,
            'version': str(manifest.get('from_version') or name.split('-')[0]),
            'to_version': str(manifest.get('to_version') or ''),
            'created_at': str(manifest.get('created_at') or ''),
            'files': len(manifest.get('updated') or []) + len(manifest.get('added') or []),
        })
    out.sort(key=lambda item: item['created_at'] or item['name'], reverse=True)
    return out


def cleanup_backups(keep=KEEP_BACKUPS):
    keep = max(1, int(keep))
    for item in list_backups()[keep:]:
        shutil.rmtree(item['path'], ignore_errors=True)


def _copy_back(files_root, rel_paths):
    """把备份里的文件还原回安装根。返回还原个数。"""
    root = repo_root()
    n = 0
    for rel in rel_paths:
        src = os.path.join(files_root, *rel.split('/'))
        dst = os.path.join(root, *rel.split('/'))
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst) or root, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def _delete_added(rel_paths):
    root = repo_root()
    n = 0
    for rel in rel_paths:
        dst = os.path.join(root, *rel.split('/'))
        if any(rel.startswith(guard) for guard in NEVER_DELETE):
            continue
        try:
            if os.path.isfile(dst):
                os.remove(dst)
                n += 1
        except OSError:
            pass
    return n


# ---------------------------------------------------------------- 安装
def self_check(expected_version):
    """用子进程在安装根里 import 一次 _core.version，确认代码真的能起来。"""
    root = repo_root()
    code = ('import sys; sys.path.insert(0, %r); '
            'from _core import version; print(version.APP_VERSION)' % root)
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env.pop('PCAL_UPDATE_ROOT', None)
    try:
        proc = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                              capture_output=True, timeout=60, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, '自检无法运行 python：%s' % exc
    out = (proc.stdout or b'').decode('utf-8', 'replace').strip()
    err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
    if proc.returncode != 0:
        return False, '自检失败（返回码 %s）：%s' % (proc.returncode, (err or out)[:600])
    got = _version.normalize(out.splitlines()[-1] if out else '')
    if got != _version.normalize(expected_version):
        return False, '自检读到的版本是 %s，期望 %s' % (got or '（空）', expected_version)
    return True, ''


def apply_package(package_root, expected_version=None, dry_run=False,
                  allow_downgrade=False, check_runtime=True):
    """把已解包的更新装进安装根：备份 → 覆盖/新增 → 自检 → 失败自动回滚。"""
    package_root = os.path.abspath(package_root)
    # 结构校验放在这里（而不只在 extract_package 里）：任何调用方——包括将来
    # 「从本地 zip 装」「把已解包目录直接喂进来」——都不能把残包/错包装进去。
    if not _looks_like_root(package_root):
        raise UpdateError('这个目录不像本工具的更新包（缺 _core/version.py 或 %s/portal.py）：%s'
                          % (PORTAL_DIR, package_root))
    plan = plan_package(package_root, expected_version)
    to_version = plan['to']
    current = installed_version()
    if not allow_downgrade and not _version.is_newer(to_version, current):
        raise UpdateError('更新包版本 %s 不比当前 %s 新，已取消安装。'
                          % (to_version, current))
    if dry_run:
        return {'ok': True, 'dry_run': True, 'from': current, 'to': to_version,
                'updated': len(plan['updated']), 'added': len(plan['added']),
                'backup_dir': '', 'restart': False,
                'message': '演练模式：将覆盖 %d 个文件、新增 %d 个文件。'
                           % (len(plan['updated']), len(plan['added']))}

    if not _APPLY_LOCK.acquire(blocking=False):
        raise UpdateError('已经有一个更新在安装中，请稍候。')
    try:
        state = load_state()
        state['busy'] = True
        _safe_save(state)
        return _apply_locked(package_root, plan, current, to_version, check_runtime)
    finally:
        state = load_state()
        state['busy'] = False
        _safe_save(state)
        _APPLY_LOCK.release()


def _safe_save(state):
    try:
        save_state(state)
    except UpdateError:
        pass


def _apply_locked(package_root, plan, current, to_version, check_runtime):
    stamp = _stamp()
    backup_dir = os.path.join(backups_dir(), _backup_name(current, stamp))
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as exc:
        raise UpdateError('无法创建备份目录：%s' % exc)

    root = repo_root()
    backed_up = []
    try:
        for rel in plan['updated']:
            src = os.path.join(root, *rel.split('/'))
            dst = os.path.join(backup_dir, 'files', *rel.split('/'))
            os.makedirs(os.path.dirname(dst) or backup_dir, exist_ok=True)
            shutil.copy2(src, dst)
            backed_up.append(rel)
        with open(os.path.join(backup_dir, 'manifest.json'), 'w',
                  encoding='utf-8', newline='\n') as fh:
            json.dump({
                'from_version': current, 'to_version': to_version,
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'updated': plan['updated'], 'added': plan['added'],
            }, fh, ensure_ascii=False, indent=2)
            fh.write('\n')

        written = 0
        for full, rel in iter_package_files(package_root):
            dst = os.path.join(root, *rel)
            os.makedirs(os.path.dirname(dst) or root, exist_ok=True)
            shutil.copy2(full, dst)
            written += 1
    except OSError as exc:
        _restore(backup_dir, backed_up, [], root)
        raise UpdateError('复制更新文件时出错（已还原到 %s）：%s' % (current, exc))

    if check_runtime:
        ok, why = self_check(to_version)
        if not ok:
            _restore(backup_dir, backed_up, plan['added'], root)
            raise UpdateError('新版本自检没通过，已自动回滚到 %s。原因：%s'
                              % (current, why))

    state = load_state()
    state['last_apply'] = {
        'from': current, 'to': to_version,
        'at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'backup': os.path.basename(backup_dir),
        'files': written,
    }
    _safe_save(state)
    cleanup_backups()
    return {
        'ok': True, 'from': current, 'to': to_version,
        'updated': len(plan['updated']), 'added': len(plan['added']),
        'skipped': 0, 'files': written,
        'backup_dir': backup_dir, 'restart': True,
        'message': '已更新到 v%s（覆盖 %d 个文件、新增 %d 个）。备份在 %s'
                   % (to_version, len(plan['updated']), len(plan['added']),
                      _rel(backup_dir)),
    }


def _restore(backup_dir, updated, added, root):
    files_root = os.path.join(backup_dir, 'files')
    for rel in updated:
        src = os.path.join(files_root, *rel.split('/'))
        dst = os.path.join(root, *rel.split('/'))
        if os.path.isfile(src):
            try:
                os.makedirs(os.path.dirname(dst) or root, exist_ok=True)
                shutil.copy2(src, dst)
            except OSError:
                pass
    _delete_added(added)


def rollback(backup_name=None):
    """用备份还原上一版；默认用最近一份。"""
    if not _APPLY_LOCK.acquire(blocking=False):
        raise UpdateError('已经有一个更新在安装中，请稍候。')
    try:
        backups = list_backups()
        if not backups:
            raise UpdateError('没有可用的备份（还没更新过，或备份已被清理）。')
        if backup_name:
            item = next((b for b in backups if b['name'] == backup_name), None)
            if item is None:
                raise UpdateError('找不到备份：%s' % backup_name)
        else:
            item = backups[0]
        manifest_path = os.path.join(item['path'], 'manifest.json')
        try:
            with open(manifest_path, 'r', encoding='utf-8') as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            raise UpdateError('备份清单损坏（%s），无法回滚：%s' % (item['name'], exc))
        target = _version.normalize(manifest.get('from_version'))
        root = repo_root()
        _restore(item['path'], manifest.get('updated') or [],
                 manifest.get('added') or [], root)
        state = load_state()
        state['last_apply'] = {
            'rollback_to': target, 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'backup': item['name'],
        }
        state['current'] = target
        _safe_save(state)
        return {'ok': True, 'to': target, 'restart': True,
                'message': '已回滚到 v%s（备份 %s）。' % (target, item['name'])}
    finally:
        _APPLY_LOCK.release()


# ---------------------------------------------------------------- 一步到位
def update_now(tag=None, expected_version=None, timeout=180, progress=None,
               dry_run=False, restart=True):
    """检查（或直接用给定 tag）→ 下载 → 解包 → 安装，返回安装结果。

    给 `_tools/launcher.py --update --apply` 和测试用；网页走 /api/update/apply。
    """
    if not tag:
        remote = latest_remote_tag(timeout=min(20, max(8, timeout // 10)))
        tag = remote['tag']
        expected_version = expected_version or remote['version']
    work = os.path.join(updates_dir(), 'download')
    os.makedirs(work, exist_ok=True)
    try:
        zip_path = os.path.join(work, '%s.zip' % tag.replace('/', '_'))
        download_package(tag, zip_path, progress=progress, timeout=timeout)
        package_root = extract_package(zip_path, os.path.join(work, 'pkg'))
        result = apply_package(package_root, expected_version=expected_version,
                               dry_run=dry_run)
    finally:
        shutil.rmtree(os.path.join(work, 'pkg'), ignore_errors=True)
        try:
            os.remove(os.path.join(work, '%s.zip' % tag.replace('/', '_')))
        except OSError:
            pass
    result['tag'] = tag
    result['restart'] = bool(result.get('restart')) and bool(restart)
    return result


if __name__ == '__main__':                # 手工排障：python _core/updater.py
    try:
        st = check_for_update(force=True)
        print('当前 %s / 最新 %s / 可更新 %s'
              % (st['current'], st['latest'], st['available']))
    except UpdateError as exc:
        print('[ERROR] %s' % exc)
        sys.exit(1)
