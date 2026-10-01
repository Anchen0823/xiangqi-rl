# Xiangqi RL

一款离线 Windows 中国象棋桌面游戏，以及为 RTX 4060 Laptop GPU 设计的可复现 NNUE 训练流水线。

> 当前处于早期开发阶段。基础走子、将军/将死/困毙、自然限着和循环裁决框架已经可运行；完整 2020 棋例差分验证、Pikafish 搜索接入和达到业余棋手水平仍属于发布前硬门槛。

## 目标

- 中国象棋协会 2020 规则，包括自然限着、长将、长杀、长捉与循环裁决。
- 人机对弈与本地双人、五档难度、悔棋、FEN、`.xqgame` 保存和分析线。
- C++ 原生进程作为规则与搜索唯一权威，Electron/React 只负责桌面交互。
- CPU NNUE 推理；训练端使用 PyTorch 2.12.1 cu132 与可选融合 CUDA 内核。
- 使用许可明确的 ODbL 数据和 CC0 教师，模型须通过 SPRT 与棋力门槛才可晋级。

## 目录

- `native/`：C++20 规则、搜索进程与测试。
- `src/`：Electron 主进程、IPC 预加载桥和 React 界面。
- `trainer/`：NNUE 模型、CUDA/PyTorch 诊断与训练入口。
- `docs/`：规则映射、数据许可、训练和棋力验收记录。

难度档位不再固定思考层数，而是对应搜索预算（节点数 + 时限 + 深度上限），
深度是搜索的结果而非硬编码常数。详见 `docs/search-budgets.md`。

## 开发

要求 Node.js 22+、Visual Studio 2022 C++ 工具、CMake，以及训练时的 Python 3.12。PyTorch 运行时固定为 cu132；Toolkit 推荐 CUDA 13.2，验证脚本也会自动发现系统安装的更新 CUDA 13.x。

```powershell
npm install
npm run native:configure
npm run native:build
npm test
npm run dev
```

### 立即试玩

试玩 2026-09-30 扩充续训候选：双击项目根目录的 `试玩新模型.cmd`。
它加载 `checkpoints/expanded-20260930/candidate.nnue`，不会替换冠军模型。
要用上一轮候选对照试玩：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/play-candidate.ps1 `
  -Network checkpoints\continue-20260930\candidate.nnue
```

进入后选择"人机对弈"，默认执红，点击棋子再点击目标位置即可。
推荐着法和着法记录使用中象记谱：红方如“炮二平五”，黑方如“马8进7”；
同路重子用前/中/后区分，多路重兵补充路数以避免歧义。
棋盘翻转不改变记谱方向，旧 `.xqgame` 存档继续兼容。

界面采用浅色木质棋盘、雕刻感棋子与上下棋手信息卡。棋盘下方可“翻转棋盘”，
随时切换红黑视角，局面与行棋方保持不变；窄屏下棋盘优先显示，设置与分析移至下方。
点击“编辑局面”可从当前棋局摆子：选择红黑棋子后点击落点，或用“移动棋子”
依次点击起点、终点；支持删除、清空、恢复初始布局和选择先行方。
编辑期间 AI、分析与计时暂停；取消保留原局，应用须通过布局和原生行棋合法性检查，
随后清空旧着法记录与计时。编辑后的局面仍可使用 `.xqgame` 保存、载入并继续对弈。

对局包含本地合成音效：落子木声、吃子重音、将军钟声，以及将死、困毙、
和棋的结束提示。音色按事件分层合成——噪声瞬态给木头的撞击感，模态泛音
模拟棋子的空腔共鸣，钟声用非谐分音并送入短混响；重子（车炮将帅）落点更低
更长，兵卒更轻更短。每次落子的音高、衰减与声像都有小幅随机化并按棋盘纵深
定位，连续行棋不会重复同一个音。选中棋子另有轻脆的拾子声。左侧"对局音效"
可静音、调节音量或试听整套音阶，设置自动保存。
棋子落定、吃子和将军有独立视觉反馈；终局可选择“留局复盘”或“再弈一局”。
载入棋谱和悔棋不会重播走子音效，动画尊重系统的“减少动态效果”设置。

