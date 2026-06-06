# 美团 AI Hackathon 2026 · 赛题 06

## 本地探索：周末闲时活动规划

本项目实现一个本地生活短时活动规划与执行 Agent。用户输入一句自然语言目标，例如“今天下午想和老婆孩子出去玩几个小时，别离家太远，孩子 5 岁，老婆最近在减肥”，系统会自动完成约束解析、POI/餐厅/活动/配送搜索、时间线编排、分享文案生成，并在用户确认后模拟完成购票、排号、配送等关键动作。

## 核心能力

- 12 维约束解析：场景、人数、饮食禁忌、儿童年龄、时间窗口、截止时间、距离、预算、场合、活动偏好、配送需求、团购优先。
- 10 个本地生活 Tool：POI、餐厅、排队、活动、配送、团购、购票、订座、配送下单等。
- 双规划模式：Demo 规则引擎离线可跑；DeepSeek/OpenAI/Claude 使用 Function Calling 调工具。
- 可执行闭环：方案确认后生成购票、餐厅预订/排号、鲜花/蛋糕配送等模拟订单。
- 两种交互入口：CLI 和 Streamlit Web UI。
- Hard Case 评测：覆盖预算、多人饮食冲突、团建、极短时间窗口、团购等 10 个场景。

## 快速运行

```bash
# 安装依赖
pip install -r requirements.txt

# Web UI（推荐演示）
streamlit run app.py

# CLI Demo（无需 API Key）
python main.py

# 一键演示
bash demo.sh

# 评测
python eval.py
```

LLM 模式需要自行配置环境变量，例如：

```bash
export DEEPSEEK_API_KEY=your_key
python main.py --mode deepseek
```

## 项目结构

```text
├── app.py            # Streamlit Web UI
├── main.py           # CLI 交互入口
├── planner.py        # ReAct 控制器 + Demo 规则规划器
├── tools.py          # 10 个核心 Tool
├── mock_data.py      # 本地 Mock 数据与订单存储
├── eval.py           # 10 个 Hard Case 评测套件
├── compare.py        # Demo vs DeepSeek 对比评测
├── DESIGN.md         # 提交版设计文档
├── PRD.md            # 产品需求说明
├── index.html        # 技术方案展示页
└── demo.sh           # 一键演示脚本
```

## 评测结果

```text
36/36 (100%) — 10 个 hard case
medium: 18/18 (100%) | hard: 18/18 (100%)
```

## 典型演示输入

```text
今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，孩子5岁，老婆最近在减肥
```

```text
团队8个人下午团建，预算人均150，要有活动有晚饭。有人不吃辣，有人恐高
```

```text
结婚纪念日，晚上想给老婆一个惊喜，要有鲜花、蛋糕，吃顿好的，但老婆最近只吃素食
```
