# 磁化率的测定 - 实验报告生成工具

## 功能

本工具用于生成《磁化率的测定》实验报告，采用古埃磁天平法测定固体物质的磁化率。

### 主要功能

- 自动处理实验数据（莫尔盐标定、样品磁化率计算）
- 计算摩尔磁化率、分子磁矩、未成对电子数
- 生成符合课程要求的 Word 格式实验报告
- 提供交互式网页界面进行数据查看和参数调整

## 使用方法

### 1. 启动工具

双击 `启动.vbs`（无黑框）或运行：

```bash
python run.py
```

### 2. 网页界面

启动后会自动打开浏览器，访问 `http://127.0.0.1:8781`。

### 3. 数据输入

- 点击"载入示例数据"使用内置的 2025 年参照数据
- 或上传 JSON 格式的实验数据文件

### 4. 生成报告

填写封面信息后，点击"生成报告"按钮。

报告输出位置：`../实验报告输出/<学号>-<姓名>-磁化率/`

## 数据格式

JSON 格式，包含以下字段：

```json
{
  "temperature_C": 22.5,
  "tube": {
    "m_zero": 18.2345,
    "m_field": 18.2340
  },
  "mohr_salt": {
    "m_zero": 24.5678,
    "m_field": 24.5890
  },
  "硫酸铜": {
    "m_zero": 23.4567,
    "m_field": 23.4612
  },
  "亚铁氰化钾": {
    "m_zero": 22.3456,
    "m_field": 22.3450
  },
  "未知样": {
    "m_zero": 21.2345,
    "m_field": 21.2389
  }
}
```

## 计算原理

### 1. 莫尔盐标定

莫尔盐的比磁化率公式：

$$\chi_{\text{莫}} = \frac{9500 \times 10^{-9}}{T + 1} \times 4\pi \quad (\text{m}^3 \cdot \text{kg}^{-1})$$

### 2. 样品磁化率

$$\chi_{\text{样}} = \chi_{\text{标}} \cdot \frac{m_{\text{标}}}{m_{\text{样}}} \cdot \frac{\Delta m_{\text{样}} - \Delta m_{\text{空}}}{\Delta m_{\text{标}} - \Delta m_{\text{空}}}$$

### 3. 摩尔磁化率

$$\chi_m = \chi \cdot M \quad (\text{m}^3 \cdot \text{mol}^{-1})$$

### 4. 分子磁矩

$$\mu = 797.7 \sqrt{\chi_m \cdot T} \quad (\mu_B)$$

### 5. 未成对电子数

$$n = \sqrt{797.7^2 \cdot \chi_m \cdot T + 1} - 1$$

## 依赖

- Python 3.9+
- numpy
- scipy
- matplotlib
- python-docx

## 文件结构

```
磁化率工具/
├─ run.py              启动入口
├─ README.md           使用说明
├─ settings.json       用户配置（自动生成）
├─ web/                网页界面
│  └─ index.html
├─ pcal/               计算内核
│  ├─ magnetic.py      磁化率计算
│  ├─ analysis.py      数据分析
│  ├─ plotting.py      绘图
│  ├─ report.py        报告生成
│  ├─ server.py        网页服务
│  ├─ docxkit.py       Word 文档工具
│  └─ omml.py          公式生成
├─ data/               数据文件
├─ assets/             资源文件
└─ templates/          报告模板
```

## 版本

v1.0 (2026-10-24)

## 许可

GPL-3.0

## 2026-10-24 工程化更新

- 导出报告时同目录写 `workspace.json`（配置、数据文件路径与 SHA256、取点、版本），便于以后复现；
- 入口页「个人档案 / 年度数据目录」统一管理姓名/学号和本模块的数据目录；
- PDF 预览在入口页「报告输出 / PDF 预览」，用本机 Word 转换。
- 编辑中的内容会自动存草稿，刷新页面会提示恢复；
- 回归测试：`python tests/run_tests.py`；核心同步：`python _core/sync_core.py --check`。
