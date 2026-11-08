# -*- coding: utf-8 -*-
"""自动更新链路（`_core/updater.py`）的安全边界测试。

全部在 `tempfile.TemporaryDirectory()` 里做：

* 用 `PCAL_UPDATE_ROOT` 把「安装根」指向临时目录，**绝不动真实仓库**；
* 联网一律 `unittest.mock.patch('urllib.request.urlopen')`，测试不联网；
* 环境变量用 `mock.patch.dict` 精确还原，结束后不泄给其它测试。

覆盖：受保护路径、白名单、先备份后覆盖、版本比较、装后自检失败自动回滚、
zip 路径穿越、非 zip 响应、tag 语义最大、rollback。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from _core import updater                     # noqa: E402

OLD_VERSION = '0.9.0'                         # 假安装根里写的旧版本（= 磁盘当前版本）
NEW_VERSION = '1.0.1'                         # 假更新包里的新版本
# updater 在内存里的模块常量（真源，真实仓库的 APP_VERSION）；
# 注意：apply_package/public_status 判断「当前版本」用的是**磁盘**上的
# `_core/version.py`（updater.installed_version()），所以拿临时安装根里的
# OLD_VERSION 作比较基准。
MODULE_VERSION = updater._version.APP_VERSION

OLD_VERSION_PY = '''# -*- coding: utf-8 -*-
"""旧版本占位。"""
APP_VERSION = '%s'
RELEASE_DATE = '2026-10-01'
''' % OLD_VERSION

NEW_VERSION_PY = '''# -*- coding: utf-8 -*-
"""更新包里的版本。"""
APP_VERSION = '%s'
RELEASE_DATE = '2026-11-08'
''' % NEW_VERSION

OLD_PORTAL_PY = '# 旧版入口\nPORT = 8700\n'
NEW_PORTAL_PY = '# 新版入口\nPORT = 8700\n'
OLD_EST_PY = '# 新增文件（旧安装根里没有）\nVALUE = 1\n'

USER_FILES = {
    'settings.json': '{"theme": "dark", "entered": true}\n',
    'profile.json': '{"name": "张瑞杰", "student_id": "2400011877"}\n',
    '燃烧热工具/data/记录.json': '{"records": [1, 2, 3]}\n',
    '实验报告输出/报告.docx': 'PK\x03\x04 假装这是 docx 的字节\n',
}


def sha256_of(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    return path


def read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


class UpdateTestBase(unittest.TestCase):
    """每个用例一套独立的临时安装根 + 假更新包。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / 'install'
        self.pkg = self.tmp / 'package'
        self._make_install_root()
        self._make_package()
        env = self._env()
        env.start()
        self.addCleanup(env.stop)

    def _env(self):
        """只在本用例内生效的环境覆盖；结束由 addCleanup 精确还原。"""
        return mock.patch.dict(os.environ, {
            'PCAL_UPDATE_ROOT': str(self.root),
            'PCAL_UPDATE_API_BASE': 'http://127.0.0.1:9',
            'PCAL_UPDATE_CODELOAD': 'http://127.0.0.1:9',
        }, clear=False)

    # ---- 假安装根（旧版本 + 用户数据）
    def _make_install_root(self):
        write(self.root / '_core' / 'version.py', OLD_VERSION_PY)
        write(self.root / '物化实验报告工具' / 'portal.py', OLD_PORTAL_PY)
        write(self.root / '_core' / 'docxkit.py', '# 旧版 docxkit\n')
        for rel, text in USER_FILES.items():
            write(self.root / rel, text)

    # ---- 假更新包（新版本 + 一个新增文件）
    def _make_package(self):
        write(self.pkg / '_core' / 'version.py', NEW_VERSION_PY)
        write(self.pkg / '物化实验报告工具' / 'portal.py', NEW_PORTAL_PY)
        write(self.pkg / '_core' / 'docxkit.py', '# 新版 docxkit\n')
        write(self.pkg / '燃烧热工具' / 'pcal' / 'est.py', OLD_EST_PY)

    # ---- 小工具
    def user_snapshot(self):
        return {rel: sha256_of(self.root / rel) for rel in USER_FILES}

    def backups(self):
        return updater.list_backups()


