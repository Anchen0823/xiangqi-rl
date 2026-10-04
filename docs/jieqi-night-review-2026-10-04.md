# 揭棋第一夜训练审计与后续评测

实际运行 7.984 小时，完整完成 13 轮：5,478 个训练局、52 个验证局、26,000 次优化更新。
这 5,530 个数据局的种子互不重复，文件哈希全部通过；13 轮 ONNX 导出一致性检查通过。
各轮合计另有 416 局轮内评测。所有轮次完成，训练汇总中没有排除的截断局。

最终候选：`runs/jieqi/night-8h/round-012/model/candidate.onnx`。
SHA256：`b979d8b3f06e74efc75ea70d70e50865dbea7fc620eca7003e23539f456b6886`。
最终一轮数据、策略样本、合法回放、评测预算与固定搜索随机源复现审计通过，
证据：`runs/jieqi/night-8h/round-012/audit.json`；跨轮文件完整性汇总：`campaign-audit.json`。

最终轮对基础搜索 12 胜 2 和 2 负，得分率 81.25%，配对 Hoeffding 95% 区间约 33.2%—100%；
对上一轮候选 7 胜 2 和 7 负，得分率 50%，区间约 2.0%—98.0%。
每项仅 8 对，不能证明提升；上一轮也不是桌面现用的训练前模型。

## 正在运行的独立复测

事先固定选择最后完整一轮，不按小样本胜率挑选中间最佳轮次。
分别对基础搜索与夜训前桌面模型（`pilot-20261003`）各 32 对，共 128 局；
每步 128 状态访问、rollout 4，使用 3,005,000,000 与 3,006,000,000 起始的新种子域。
按整对统计区间，两个对手分别报告；不将逐轮、不同对手的胜率混为同一模型成绩。
初始模型及裁判哈希固定，逐局保存，配置不符拒绝恢复。当前启动预算为 60 分钟，
截止时允许当前一局收尾；未完成部分明确计为缺失，重复命令按原编号补齐。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/variants/evaluate-jieqi-night.ps1
```

结果目录 `runs/jieqi/night-review-20261004/evaluation/`，两个对手各有中文 HTML、JSON、CSV。
本报告只确认评测已启动，不声称 128 局已完成。桌面默认权重暂不替换。

## 下一批训练

原输出目录已到期，重复原命令不会再获得 8 小时。需新输出目录及新种子段，例如：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/variants/train-jieqi-8hours.ps1 `
  -Output runs/jieqi/night-second -Initial runs/jieqi/night-8h/round-012/model -SeedRoundStart 13
```

尚未启动第二夜。新增种子起点参数保留旧任务兼容性，并在恢复时拒绝更换种子段。
等待独立评测后再决定继续此候选还是回退；新的 8 小时运行不代表通过棋力晋级。
