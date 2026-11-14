# -*- coding: utf-8 -*-
"""可移植包的静态体检：换台电脑解压也必须能跑。

这里是**纯静态检查**（不打包、不起服务器、不读真实数据），几毫秒跑完，
专门挡住那类"在开发机上好好的、拷到别人电脑上就炸"的回归：

  · 代码里写死开发机的绝对路径（``D:\\北大\\…``）——可移植包解压到别人
    电脑上该路径根本不存在，于是 --test 直接 exit 1、默认数据目录指向一个
    不存在的盘。
  · .cmd 不是纯 ASCII（cmd.exe 按 OEM 代码页解释，中文注释会乱码甚至把
    命令截断）；.vbs 不是 UTF-16 BOM（WSH 只认 UTF-16/ANSI，UTF-8 存中文
    会弹出乱码提示框）。
  · 入口页登记的 11 个模块目录不存在或缺 run.py。
  · 可移植包里混进了本机状态（settings.json / profile.json / data/*.json），
    使用者解压后会看到别人的姓名学号，或者本机数据被顶掉。

只做静态断言，所以能在 5 秒内跑完；真机验证仍然靠打包后手工解压跑一次。
"""
from __future__ import annotations

import re
import zipfile
import unittest
from pathlib import Path

from support import REPO_ROOT

# 会进可移植包、并且会被 cmd.exe / WSH / 浏览器真正执行的代码文件
CODE_SUFFIXES = {'.py', '.js', '.html', '.cmd', '.vbs'}

# 构建中间产物与缓存不参与检查（在遍历时直接剪枝，否则要扫 3 万多个文件）
SKIP_DIRS = {'__pycache__', '_stage_portable', '.git', '_tmp_update',
             '_test_out', '实验报告输出', '更新日志', '发布', 'backups',
             'updates', 'data', '高斯计算工具', 'node_modules', '.venv'}

# 开发机上那条写死的绝对路径（出现在代码里就是 bug）
DEV_ROOT_RE = re.compile(r'D:\\?北大')


def _iter_files(suffixes):
    """仓库里所有后缀命中的文件（遍历时跳过缓存/构建产物/第三方大目录）。

    用 os.walk + 剪枝，而不是 Path.rglob：仓库里 发布/_stage_portable 和
    高斯计算工具（vendor 了 cffi 等）加起来三万多文件，全量 rglob 要 3 秒。
    """
    import os

    def _walk(root):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() in suffixes:
                    yield path

    return _walk(str(REPO_ROOT))


def _rel(path):
    return str(path.relative_to(REPO_ROOT)).replace('\\', '/')


class NoHardcodedDevPathTests(unittest.TestCase):
    """代码里不许写死开发机的绝对路径（P0：可移植包换电脑就炸）。"""

    def test_no_dev_root_literal_in_code(self):
        hits = []
        for path in _iter_files(CODE_SUFFIXES):
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
            except OSError as exc:                    # pragma: no cover
                self.fail('读不了 %s：%s' % (_rel(path), exc))
            for lineno, line in enumerate(text.splitlines(), 1):
                if DEV_ROOT_RE.search(line):
                    hits.append('%s:%d: %s' % (_rel(path), lineno, line.strip()))
        self.assertEqual(
            hits, [],
            '代码里还有写死的开发机路径（可移植包到别人电脑上必然失败）。\n'
            '改成运行时推导：套件根下的 数据/ → 工具目录内的 样例数据/ → 工具目录本身。\n'
            + '\n'.join(hits))

    def test_scanned_enough_files(self):
        """自检：确实扫到了那些关键文件（避免路径写错导致"0 命中"的假绿）。"""
        names = {_rel(p) for p in _iter_files(CODE_SUFFIXES)}
        for must in ('_tools/launcher.py',
                     '物化实验报告工具/portal.py',
                     '燃烧热工具/run.py',
                     '溶解热工具/run.py',
                     '紫外光谱工具/run.py',
                     '紫外光谱工具/web/app.js'):
            self.assertIn(must, names, '扫描没覆盖到 %s，检查 SKIP_DIRS' % must)


