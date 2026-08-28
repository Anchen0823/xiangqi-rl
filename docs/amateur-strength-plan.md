# 训练目标与执行计划：击败业余棋手的自研 AI

状态：2026-08-28 审查后制定；审查基线提交 `700a48c`（分支 `codex/training-candidate-report`），本计划的实施 PR 从 `main`（`f44ec37`）开始。
目标：在诚实记录验证边界的前提下，先做到“可部署、能通过机器门槛”，再争取“俱乐部业余棋手（约 1800–2000）水平”的线下验证。

## 1. 审查结论

当前项目已经具备一条可运行的最小训练流水线，但**还不能把训练产物用于对弈**，也不具备宣称棋力的条件。

### 1.1 已验证可用的部分

- 原生 C++20 规则进程：走子、将军/将死/困毙、自然限着、循环裁决钩子已实现；`npm test`（Vitest 2 例 + CTest rules 1 例）通过。
- Electron/React 棋盘与 AI/本地对弈模式可用。
- 训练特征提取：本地 `native/bin/pikafish.exe`（Pikafish pinned `b97ef0f` + `third_party/pikafish-training.patch`）能输出 `training_features`，JSON 索引与 PyTorch 模型维度一致（PSQ 16,536 + Threat 45,547）。
- CC0 教师：`native/bin/fairy-stockfish-teacher.exe` 与 `third_party/fairy-stockfish-teacher.json` 的 SHA-256 匹配，许可链清晰。
- PyTorch 模型：HalfKAv2_hm + FullThreats 拓扑、16 个 material buckets、pairwise 1024→512 变换、16→32→32→1 dense 栈已实现；31 个 Python 单元测试通过；CUDA float16/bfloat16 前向+反向 smoke 通过。
- 训练循环：流式 gzip shard、断点可恢复、AMP、温度墙（83/78 °C）、6.5 GiB 显存软限制均已接线。
- 数据许可与溯源：self-play 源标注 ODbL-1.0，教师标签标注 CC0-1.0，manifest 含 SHA-256。

### 1.2 关键缺口（按阻塞程度排序）

1. **没有 `.nnue` 导出器/量化器**。PyTorch checkpoint 无法被 Pikafish 加载，自研模型不能进入搜索，因此当前 UI 实际使用的是 CC0 教师或一步吃子 fallback，而不是自研 AI。
2. **没有比赛与强度验证设施**。没有 UCI/UCCI 对局 harness、确定性开局套件、SPRT/Wilson 统计、战术测试套件、PGN/日志归档；`strength-protocol.md` 的四道门全都没有执行过。
3. **没有可标定的 club baseline**。当前唯一内置弱 AI 是 `Position::fallbackBestMove()`（一步贪吃子）。800 局基线赛的对手必须先定义并标定。
4. **数据规模严重不足**。`candidate-101` 只用了 2,975 个训练位置，训练 Huber 降到约 0.0004，属于过拟合演示，不是泛化证据。目标量级是 3–8M 已标注位置。
5. **训练评估不严谨**。`train.toml` 未被训练代码读取；学习率、weight decay、batch 等硬编码在 `train.py`；无训练/验证/测试按对局切分，无验证指标、早停或学习率调度。
6. **规则引擎尚未完成发布级验证**。文档列出的 2020 棋例特例、100,000 随机局面差分、500 局无崩溃对弈尚未完成。
7. **可复现性有小缺口**。Pikafish 源码与二进制、checkpoints、datasets 均不入 Git，虽有固定 revision 与 patch，但缺少“校验当前二进制/数据集/checkpoint 是否与 manifest 一致”的统一脚本。

### 1.3 实测基准（2026-08-28，本机）

