# 项目结构与产物边界

产品提供四个平级模式：**普通象棋 / 变体实验室 / 揭棋 / 翻棋**。
自定义棋子实验属于变体实验室；揭棋和翻棋拥有独立入口、规则哈希及权重。

```text
src/
  main/                    Electron 主进程
  preload/                 桌面桥接
  renderer/                四模式界面；LabApp 为新增模式共享界面
  variants/                新增三模式共享 TS 裁判、观测、搜索、评测
native/                    普通象棋 C++ 裁判、搜索、NNUE
trainer/src/
  xiangqi_nnue/            普通象棋训练（保留原夜训改动）
  xiangqi_variants/
    lab.py                 共享策略价值模型、训练、导出
    jieqi.py               揭棋限时试训与独立配对评测
scripts/
  variants/                新增模式构建、服务、实验、训练、审计
  *.ps1 / *.py             普通象棋原入口及少量旧路径兼容转发
docs/                      规则、训练与验收说明
runs/
  jieqi/<run-id>/          揭棋每次试训的完整可追溯产物
  variants/               早期三模式短训快照，保留用于对照
checkpoints/               普通象棋历史权重，保持原路径
data/、datasets/           普通象棋历史数据，保持原路径
reports/variants/          已完成的子力实验与历史验收证据
build/、dist/、dist-electron/ 可重建的编译产物
output/                    浏览器测试截图等临时验证产物
```

本轮整理把六个新增模式工具的实现归入 `scripts/variants/`，为旧路径保留转发入口。
普通象棋训练目录、现有大数据和历史检查点保持原位置，避免已有续训命令失效。
新揭棋任务统一保存到 `runs/jieqi/<run-id>`，不向普通 NNUE 目录写权重。

每次揭棋试训目录包含：

- `run.json`、`status.json`、`summary.json`：固定配置、进度、最终结果。
- `engine.mjs`：此次运行的裁判快照；哈希写入数据与评测配置。
- `previous/`：旧揭棋候选的 PT、ONNX 与清单快照。
- `dataset/`：分局压缩训练数据、完整棋谱、数据清单；截断另列。
- `model/`：可恢复检查点、ONNX、兼容清单、导出误差和整份验证集指标。
- `evaluation/baseline/`、`evaluation/previous/`：独立种子的换色局，JSON、CSV、中文 HTML。
- `logs/`：本次后台执行日志（交互启动也可用终端留存）。

目录名 `variants` 表示实现复用，不把揭棋、翻棋收进“变体实验室”菜单。
