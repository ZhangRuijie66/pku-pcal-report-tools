# v1.3.3

- **类型**：修复
- **日期**：2026-11-14
- **说明**：修复：依赖清单含中文注释导致别人电脑首次运行 pip 报 UnicodeDecodeError（gbk codec can't decode byte 0xaa）

## 变更

- 修复：依赖清单含中文注释导致别人电脑首次运行 pip 报 UnicodeDecodeError（gbk codec can't decode byte 0xaa）
- requirements.txt 改纯 ASCII，启动器与安装脚本给 pip 强制 UTF-8