首次构建或修改代码后，运行以下命令；后续双击入口直接使用已构建版本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/play-candidate.ps1
```

候选启动入口需要本地检查点与 Pikafish 二进制；这些大文件不在 Git 中。
下述 `play-demo.ps1` 仍用于 CC0 教师试玩。

当前仓库尚未产生通过棋力门槛的自研冠军权重。若本地已安装仓库固定、许可已校验的 Fairy-Stockfish CC0 教师，native 引擎会在缺少 `models/champion.nnue` 时自动使用它作为试玩 AI；界面分析响应中的后端标记为 `cc0-teacher`，不会冒充自研模型。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/play-demo.ps1
```

首次缺少教师引擎时先运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-teacher.ps1
```

进入游戏后选择“人机对弈”、执红或执黑以及五档棋力即可。关闭 Electron 窗口或在启动终端按 `Ctrl+C` 停止。

### 立即看到 CUDA 训练成果

本机已有校准标签时，以下命令会在 RTX GPU 上训练 21 步，输出第 0、10、20 步 loss，并生成不入 Git 的 `checkpoints/demo.pt`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/train-demo.ps1
```

继续同一 checkpoint 至 41 步：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/train-demo.ps1 -Steps 41 -Resume
```

#### 生成新的演示数据

以下流程生成 2 局规则安全的自博弈源数据，再提取 Pikafish 精确稀疏特征并写成可恢复标签分片：

```powershell
.\.venv\Scripts\python.exe -m xiangqi_nnue.selfplay `
  --rules-engine .\build\native\xiangqi-engine.exe `
  --teacher-engine .\native\bin\fairy-stockfish-teacher.exe `
  --teacher-manifest .\third_party\fairy-stockfish-teacher.json `
  --output .\datasets\demo-source --games 2 --nodes 2000 `
  --max-plies 240 --random-plies 4 --workers 1

.\.venv\Scripts\python.exe -m xiangqi_nnue.label `
  --source .\datasets\demo-source `
  --source-url "local:selfplay-demo" --attribution "Xiangqi RL self-play" `
  --dataset .\datasets\demo-labeled --dataset-id demo-v1 `
  --feature-engine .\native\bin\pikafish.exe `
  --teacher-engine .\native\bin\fairy-stockfish-teacher.exe `
  --teacher-manifest .\third_party\fairy-stockfish-teacher.json `
  --nodes 2000 --threads 1 --hash-mb 128

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/train-demo.ps1 `
  -Dataset datasets\demo-labeled -Checkpoint checkpoints\demo-fresh.pt
```

演示 loss 下降只证明流水线有效，不等于达到业余棋手水平。正式宣称棋力前仍须完成大规模数据生成、量化、SPRT、800 局基线赛与线下人类验证。

训练环境安装与 GPU 烟雾测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-local-cuda.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-cuda.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-training.ps1
.\.venv\Scripts\python.exe -m xiangqi_nnue.smoke
```

`setup-local-cuda.ps1` 从 NVIDIA 官方 CUDA 13.2.1 redistributable manifest 下载约 89 MB 的最小编译组件，并逐项校验 SHA-256，安装到仓库忽略的 `.cuda/v13.2`，无需管理员权限且不替换显卡驱动。它提供本项目编译和训练所需的编译器、运行库与 NVVM；Visual Studio 的全局 CUDA 项目模板集成仍需使用 NVIDIA 系统安装器单独安装。

训练数据、检查点、构建产物与第三方引擎源码不进入 Git。冠军权重通过 GitHub Release 发布，并附 SHA-256、训练报告和第三方归属清单。

## 许可证

项目代码采用 GPL-3.0-or-later。第三方组件和数据集保留各自许可证，详见 `THIRD_PARTY_NOTICES.md`。
