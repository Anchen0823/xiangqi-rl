# 工具入口

所有命令从项目根目录运行。根目录中文 `.cmd` 是日常入口，下面是实现位置。

| 用途 | 实现 |
| --- | --- |
| 揭棋限时试训、恢复、独立评测 | `variants/train-jieqi.ps1` |
| 揭棋 8 小时分轮训练 | `variants/train-jieqi-8hours.ps1` |
| 自定义棋子／揭棋／翻棋短训验收 | `variants/train-variants.ps1` |
| TypeScript 裁判构建 | `variants/build-lab.mjs` |
| 四模式离线网页服务 | `variants/serve-lab.mjs` |
| 后与车固定预算实验 | `variants/run-variant-pilot.mjs` |
| 存档、预算、恢复审计 | `variants/verify-variant-artifacts.py` |
| 揭棋试训数据、对局、模型审计 | `variants/verify-jieqi-run.py` |
| 普通棋子合法着法差分 | `variants/verify-variant-differential.py` |
| 普通象棋夜训 | `train-night.ps1`、`train-8hours.ps1` |
| 普通象棋环境、数据、试玩 | 保留现有根目录脚本 |

原有六个变体脚本路径是兼容转发入口；新增实现请放在 `variants/`。
共享代码目录名不代表产品菜单层级：普通象棋、变体实验室、揭棋、翻棋仍为四个平级玩法。
