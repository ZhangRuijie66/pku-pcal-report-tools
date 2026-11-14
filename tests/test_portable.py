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


class DependencyTableTests(unittest.TestCase):
    """启动器的依赖表必须写 pip 安装名、且与各工具真实 import 对齐。

    2026-11-14 排查「别人电脑装不上」时，顺带发现两个同类缺陷：

    · ``DEPS`` 里写的是 ``docx``。PyPI 上 ``docx`` 是 2011 年那个废弃包
      （0.2.4，只有一个单文件 docx.py），而项目要的是 ``python-docx``。
      更麻烦的是装了假包之后 ``import docx`` **会通过**，`_has()` 于是判
      「依赖齐了」，真正崩在 docxkit 的 ``docx.shared`` 上。
    · 表面吸附工具的 ``pcal/exportdata.py`` 真的 import openpyxl，但
      ``DEPS`` 没给它列 → 缺这个包时不会弹安装窗，直接启动失败。
      表现是「双击没反应 / 秒退」，没有任何提示。

    这里做**静态交叉核对**：依赖表 vs 各工具 pcal 里的真实 import。
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = REPO_ROOT / '_tools' / 'launcher.py'
        spec = importlib.util.spec_from_file_location('_launcher_deps', str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.mod = mod

    def _all_declared(self):
        names = set(self.mod.DEFAULT_DEPS)
        for deps in self.mod.DEPS.values():
            names |= set(deps)
        return names

    def test_no_legacy_docx_distribution(self):
        """依赖表里不许出现 ``docx`` 这个分发包名（必须是 python-docx）。"""
        used = self._all_declared()
        self.assertNotIn(
            'docx', used,
            'DEPS 里写的是 PyPI 上废弃的 docx 包，装完 import docx 会「成功」'
            '但缺 docx.shared，实际起不来。请改成 python-docx。')

    def test_probe_table_covers_every_declared_dep(self):
        """每个声明过的依赖都要有探测表达式，否则探测会退化成死猜。"""
        declared = self._all_declared()
        probes = set(self.mod.PROBE_EXPR)
        missing = sorted(declared - probes)
        self.assertEqual(
            missing, [],
            '这些依赖没有登记探测表达式（PROBE_EXPR）：%s\n'
            '没登记会退回「import 模块名」，而 python-docx 这种必须探子模块'
            '才能认出冒牌包。' % missing)

    def test_python_docx_probe_reaches_submodule(self):
        """python-docx 的探测必须到 docx.shared（只 import docx 挡不住假包）。"""
        expr = self.mod.PROBE_EXPR.get('python-docx', '')
        self.assertIn('docx.shared', expr,
                      'python-docx 的探测表达式要包含 docx.shared，'
                      '否则 PyPI 上的假 docx 会被误判成「已安装」；'
                      '当前是 %r' % expr)

    def test_tools_importing_openpyxl_declare_it(self):
        """pcal 里真 import openpyxl 的工具，DEPS 必须列 openpyxl。"""
        offenders = []
        for mod in self._tool_dirs():
            real = self._real_imports(mod, 'openpyxl')
            if not real:
                continue
            declared = set(self.mod.DEPS.get(mod, self.mod.DEFAULT_DEPS))
            if 'openpyxl' not in declared:
                offenders.append('%s：%s 里 import 了 openpyxl，但 DEPS 没列'
                                 % (mod, ', '.join(sorted(real))))
        self.assertEqual(
            offenders, [],
            '这些工具会用 openpyxl 却不会因此弹安装窗，缺包时只会启动即崩：\n'
            + '\n'.join(offenders))

    #: pcal 里可能出现的第三方包 → 它在 DEPS 里的分发包名。
    #: 只列「项目真会用到」的，标准库不在内。
    IMPORT_TO_DIST = {
        'numpy': 'numpy',
        'scipy': 'scipy',
        'matplotlib': 'matplotlib',
        'docx': 'python-docx',      # import 名 docx ↔ 分发包 python-docx
        'openpyxl': 'openpyxl',
        'rdkit': 'rdkit',
        'paramiko': 'paramiko',
    }

    def test_declared_deps_cover_real_imports(self):
        """每个工具真实 import 的第三方包，都要被它的依赖清单覆盖。

        这是「缺包时会不会弹安装窗」的正面判据：漏登一个包，使用者那台
        机器上没有它，就会启动即崩且没有任何提示。
        """
        offenders = []
        for tool in self._tool_dirs():
            declared = set(self.mod.DEPS.get(tool, self.mod.DEFAULT_DEPS))
            for module, dist in self.IMPORT_TO_DIST.items():
                hits = self._real_imports(tool, module)
                if not hits:
                    continue
                if dist in declared:
                    continue
                # 高斯计算工具的 paramiko 可走 vendor/，不算硬依赖
                if tool == '高斯计算工具' and dist == 'paramiko':
                    continue
                offenders.append('%s：import 了 %s（分发包 %s），但依赖清单是 %s'
                                 % (tool, module, dist, sorted(declared)))
        self.assertEqual(
            offenders, [],
            '这些工具用到的包没有登记进 DEPS，缺包时不会弹安装窗、'
            '只会启动即崩：\n' + '\n'.join(offenders))

    # ---- 辅助 ---------------------------------------------------------
    def _tool_dirs(self):
        import importlib.util
        path = REPO_ROOT / '物化实验报告工具' / 'portal.py'
        spec = importlib.util.spec_from_file_location('_portal_deps', str(path))
        portal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(portal)
        names = [m.get('tool') for m in portal.MODULES if m.get('tool')]
        # 高斯计算工具不在 MODULES 里（独立仓库），但确实由同一启动器拉起
        if (REPO_ROOT / '高斯计算工具' / 'gcalc').is_dir():
            names.append('高斯计算工具')
        return names

    def _real_imports(self, tool, module):
        """这个工具目录里真正 import 了 module 的文件（相对路径列表）。

        ⚠️ 返回的是**文件路径**，不是模块名。判「有没有用到」要写
        ``if not hits``，不要写 ``if module not in hits``。

        只看 ``import x`` / ``from x`` 这种**语句**，注释和字符串里的不算；
        跳过 vendor/（第三方自带副本不算工具的依赖）。还要排除
        ``workspace.py`` 里那种「字符串清单」——它是元数据，不是依赖。
        """
        import re
        pat = re.compile(r'^\s*(?:import|from)\s+%s(?:[\s.,]|$)' % module,
                         re.MULTILINE)
        hits = []
        root = REPO_ROOT / tool
        if not root.is_dir():
            return hits
        for path in root.rglob('*.py'):
            rel = str(path.relative_to(root)).replace('\\', '/')
            if 'vendor/' in rel or '__pycache__' in rel:
                continue
            try:
                src = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            # 去掉整行注释，避免 ``# import openpyxl`` 这种说明被当成依赖
            code = '\n'.join(ln for ln in src.splitlines()
                              if not ln.lstrip().startswith('#'))
            if pat.search(code):
                hits.append(rel)
        return hits


class ShortcutScriptTests(unittest.TestCase):
    """桌面快捷方式的创建脚本必须存在、可移植、且不会写死开发机路径。

    以前这一步只写在技能文档里（手工敲 PowerShell），换台电脑就得重来，
    而且很容易漏 ``IconLocation``——漏了不会报错，只是变成 pythonw.exe 的
    默认蓝图标，属于「不说话的错误」。现在脚本化并加测试。
    """

    @classmethod
    def setUpClass(cls):
        cls.path = REPO_ROOT / '_tools' / '创建快捷方式.py'
        cls.src = cls.path.read_text(encoding='utf-8')

    def test_script_exists(self):
        self.assertTrue(self.path.is_file(),
                        '缺少 _tools/创建快捷方式.py（桌面快捷方式没法重建）')

    def test_paths_derived_from_file(self):
        """根目录必须从 __file__ 推导，不能写死盘符。"""
        self.assertIn('__file__', self.src,
                      '创建快捷方式.py 应从头文件位置推导套件根目录')
        self.assertIsNone(DEV_ROOT_RE.search(self.src),
                          '创建快捷方式.py 里不许出现写死的开发机路径')

    def test_sets_icon_location(self):
        """必须显式设 IconLocation，否则退回默认蓝图标（属于不说话的错误）。"""
        self.assertIn('IconLocation', self.src,
                      '要设 $link.IconLocation，否则快捷方式没有锥形瓶图标')
        self.assertIn('pcal.ico', self.src,
                      '图标应指向 _tools/pcal.ico')

    def test_targets_wscript_with_vbs(self):
        """双击要无黑框启动：Target=wscript.exe，Arguments 是 启动入口.vbs。"""
        self.assertIn('wscript', self.src.lower(),
                      '快捷方式应以 wscript.exe 为目标（这样才没有命令行窗口）')
        self.assertIn('启动入口.vbs', self.src,
                      '参数要指向 启动入口.vbs')

    def test_verifies_after_save(self):
        """建完要回读校验，不能存完就宣布成功。"""
        self.assertIn('def read(', self.src)
        create_body = self.src.split('def create(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('read(', create_body,
                      'create() 写完应回读校验（否则存坏了也不知道）')

    def test_reports_errors_instead_of_silent_none(self):
        """读 .lnk 失败要明确报错，不能静默返回 None 属性。

        WScript.Shell.CreateShortcut 对非 .lnk 后缀抛 COMException，而
        PowerShell 默认不把它变成非零退出码——原实现因此静默返回
        Target=None，看起来像「读到了一个没有目标的快捷方式」。
        """
        self.assertIn('ERR ', self.src,
                      'read() 应把 PowerShell 的异常显式带出来（ERR 前缀）')
        self.assertIn("Write-Output ('ERR '", self.src,
                      'PS 片段里要 try/catch 并把错误信息打出来')

    def test_script_runs_and_checks(self):
        """真跑一次 --check：能回读现有快捷方式或明确说不存在。"""
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable, str(self.path), '--check'],
            capture_output=True, timeout=60)
        out = (r.stdout or b'').decode('utf-8', 'replace')
        # 0 = 读到了；1 = 没装（也合理，比如别人的电脑还没建过）
        self.assertIn(r.returncode, (0, 1),
                      '--check 异常退出：%s / %s'
                      % (out[:300], (r.stderr or b'').decode('utf-8', 'replace')[:300]))
        if r.returncode == 0:
            self.assertIn('目标', out)
        else:
            self.assertTrue('读不到快捷方式' in out or '不存在' in out,
                            '找不到快捷方式时应给出可读提示，实际输出：%r' % out[:300])


class FrontendBootTests(unittest.TestCase):
    """每个模块的 web/app.js 必须能在最小 DOM 环境里真跑起来。

    挡的是**语法合法但运行即崩**的前端 bug（如 ``cfg is not defined``）：
    ``node --check`` 只看语法，这类错误它一个都抓不到。
    """

    @classmethod
    def setUpClass(cls):
        import shutil
        cls.node = shutil.which('node')
        cls.harness = REPO_ROOT / 'tests' / 'smoke_app.js'
        cls.state_dir = REPO_ROOT / 'tests' / 'fixtures' / 'web_state'

    def _modules(self):
        import importlib.util
        path = REPO_ROOT / '物化实验报告工具' / 'portal.py'
        spec = importlib.util.spec_from_file_location('_portal_boot', str(path))
        portal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(portal)
        return [m.get('tool') for m in portal.MODULES if m.get('tool')]

    def test_node_available(self):
        self.assertIsNotNone(
            self.node,
            '找不到 node，无法做前端冒烟检查。'
            '这台机器上 node 是有的（v26.x）；CI 里缺 node 时应显式跳过而不是静默通过。')
        self.assertTrue(self.harness.is_file(),
                        '缺少 tests/smoke_app.js（前端冒烟脚本）')

    def test_every_module_app_boots(self):
        """逐个模块真跑 app.js，不许出现运行时错误或"初始化失败"。"""
        import subprocess
        if not self.node:
            self.skipTest('没有 node')
        bad = []
        for tool in self._modules():
            app = REPO_ROOT / tool / 'web' / 'app.js'
            if not app.is_file():
                bad.append('%s：没有 web/app.js' % tool)
                continue
            # 第二个参数是该模块真实的 /api/state 快照（tests/fixtures/web_state）。
            # 手写假数据字段对不上会报 "Cannot read properties of undefined"，
            # 那是假数据的错，会淹没真正的前端 bug。
            state = self.state_dir / (tool + '.json')
            args = [self.node, str(self.harness), str(app)]
            if state.is_file():
                args.append(str(state))
            r = subprocess.run(args, capture_output=True, timeout=120)
            out = ((r.stdout or b'') + (r.stderr or b'')).decode('utf-8', 'replace')
            if r.returncode != 0:
                head = ' / '.join(ln.strip() for ln in out.strip().splitlines()[-3:])
                bad.append('%s：%s' % (tool, head[:300]))
        self.assertEqual(
            bad, [],
            '这些模块的前端脚本一加载就报错，界面上会停在「初始化失败」：\n'
            + '\n'.join(bad))

    def test_state_fixtures_exist(self):
        """每个模块都要有真实 /api/state 快照，否则冒烟用的是空数据（形同虚设）。"""
        missing = [tool for tool in self._modules()
                   if not (self.state_dir / (tool + '.json')).is_file()]
        self.assertEqual(
            missing, [],
            '这些模块缺少 tests/fixtures/web_state/<工具>.json。\n'
            '用下面的命令重新抓（需先确保各模块能独立启动）：\n'
            '  node tests/dump_states.js <仓库根> tests/fixtures/web_state '
            '\'["工具名", ...]\'\n'
            '缺快照时冒烟脚本会喂空数据，前端问题就查不出来了。')

    def test_state_fixtures_have_no_personal_info(self):
        """夹具是 /api/state 的真实响应，会进**公开仓库**——必须清掉个人信息。

        2026-11-14 抓完快照差点直接提交：里面带着真实姓名、学号、组别，
        还有 `report_name`（"2400011877-张三-偶极矩.docx"）和本机绝对路径。
        冒烟测试只需要结构，不需要真实值，所以统一换成占位符。
        这条守住"以后重新抓快照时别忘了洗一遍"。
        """
        import json as _json
        leaks = []
        for path in sorted(self.state_dir.glob('*.json')):
            text = path.read_text(encoding='utf-8')
            hits = []
            # ⚠ 不能假设学号的位数开头。北大本科是 10 位（2400011877），
            # 但更稳的判据是「数字串整体恰为 10 位」——用零宽断言把它从
            # 浮点数里摘出来（293.84999999999997 里的数字串不是独立 token）。
            for pat, label in ((r'(?<![\d.])2\d{9}(?![\d.])', '学号'),
                               (r'[Dd]:\\\\+北大', '开发机路径'),
                               (r'C:\\\\+Users\\\\+[A-Za-z]', '用户目录'),
                               (r'张瑞杰', '真实姓名')):
                if re.search(pat, text):
                    hits.append(label)
            try:
                data = _json.loads(text)
            except ValueError as exc:
                leaks.append('%s：JSON 坏了（%s）' % (path.name, exc))
                continue
            if hits:
                leaks.append('%s：含 %s' % (path.name, '、'.join(hits)))
        self.assertEqual(
            leaks, [],
            '这些前端状态快照里还有个人信息/本机路径，不能进公开仓库：\n'
            + '\n'.join(leaks)
            + '\n清洗方法见 tests/fixtures/web_state/README.md')

    def test_js_syntax_all_apps(self):
        """顺带保一层语法：node --check 每个 app.js。"""
        import subprocess
        if not self.node:
            self.skipTest('没有 node')
        bad = []
        for tool in self._modules():
            app = REPO_ROOT / tool / 'web' / 'app.js'
            if not app.is_file():
                continue
            r = subprocess.run([self.node, '--check', str(app)],
                               capture_output=True, timeout=60)
            if r.returncode != 0:
                err = (r.stderr or b'').decode('utf-8', 'replace').strip()
                bad.append('%s：%s' % (tool, err.splitlines()[0][:200] if err else '?'))
        self.assertEqual(bad, [], 'JS 语法错误：\n' + '\n'.join(bad))


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
