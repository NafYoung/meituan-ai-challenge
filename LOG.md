# 开发日志

## 2026-05-17

### 选题

美团AI挑战赛6个赛道，选了赛道6：短时活动规划Agent。理由：技术栈干净（LLM+Tool Use）、Demo效果直观、数据门槛低（Mock即可）、业务贴合度高。

### 已完成

- 技术方案展示页 `index.html`
- `mock_data.py`：35条模拟数据（11POI/9餐厅/6活动/9配送/7团购）
- `tools.py`：10个核心Tool（search_poi、get_poi_detail、search_restaurant、check_waitlist、check_event、search_coupon、search_delivery、reserve_table、buy_ticket、order_delivery）
- `planner.py`：规划引擎（DemoPlanner规则引擎 + Planner LLM ReAct循环）
- `main.py`：CLI交互入口
- `app.py`：Streamlit Web UI（多轮对话、快捷输入、一键执行）
- `eval.py`：10个hard case评测套件
- `compare.py`：Demo vs DeepSeek对比评测
- `DESIGN.md`：设计文档（≤2页）
- `PRD.md`：产品需求文档
- `demo.sh`：一键演示脚本
- `README.md`：项目说明

### 评测结果

36/36 (100%) — 10个hard case，medium 100%，hard 100%

### 2026-06-06 提交前收尾

- 修复赛题06关键场景：纪念日素食餐厅、8人团建活动匹配
- README 更新为赛题06提交版
- DESIGN.md 压缩为提交版设计文档
- CLI/Web 一键执行统一走 `get_executable_actions()`，购票/订座人数跟随规划人数，并支持鲜花/蛋糕配送动作

### 决策记录

- 选赛道6：技术栈干净、数据门槛低、Demo效果直观
- Demo模式保留规则引擎：确保不依赖外部API
- 支持DeepSeek：成本敏感，兼容OpenAI格式
- Streamlit选型：Python原生，搭UI快
- Mock数据而非真实API：比赛要求如此

### 项目状态

**已完成交付**。2026-05-17 全天开发完成。
