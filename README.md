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

要求 Node.js 22+、Visual Studio 2022 C++ 工具、CMake，以及训练时的 Python 3.12/CUDA 13.2。

```powershell
npm install
npm run native:configure
npm run native:build
npm test
npm run dev
```

训练环境安装与 GPU 烟雾测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-training.ps1
.\.venv\Scripts\python.exe -m xiangqi_nnue.smoke
```

训练数据、检查点、构建产物与第三方引擎源码不进入 Git。冠军权重通过 GitHub Release 发布，并附 SHA-256、训练报告和第三方归属清单。

## 许可证

项目代码采用 GPL-3.0-or-later。第三方组件和数据集保留各自许可证，详见 `THIRD_PARTY_NOTICES.md`。
