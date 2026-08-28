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

当前仓库尚未产生通过棋力门槛的自研冠军权重。下面的命令会启动桌面游戏，并使用仓库固定、许可已校验的 Fairy-Stockfish CC0 教师作为试玩 AI；界面分析响应中的后端标记为 `cc0-teacher`，不会冒充自研模型。

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
