# OpenRA Assistant (重构版)

OpenRA Assistant 是一个分层式智能体系统，面向即时战略（RTS）场景，提供战略路由、后勤运营、旅长战术分配、连长局部作战与编制管理等功能。当前版本重构了提示词体系、模块职责与运行链路，并提供调试日志与黑暗半透明 UI 架构视图。

## 架构概览

```
司令(Commander)
  └─ 秘书(Secretary)
      ├─ 后勤部长(Logistics)
      ├─ 旅长(Brigades: 第一/第二/第三/第四)
      │    └─ 连长(Companies: 每旅固定3个 — brigade_#_company1/2/3；不创建/撤销)
      └─ 征兵部长(Recruitment)
```

## 运行与依赖

- Python 3.9+
- 建议在 Conda 环境 `OpenRA_Assistant` 中运行
- 安装依赖：`pip install -r requirements.txt`
- 配置环境变量：编辑 `.env`（模型/客户端分配与调试开关）
- 启动：`python main.py`
- 验证：查看终端日志与 UI 架构树，确认各角色任务变量与链路工作正常

## 许可协议

本项目采用 GPL-3.0 开源许可证。详情参见仓库中的 `LICENSE` 文件。

## 代码隐藏说明

公开仓库中通过 `.gitignore` 隐藏以下屎山代码：

- `assistant/command_parser.py`（NLP模块，对应“指令”功能）

## 注意事项

- 地图/端口依赖：请确保游戏服务端端口就绪，否则快照与队列调用会失败
- 参谋长与所有后台循环（后勤/旅长/征兵）的引擎查询在司令首次输入战略或指令后才开始，避免自动查询
