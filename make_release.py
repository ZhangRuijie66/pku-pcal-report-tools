# -*- coding: utf-8 -*-
"""发版一条龙：改版本号 → 写更新日志 → 同步核心件 → 跑全量测试 → commit + tag + push。

    python make_release.py patch --notes "修复：更新检查的节流" --type 修复
    python make_release.py minor --notes "新增：自动抓取更新；修：入口页版本号" --type 功能 --apply
    python make_release.py major --notes "破坏：settings.json 键名改了" --type 破坏 --apply

**默认只打印计划**，不动任何文件、不碰 git；确认无误再加 `--apply` 才真正执行。

`--apply` 的步骤（任一步失败都会把版本号与 CHANGELOG 还原，打印「已中止：原因」，返回码 1）：

    1. `git status --porcelain` 必须为空（`--allow-dirty` 可跳过，输出里会显著提示）；
    2. 读 `_core/version.py` 的 APP_VERSION，按 `version.bump()` 算新版本；
       若 `更新日志/CHANGELOG_v<新版本>.md` 已存在则拒绝（不许重号）；
    3. 正则改 `APP_VERSION` 与 `RELEASE_DATE`（今天，本地时区 `%Y-%m-%d`），
       保留文件其余内容与行尾风格；
    4. 写 `更新日志/CHANGELOG_v<X>_<Y>_<Z>.md`（UTF-8、LF）；
    5. `python _core/sync_core.py --apply`（把 version.py 同步进 11 个工具）；
    6. `python tests/run_tests.py` 必须退出码 0，否则中止；
    7. `git add -A` → `git commit -m "发布 vX.Y.Z：<notes 第一条>"`
       → `git tag vX.Y.Z` → `git push` → `git push --tags`；
    8. `git ls-remote --tags origin` 复核新 tag 在远端，打印结果。

版本号规则（真源 `_core/version.py`，与 SpectraLab 一致）：三段式 `X.Y.Z`，
PATCH 只装递增序号，修复类别用 `--type` 的文字写进 CHANGELOG 的「类型」，
不编进版本号；MAJOR 改变后 MINOR/PATCH 归 0。

只用标准库；不覆盖仓库已配置的 git 提交身份（`git config user.name`）。
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / '_core' / 'version.py'
CHANGELOG_DIR = ROOT / '更新日志'
README_FILE = ROOT / 'README.md'
CHECK_VERSION = ROOT / '_core' / 'check_version.py'

sys.path.insert(0, str(ROOT))
from _core import version as ver  # noqa: E402  （真源：APP_VERSION / bump / tag_for）

KINDS = ('patch', 'minor', 'major')
DEFAULT_TYPE = '修复'

# 11 个实验模块（与 _core/sync_core.py 的 TOOLS 一致）
TOOL_DIRS = (
    '燃烧热工具', '溶解热工具', '蒸气压工具', '双液系工具', '化学动力学工具',
    '表面吸附工具', '电导率工具', '电化学工具', '偶极矩工具', '磁化率工具',
    '紫外光谱工具',
)

_APP_VERSION_RE = re.compile(r"""^(\s*APP_VERSION\s*=\s*)(['"])(.*?)\2""", re.MULTILINE)
_RELEASE_DATE_RE = re.compile(r"""^(\s*RELEASE_DATE\s*=\s*)(['"])(.*?)\2""", re.MULTILINE)
_QUOTED_RE = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['"])(.*?)\2""", re.MULTILINE)
# README 顶部那句：当前版本 **v1.0.0**（2026-11-06），版本号与更新日志见 …
_README_VERSION_RE = re.compile(
    r'(当前版本\s*\*\*v)(\d+\.\d+\.\d+)(\*\*（)(\d{4}-\d{2}-\d{2})(）)')


class ReleaseError(Exception):
    """可直接展示给用户的中文失败原因。"""


# --------------------------------------------------------------------------- 小工具


def _run(cmd):
    """跑一条子进程命令（cwd=仓库根），返回 (returncode, stdout, stderr)。"""
    env = dict(os.environ)
    # 子进程的 stdout 是管道；显式 UTF-8，免得脚本打印中文/✓ 时抛 UnicodeEncodeError
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    proc = subprocess.run([str(c) for c in cmd], cwd=str(ROOT), capture_output=True, env=env)
    out = (proc.stdout or b'').decode('utf-8', 'replace')
    err = (proc.stderr or b'').decode('utf-8', 'replace')
    return proc.returncode, out, err


def _git(*args):
    return _run(['git'] + list(args))


def _tail(text, lines=12):
    """只留最后几行，避免把整份测试输出糊到屏幕上。"""
    rows = [r for r in (text or '').replace('\r\n', '\n').split('\n') if r.strip()]
    if len(rows) <= lines:
        return '\n'.join(rows)
    return '\n'.join(['…（省略 %d 行）' % (len(rows) - lines)] + rows[-lines:])


def split_notes(notes):
    """`--notes` 支持用 `;` 或 `；` 分隔多条，一条一个 bullet。"""
    if not notes:
        return []
    items = []
    for chunk in re.split(r'[;；]', ' '.join(notes)):
        text = chunk.strip()
        if text:
            items.append(text)
    return items


def stale_tool_copies(new_version):
    """同步之后检查 11 个工具的 pcal/version.py 是否都是 new_version。

    返回 (缺失的, 版本不对的) 两个列表（都是仓库相对路径）。
    """
    missing, mismatched = [], []
    for tool in TOOL_DIRS:
        path = ROOT / tool / 'pcal' / 'version.py'
        rel = '%s/pcal/version.py' % tool
        if not path.exists():
            missing.append(rel)
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        found = {m.group(1): m.group(3) for m in _QUOTED_RE.finditer(text)}
        if ver.normalize(found.get('APP_VERSION', '')) != new_version:
            mismatched.append(rel)
    return missing, mismatched


def read_source():
    """按原始行尾风格读 `_core/version.py`（newline='' 保留 CRLF/LF 原样）。"""
    with open(VERSION_FILE, 'r', encoding='utf-8', newline='') as fh:
        return fh.read()


def read_app_version():
    """从 `_core/version.py` 源文本里取 APP_VERSION 与 RELEASE_DATE。"""
    text = read_source()
    found = {m.group(1): m.group(3) for m in _QUOTED_RE.finditer(text)}
    app_version = found.get('APP_VERSION')
    if ver.version_tuple(app_version) is None:
        raise ReleaseError('_core/version.py 里的 APP_VERSION 不是一个三段式版本号：%r'
                           % (app_version,))
    return app_version, found.get('RELEASE_DATE', '')


def bump_version(current, kind):
    try:
        return ver.bump(current, kind)
    except ValueError as exc:
        raise ReleaseError(str(exc))


def changelog_text(new_version, release_date, release_type, notes):
    """CHANGELOG 正文（LF 行尾）。"""
    bullets = notes or ['常规维护']
    head = [
        '# v%s' % new_version,
        '',
        '- **类型**：%s' % release_type,
        '- **日期**：%s' % release_date,
        '- **说明**：%s' % (notes[0] if notes else '常规维护'),
        '',
        '## 变更',
        '',
    ]
    head.extend('- %s' % item for item in bullets)
    return '\n'.join(head) + '\n'


def rewrite_version_file(text, new_version, release_date):
    """正则替换 APP_VERSION / RELEASE_DATE，其余内容与行尾风格原样保留。"""
    for pattern, label, value in (
        (_APP_VERSION_RE, 'APP_VERSION', new_version),
        (_RELEASE_DATE_RE, 'RELEASE_DATE', release_date),
    ):
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ReleaseError('_core/version.py 里 %s 出现 %d 次（应为 1 次），不敢改'
                               % (label, len(matches)))
        match = matches[0]
        quote = match.group(2)
        text = text[:match.start()] + match.group(1) + quote + value + quote + text[match.end():]
    return text


def read_text_raw(path):
    """按原始行尾风格读文本（newline='' 保留 CRLF/LF）。"""
    with open(path, 'r', encoding='utf-8', newline='') as fh:
        return fh.read()


def rewrite_readme_version(text, new_version, release_date):
    """README 顶部那句「当前版本 **vX.Y.Z**（YYYY-MM-DD）」跟着版本走。

    `_core/check_version.py` 会扫描 README 里的旧版本号，这句话不更新的话，
    下次发版就会 fail。
    """
    new_text, n = _README_VERSION_RE.subn(
        lambda m: '%s%s%s%s%s' % (m.group(1), new_version, m.group(3),
                                  release_date, m.group(5)),
        text)
    if n != 1:
        raise ReleaseError('README.md 里找不到唯一的「当前版本 **vX.Y.Z**（日期）」那一行'
                           '（匹配到 %d 处），发版后 check_version 会报旧版本号残留' % n)
    return new_text


def dirty_entries():
    """工作区未提交改动（含未跟踪文件）；git 不可用时返回 None。"""
    code, out, err = _git('status', '--porcelain')
    if code != 0:
        return None
    return [line for line in out.replace('\r\n', '\n').split('\n') if line.strip()]


# --------------------------------------------------------------------------- 计划


def build_plan(kind, notes, release_type, allow_dirty):
    """收集计划所需的全部信息（只读，不写任何文件）。"""
    current, current_date = read_app_version()
    new_version = bump_version(current, kind)
    release_date = datetime.date.today().strftime('%Y-%m-%d')
    changelog_path = CHANGELOG_DIR / ver.changelog_filename(new_version)
    tag = ver.tag_for(new_version)
    first_note = notes[0] if notes else '常规维护'
    plan = {
        'current': current,
        'current_date': current_date,
        'kind': kind,
        'new_version': new_version,
        'release_date': release_date,
        'release_type': release_type,
        'notes': notes,
        'changelog_path': changelog_path,
        'tag': tag,
        'commit_message': '发布 v%s：%s' % (new_version, first_note),
        'allow_dirty': allow_dirty,
        'dirty': dirty_entries(),
    }
    plan['changelog_text'] = changelog_text(new_version, release_date, release_type, notes)
    # 计划阶段就先确认 README 那句改得动（改不动说明文案变了，得先修，不然发版半路炸）
    try:
        plan['readme_text'] = rewrite_readme_version(
            read_text_raw(README_FILE), new_version, release_date)
    except ReleaseError as exc:
        plan['readme_text'] = None
        plan['readme_problem'] = str(exc)
    return plan


def print_plan(plan, apply_mode=False):
    """打印发版计划（默认模式与 --apply 开头都会走这里）。"""
    title = '发版执行' if apply_mode else '发版计划（只打印，不动手；确认后加 --apply 才执行）'
    print(title)
    print('  当前版本   %s（%s）' % (plan['current'], plan['current_date'] or '未知日期'))
    print('  发版类型   %s' % plan['kind'])
    print('  新版本     %s   →  tag %s' % (plan['new_version'], plan['tag']))
    print('  CHANGELOG 类型   %s' % plan['release_type'])
    print('  CHANGELOG 日期   %s（今天，本地时区）' % plan['release_date'])
    print('  说明       %s' % (plan['notes'][0] if plan['notes'] else '常规维护（未给 --notes）'))
    if len(plan['notes']) > 1:
        for item in plan['notes'][1:]:
            print('             %s' % item)
    print('  将改文件   _core/version.py（APP_VERSION / RELEASE_DATE）')
    print('             %s（新建）' % plan['changelog_path'].relative_to(ROOT).as_posix())
    print('             README.md（顶部「当前版本 **vX.Y.Z**（日期）」那句）')
    print('  同步       _core/version.py → 11 个工具的 pcal/version.py'
          '（python _core/sync_core.py --apply）')

    print('\n  CHANGELOG 首几行：')
    for line in plan['changelog_text'].split('\n')[:8]:
        print('    %s' % line)
    print('    …')

    if plan.get('readme_text') is None:
        print('\n  [WARN] README.md 的「当前版本」那句没匹配上：%s' % plan.get('readme_problem'))
        print('         --apply 会在这里中止（发版后 check_version 会报旧版本号残留）。')

    print('  将执行的 git 命令：')
    print('    git add -A')
    print('    git commit -m "%s"' % plan['commit_message'])
    print('    git tag %s' % plan['tag'])
    print('    git push')
    print('    git push --tags')
    print('    git ls-remote --tags origin   （复核 tag 是否已在远端）')

    dirty = plan['dirty']
    if dirty is None:
        print('\n  [WARN] 读不到 git 状态（git 不可用？），--apply 时会被拒绝。')
    elif dirty:
        print('\n  工作区有 %d 处未提交改动（--apply 会拒绝；--allow-dirty 可跳过）：' % len(dirty))
        for line in dirty[:10]:
            print('    %s' % line)
        if len(dirty) > 10:
            print('    …（共 %d 行）' % len(dirty))
    else:
        print('\n  工作区干净（git status --porcelain 为空）。')

    # 新日期早于旧日期时提一句：说明系统时钟或上一版日期写错了，别默默发出一个「倒着走」的版本
    if plan['current_date'] and plan['release_date'] < plan['current_date']:
        print('\n  [WARN] 新 RELEASE_DATE %s 早于当前版本的 %s。'
              '若不是在补发旧版，请先核对系统日期或 _core/version.py 的 RELEASE_DATE。'
              % (plan['release_date'], plan['current_date']))


# --------------------------------------------------------------------------- 执行


def _restore(original_text, original_readme, changelog_path, sync_ran):
    """失败收尾：还原 version.py / README.md、删掉新建的 CHANGELOG、
    必要时把旧版本同步回 11 个工具。"""
    problems = []
    try:
        with open(VERSION_FILE, 'w', encoding='utf-8', newline='') as fh:
            fh.write(original_text)
    except OSError as exc:
        problems.append('还原 _core/version.py 失败：%s' % exc)
    if original_readme is not None:
        try:
            with open(README_FILE, 'w', encoding='utf-8', newline='') as fh:
                fh.write(original_readme)
        except OSError as exc:
            problems.append('还原 README.md 失败：%s' % exc)
    try:
        if changelog_path.exists():
            changelog_path.unlink()
    except OSError as exc:
        problems.append('删除 %s 失败：%s' % (changelog_path.name, exc))
    if sync_ran:
        code, out, err = _run([sys.executable, '_core/sync_core.py', '--apply'])
        if code != 0:
            problems.append('把旧版本同步回 11 个工具失败（%d）：%s'
                            % (code, _tail(out + err, 6)))
    return problems


def do_apply(plan):
    """真正执行发版；任一步失败抛 ReleaseError（已尽量还原现场）。"""
    notes = plan['notes']
    new_version = plan['new_version']
    changelog_path = plan['changelog_path']
    tag = plan['tag']
    original_text = read_source()
    original_readme = None
    state = {'sync_tried': False, 'committed': False, 'tagged': False}

    def abort(reason, extra=()):
        problems = [str(item) for item in extra if item]
        if not state['committed']:
            problems += _restore(original_text, original_readme, changelog_path,
                                 state['sync_tried'])
        lines = ['已中止：%s' % reason]
        for item in problems:
            lines.append('  - %s' % item)
        if not state['committed']:
            lines.append('  版本号与 CHANGELOG 已还原。')
        else:
            lines.append('  注意：提交已经生成，代码已按新版本落盘，没有回退。')
            todo = []
            if not state['tagged']:
                todo.append('git tag %s' % tag)
            todo += ['git push', 'git push --tags']
            lines.append('  修好远端后接着跑：' + ' && '.join(todo))
        raise ReleaseError('\n'.join(lines))

    # 1) 工作区检查
    dirty = plan['dirty']
    if dirty is None:
        abort('读不到 git 状态（git 不可用或不在仓库里），无法确认工作区干净')
    if dirty:
        if not plan['allow_dirty']:
            abort('工作区有未提交改动，先提交或 stash（共 %d 处）；'
                  '确要带脏发版可加 --allow-dirty' % len(dirty))
        print('[WARN] 已用 --allow-dirty 跳过工作区检查：下面这些未提交改动会被一起提交。')
        for line in dirty[:10]:
            print('       %s' % line)
        if len(dirty) > 10:
            print('       …（共 %d 行）' % len(dirty))

    # 2) 不许重号
    if changelog_path.exists():
        abort('%s 已存在，不允许重号；请先确认版本号' % changelog_path.name)

    # 3) 改 version.py（README 那句在发版前先试着改一遍，改不动就别动 version.py）
    if plan.get('readme_text') is None:
        abort('README.md 顶部「当前版本 **vX.Y.Z**（日期）」那句改不动：%s\n'
              '       先修好 README 的这行文案再发版（check_version 会扫它）。'
              % plan.get('readme_problem'))

    new_text = rewrite_version_file(original_text, new_version, plan['release_date'])
    try:
        with open(VERSION_FILE, 'w', encoding='utf-8', newline='') as fh:
            fh.write(new_text)
    except OSError as exc:
        abort('写 _core/version.py 失败：%s' % exc)
    print('[OK] _core/version.py：APP_VERSION %s → %s，RELEASE_DATE → %s'
          % (plan['current'], new_version, plan['release_date']))

    # 3b) README 顶部那句当前版本跟着走（否则 check_version 会报旧版本号残留）
    try:
        original_readme = read_text_raw(README_FILE)
        with open(README_FILE, 'w', encoding='utf-8', newline='') as fh:
            fh.write(plan['readme_text'])
    except OSError as exc:
        abort('写 README.md 失败：%s' % exc)
    print('[OK] README.md：顶部当前版本改为 v%s（%s）'
          % (new_version, plan['release_date']))

    # 4) 写 CHANGELOG
    try:
        CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(changelog_path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(plan['changelog_text'])
    except OSError as exc:
        abort('写 %s 失败：%s' % (changelog_path.name, exc))
    print('[OK] 已写 %s' % changelog_path.relative_to(ROOT).as_posix())

    # 5) 同步核心件
    state['sync_tried'] = True
    code, out, err = _run([sys.executable, '_core/sync_core.py', '--apply'])
    if code != 0:
        abort('python _core/sync_core.py --apply 失败（退出码 %d）' % code,
              [_tail(out + err, 10)])
    missing, mismatched = stale_tool_copies(new_version)
    if missing or mismatched:
        detail = []
        if missing:
            detail.append('没有生成 %d 个（%s）' % (len(missing), '、'.join(missing[:3])
                                                    + ('…' if len(missing) > 3 else '')))
        if mismatched:
            detail.append('版本没跟上 %d 个（%s）' % (len(mismatched),
                                                      '、'.join(mismatched[:3])
                                                      + ('…' if len(mismatched) > 3 else '')))
        abort('同步后 11 个工具的 pcal/version.py 没全部到位：%s。\n'
              '       多半是 _core/sync_core.py 的 FILES 里还没列 version.py'
              '（updater-core 负责）。先把它补上再发版。' % '；'.join(detail))
    print('[OK] 已同步 version.py 进 11 个工具的 pcal/')

    # 6) 全量测试
    print('     正在跑全量测试（python tests/run_tests.py）…')
    code, out, err = _run([sys.executable, 'tests/run_tests.py'])
    if code != 0:
        abort('全量测试未通过（退出码 %d）' % code, [_tail(out + err, 14)])
    print('[OK] 全量测试通过')

    # 6b) 版本号一致性（有 check_version.py 时必跑：能抓到 README 旧版本号残留这类问题）
    if CHECK_VERSION.exists():
        code, out, err = _run([sys.executable, '_core/check_version.py'])
        if code != 0:
            abort('版本号一致性检查没过（退出码 %d）' % code, [_tail(out + err, 14)])
        print('[OK] 版本号一致性检查通过')

    # 7) commit + tag + push
    for args, label in (
        (('add', '-A'), 'git add -A'),
        (('commit', '-m', plan['commit_message']), 'git commit'),
    ):
        code, out, err = _git(*args)
        if code != 0:
            abort('%s 失败（退出码 %d）' % (label, code), [_tail(out + err, 10)])
    state['committed'] = True
    code, out, _ = _git('rev-parse', '--short', 'HEAD')
    short_sha = out.strip().split('\n')[-1] if code == 0 else '?'
    print('[OK] 已提交 %s（%s）' % (short_sha, plan['commit_message']))

    code, out, err = _git('tag', tag)
    if code != 0:
        abort('git tag %s 失败（退出码 %d）' % (tag, code), [_tail(out + err, 10)])
    state['tagged'] = True
    print('[OK] 已打 tag %s' % tag)

    for args, label in ((('push',), 'git push'),
                        (('push', '--tags'), 'git push --tags')):
        print('     正在执行 %s …' % label)
        code, out, err = _git(*args)
        if code != 0:
            abort('%s 失败（退出码 %d）' % (label, code), [_tail(out + err, 10)])
    print('[OK] 已推送到远端')

    # 8) 远端复核
    code, out, err = _git('ls-remote', '--tags', 'origin')
    if code != 0:
        abort('git ls-remote --tags origin 失败（退出码 %d）' % code, [_tail(out + err, 10)])
    remote_ok = any(line.rstrip().endswith('refs/tags/' + tag) for line in out.split('\n'))
    if not remote_ok:
        abort('远端没有找到 tag %s（推送可能没生效）' % tag)

    print('[OK] 远端已确认 tag %s' % tag)
    print('\n发版完成')
    print('  版本号     %s（%s）' % (new_version, plan['release_date']))
    print('  commit     %s' % short_sha)
    print('  tag        %s' % tag)
    print('  远端确认   git ls-remote --tags origin 里已有 refs/tags/%s' % tag)
    print('  更新说明   %s/%s' % (ver.REPO_URL + '/releases/tag', tag))
    return 0


# --------------------------------------------------------------------------- 入口


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='发版：改版本号 + 写 CHANGELOG + 同步核心件 + 全量测试 + commit/tag/push',
        epilog='默认只打印计划；加 --apply 才真正执行。')
    ap.add_argument('kind', choices=KINDS, help='patch 修 bug / minor 新功能 / major 破坏性变更')
    ap.add_argument('--notes', action='append', default=[],
                    help='更新说明，多条用 ; 或 ； 分隔（一条一个 bullet）')
    ap.add_argument('--type', default=DEFAULT_TYPE,
                    help='写进 CHANGELOG 的「类型」：修复|功能|破坏|数值|界面|文档…（默认 %s）'
                         % DEFAULT_TYPE)
    ap.add_argument('--apply', action='store_true', help='真正执行（默认只打印计划）')
    ap.add_argument('--allow-dirty', action='store_true',
                    help='跳过「工作区必须干净」检查（CI/首次使用留的口子，会显著提示）')
    args = ap.parse_args(argv)

    release_type = (args.type or DEFAULT_TYPE).strip()
    if not release_type:
        print('已中止：--type 不能为空')
        return 1

    notes = split_notes(args.notes)
    try:
        plan = build_plan(args.kind, notes, release_type, args.allow_dirty)
        print_plan(plan, apply_mode=args.apply)
        if not args.apply:
            print('\n（这是计划。确认无误后重跑并加 --apply 才会真正发版。）')
            return 0
        return do_apply(plan)
    except ReleaseError as exc:
        print('\n%s' % exc)
        return 1


if __name__ == '__main__':
    sys.exit(main())