- GPU：RTX 4060 Laptop GPU，PyTorch `2.12.1+cu132`，CUDA 13.2 可用。
- 教师标注吞吐：2,000 nodes 单线程约 277 位置/秒；5,000 nodes 单线程约 100–124 位置/秒，8 线程约 872 位置/秒。
- 特征提取吞吐：单进程约 10,700 位置/秒，不构成瓶颈。
- 全尺寸合成训练吞吐：micro-batch 1024 × accumulate 8（8192 位置/优化步）约 0.31 步/秒，即约 2,500 位置/秒；4M 位置一个 epoch 约 26 分钟，训练算力在预算内。
- 当前候选 `candidate-101.pt` 大小约 746 MiB（含模型、优化器与数据游标状态），不能在 UI 中加载。

## 2. 目标定义（分两级，不跳级宣称）

- **M0 可部署**：训练出的权重可导出为标准 `.nnue`，Pikafish 能加载并稳定搜索；PyTorch 浮点前向与 Pikafish 量化前向在随机局面集上达到规定容差。
- **M1 击败休闲/入门业余棋手**：通过 800 局基线赛（胜率 95% Wilson 下界 > 60%）、90% 战术题门槛；UI 不再回退到 `fallback` 或 `cc0-teacher`。
- **M2 击败俱乐部业余棋手（约 1800–2000）**：额外通过 400 局与强 CC0 教师同节点赛（95% Wilson 下界 ≥ 20%）、至少 20 局线下俱乐部棋手验证（胜率 > 50%），才能按 `strength-protocol.md` 宣称人类等级。

M1/M2 都未通过前，只能把候选称为“实验权重”，不得在 UI 中标记为冠军。

## 3. 执行计划

### 阶段 0：冻结基线并建立可复现锚点（0.5 天）

任务：
- 记录基线：当前 commit、`build/native/xiangqi-engine.exe`、`native/bin/pikafish.exe`、`native/bin/fairy-stockfish-teacher.exe` 的 SHA-256，写入 `reports/baseline-manifest.json`。
- 新增 `scripts/verify-artifacts.ps1`：校验教师 manifest、Pikafish revision/patch、本地数据集/checkpoint 可选校验。
- 定义确定性开局套件：初始局面 + 若干由固定 seed 随机生成的合法开局，黑白换先；每个局面同时归档 FEN 与 UCCI 走法序列。
- 实现 `trainer/src/xiangqi_nnue/match.py` 骨架：长生命周期 UCI 引擎适配器、`go nodes`、`position fen`、bestmove 解析、超时与崩溃处理、UCCI/PGN 日志。

退出标准：同引擎固定 seed 连跑 2 局结果逐字节一致；哈希验证脚本通过。

### 阶段 1：正确性、导出与部署（2 天，关键路径，最先做）

任务：
- 1.1 规则差分：把 `native/tests/position_tests.cpp` 扩展到 100,000 随机残局 legal-move 差分（以 Pikafish 或教师为参考，排除循环裁决差异），并跑 500 局无崩溃对弈。
- 1.2 特征黄金测试：从随机 FEN 集合生成 `training_features` 快照，锁定 `features.py` 解析与 `collate_model_inputs` 行为。
- 1.3 实现 `trainer/src/xiangqi_nnue/export_nnue.py`：
  - 按 Pikafish `Version=0x6A448AFA` 写文件头、feature transformer + 16 层 stack；
  - 量化映射：accumulator bias → int16 LEB128，PSQ/threat 权重 → int8/int8，PSQT → int32；
  - 写前/写后做哈希、尺寸、有限值检查；
  - 导出为 `models/candidate.nnue`，原子替换。
- 1.4 量化回读闭环：让 Pikafish 加载导出的 `.nnue`，对至少 10,000 个随机 FEN 比较 PyTorch 浮点前向与 Pikafish `eval` 的 side-to-move 分值，超差则调整量化或做 QAT。
- 1.5 搜索稳定性：候选网络在 100 局自对弈中无非法走法、无崩溃、无超时。

退出标准：M0 达成；`models/champion.nnue` 流程可随时从 checkpoint 生成。

### 阶段 2：比赛与强度门基础设施（1 天，可与阶段 1 并行）

