# 变体、揭棋与翻棋：训练和可复现实验

先阅读 [lab-v1 规则与摆法](variant-laboratory.md)。所有命令从项目根目录执行。三个模式使用独立规则哈希和模型，不改变普通象棋的训练命令或夜间训练任务。

## 最短闭环

在现有 PyTorch 环境中安装导出依赖，然后双击 `训练变体.cmd`：

```powershell
.venv/Scripts/python.exe -m pip install -r trainer/requirements-variants.txt
npm.cmd run lab:engine
$env:PYTHONPATH='trainer/src'
.venv/Scripts/python.exe -m xiangqi_variants.lab smoke --mode all --out runs/variants/short-training
```

默认使用可用 CUDA，否则 CPU；如果标准象棋正在占用 GPU，可追加 `--device cpu`。`--mode custom`、`jieqi`、`banqi` 可单独运行。`smoke` 每模式完成：

1. 8 个完整自博弈训练局，另 2 个完整验证局，每步 32 状态访问、rollout 4。保存搜索分布、合法掩码和真实终局结果。达到 1000 半回合仍未终局则停止验收，保留截断记录，不写终局标签，也不换种子补局。
2. 先优化 50 次保存，再重新加载模型、AdamW 状态、Python / NumPy / Torch / CUDA 随机状态、样本顺序和游标，继续到 100 次。
3. 导出 ONNX，检查结构，并用最多 8 个验证观测比较 PyTorch 和 ONNX Runtime 输出；最大绝对误差须不超过 1e-4。
4. 候选实际通过 Node ONNX Runtime 加载，在每步 64 状态访问下对基础搜索完成 4 组独立验证。明棋和揭棋每组两局，翻棋每组四局。

训练种子从 1000 起，验证数据从 11000 起，独立验证赛从 900000 起；按整局/配对组划分，局内位置不拆分到不同集合。布局和搜索使用不同随机源；搜索入口只接收观测和自己的种子。检查点与数据清单哈希绑定，不接受换数据后直接恢复。

输出目录 `<out>/<mode>/` 包含 `dataset/manifest.json`、压缩数据分片、研究棋谱、`model/candidate.pt`、`candidate.onnx`、`candidate.json`、`parity.json`、`training.json`、`evaluation/`、`acceptance.json`。网页“载入训练候选”同时选择 `.json` 和 `.onnx`；规则不匹配会拒载。短训通过只证明流水线可用，不设棋力晋级门槛。

## 自定义棋子也能训练

网页摆棋后“导出摆法”，传入该局面即可使用同一闭环：

```powershell
.venv/Scripts/python.exe -m xiangqi_variants.lab smoke --mode custom `
  --scenario '我的摆法.json' --out runs/variants/my-piece --device cpu