class FakeResponse:
    """够用的 urlopen 返回值：支持 with、read、headers、status。"""

    def __init__(self, body, status=200, headers=None):
        self._body = body
        self._pos = 0
        self.status = status
        self.headers = headers if headers is not None else {
            'Content-Length': str(len(body))}

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._body) - self._pos
        chunk = self._body[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class ProtectedPathTests(unittest.TestCase):
    """受保护路径：任意层级命中即跳过，用户数据永不被覆盖。"""

    def test_user_data_paths_are_protected(self):
        cases = (
            'settings.json',
            'profile.json',
            'update_state.json',
            '燃烧热工具/data/x.json',
            '紫外光谱工具/data/2026/记录.json',
            '实验报告输出/a.docx',
            '发布/x.zip',
            '__pycache__/x.pyc',
            '燃烧热工具/pcal/__pycache__/est.cpython-311.pyc',
            '~$报告.docx',
            '.git/config',
            '_core/updates/backups/x/manifest.json',
            '_core/backups/20260101-000000/omml.py',
            '_tools/启动日志.log',
        )
        for rel in cases:
            with self.subTest(rel=rel):
                self.assertTrue(updater._is_protected(rel.split('/')),
                                '%s 应该被视为受保护路径' % rel)

    def test_code_paths_are_not_protected(self):
        cases = (
            '_core/version.py',
            '燃烧热工具/pcal/est.py',
            '物化实验报告工具/portal.py',
            '更新日志/CHANGELOG_v1_0_1.md',
            'README.md',
            '_tools/launcher.py',
            'tests/test_update.py',
        )
        for rel in cases:
            with self.subTest(rel=rel):
                self.assertFalse(updater._is_protected(rel.split('/')),
                                 '%s 不该被视为受保护路径' % rel)

    def test_backup_and_cache_suffixes_are_protected(self):
        for rel in ('_core/omml.py.bak', '燃烧热工具/pcal/docxkit.pyc',
                    '旧包.zip', '$lock.docx', '.~lock.报告.docx#'):
            with self.subTest(rel=rel):
                self.assertTrue(updater._is_protected(rel.split('/')),
                                '%s 应受保护' % rel)


class PlanPackageTests(UpdateTestBase):
    """plan_package：只算计划、只认白名单。"""

    def test_plan_lists_updated_and_added(self):
        plan = updater.plan_package(self.pkg)
        self.assertEqual(plan['to'], NEW_VERSION)
        self.assertIn('_core/version.py', plan['updated'])
        self.assertIn('物化实验报告工具/portal.py', plan['updated'])
        self.assertIn('燃烧热工具/pcal/est.py', plan['added'])
        self.assertEqual(plan['total'], len(plan['updated']) + len(plan['added']))

    def test_plan_ignores_top_level_dirs_outside_whitelist(self):
        write(self.pkg / '高斯计算工具' / 'pcal' / 'gauss.py', '# 不该进计划\n')
        write(self.pkg / '随机' / 'x.py', '# 也不该进计划\n')
        write(self.pkg / 'build' / 'out.py', '# 更不该\n')
        write(self.pkg / 'notes.txt', '# 顶层非白名单文件\n')
        plan = updater.plan_package(self.pkg)
        touched = plan['updated'] + plan['added']
        for prefix in ('高斯计算工具/', '随机/', 'build/', 'notes.txt'):
            self.assertFalse([rel for rel in touched if rel.startswith(prefix)],
                             '白名单外的 %s 不该进计划：%r' % (prefix, touched))

    def test_plan_skips_protected_inside_whitelist(self):
        write(self.pkg / '燃烧热工具' / 'data' / 'x.json', '{"evil": true}\n')
        write(self.pkg / '实验报告输出' / 'a.docx', 'evil\n')
        write(self.pkg / '_core' / 'version.pyc', 'evil\n')
        plan = updater.plan_package(self.pkg)
        touched = plan['updated'] + plan['added']
        for rel in touched:
            self.assertFalse(rel.endswith(('.pyc', 'x.json', 'a.docx')),
                             '包里的受保护文件不该进计划：%s' % rel)

    def test_plan_rejects_expected_version_mismatch(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.plan_package(self.pkg, expected_version='1.0.2')
        self.assertIn('不一致', str(ctx.exception))

    def test_plan_rejects_package_without_app_version(self):
        write(self.pkg / '_core' / 'version.py', '# 没有 APP_VERSION\n')
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.plan_package(self.pkg)
        self.assertIn('APP_VERSION', str(ctx.exception))


class ApplyPackageTests(UpdateTestBase):
    """apply_package：先备份后覆盖、用户数据逐字节不变、版本守门。"""

    def test_apply_updates_code_and_keeps_user_data(self):
        before = self.user_snapshot()
        result = updater.apply_package(self.pkg, expected_version='v' + NEW_VERSION)

        self.assertTrue(result['ok'])
        self.assertEqual(result['to'], NEW_VERSION)
        self.assertGreaterEqual(result['updated'], 2)
        self.assertGreaterEqual(result['added'], 1)

        # 代码升到新版本
        self.assertEqual(read(self.root / '_core' / 'version.py'), NEW_VERSION_PY)
        self.assertEqual(read(self.root / '物化实验报告工具' / 'portal.py'),
                         NEW_PORTAL_PY)
        self.assertTrue((self.root / '燃烧热工具' / 'pcal' / 'est.py').is_file())

        # 用户数据逐字节未变
        self.assertEqual(self.user_snapshot(), before, '用户数据被改动了')
        self.assertEqual(read(self.root / 'settings.json'),
                         USER_FILES['settings.json'])
        self.assertEqual(read(self.root / 'profile.json'),
                         USER_FILES['profile.json'])

        # 备份目录有 manifest.json 且记录了被覆盖的文件
        backup_dir = Path(result['backup_dir'])
        self.assertTrue(backup_dir.is_dir(), '没有创建备份目录')
        manifest_path = backup_dir / 'manifest.json'
        self.assertTrue(manifest_path.is_file(), '备份目录缺 manifest.json')
        manifest = json.loads(read(manifest_path))
        self.assertIn('_core/version.py', manifest['updated'])
        self.assertIn('物化实验报告工具/portal.py', manifest['updated'])
        self.assertEqual(manifest['to_version'], NEW_VERSION)
        self.assertTrue(manifest.get('created_at'))
        # 备份里存的是**旧内容**
        backed_up = backup_dir / 'files' / '_core' / 'version.py'
        self.assertTrue(backed_up.is_file(), '被覆盖的文件没有进备份')
        self.assertEqual(read(backed_up), OLD_VERSION_PY)

    def test_apply_backup_is_registered_by_list_backups(self):
        result = updater.apply_package(self.pkg)
        names = [item['name'] for item in self.backups()]
        self.assertIn(Path(result['backup_dir']).name, names)
        self.assertTrue(updater.public_status()['can_rollback'])

    def test_same_version_is_rejected(self):
        write(self.pkg / '_core' / 'version.py',
              NEW_VERSION_PY.replace(NEW_VERSION, OLD_VERSION))
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply_package(self.pkg)
        message = str(ctx.exception)
        self.assertIn('不比当前', message)
        self.assertIn(OLD_VERSION, message)
        # 拒绝时安装目录必须没变
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)

    def test_lower_version_is_rejected(self):
        write(self.pkg / '_core' / 'version.py',
              NEW_VERSION_PY.replace(NEW_VERSION, '0.0.1'))
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply_package(self.pkg)
        self.assertIn('不比当前', str(ctx.exception))
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)
        self.assertFalse((self.root / '燃烧热工具' / 'pcal' / 'est.py').exists())

    def test_expected_version_mismatch_is_rejected(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply_package(self.pkg, expected_version='1.0.2')
        message = str(ctx.exception)
        self.assertIn('不一致', message)
        self.assertIn('1.0.2', message)
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)

    def test_package_missing_portal_is_not_installable(self):
        """包结构不合法（缺 portal.py）不许装进安装根。

        `extract_package` 会先校验包根必须同时有 `_core/version.py` 与
        `物化实验报告工具/portal.py`（CONTRACT C.3「先校验后落盘」），
        所以这种包在解包阶段就被挡下来了。
        """
        zip_path = self.tmp / 'no_portal.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('repo-1.0.1/_core/version.py', NEW_VERSION_PY)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.extract_package(zip_path, self.tmp / 'work_noportal')
        self.assertIn('portal.py', str(ctx.exception))
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)

    def test_dry_run_does_not_touch_install_root(self):
        before = self.user_snapshot()
        result = updater.apply_package(self.pkg, dry_run=True)
        self.assertTrue(result.get('dry_run'))
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)
        self.assertEqual(self.user_snapshot(), before)
        self.assertEqual(self.backups(), [])

    def test_self_check_failure_rolls_back_automatically(self):
        """装完自检失败 → 抛 UpdateError，且安装根回到旧版本原样。"""
        before = self.user_snapshot()
        with mock.patch.object(updater, 'self_check',
                               return_value=(False, '模拟失败')):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.apply_package(self.pkg)
        message = str(ctx.exception)
        self.assertIn('自检', message)
        self.assertIn('回滚', message)
        # 安装根回到旧内容
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)
        self.assertEqual(read(self.root / '物化实验报告工具' / 'portal.py'),
                         OLD_PORTAL_PY)
        self.assertEqual(read(self.root / '_core' / 'docxkit.py'), '# 旧版 docxkit\n')
        # 新增的文件必须被删掉
        self.assertFalse((self.root / '燃烧热工具' / 'pcal' / 'est.py').exists(),
                         '自检失败后新增文件应被删除')
        # 用户数据仍未变
        self.assertEqual(self.user_snapshot(), before)

    def test_self_check_real_run_succeeds(self):
        """不 mock 时真的跑一次子进程自检（假安装根里的 _core 能被 import）。"""
        ok, why = updater.self_check(OLD_VERSION)
        self.assertTrue(ok, '子进程自检失败：%s' % why)

    def test_self_check_detects_wrong_version(self):
        ok, why = updater.self_check(NEW_VERSION)
        self.assertFalse(ok)
        self.assertIn(OLD_VERSION, why)


