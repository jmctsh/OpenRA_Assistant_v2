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

- 司令：输入“指令”或“战略”
  - 指令 → 直接进入指令解析与执行
  - 战略 → 秘书分类与路由至下级
- 秘书：仅处理战略，注入战场与部队结构，输出多路由方案（包含“可调用”旅长）；战场单位/建筑统一使用英文代码
- 后勤：生产/建造/防御/开矿，8 秒循环；支持坐标放置入队与 Worker 动态放置；识别“完成任务”清除秘书任务变量
- 旅长：10 秒循环；优先完成上级任务；无任务时近战与巡逻；派遣后为连队设置局部战斗任务
- 连长：10 秒循环；在目标坐标的圆形范围内生成逐单位攻击对；若视野范围内无敌或无我方，则休眠等待下一次任务
- 征兵部长：10 秒循环；仅负责编入未编入单位；当未编入数量不足以将所有残部补足到≥5时，使用各旅 company3（预备队）合并到一/二连；向后勤输出优先建造建议
- 连长：目标坐标圆形范围内生成逐单位的攻击对；无敌或无我方时自动清队
- 征兵：编制连队（固定三连，不创建/撤销）；识别残部并在必要时合并；向后勤输出“优先建造建议”留言

## 模块说明

- `assistant/ai_hq.py`：系统协调与路由执行；角色客户端初始化（按 .env 分配不同模型）
- `assistant/doubao_client.py`：豆包 Ark 客户端封装，支持非流式与流式 JSON 输出
- `assistant/llm_roles.py`：角色 LLM 提示词与计划/执行接口（秘书/后勤/旅长/连长/征兵）
- `assistant/prompts/*`：提示词构造器（注入战场/编制/路由等上下文）
- `assistant/logistics_runner.py`：后勤循环器与坐标放置 Worker
- `assistant/brigade_runner.py`：旅长循环器（任务/巡逻）
- `assistant/company_manager.py`：连队管理（固定三连：分配/合并/快照；不创建/撤销；标准命名）
- `assistant/chief_of_staff.py`：参谋长快照（含 zones、候选防御坐标）
- `assistant/ui/main_window.py`：黑暗半透明 UI 与架构树视图（展示各角色任务变量；点击连队名称将静默执行引擎选择）
- `assistant/command_parser.py`：指令解析器

## 运行与依赖

- Python 3.9+
- 建议在 Conda 环境 `OpenRA_Assistant` 中运行
- 安装依赖：`pip install -r requirements.txt`
- 配置环境变量：编辑 `.env`（模型/客户端分配与调试开关）
- 启动：`python main.py`
- 验证：查看终端日志与 UI 架构树，确认各角色任务变量与链路工作正常

## 调试与日志

- 终端输出：
  - `[DEBUG][AIHQ]` 输入与路由执行
  - `[DEBUG][LogisticsRunner]` 秘书任务与征兵留言
  - `[DEBUG][BrigadeRunner]` 任务与派遣数
  - `[DEBUG][CompanyAttackRunner]` AOI 采集与 pairs 数量
  - `[LLM_DEBUG]` DoubaoClient 初始化与 chat_json(_stream)
- 设置：`$env:LLM_DEBUG = "1"` 可开启更详细日志

## 许可协议

本项目采用 GPL-3.0 开源许可证。详情参见仓库中的 `LICENSE` 文件。

## 核心代码隐藏说明

为保护核心策略与避免被直接拿去用，公开仓库中通过 `.gitignore` 隐藏以下文件：

- `assistant/command_parser.py`（指令解析）
- `assistant/biods_enhancer.py`（本地算法增强）

## 注意事项

- 地图/端口依赖：请确保游戏服务端端口就绪，否则快照与队列调用会失败
- 参谋长与所有后台循环（后勤/旅长/征兵）的引擎查询在司令首次输入战略或指令后才开始，避免自动查询
