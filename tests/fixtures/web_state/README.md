# web_state —— 前端冒烟用的 /api/state 快照

每个模块一份 `<工具名>.json`，是它**真实的** `/api/state` 响应，供
`tests/smoke_app.js` 在 node 里把 `web/app.js` 真跑一遍时使用。

## 为什么需要

`node --check` 只查语法。2026-11-14 化学动力学的 `fillConfig` 里把参数名
`c` 写成 `cfg`，语法完全合法，但页面一加载就是：

```
初始化失败：cfg is not defined
```

冒烟脚本会触发 `boot()`，既抓未捕获异常，**也读状态栏文字**——因为
`boot()` 内部有 try/catch，会把异常吞进 `setStatus`，只看异常会漏掉。

## 为什么不能手写假数据

前端 `boot()` 直接消费这个结构。手写的假数据一旦字段对不上，就会报
`Cannot read properties of undefined`——那是**假数据的错**，会淹没真正的
前端 bug。所以一律用真实响应。

## ⚠️ 个人信息必须清洗

这些文件会进**公开仓库**。真实的 `/api/state` 里带着姓名、学号、组别，
`report_name` 里甚至有 `"2400011877-张三-偶极矩.docx"`，还有本机绝对路径。

清洗规则：结构、键名、数组长度**全部保留**（测试只需要结构），只把值换成
占位符；学号、姓名、路径用文本替换兜底。

`tests/test_portable.py::test_state_fixtures_have_no_personal_info` 会守住这条。

## 重新抓取

```bash
node tests/dump_states.js <仓库根> tests/fixtures/web_state \
  '["燃烧热工具","溶解热工具","蒸气压工具","双液系工具","化学动力学工具",
    "表面吸附工具","电导率工具","电化学工具","偶极矩工具","磁化率工具","紫外光谱工具"]'
```

抓完**务必**再洗一遍个人信息（学号、姓名、`report_name`、绝对路径），
然后跑：

```bash
python tests/run_tests.py
```

`test_state_fixtures_exist` 会检查 11 个模块都有快照——缺了冒烟就是喂空
数据，形同虚设。