class ExtractPackageTests(UpdateTestBase):
    """extract_package：正常解包 + 拒绝路径穿越。"""

    def _make_zip(self, members, name='pkg.zip'):
        path = self.tmp / name
        with zipfile.ZipFile(path, 'w') as zf:
            for member_name, body in members:
                zf.writestr(member_name, body)
        return path

    def test_extract_normal_package(self):
        zip_path = self._make_zip([
            ('repo-1.0.1/_core/version.py', NEW_VERSION_PY),
            ('repo-1.0.1/物化实验报告工具/portal.py', NEW_PORTAL_PY),
        ])
        root = updater.extract_package(zip_path, self.tmp / 'work')
        root = Path(root)
        self.assertEqual(read(root / '_core' / 'version.py'), NEW_VERSION_PY)
        self.assertTrue((root / '物化实验报告工具' / 'portal.py').is_file())

    def test_extract_handles_directory_entries(self):
        """GitHub 打的 zip 每个目录都有一条 `<dir>/` 目录条目。

        早先这些条目被当成普通文件，先落成一个**同名文件**，随后真正建子目录时
        报 `FileExistsError: WinError 183` —— 自造的测试包没有目录条目，
        所以只有对着真实 tag 下载才会踩到（v1.0.0 首发就是这么翻车的）。
        """
        path = self.tmp / 'withdirs.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('repo-1.0.1/', '')                       # 顶层目录
            zf.writestr('repo-1.0.1/_core/', '')                 # 子目录
            zf.writestr('repo-1.0.1/_core/version.py', NEW_VERSION_PY)
            zf.writestr('repo-1.0.1/物化实验报告工具/', '')
            zf.writestr('repo-1.0.1/物化实验报告工具/portal.py', NEW_PORTAL_PY)
            zf.writestr('repo-1.0.1/燃烧热工具/', '')
            zf.writestr('repo-1.0.1/燃烧热工具/pcal/', '')
            zf.writestr('repo-1.0.1/燃烧热工具/pcal/docxkit.py', 'X = 1\n')
        root = Path(updater.extract_package(path, self.tmp / 'work_dirs'))
        self.assertEqual(read(root / '_core' / 'version.py'), NEW_VERSION_PY)
        self.assertTrue((root / '物化实验报告工具' / 'portal.py').is_file())
        self.assertTrue((root / '燃烧热工具' / 'pcal' / 'docxkit.py').is_file())
        # 目录条目不能变成同名文件
        self.assertTrue((root / '_core').is_dir())
        self.assertFalse((root / '_core').is_file())

    def test_extract_rejects_parent_traversal(self):
        zip_path = self._make_zip([
            ('../evil.txt', 'evil\n'),
            ('repo/_core/version.py', NEW_VERSION_PY),
        ], name='evil.zip')
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.extract_package(zip_path, self.tmp / 'work_evil')
        self.assertIn('越级', str(ctx.exception))
        self.assertFalse((self.tmp / 'evil.txt').exists(), '穿越文件被写到外面了')

    def test_extract_rejects_absolute_path(self):
        zip_path = self._make_zip([
            ('C:/x.txt', 'evil\n'),
            ('repo/_core/version.py', NEW_VERSION_PY),
        ], name='abs.zip')
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.extract_package(zip_path, self.tmp / 'work_abs')
        self.assertIn('绝对路径', str(ctx.exception))

    def test_extract_rejects_broken_zip(self):
        path = self.tmp / 'broken.zip'
        write(path, '这不是 zip\n')
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.extract_package(path, self.tmp / 'work_broken')
        self.assertIn('zip', str(ctx.exception))

    def test_extract_rejects_wrong_structure(self):
        zip_path = self._make_zip([('repo/README.md', '# 不是本工具的仓库\n')],
                                  name='wrong.zip')
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.extract_package(zip_path, self.tmp / 'work_wrong')
        self.assertIn('portal.py', str(ctx.exception))


