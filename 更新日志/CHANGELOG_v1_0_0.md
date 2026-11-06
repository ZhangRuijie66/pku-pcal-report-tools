# v1.0.0

- **类型**：功能
- **日期**：2026-11-06
- **说明**：首个带版本号与自动更新能力的发行版。

## 新增

- **版本号体系**：整套工具一个版本号，真源在 `_core/version.py`
  （`APP_VERSION` / `RELEASE_DATE` / `REPO_SLUG`），11 个工具的 `pcal/version.py`
  由 `_core/sync_core.py` 同步，`_core/check_version.py` 一致性自检。
- **自动抓取更新**：入口页「软件更新 / 版本号」卡片可以检查新版本
  （认 git tag，不看 main 的最新提交）、看更新说明、一键下载并安装，
  并支持回滚上一版。
- **安全边界**：安装前先把要覆盖的文件备份到 `_core/updates/backups/<旧版本>-<时间>/`；
  `settings.json`、`profile.json`、各工具 `data/`、`实验报告输出/`、`发布/`、
  日志与 `.git/` 一律不覆盖；装完用子进程自检，自检不过自动还原。
- **命令行通道**：`python _tools/launcher.py --update [--apply] [--no-restart]`，
  可在没有界面的场合检查/安装更新。
- **发版脚本**：`python make_release.py patch|minor|major --notes "…" --type 修复`
  一条命令完成改版本号、写更新日志、同步核心件、跑全量测试、commit + tag + push。

## 版本号规则

- 三段式 `X.Y.Z`；第三段只装**递增序号**，修复类别用文字写在本文件的「类型」里，
  不编进版本号（与光谱可视化分析工具 SpectraLab 的口径一致）。
- `MAJOR` = 破坏性变更（目录结构、报告输出布局、`settings.json` 键名）；
  `MINOR` = 用户可感知的新功能；`PATCH` = 修复，序号 +1，不跳号。

## 基线

- 11 个实验模块：燃烧热、溶解热、蒸气压、双液系、化学动力学、表面吸附、
  电导率、电化学、偶极矩、磁化率、紫外光谱；入口页按讲义实验顺序排列、按需启动。
- 核心排版件 canonical 在 `_core/`，`python tests/run_tests.py` 全量回归。