class LauncherEncodingTests(unittest.TestCase):
    """.cmd 必须是纯 ASCII，.vbs 必须是 UTF-16 BOM（否则 cmd/WSH 乱码）。"""

    def test_cmd_files_are_pure_ascii(self):
        bad = []
        for path in _iter_files({'.cmd'}):
            data = path.read_bytes()
            offenders = [(i, b) for i, b in enumerate(data) if b > 127]
            if offenders:
                bad.append('%s：%d 个非 ASCII 字节（首个在偏移 %d）'
                           % (_rel(path), len(offenders), offenders[0][0]))
        self.assertEqual(
            bad, [],
            '.cmd 里有非 ASCII 字节——cmd.exe 按 OEM 代码页解释，中文会乱码'
            '甚至把命令截断。这些文件必须是纯 ASCII：\n' + '\n'.join(bad))

    def test_vbs_files_are_utf16_with_bom(self):
        bad, checked = [], 0
        for path in _iter_files({'.vbs'}):
            checked += 1
            data = path.read_bytes()
            if len(data) < 2 or data[0] != 0xFF or data[1] != 0xFE:
                head = ' '.join('%02X' % b for b in data[:4])
                bad.append('%s：开头是 %s，不是 UTF-16 LE BOM（FF FE）'
                           % (_rel(path), head))
        self.assertEqual(
            bad, [],
            'WSH 只认 UTF-16/ANSI，UTF-8 存中文会弹出乱码提示框。'
            '用 python _tools/生成vbs.py 重新生成（它写 UTF-16 BOM）：\n'
            + '\n'.join(bad))
        self.assertGreater(checked, 0, '一个 .vbs 都没找到，检查路径不对')


class RequirementsEncodingTests(unittest.TestCase):
    """依赖清单必须是纯 ASCII，且 pip 子进程强制 UTF-8 模式。

    2026-11-14 用户拷到别人电脑上，首次运行就炸在 pip 上：

        UnicodeDecodeError: 'gbk' codec can't decode byte 0xaa in position 7

    根因不是网络也不是缺包：pip 解析 requirements 文件时，**只有**文件带
    UTF-8 BOM、或头两行有 PEP 263 声明，才按 UTF-8 解码；否则退回
    ``locale.getpreferredencoding()``。中文 Windows 是 cp936，于是清单里
    第一行那句中文注释就让 pip 直接抛异常，而那层只报「依赖安装失败，请检查
    网络」——看着像网络问题，其实是编码问题。

    两道防线各测一条：清单本身纯 ASCII（治本）+ 启动器给 pip 设
    PYTHONUTF8=1（治标，防旧包或以后又写进中文）。
    """

    #: 明确要检查的清单（高斯计算工具在 SKIP_DIRS 里，单独点名）
    KNOWN = ('requirements.txt', '高斯计算工具/requirements.txt')

    def _requirements_files(self):
        found = {p for p in self.KNOWN
                 if (REPO_ROOT / p).is_file()}
        # 兜底：以后再冒出别的依赖清单也别漏掉
        for path in _iter_files({'.txt'}):
            if path.name.lower().startswith('requirement'):
                found.add(_rel(path))
        return sorted(found)

    def test_requirements_files_are_pure_ascii(self):
        files = self._requirements_files()
        self.assertIn('requirements.txt', files,
                      '没找到根目录的 requirements.txt，检查路径不对')
        bad = []
        for rel in files:
            data = (REPO_ROOT / rel).read_bytes()
            offenders = [(i, b) for i, b in enumerate(data) if b > 127]
            if offenders:
                line = data[:offenders[0][0]].count(b'\n') + 1
                bad.append('%s：%d 个非 ASCII 字节（首个在第 %d 行偏移 %d）'
                           % (rel, len(offenders), line, offenders[0][0]))
        self.assertEqual(
            bad, [],
            '依赖清单里有非 ASCII 字节。pip 在 cp936 环境下会用 GBK 解码这个'
            '文件，遇到 UTF-8 中文注释直接抛 UnicodeDecodeError，'
            '首次运行就装不上依赖。注释请写成英文：\n' + '\n'.join(bad))

    def test_requirements_files_parse_as_ascii(self):
        """再解一遍：确认真的能按 ASCII 读出来（而不是只有字节全 <=127）。"""
        for rel in self._requirements_files():
            with self.subTest(file=rel):
                (REPO_ROOT / rel).read_bytes().decode('ascii')

    def test_launcher_forces_utf8_for_pip(self):
        """启动器跑 pip 时要带 PYTHONUTF8=1，且确实传给了 pip 子进程。"""
        src = (REPO_ROOT / '_tools' / 'launcher.py').read_text(encoding='utf-8')
        self.assertIn('def _pip_env(', src,
                      'launcher.py 应有 _pip_env()，给 pip 子进程强制 UTF-8 模式')
        self.assertIn("env['PYTHONUTF8'] = '1'", src,
                      '_pip_env() 里要设 PYTHONUTF8=1')
        pip_calls = [ln for ln in src.splitlines()
                     if 'subprocess.call(' in ln or 'subprocess.run(' in ln]
        self.assertTrue(any('env=_pip_env()' in ln for ln in pip_calls),
                        '调用 pip 的 subprocess 必须传 env=_pip_env()，'
                        '否则 UTF-8 兜底根本没生效；当前调用：%s' % pip_calls)

    def test_install_cmd_forces_utf8(self):
        """双击安装依赖.cmd 的路径同样要设 PYTHONUTF8。"""
        data = (REPO_ROOT / '安装依赖.cmd').read_bytes()
        text = data.decode('ascii')          # 顺便再验一次纯 ASCII
        self.assertIn('PYTHONUTF8', text.upper(),
                      '安装依赖.cmd 里要 set "PYTHONUTF8=1"，'
                      '否则双击安装的路径仍会用 cp936 解码依赖清单')