class DownloadPackageTests(UpdateTestBase):
    """download_package：非 zip 响应要抛中文 UpdateError。"""

    def test_non_zip_response_is_rejected(self):
        body = b'<html><body>proxy login page</body></html>' * 60   # > 1024 字节
        self.assertGreater(len(body), 1024)
        dest = self.tmp / 'dl' / 'pkg.zip'
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(body)):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.download_package('v' + NEW_VERSION, str(dest))
        message = str(ctx.exception)
        self.assertIn('不是 zip', message)
        self.assertFalse(dest.exists(), '失败的下载不该留下目标文件')
        self.assertFalse(Path(str(dest) + '.part').exists(), '不该留下 .part 临时文件')

    def test_too_small_response_is_rejected(self):
        dest = self.tmp / 'dl' / 'small.zip'
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(b'PK\x03\x04')):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.download_package('v' + NEW_VERSION, str(dest))
        self.assertIn('字节', str(ctx.exception))

    def test_good_zip_is_saved(self):
        src = self.tmp / 'src.zip'
        with zipfile.ZipFile(src, 'w') as zf:
            zf.writestr('repo/_core/version.py', NEW_VERSION_PY)
            # 真包远大于 1 KB；download_package 会把过小的响应当成异常
            zf.writestr('repo/_core/pad.py', '# 填充\n' + 'x = 1\n' * 400)
        body = src.read_bytes()
        self.assertGreater(len(body), 1024)
        dest = self.tmp / 'dl' / 'good.zip'
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(body)):
            got = updater.download_package('v' + NEW_VERSION, str(dest))
        self.assertTrue(Path(got).is_file())
        self.assertEqual(Path(got).read_bytes(), body)

    def test_progress_callback_is_called(self):
        src = self.tmp / 'prog.zip'
        with zipfile.ZipFile(src, 'w') as zf:
            zf.writestr('repo/_core/version.py', NEW_VERSION_PY)
            zf.writestr('repo/_core/pad.py', '# 填充\n' + 'x = 1\n' * 400)
        body = src.read_bytes()
        seen = []
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(body)):
            updater.download_package('v' + NEW_VERSION,
                                     str(self.tmp / 'dl' / 'prog.zip'),
                                     progress=lambda got, total: seen.append(got))
        self.assertTrue(seen, '进度回调一次都没被调用')
        self.assertEqual(seen[-1], len(body))


