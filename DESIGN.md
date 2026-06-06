# 赛题 06 · 短时活动规划 Agent 设计文档

## 1. Planning 策略

系统采用“约束驱动的 ReAct Agent”架构，主链路为：

```text
自然语言输入 -> 约束解析 -> 工具搜索 -> 方案编排 -> 用户确认 -> 模拟执行
```

Demo 模式使用 `DemoPlanner` 规则引擎，保证无 API Key 时稳定演示；LLM 模式使用统一 `Planner` ReAct 循环，由 Claude/OpenAI/DeepSeek 通过 Function Calling 自主选择工具。两种模式共享 `tools.py` 的 Tool Schema 和 `call_tool()` 调用入口。

约束解析覆盖 12 类信息：场景、人数、儿童年龄、性别组合、饮食禁忌、分人饮食、截止时间、时间窗口、距离、预算、特殊场合、特殊需求。典型输入：

```text
和2个朋友聚一下午，小王吃素，老李海鲜过敏，赶6点飞机
```

会被解析为 `party_size=3`、`dietary=["素食","无海鲜"]`、`time_deadline="18:00"` 等结构化约束。

方案编排不是固定模板，而是根据约束动态计算：

- 家庭/亲子：优先亲子 POI + 低卡/亲子餐厅。
- 朋友/团建：优先娱乐、密室、团队活动，避开恐高或不适合群体的项目。
- 约会/纪念日：优先展览/文艺活动、精致餐厅，并加入鲜花/蛋糕配送。
- 时间紧：压缩活动时长或跳过二级活动，保证截止时间。
- 预算紧：优先免费/低价 POI，并查团购/优惠券。

## 2. 工具调用链路

项目实现 10 个核心 Tool，覆盖查询与执行两类动作。

| 类型 | Tool | 作用 |
| --- | --- | --- |
| 查询 | `search_poi` | 搜索 POI，支持类型、人群、距离过滤 |
| 查询 | `get_poi_detail` | 获取 POI 详情 |
| 查询 | `search_restaurant` | 搜索餐厅，支持标签、人群、距离过滤 |
| 查询 | `check_waitlist` | 查询餐厅排队桌数与等待时间 |
| 查询 | `check_event` | 查询当天活动 |
| 查询 | `search_delivery` | 搜索蛋糕、鲜花、饮品等配送商品 |
| 查询 | `search_coupon` | 搜索团购、满减、折扣券 |
| 执行 | `buy_ticket` | 模拟购买景点/活动门票 |
| 执行 | `reserve_table` | 模拟餐厅预订/排号 |
| 执行 | `order_delivery` | 模拟配送下单 |

官方家庭场景的典型调用链：

```text
search_poi(suitable_for="亲子", distance_limit=5)
-> search_restaurant(tags=["低卡","亲子"], party_size=3)
-> check_waitlist(restaurant_id)
-> check_event(date)
-> 生成时间线、预算、分享文案
-> 用户确认
-> buy_ticket + reserve_table
```

如果输入包含“鲜花”“蛋糕”，规划阶段会调用 `search_delivery`，确认后 `get_executable_actions()` 会把对应商品加入 `order_delivery` 执行动作。CLI 和 Web UI 共用这套动作生成逻辑，避免人数、预订时间、配送动作在入口层硬编码。

## 3. 异常处理机制

搜索层：

- 指定 POI 类型无结果时，去掉类别过滤扩大搜索范围。
- 多饮食标签找不到餐厅时，逐标签降级搜索。
- 没有精确匹配时返回最近似方案，并在文案中展示约束命中或未命中说明。

规划层：

- Demo 模式完全基于本地 Mock 数据，保证离线演示可用。
- LLM 模式最大工具轮次为 8，超限时返回已有方案。
- 空输入不会触发规划。

执行层：

- 所有执行动作只在用户确认后触发。
- 执行类 Tool 返回 `status` 或 `error`，失败原因可追踪。
- 模拟订单写入 `orders.json`，可在 CLI/Web 中查看。
- 不接入真实支付，不访问真实美团 API，不存储用户隐私数据。

## 4. 验证

当前 Demo 模式通过 10 个 Hard Case：

```text
python eval.py
36/36 (100%)
```
