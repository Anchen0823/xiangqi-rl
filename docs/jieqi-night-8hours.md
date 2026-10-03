# 揭棋 8 小时训练

双击根目录 **训练揭棋8小时.cmd**。本次更新只准备并短时验证入口，没有启动整夜任务。

默认从 `runs/jieqi/pilot-20261003/model` 的最新揭棋候选继续，输出 `runs/jieqi/night-8h/`。
普通象棋 NNUE、冠军与桌面随包权重不自动替换。

每轮最多约 60 分钟，60% 时间生成独立自博弈数据，再训练 2000 次更新、恢复检查点、导出 ONNX，
分别对战基础搜索和上一轮候选，各 8 对镜像换色局。每步固定 128 次状态访问。
每轮最多 512 个训练局和 4 个验证局，避免一夜的数据同时全部装入内存。
只有真实终局进入标签；截断和未完成评测单列。下一轮使用已完成本轮的候选生成新数据，
这是继续学习，不是通过棋力晋级；模型好坏仍须看独立评测。

每轮使用不同种子域，训练、验证、两类评测互不重叠。默认 CPU 两线程训练，搜索与 ONNX 单线程，
不占用普通象棋夜训的 GPU。可明确选择 `-Device cuda` 或 `auto`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/variants/train-jieqi-8hours.ps1
```

中断后再次运行同一命令恢复，已落盘对局和检查点不会换种子重建。
**8 小时从首次启动计时，中断／关机时间也计入；恢复不会再赠送 8 小时。**
时间在整局和阶段边界检查，当前完整局、训练／导出收尾可能略微超时；余时不足时不新开一轮。
截止后想开始新的 8 小时，请更换输出目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/variants/train-jieqi-8hours.ps1 `
  -Output runs/jieqi/night-next -Initial runs/jieqi/night-8h/round-000/model
```

`night.json` 保存截止时间、当前轮次、已完成轮次及最新可用模型；
`logs/session-*.log` 保存终端日志；每轮的 `status.json`、`report.html` 与两组 `evaluation/` 查看详细进度和评测。
若权重、规则、代码或配置不兼容，脚本会停止并保留数据，不静默跳过失败。
未完成的最后一轮保留在原编号目录；`latestModel` 始终指向完整结束的一轮或原始候选。

启动前需要已有项目训练依赖、Node.js 和初始 PT／ONNX／JSON。桌面免安装包只负责对弈，训练在源码项目运行。

## 入口验收

2026-10-03 使用同一个 PowerShell 入口进行 90 秒预算的实跑：`-Hours 0.025 -RoundMinutes 1.5 -Nodes 8 -Steps 4 -Pairs 1`。
实际完成两轮：54 和 11 个训练局，每轮 4 个验证局、4 次优化更新、一次保存恢复、ONNX 导出，
每轮完成对基础搜索／上一轮模型各 1 对换色局。第二轮初始化权重来自第一轮完成的候选。
证据在 `runs/jieqi/night-script-smoke-20261003/`。这验证调度与训练闭环，不代表已执行 8 小时或棋力达标。
调度单测还覆盖中断恢复保持原截止时间与轮次、到期不再开训、配置不匹配拒绝及跨轮种子隔离。