class LatestRemoteTagTests(UpdateTestBase):
    """latest_remote_tag：取语义最大的 vX.Y.Z tag，忽略非三段式。"""

    def _patch_tags(self, items):
        body = json.dumps(items).encode('utf-8')
        return mock.patch('urllib.request.urlopen',
                          return_value=FakeResponse(body))

    def test_picks_semantically_largest_tag(self):
        items = [
            {'name': 'v1.0.1', 'commit': {'sha': 'aaa'}},
            {'name': 'v1.0.10', 'commit': {'sha': 'bbb'}},
            {'name': 'v1.0.9', 'commit': {'sha': 'ccc'}},
            {'name': 'not-a-version', 'commit': {'sha': 'ddd'}},
            {'name': 'v2.0.0-rc1', 'commit': {'sha': 'eee'}},
        ]
        with self._patch_tags(items):
            got = updater.latest_remote_tag(timeout=1)
        self.assertEqual(got['version'], '1.0.10')
        self.assertEqual(got['tag'], 'v1.0.10')
        self.assertEqual(got['sha'], 'bbb')

    def test_no_semver_tags_raises(self):
        with self._patch_tags([{'name': 'nightly'},
                               {'name': 'v2.0.0-rc1'}]
                              ):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.latest_remote_tag(timeout=1)
        self.assertIn('tag', str(ctx.exception))

    def test_non_json_response_raises(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(b'<html>blocked</html>')):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.latest_remote_tag(timeout=1)
        self.assertIn('JSON', str(ctx.exception))