class LauncherStopTests(unittest.TestCase):
    """launcher.py 的 --stop 自动化路径必须不弹框、且要秒回。"""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO_ROOT / '_tools' / 'launcher.py').read_text(encoding='utf-8')

    def test_stop_all_has_interactive_switch(self):
        self.assertIn('def stop_all(interactive=', self.src,
                      'stop_all 必须带 interactive 开关（双击弹框、命令行不弹）')
        self.assertIn("interactive=('--interactive' in argv[1:])", self.src,
                      "--stop 只在带 --interactive 时才弹框")

    def test_alert_is_guarded_by_interactive(self):
        """_alert 必须被 `if interactive:` 罩住，否则无交互环境下永久卡死。"""
        stop_src = self.src.split('def stop_all(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('if interactive:', stop_src,
                      'stop_all 里要用 `if interactive:` 罩住 _alert')
        guarded = stop_src.split('if interactive:', 1)[1]
        self.assertIn('_alert(', guarded,
                      '_alert 必须写在 `if interactive:` 里面')

    def test_double_click_path_passes_interactive(self):
        hidden = REPO_ROOT / '_tools' / 'hidden-launch.vbs'
        self.assertTrue(hidden.exists(), '缺少 _tools/hidden-launch.vbs')
        hl = hidden.read_bytes().decode('utf-16')
        self.assertIn(
            '--stop --interactive', hl,
            'hidden-launch.vbs 里双击路径应传 `--stop --interactive`：'
            '双击要弹框确认「已停止」，命令行调用不弹')

    def test_stop_probes_ports_in_parallel(self):
        """入口没在跑时 --stop 要秒回：不能串行探 30 个端口（每个 0.4s 超时）。"""
        self.assertIn('_probe_ports', self.src,
                      'launcher 应先并发筛端口，否则 --stop 空跑要 12s')
        self.assertIn('ThreadPoolExecutor', self.src)


