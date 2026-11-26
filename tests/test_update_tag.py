# -*- coding: utf-8 -*-
"""tag 写法的兼容性守卫：`1.4.3` 与 `v1.4.3` 都必须能下载。

背景（2026-11-26 用户同学实测撞到）：
入口页从 v1.0.0 起就一直把**归一化版本号**（`UPD.latest`，没有 `v`）
当 tag 发给 `/api/update/apply`，后端于是拼出

    https://codeload.github.com/<slug>/zip/refs/tags/1.4.3

而仓库打的 tag 是 `v1.4.3` → codeload 回 **404**。症状是
「安装失败：下载更新包失败（HTTP 404）：…/refs/tags/1.4.3」，
而且**在每一个已发布版本上都会复现**——从 v1.0.0 到 v1.4.3 无一例外。
既有测试全绿却抓不到：`DownloadPackageTests` 一律传 `'v' + NEW_VERSION`，
`latest_remote_tag` 的用例只验「从 API 里挑最大 tag」，两端各自都对，
拼在一起才错。

因为坏掉的前端已随旧版本发出去了，**必须在后端兜住**（`canonical_tag`），
所以本文件守着后端这一层；前端那条断言只是防止以后再退化。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from support import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from _core import updater                     # noqa: E402

NEW_VERSION = '1.4.3'
GOOD_ZIP = b'PK\x03\x04' + b'x' * 2048        # >1 KB 且以 PK 开头，够过校验


class CanonicalTagTests(unittest.TestCase):
    """`canonical_tag` / `_tag_candidates` 的纯函数行为。"""

    def test_bare_version_gets_v_prefix(self):
        self.assertEqual(updater.canonical_tag('1.4.3'), 'v1.4.3')
        self.assertEqual(updater.canonical_tag('v1.4.3'), 'v1.4.3')
        # 多余空白不能破坏拼 URL
        self.assertEqual(updater.canonical_tag('  1.4.3  '), 'v1.4.3')

    def test_two_part_version_is_not_touched(self):
        """`1.4` 不是三段式，`version_tuple` 认不出，就不该被改写。

        仓库的 tag 一律是 `vX.Y.Z`（`make_release.py` 用 `version.tag_for`），
        两段式根本不是合法 tag，改写它只会掩盖配置错误。
        """
        self.assertEqual(updater.canonical_tag('1.4'), '1.4')
        self.assertEqual(updater.canonical_tag('v1.4'), 'v1.4')

    def test_non_version_tag_is_untouched(self):
        """非 X.Y.Z tag（分支名之类）不许被改写——那是另一种合法用法。"""
        for raw in ('main', 'nightly', 'release-2026'):
            self.assertEqual(updater.canonical_tag(raw), raw)

    def test_empty_is_safe(self):
        self.assertEqual(updater.canonical_tag(''), '')
        self.assertEqual(updater.canonical_tag(None), '')
        self.assertEqual(updater._tag_candidates(None), [])

    def test_candidates_put_canonical_first(self):
        self.assertEqual(updater._tag_candidates('1.4.3'), ['v1.4.3', '1.4.3'])
        self.assertEqual(updater._tag_candidates('v1.4.3'), ['v1.4.3', '1.4.3'])


class DownloadTagCompatibilityTests(unittest.TestCase):
    """两种 tag 写法都必须落到**同一个** `v` 前缀 URL 上并能下下来。"""

    def setUp(self):
        self.seen_urls = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            self.seen_urls.append(url)
            return _FakeResponse(GOOD_ZIP)

        patcher = mock.patch('urllib.request.urlopen', side_effect=fake_urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _download(self, tag):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / ('%s.zip' % str(tag).replace('/', '_'))
            got = updater.download_package(tag, str(dest), timeout=5)
            return Path(got).read_bytes()

    def test_bare_version_downloads(self):
        """核心回归：传 `1.4.3` 必须成功，且第一次就打到 /refs/tags/v1.4.3。"""
        self.assertEqual(self._download(NEW_VERSION), GOOD_ZIP)
        self.assertEqual(self.seen_urls,
                         ['https://codeload.github.com/%s/zip/refs/tags/v1.4.3'
                          % updater._version.REPO_SLUG])

    def test_v_prefixed_version_downloads(self):
        self.assertEqual(self._download('v' + NEW_VERSION), GOOD_ZIP)
        self.assertEqual(len(self.seen_urls), 1)

    def test_404_falls_back_to_bare_tag(self):
        """仓库万一打的是不带 v 的 tag，也要能退回去试一次。"""
        calls = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            calls.append(url)
            if url.endswith('/refs/tags/v1.4.3'):
                raise _http_error(404, url)
            return _FakeResponse(GOOD_ZIP)

        import tempfile
        with mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            with tempfile.TemporaryDirectory() as tmp:
                got = updater.download_package(
                    NEW_VERSION, str(Path(tmp) / 'x.zip'), timeout=5)
                self.assertEqual(Path(got).read_bytes(), GOOD_ZIP)
        self.assertEqual(len(calls), 2, '404 后应换一种 tag 写法重试一次')
        self.assertTrue(calls[1].endswith('/refs/tags/1.4.3'))

    def test_both_missing_reports_404(self):
        """两种写法都不存在时，错误信息里要留下 404 与 URL（便于用户报障）。"""

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            raise _http_error(404, url)

        import tempfile
        with mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(updater.UpdateError) as ctx:
                    updater.download_package(
                        NEW_VERSION, str(Path(tmp) / 'x.zip'), timeout=5)
        message = str(ctx.exception)
        self.assertIn('404', message)
        self.assertIn('refs/tags/', message)


class UpdateNowTagTests(unittest.TestCase):
    """`update_now` 拿到裸版本号时，也要能推出 expected_version 守门。"""

    def test_bare_tag_derives_expected_version(self):
        captured = {}

        def fake_download(tag, dest_zip, progress=None, timeout=180):
            captured['tag'] = tag
            raise updater.UpdateError('停在这里，不真的装')

        with mock.patch.object(updater, 'download_package', side_effect=fake_download):
            with self.assertRaises(updater.UpdateError):
                updater.update_now(tag=NEW_VERSION, timeout=5)
        self.assertEqual(captured['tag'], 'v1.4.3',
                         'update_now 应把裸版本号归一化成带 v 的 tag 再下载')

    def test_expected_version_defaults_to_tag_version(self):
        """不传 expected_version 时，用 tag 的版本号守门（装错包能立刻发现）。"""
        captured = {}

        def fake_download(tag, dest_zip, progress=None, timeout=180):
            captured['tag'] = tag

        def fake_apply(package_root, expected_version=None, **kwargs):
            captured['expected'] = expected_version
            return {'ok': True}

        with mock.patch.object(updater, 'download_package', side_effect=fake_download), \
                mock.patch.object(updater, 'extract_package', return_value='pkg'), \
                mock.patch.object(updater, 'apply_package', side_effect=fake_apply):
            updater.update_now(tag='v' + NEW_VERSION, timeout=5)
        self.assertEqual(captured['expected'], NEW_VERSION)


class FrontendSendsTagTests(unittest.TestCase):
    """前端那条 404 的源头：不许再把归一化版本号当 tag 发出去。"""

    def setUp(self):
        self.src = (REPO_ROOT / '物化实验报告工具' / 'web' / 'index.html'
                    ).read_text(encoding='utf-8')

    def test_apply_does_not_send_bare_latest(self):
        self.assertNotIn("'/api/update/apply', { tag: latest",
                         self.src,
                         '入口页又直接把 latest（归一化版本号）当 tag 发了，'
                         '这就是 2026-11-26 那个 404 的成因')

    def test_apply_prefers_tag_field(self):
        self.assertIn('UPD.tag', self.src,
                      '入口页应优先用后端给的 tag（带 v）')


class _FakeResponse:
    def __init__(self, body):
        self._body = body
        self._pos = 0
        self.headers = {'Content-Length': str(len(body))}
        self.status = 200

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


def _http_error(code, url):
    import urllib.error
    return urllib.error.HTTPError(url, code, 'Not Found', {}, None)


if __name__ == '__main__':
    unittest.main()