任务：
- 完善 `match.py`：并发对局、固定节点/时间、颜色换先、断点续跑、结果统计（胜率、Wilson 95% 下界、SPRT α=β=0.05）。
- 实现标定 baseline：
  - 短期用 `xiangqi-engine.exe` 的 `fallback` 作为“入门基线”；
  - 随后在 native 中实现一个简单 depth-limited 搜索 + material/PST 评估，作为可复现、不可调参的 club baseline；
  - 用教师不同节点（如 50/200/1000 nodes）标定 baseline 强度，确保它弱于教师但强于一步吃子。
- 创建版本化战术套件：从公开 ODbL/CC0 局面或人工构造的杀棋/得子题中筛选 100–200 题，教师多节点验证答案，专用于测试、绝不进入训练集。
- 归档脚本：`reports/` 保存引擎提交、权重 SHA-256、硬件、节点、命令行、原始 PGN/UCCI、统计结果。

退出标准：可以用一条命令运行 Gate 1、Gate 2、战术套件，并生成审计报告。

### 阶段 3：规模化数据生产（1–2 天，后台运行）

任务：
- 重新干净构建并校验规则引擎与 Pikafish feature 引擎。
- 生成 self-play 源数据：12 workers、`max-plies 240`、`random-plies` 分层（4/8/12）、节点分层（2,000/5,000）、每局 seed 确定性；先产 10 万位置试跑，检查结果分布、规则终止原因、非法走法率（应为 0）。
- 教师标注：`--nodes 5000 --threads 8`，先标 200 万位置作为 `train-v1`，通过质量门后扩到 3–8M；按 50,000 记录/分片。
- 数据质量门：每 100 万位置统计 score 分布、outcome 分布、重复 FEN 比例、抽检 bestmove 合法性；保留 manifest 与 SHA-256。
- 切分：按**对局边界**切分 90/5/5 train/val/test，并在三集合间按 FEN 去重，防止同局面泄漏；另留 1 万位置做导出回读测试，不参与训练。

退出标准：至少 3M 位置通过质量门与许可校验，切分 manifest 就绪；磁盘占用在 160 GiB 缓存上限内。

### 阶段 4：监督训练出 S1 候选（1 天算力 + 多轮检查）

任务：
- 将 `trainer/config/train.toml` 真正接入 `train.py`：seed、micro-batch 1024、accumulate 8、学习率 warmup + cosine、weight decay、shuffle buffer、val 间隔、早停条件。
- 训练指标升级：每个 val 间隔输出 train/val Huber、MAE、皮尔逊相关；记录 `metrics.jsonl` 与学习曲线。
- 在 3M+ 训练集上训练约 10 epoch，或直到 val 连续 2 epoch 不降；每 30 分钟原子写 checkpoint。
- 用 val 选最佳 checkpoint（禁止用 test 调参），导出 `.nnue`，跑阶段 1.4/1.5 的回读与搜索稳定性检查。
- 记录训练报告：数据 manifest、许可、曲线、超参、导出报告、回读误差。

退出标准：`candidate-s1.nnue` 部署在本地 Pikafish 中，M0 检查全通过。

### 阶段 5：强度门与强化微调迭代（1.5 天）

任务：
- Gate 1：候选 vs 标定 baseline，800 局，95% Wilson 下界 > 60%。
- Gate 2：候选 vs 强 CC0 教师，同节点 400 局，95% Wilson 下界 ≥ 20%。
- 战术套件 ≥ 90%。
- 若未通过：
  - 分析薄弱项（开局/残局/杀棋/重复局面）；
  - 用已导出的候选在 Pikafish 中生成 candidate-vs-candidate 与 candidate-vs-teacher 对局源；
  - 以对局结果或教师值作为 value 标签，对 S1 做低学习率微调；最多 2–3 次迭代；
  - 迭代候选未通过时不得覆盖 champion 记录。
- 每次迭代都重跑 M0 回读与 Gate 1 快速抽检（100 局）后再上完整 800 局。