class PortalModulesTests(unittest.TestCase):
    """入口页登记的 11 个模块目录都要在，且各有 run.py。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        portal_path = REPO_ROOT / '物化实验报告工具' / 'portal.py'
        spec = importlib.util.spec_from_file_location(
            'pcal_portal_portable_test', str(portal_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.portal = module

    def test_eleven_modules_declared(self):
        mods = [m for m in self.portal.MODULES if m.get('tool')]
        self.assertGreaterEqual(len(mods), 11,
                                '入口页至少应登记 11 个实验模块，实际 %d' % len(mods))

    def test_every_module_has_run_py(self):
        missing = []
        for mod in self.portal.MODULES:
            tool = mod.get('tool')
            if not tool:
                continue
            tool_dir = REPO_ROOT / tool
            if not tool_dir.is_dir():
                missing.append('%s：目录不存在' % tool)
            elif not (tool_dir / 'run.py').is_file():
                missing.append('%s：缺 run.py' % tool)
        self.assertEqual(missing, [], '模块目录不完整：\n' + '\n'.join(missing))


class PortableZipTests(unittest.TestCase):
    """若已打好可移植包，断言本机状态没有混进去。"""

    ZIP_NAME = '物化实验报告工具-可移植版.zip'

    def _zip_path(self):
        return REPO_ROOT / '发布' / self.ZIP_NAME

    def test_zip_excludes_local_state(self):
        path = self._zip_path()
        if not path.is_file():
            self.skipTest('还没打可移植包（发布/%s 不存在）' % self.ZIP_NAME)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        self.assertIn('启动入口.cmd', names, '包里缺 启动入口.cmd')
        self.assertTrue(any(n.endswith('portal.py') for n in names),
                        '包里缺入口页 portal.py')
        self.assertTrue(any(n.endswith('_tools/launcher.py') for n in names),
                        '包里缺启动器 _tools/launcher.py')

        bad = []
        for name in names:
            base = name.rsplit('/', 1)[-1]
            if base in ('settings.json', 'profile.json'):
                bad.append(name)
            elif re.search(r'(^|/)data/[^/]+\.json$', name):
                bad.append(name)          # 本机录入数据
            elif base == 'update_state.json':
                bad.append(name)          # 本机更新检查缓存
        self.assertEqual(
            bad, [],
            '可移植包里混进了本机状态（使用者解压后会看到别人的姓名学号，'
            '或本机数据被顶掉）：\n' + '\n'.join(bad[:20]))

    def test_zip_has_no_hardcoded_dev_path(self):
        """包里的代码不许写死开发机路径——但只对**本次源码已修好**的包判定。

        `发布/*.zip` 是某次打包时的快照：源码修好前打的包当然还带着旧路径。
        那种情况不该让测试失败（用户还没重新打包），但要说清楚——
        用 skip 把"包是旧的"和"代码又退化了"区分开。
        """
        path = self._zip_path()
        if not path.is_file():
            self.skipTest('还没打可移植包')
        hits = []
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if Path(name).suffix.lower() not in CODE_SUFFIXES:
                    continue
                try:
                    text = zf.read(name).decode('utf-8', 'replace')
                except (KeyError, OSError):           # pragma: no cover
                    continue
                if DEV_ROOT_RE.search(text):
                    hits.append(name)
        if not hits:
            return
        # 包里有旧路径：区分"包是旧快照"（源码已修好）还是"源码又退化了"
        src_hits = []
        for rel in hits:
            local = REPO_ROOT / rel
            if not local.is_file():
                continue
            if DEV_ROOT_RE.search(local.read_text(encoding='utf-8',
                                                  errors='replace')):
                src_hits.append(rel)
        self.assertEqual(
            src_hits, [],
            '当前源码里仍写死开发机路径（不是包旧，是代码退化了）：\n'
            + '\n'.join(src_hits))
        self.skipTest(
            '发布/%s 是修复前打的旧快照，里面还有 %d 个文件带着开发机路径；'
            '重跑 python make_portable.py 重新打包即可（当前源码已干净）。'
            % (self.ZIP_NAME, len(hits)))


if __name__ == '__main__':
    unittest.main()
