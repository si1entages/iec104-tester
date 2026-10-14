---
feature: ui-workspace-refine
status: designed
updated: 2026-06-15
branch: feature/ui-workspace-refine
commits: 912c97c..912c97c
---

# 主站/子站工作区 UI 完善

## Report

## [S1] Problem

双应用上线后用户反馈：

1. 部分界面模块显示不全（工具栏/侧栏被裁切、底部面板挤占）
2. 浅色主题效果差，希望**只保留深色**
3. YX/YC/YK/YM 混在同一列表里不便，缺少按类型分视图
4. 无批量修改（多选后改组号/启用/删除等）
5. 数据区与报文区 splitter 拉不动/不能自由缩放

## [S2] Design

### S2.1 深色 Only
- 桌面公共模块 `theme.py`：`get_theme()` 固定返回深色
- 主站/子站菜单去掉「浅色主题」；保留深色或直接去掉主题菜单
- `apps/*_main.py` 的 `--theme` 仅接受 `dark`（或忽略 light）

### S2.2 点表按类型分页签
- 主站 `DefinitionTable` 与子站 `SlavePointTable` 外包 `QTabWidget`
- 页签：遥信 YX | 遥测 YC | 遥控 YK | 遥脉 YM
- 每页独立表格，列更宽松；「全部」页签可选做总览（首版不做）
- 添加点时默认落在当前页签对应类型

### S2.3 批量操作
- 表格 `MultiSelection`
- 工具栏：删除选中、批量改组号、批量启用/禁用
- 子站：批量设 YX 值（选中多行同值）— 有则做，无则 YX 页签单行双击保留

### S2.4 可自由拉伸的布局
- 去掉过大的 `setStretchFactor` 强制比例；`setOpaqueResize(True)`
- 主区分割：数据区 | 命令/侧栏；底部：报文/日志等
- `setChildrenCollapsible(False)` 避免面板被压没；合理 `setMinimumWidth/Height`
- 连接栏按钮过多时允许换行或收缩（用 `QHBoxLayout` + spacer，降低 min-width）

### S2.5 显示完整性
- 顶部连接栏控件 `setMaximumWidth` 适度放宽，避免截断
- 状态条字段过多时用更短文案
- 侧栏 QScrollArea 包住响应配置/模拟面板，小窗口可滚动

## [S3] Out of Scope

- 浅色主题美化
- 图表重构、协议功能变更
- 打包/安装流程

## Tasks

- [ ] T1: 固定深色主题并移除浅色入口 — acceptance: 双窗口无浅色菜单，样式为深色 (covers: S2.1)
- [ ] T2: 主站点表 YX/YC/YK/YM 分页签 — acceptance: 四页签切换，值刷新正确 (covers: S2.2)
- [ ] T3: 子站点表分页签 + 双击改值 — acceptance: 分页后改值仍自发上送 (covers: S2.2; depends: T2)
- [ ] T4: 批量删除/改组号/启用禁用 — acceptance: 多选后操作生效 (covers: S2.3; depends: T2)
- [ ] T5: Splitter 自由拉伸 + 防塌缩 — acceptance: 数据/报文区可拖动缩小放大 (covers: S2.4)
- [ ] T6: 连接栏/侧栏布局防截断（滚动+宽度） — acceptance: 1280 宽度下控件可见 (covers: S2.5; depends: T5)
- [ ] T7: 回归 224 tests + 双窗口 offscreen 冒烟 — acceptance: 测试与冒烟通过 (covers: S2; depends: T6)