class RollbackTests(UpdateTestBase):
    """rollback：装过一版之后能回到旧版本。"""

    def test_rollback_restores_previous_version(self):
        before = self.user_snapshot()
        updater.apply_package(self.pkg)
        self.assertEqual(read(self.root / '_core' / 'version.py'), NEW_VERSION_PY)

        result = updater.rollback()
        self.assertTrue(result['ok'])
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)
        self.assertEqual(read(self.root / '物化实验报告工具' / 'portal.py'),
                         OLD_PORTAL_PY)
        self.assertFalse((self.root / '燃烧热工具' / 'pcal' / 'est.py').exists(),
                         '回滚应删掉那一版新增的文件')
        self.assertEqual(self.user_snapshot(), before)

    def test_rollback_without_backup_raises(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.rollback()
        self.assertIn('备份', str(ctx.exception))

    def test_rollback_unknown_backup_name_raises(self):
        updater.apply_package(self.pkg)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.rollback(backup_name='0.0.0-19700101-000000')
        self.assertIn('找不到备份', str(ctx.exception))

    def test_rollback_by_explicit_name(self):
        result = updater.apply_package(self.pkg)
        name = Path(result['backup_dir']).name
        got = updater.rollback(backup_name=name)
        self.assertEqual(got['to'], OLD_VERSION)
        self.assertEqual(read(self.root / '_core' / 'version.py'), OLD_VERSION_PY)

    def test_rollback_restores_disk_version(self):
        """回滚后 `installed_version()`（读磁盘）要回到旧版本。"""
        updater.apply_package(self.pkg)
        self.assertEqual(updater.installed_version(), NEW_VERSION)
        updater.rollback()
        self.assertEqual(updater.installed_version(), OLD_VERSION)


class StateAndStatusTests(UpdateTestBase):
    """状态缓存：原子写、只读状态、不联网。"""

    def test_public_status_shape(self):
        status = updater.public_status()
        for key in ('ok', 'current', 'release_date', 'repo', 'available',
                    'latest', 'tag', 'checked_at', 'from_cache', 'busy',
                    'error', 'backups', 'can_rollback', 'last_apply'):
            self.assertIn(key, status, 'public_status 缺键：%s' % key)
        # current 取磁盘上的版本（临时安装根里是旧版本）
        self.assertEqual(status['current'], OLD_VERSION)
        self.assertEqual(status['release_date'], '2026-10-01')
        self.assertTrue(status['ok'])
        self.assertFalse(status['can_rollback'])

    def test_installed_version_reads_disk_not_module_constant(self):
        self.assertEqual(updater.installed_version(), OLD_VERSION)
        self.assertNotEqual(updater.installed_version(), MODULE_VERSION,
                            '假安装根里的版本应与模块常量不同，'
                            '否则测不出「读磁盘」这件事')
        write(self.root / '_core' / 'version.py',
              NEW_VERSION_PY)
        self.assertEqual(updater.installed_version(), NEW_VERSION)

    def test_installed_version_falls_back_to_module_constant(self):
        (self.root / '_core' / 'version.py').unlink()
        self.assertEqual(updater.installed_version(), MODULE_VERSION)

    def test_state_roundtrip_and_atomic_write(self):
        state = updater.load_state()
        state['latest'] = '9.9.9'
        state['checked_epoch'] = 1234567890
        updater.save_state(state)
        self.assertEqual(updater.load_state()['latest'], '9.9.9')
        self.assertTrue(Path(updater.state_path()).is_file())
        self.assertFalse(Path(updater.state_path() + '.tmp').exists(),
                         '原子写不该留下 .tmp')

    def test_corrupt_state_falls_back_to_defaults(self):
        write(updater.state_path(), '{坏掉的 json')
        state = updater.load_state()
        self.assertEqual(state['current'], MODULE_VERSION)
        self.assertEqual(state['available'], False)

    def test_check_for_update_uses_mocked_api(self):
        tags = [{'name': 'v' + NEW_VERSION, 'commit': {'sha': 'abc'}}]
        with mock.patch('urllib.request.urlopen',
                        return_value=FakeResponse(
                            json.dumps(tags).encode('utf-8'))):
            status = updater.check_for_update(force=True, timeout=1)
        self.assertTrue(status['available'])
        self.assertEqual(status['latest'], NEW_VERSION)
        self.assertEqual(status['tag'], 'v' + NEW_VERSION)
        self.assertFalse(status['from_cache'])
        self.assertEqual(status['error'], '')


class RateLimitTests(UpdateTestBase):
    """403 / 429 限流：必须单独提示「被限流」，不能笼统说「网络错误」。

    背景（2026-11-08 审计 D P1-4）：`_core/updater.py:276-282` 已经实现了这条
    分支，但 `tests/test_update.py` 里搜 `403|429|限流` 命中 **0**——下次有人
    改动 `_fetch` 的异常分类，限流能力会静默消失，用户只会看到一句
    「检查更新失败」，不知道是 GitHub 匿名 API 60 次/小时用完了（该等一小时），
    还是一个可以重试的网络抖动。

    这里不 mock `urllib.error.HTTPError`，而是起一个**真的本地 http.server**
    返 403 / 429——这样连「HTTPError 有没有被正确构造/捕获」这条链也一起测到。
    """

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            code = 403

            def do_GET(self):                      # noqa: N802  (http.server 接口)
                body = b'{"message": "API rate limit exceeded"}'
                self.send_response(Handler.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):          # 静音：测试输出别被访问日志淹没
                pass

        cls._handler = Handler
        cls._server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls._port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)
        cls._handler = None

    def _with_status(self, code):
        """把本地假 GitHub 切到指定状态码，并让 updater 指向它。"""
        self._handler.code = code
        base = 'http://127.0.0.1:%d' % self._port
        patcher = mock.patch.dict(os.environ, {
            'PCAL_UPDATE_API_BASE': base,
            'PCAL_UPDATE_CODELOAD': base,
            'PCAL_UPDATE_RAW': base,
        }, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_403_is_reported_as_rate_limit(self):
        """HTTP 403（GitHub 匿名 API 超 60 次/小时）要说「被限流」。"""
        self._with_status(403)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.latest_remote_tag(timeout=5)
        message = str(ctx.exception)
        self.assertIn('限流', message,
                      '403 必须明确说是「被限流」，实际消息：%r' % message)
        self.assertIn('403', message, '消息里要带状态码便于排障：%r' % message)
        # 不能退化成笼统的「失败」/「网络」说法
        self.assertNotIn('不是合法 JSON', message)

    def test_429_is_reported_as_rate_limit(self):
        """HTTP 429（Too Many Requests）同样要说「被限流」。"""
        self._with_status(429)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.latest_remote_tag(timeout=5)
        message = str(ctx.exception)
        self.assertIn('限流', message,
                      '429 必须明确说是「被限流」，实际消息：%r' % message)
        self.assertIn('429', message, '消息里要带状态码便于排障：%r' % message)

    def test_other_http_errors_are_not_called_rate_limit(self):
        """500 这类服务端错误不该被说成「限流」（宁少勿虚：别误导用户）。"""
        self._with_status(500)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.latest_remote_tag(timeout=5)
        message = str(ctx.exception)
        self.assertNotIn('限流', message,
                         '500 是服务端错误，不该说成限流：%r' % message)
        self.assertIn('500', message, '消息里要带状态码：%r' % message)

    def test_rate_limit_message_survives_check_for_update(self):
        """走 check_for_update() 也要把「限流」这句话原样传给用户。"""
        self._with_status(429)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.check_for_update(force=True, timeout=5)
        self.assertIn('限流', str(ctx.exception))


class NoRealRepoMutationGuard(unittest.TestCase):
    """兜底：确认测试全程没把 PCAL_UPDATE_ROOT 指到真实仓库、也没改真文件。"""

    def test_env_not_leaked(self):
        """用例结束后环境变量必须被精确还原，不能泄给其它测试。"""
        self.assertIsNone(os.environ.get('PCAL_UPDATE_ROOT'),
                          'PCAL_UPDATE_ROOT 泄漏了：%r'
                          % (os.environ.get('PCAL_UPDATE_ROOT'),))

    def test_env_root_is_not_real_repo(self):
        root = os.environ.get('PCAL_UPDATE_ROOT') or ''
        if root:
            self.assertNotEqual(os.path.abspath(root), str(REPO_ROOT),
                                'PCAL_UPDATE_ROOT 泄漏成了真实仓库路径')

    def test_real_version_file_untouched(self):
        """真实仓库的 _core/version.py 必须还是真源内容（没被测试写坏）。"""
        canonical = (REPO_ROOT / '_core' / 'version.py').read_text(encoding='utf-8')
        self.assertIn("APP_VERSION = '%s'" % MODULE_VERSION, canonical)
        self.assertNotIn(OLD_VERSION_PY, canonical)
        self.assertNotIn(NEW_VERSION_PY, canonical)

    def test_real_repo_has_no_fake_update_state(self):
        """测试造出来的「1.0.1 可用」状态不许落到真实仓库的 update_state.json。"""
        path = REPO_ROOT / 'update_state.json'
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding='utf-8') or '{}')
        self.assertNotEqual(
            data.get('last_apply', {}).get('to'), NEW_VERSION,
            '测试的假更新结果写进了真实仓库的 update_state.json')


if __name__ == '__main__':
    unittest.main()