```

也接受 `.xqlab`，使用其中的**初始局面**。模型按规则哈希隔离，摆法变化但规则不变时模型仍可加载；修改走法、棋子定义或规则版本时必须重新检查兼容性。基础自博弈数据不是普通象棋 NNUE 或教师引擎标注。

可分步运行：

```powershell
.venv/Scripts/python.exe -m xiangqi_variants.lab generate --mode jieqi --out runs/variants/jieqi-study
.venv/Scripts/python.exe -m xiangqi_variants.lab train --mode jieqi --out runs/variants/jieqi-study --steps 50
.venv/Scripts/python.exe -m xiangqi_variants.lab train --mode jieqi --out runs/variants/jieqi-study --steps 100 --resume
.venv/Scripts/python.exe -m xiangqi_variants.lab export --mode jieqi --out runs/variants/jieqi-study
```

数据生成按既定编号恢复；训练每 25 次及目标步保存原子检查点。`smoke` 会重新跑其训练验收段；长期训练应使用 `train --resume`。若规则或程序哈希改变，使用新实验目录，不混合历史数据。

## 后对车固定预算实验

完整默认矩阵：六个预设 × 两档预算 × 16 对换色局，共 384 局。

```powershell
npm.cmd run lab:engine
node scripts/run-variant-pilot.mjs reports/variants/my-queen-pilot
```

每个搜索单线程；默认并发 4 个独立实验进程以缩短总等待时间，可设置 `$env:XQLAB_JOBS='1'` 串行运行。预算固定为 1024 / 4096 状态访问、rollout 8，布局/组种子从 42000 起，最多 1000 半回合。无时限干扰，记录实际耗时但不据此比较速度。每步根访问、树访问和 rollout 都收费，精确定义见规则文档。

单项实验、自定义局面或带模型对照：

```powershell
node build/variants/cli.mjs batch --mode custom --preset queen-left-3 --pairs 16 --nodes 1024 --out reports/variants/left-3
node build/variants/cli.mjs batch --mode custom --scenario '我的摆法.json' --pairs 16 --nodes 4096 --out reports/variants/my-piece
node build/variants/cli.mjs batch --mode jieqi --purpose candidate --model runs/variants/short-training/jieqi/model/candidate.onnx --pairs 16 --nodes 1024 --out reports/variants/jieqi-candidate
```

子力实验双方必须同引擎、同模型，`custom` 指定单个 `--model` 时自动供双方使用；不指定则双方均为基础 MCTS。候选评测使用 `--purpose candidate`，`--opponent` 可指定另一模型，省略则对基础搜索。模型旁须有同名 JSON 清单。

揭棋配对使用镜像布局并交换模型颜色；翻棋每组为相同暗子布局交换模型席位两局，再将布局中所有棋子颜色反转并交换席位两局。先手与最终阵营分别统计。每组独立种子，同组中的相关对局不会被误当独立样本。

## 报告、故障与恢复

每局保存完整规则、初始布局、规则哈希、执行程序哈希、模型哈希、组号、逐着动作、搜索种子、实际预算、模拟数、推理数、耗时及终局原因。批量目录附执行时的 `engine.mjs`，其 SHA256 就是 `config.codeHash`；`package-lock.json` 固定推理依赖版本。源码更新后，请重新构建并使用新目录。若需要在原规则程序下恢复，可从项目根运行对应目录归档的 `engine.mjs batch ...`，保持原配置和输出路径。

每完成一局即原子写盘并刷新 JSON / CSV / 中文 HTML。重复运行同命令会读取已有固定编号并校验配置与初始摆法，只补缺少的局。被进程中断且尚未落盘的一局用原编号、原种子从头重跑；已记录的截断、超时、非法动作、崩溃单列，不自动替换为另一个种子。终局截断保持 `ongoing`，不伪装成规则和棋。

报告给出胜/和/负、纯胜率、和棋半分的得分率、先后手和阵营分项，以及 95% 区间。对每个完整组，先计算组内平均得分 `X_g ∈ [0,1]`，再对 `G` 个独立组使用：

```text
区间 = [mean(X) - sqrt(log(40)/(2G)), mean(X) + sqrt(log(40)/(2G))] ∩ [0,1]
```

纯胜率把每局胜记 1、其余记 0 后按同样的整组方式统计。和棋半分不是“半次二项胜利”。区间针对单项比较，不是覆盖全部矩阵的同时置信区间。16 组时区间仍很宽，这正是有限样本应保留的不确定性。

未完成所有组时不显示整体置信区间；另给完整组的描述性区间、完成率，并把每场未知结果分别按 0 分/1 分得到全部预定对局得分上下界。零完成时得分率为空、界限为 [0,1]；全胜和全和仍有非零统计不确定性。

结论只能描述该规则、摆法、引擎和预算下的表现。弱引擎会错过基本战术；接近 50% 的点估计不能证明子力等价，更不能从训练损失下降推导棋力提升。

## 验证命令

```powershell
npm.cmd run typecheck
npm.cmd test
$env:PYTHONPATH='trainer/src'
.venv/Scripts/python.exe -m unittest discover -s trainer/tests -p test_variants.py
.venv/Scripts/python.exe scripts/verify-variant-differential.py
```

合法着法差分只检查普通棋子与将帅安全，不将 lab-v1 循环裁决冒充正式棋例。实际执行结果与已知回归缺口见 [本轮验收记录](variant-validation-2026-10-02.md)。