退出标准：某候选连续通过 Gate 1、Gate 2 与战术套件，结果可复现并归档。

### 阶段 6：人类验证与发布（0.5–1 天）

任务：
- 准备可打包的 Electron 对弈版本，确认 UI 后端显示 `pikafish` 且 `models/champion.nnue` 生效。
- 安排至少 20 局线下俱乐部棋手对局，归档 PGN 与棋手声明，统计胜率。
- 发布前按 `strength-protocol.md` 生成完整报告：权重 SHA-256、引擎提交、比赛命令、原始日志、统计下界、战术成绩、人类验证。
- 若人类验证不达标，只发布 M1 结论，并明确写“未宣称 1800–2000”。

退出标准：`models/champion.nnue` + 完整报告通过发布门槛，README 与 UI 文案同步更新。

## 4. 七天预算映射

| 阶段 | 关键资源 | 预算 |
|---|---|---|
| 0–1 基线与导出 | CPU/GPU 少量 | 2.5 天（含规则差分） |
| 2 比赛设施 | CPU | 与 1 并行 |
| 3 数据生产 | ≤12 CPU 线程，后台 | 1–2 天（预计 5k nodes、8 线程约 87 万位置/小时） |
| 4 监督训练 | GPU，6.5 GiB 软限 | 1 天算力 |
| 5 强度门+微调 | CPU/GPU | 1.5 天 |
| 6 人类验证与发布 | CPU | 0.5–1 天 |

热约束不变：GPU 达到 83 °C 暂停、回到 78 °C 恢复；每 30 分钟原子写 checkpoint；进程 RSS 上限 12 GiB。

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 量化后棋力损失过大 | M1/M2 失败 | 回读容差自动化；必要时 QAT；降低宣称等级 |
| 教师低节点标签太弱 | 上限被教师拖低 | 标签用 5,000 nodes，并分层混入 10,000 nodes 高价值局面；Gate 2 直接验证上限 |
| 训练数据泄漏/过拟合 | 虚高胜率 | 按对局切分 + 跨集合 FEN 去重 + val 选型 + test 终检 |
| 规则引擎棋例错误 | 训练源污染 | 阶段 1 先差分 100k 残局；self-play 中双引擎校验关键局面 |
| 比赛统计不足 | 错误升级 | 严格按 Wilson 下界；失败候选不覆盖 champion |
| 无法安排线下棋手 | M2 无法宣称 | 保留 M1 门槛与教师占位方案，不夸大 |
| 导出格式细节错误 | Pikafish 拒绝加载 | 以小随机权重网络先跑通 writer→loader→eval 回路，再导出大模型 |

## 6. 建议的首批代码任务（按优先级）

1. `trainer/src/xiangqi_nnue/export_nnue.py` + 小网络/随机权重读写回路测试（最高优先级）。
2. `trainer/src/xiangqi_nnue/match.py` + 同引擎确定性比赛测试。
3. `native` 中实现可标定的 depth-limited baseline 搜索。
4. `trainer/src/xiangqi_nnue/config.py` 接入 `train.toml`；`train.py` 增加 train/val 指标与早停。
5. `scripts/verify-artifacts.ps1` 与 `scripts/run-gates.ps1`。
6. 数据质量统计脚本 `scripts/inspect-dataset.ps1`（调用 Python 输出分布与重复率）。

## 7. 完成定义（Definition of Done）

- UI 对局后端为 `pikafish`，加载 `models/champion.nnue`，不再回退 `cc0-teacher` 或 `fallback`。
- `champion.nnue` 有 SHA-256、量化报告、PyTorch→Pikafish 回读误差报告。
- Gate 1、Gate 2、战术套件报告齐全且全部通过；若有人类验证，含 20 局原始记录。
- 训练报告记录数据许可、manifest、曲线、超参、硬件与复现命令。
- 所有失败候选与试验日志保留，不覆盖冠军记录。
