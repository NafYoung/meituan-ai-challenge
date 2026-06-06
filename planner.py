"""规划引擎 — ReAct 循环，支持 Claude / OpenAI API 和 Demo 模式"""

import json
import os
from tools import TOOL_SCHEMAS, call_tool

# ── 系统提示词 ────────────────────────────────────────────────

SYSTEM_PROMPT = """你是美团本地生活智能规划助手。你的任务是根据用户的一句话描述，规划出完整的短时活动方案。

## 工作流程

1. **意图解析**：从用户输入中提取关键信息（场景、人数、时长、偏好、约束）
2. **信息收集**：调用工具搜索 POI、餐厅、活动等信息
3. **方案编排**：将收集到的信息编排成时间线
4. **用户确认**：输出方案供用户确认
5. **一键执行**：用户确认后调用执行类工具完成下单

## 约束规则

- 方案必须考虑用户提到的所有约束（减肥→低卡餐、带娃→亲子友好、距离近→5km内）
- 时间线要合理：活动时长 + 路程时间 + 用餐时间
- 优先推荐评分高、距离近的选项
- 如果用户提到特殊需求（如蛋糕、鲜花），自动加入配送

## 输出格式

在收集完信息后，输出一个结构化的方案，包含：
- 时间线（时间 → 活动/地点 → 状态）
- 总预算估算
- 执行动作列表（待用户确认后执行）

## 重要

- 每次只调用 1-2 个工具，不要一次性调用太多
- 如果信息不足，继续调用工具补充
- 方案要具体到餐厅名称、POI 名称、价格
"""

# ── 工具定义转 Anthropic 格式 ─────────────────────────────────

def schemas_to_anthropic_tools():
    tools = []
    for s in TOOL_SCHEMAS:
        tools.append({
            "name": s["name"],
            "description": s["description"],
            "input_schema": s["parameters"],
        })
    return tools


def schemas_to_openai_tools():
    tools = []
    for s in TOOL_SCHEMAS:
        tools.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
            },
        })
    return tools


def _format_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _estimate_meal_time(plan_data: dict) -> str:
    constraints = plan_data.get("constraints", {})
    best_poi = plan_data.get("best_poi")
    start_total = 14 * 60

    if constraints.get("time_deadline"):
        try:
            dl_h, dl_m = map(int, constraints["time_deadline"].split(":"))
            dl_total = dl_h * 60 + dl_m
            poi_dur = int(best_poi["avg_duration_hours"] * 60) if best_poi else 0
            start_total = max(12 * 60, dl_total - poi_dur - 60 - 45)
        except Exception:
            pass
    elif constraints.get("time_window_hours") and constraints["time_window_hours"] <= 2.5:
        start_total = 14 * 60 + 30 if best_poi else 16 * 60

    if best_poi:
        start_total += int(best_poi["avg_duration_hours"] * 60) + 15

    return _format_minutes(start_total)


def build_executable_actions(plan_data: dict, tool_log: list[dict]) -> list[dict]:
    """Build mock execution actions from the latest plan state."""
    plan_data = plan_data or {}
    constraints = plan_data.get("constraints", {})
    party_size = constraints.get("party_size", 2)
    best_poi = plan_data.get("best_poi")
    best_rest = plan_data.get("best_rest")

    if not best_poi or not best_rest:
        for log in tool_log:
            result = log.get("result")
            if not isinstance(result, list) or not result:
                continue
            if not best_poi and log.get("tool") == "search_poi":
                best_poi = result[0]
            elif not best_rest and log.get("tool") == "search_restaurant":
                best_rest = result[0]

    actions = []
    if best_poi:
        actions.append({
            "tool": "buy_ticket",
            "args": {"venue_id": best_poi["id"], "quantity": party_size},
        })
    if best_rest:
        action_plan_data = {
            "constraints": constraints,
            "best_poi": best_poi,
            "best_rest": best_rest,
        }
        actions.append({
            "tool": "reserve_table",
            "args": {
                "restaurant_id": best_rest["id"],
                "time": _estimate_meal_time(action_plan_data),
                "party_size": party_size,
            },
        })

    delivery_address = f"送至{best_rest['name']}" if best_rest else "按方案指定地点"
    seen_items = set()
    for log in tool_log:
        if log.get("tool") != "search_delivery":
            continue
        result = log.get("result")
        if not isinstance(result, list) or not result:
            continue
        item = result[0]
        item_id = item.get("id")
        if not item_id or item_id in seen_items:
            continue
        seen_items.add(item_id)
        actions.append({
            "tool": "order_delivery",
            "args": {
                "item_id": item_id,
                "address": delivery_address,
                "delivery_time": "按方案时间送达",
            },
        })

    return actions


# ══════════════════════════════════════════════════════════════
# LLM 后端
# ══════════════════════════════════════════════════════════════

class ClaudeBackend:
    """使用 Anthropic Claude API"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
            self.client = anthropic.Anthropic()
            self.model = model
            self.tools = schemas_to_anthropic_tools()
        except ImportError:
            raise ImportError("需要安装 anthropic: pip install anthropic")
        except Exception as e:
            raise RuntimeError(f"初始化 Claude 客户端失败: {e}")

    def chat(self, messages: list[dict], system: str = SYSTEM_PROMPT) -> dict:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            tools=self.tools,
            messages=messages,
        )
        return self._parse_response(response)

    def _parse_response(self, response) -> dict:
        result = {"text": "", "tool_calls": [], "stop_reason": response.stop_reason}
        for block in response.content:
            if block.type == "text":
                result["text"] += block.text
            elif block.type == "tool_use":
                result["tool_calls"].append({
                    "id": block.id,
                    "name": block.name,
                    "args": block.input,
                })
        return result


class OpenAIBackend:
    """使用 OpenAI API（兼容任何 OpenAI 格式的 API）"""

    def __init__(self, model: str = "gpt-4o", base_url: str = None, api_key: str = None):
        try:
            from openai import OpenAI
            kwargs = {}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:
                kwargs["api_key"] = api_key
            self.client = OpenAI(**kwargs)
            self.model = model
            self.tools = schemas_to_openai_tools()
        except ImportError:
            raise ImportError("需要安装 openai: pip install openai")

    def chat(self, messages: list[dict], system: str = SYSTEM_PROMPT) -> dict:
        full_messages = [{"role": "system", "content": system}] + messages
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            tools=self.tools,
            messages=full_messages,
        )
        return self._parse_response(response.choices[0])

    def _parse_response(self, choice) -> dict:
        result = {"text": "", "tool_calls": [], "stop_reason": choice.finish_reason}
        msg = choice.message
        if msg.content:
            result["text"] = msg.content
        if msg.tool_calls:
            for tc in msg.tool_calls:
                result["tool_calls"].append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments),
                })
        return result


class DeepSeekBackend(OpenAIBackend):
    """使用 DeepSeek API（兼容 OpenAI 格式）"""

    def __init__(self, model: str = "deepseek-chat"):
        import os
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("请设置环境变量 DEEPSEEK_API_KEY")
        super().__init__(
            model=model,
            base_url="https://api.deepseek.com",
            api_key=api_key,
        )


# ══════════════════════════════════════════════════════════════
# ReAct 规划器
# ══════════════════════════════════════════════════════════════

class Planner:
    """ReAct 循环控制器"""

    def __init__(self, backend=None, verbose: bool = True):
        self.backend = backend
        self.verbose = verbose
        self.messages: list[dict] = []
        self.tool_log: list[dict] = []
        self._last_plan_text: str = ""

    def share(self) -> str:
        """生成可转发的分享消息（LLM模式基础版）"""
        if not self._last_plan_text:
            return "还没有生成方案，请先说你的需求。"
        # LLM模式的方案已经是自然语言，直接加前缀
        lines = self._last_plan_text.strip().split("\n")
        short = " ".join(l for l in lines[:3] if l.strip() and not l.strip().startswith("#"))
        return f"搞定了！{short}"

    def _log(self, msg: str, style: str = "info"):
        if not self.verbose:
            return
        colors = {
            "info": "\033[36m",      # cyan
            "tool": "\033[33m",      # yellow
            "result": "\033[32m",    # green
            "plan": "\033[35m",      # magenta
            "error": "\033[31m",     # red
            "reset": "\033[0m",
        }
        c = colors.get(style, colors["info"])
        print(f"{c}{msg}{colors['reset']}")

    def chat(self, user_input: str) -> str:
        """多轮对话：追加上下文，不清空历史"""
        is_first = len(self.messages) == 0
        self.messages.append({"role": "user", "content": user_input})
        return self._replan(is_first)

    def plan(self, user_input: str) -> str:
        """单轮规划：清空历史从头开始"""
        self.messages = [{"role": "user", "content": user_input}]
        return self._replan(is_first=True)

    def _replan(self, is_first: bool) -> str:
        """ReAct 循环核心（单轮/多轮共用）"""
        if is_first:
            self._log(f"\n{'='*60}")
            self._log(f"  用户: {self.messages[0]['content']}", "info")
        self._log(f"{'='*60}\n")

        max_rounds = 8
        for round_num in range(max_rounds):
            self._log(f"--- 第 {round_num + 1} 轮思考 ---", "info")

            # 调用 LLM
            response = self.backend.chat(self.messages)
            stop_reason = response.get("stop_reason", "")

            # 输出文本
            if response["text"]:
                self._log(f"  思考: {response['text'][:200]}...", "plan")

            # 如果没有工具调用，说明方案完成
            if not response["tool_calls"]:
                self._log("\n  ✓ 方案生成完毕", "result")
                self._last_plan_text = response["text"]
                return response["text"]

            # 执行工具调用：检测后端类型，用对应格式构建消息
            is_openai = isinstance(self.backend, OpenAIBackend)

            if is_openai:
                # OpenAI 格式：tool_calls + tool role
                tc_list = []
                for tc in response["tool_calls"]:
                    tc_list.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)},
                    })
                assistant_msg = {
                    "role": "assistant",
                    "content": response["text"] or None,
                    "tool_calls": tc_list,
                }
                self.messages.append(assistant_msg)

                for tc in response["tool_calls"]:
                    self._log(f"  → 调用工具: {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})", "tool")
                    result = call_tool(tc["name"], tc["args"])
                    self._log(f"  ← 返回: {json.dumps(result, ensure_ascii=False)[:150]}...", "result")
                    self.tool_log.append({"tool": tc["name"], "args": tc["args"], "result": result})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                # Anthropic 格式：content blocks + user role tool_result
                assistant_msg = {"role": "assistant", "content": []}
                if response["text"]:
                    assistant_msg["content"].append({"type": "text", "text": response["text"]})

                tool_results = []
                for tc in response["tool_calls"]:
                    self._log(f"  → 调用工具: {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})", "tool")
                    result = call_tool(tc["name"], tc["args"])
                    self._log(f"  ← 返回: {json.dumps(result, ensure_ascii=False)[:150]}...", "result")
                    self.tool_log.append({"tool": tc["name"], "args": tc["args"], "result": result})
                    assistant_msg["content"].append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["args"],
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                self.messages.append(assistant_msg)
                self.messages.append({"role": "user", "content": tool_results})

        self._last_plan_text = "达到最大轮次，返回当前方案。"
        return "达到最大轮次，返回当前方案。"

    def execute(self, confirmations: list[dict] = None) -> list[dict]:
        """执行下单动作（在用户确认方案后调用）"""
        if not confirmations:
            return []

        results = []
        for action in confirmations:
            tool_name = action.get("tool")
            args = action.get("args", {})
            self._log(f"  ⚡ 执行: {tool_name}({json.dumps(args, ensure_ascii=False)})", "tool")
            result = call_tool(tool_name, args)
            self._log(f"  ✓ 结果: {json.dumps(result, ensure_ascii=False)[:100]}", "result")
            results.append({"tool": tool_name, "args": args, "result": result})

        return results

    def get_executable_actions(self) -> list[dict]:
        """Return executable mock actions inferred from tool results."""
        return build_executable_actions({}, self.tool_log)


# ══════════════════════════════════════════════════════════════
# Demo 模式（不需要 API key）
# ══════════════════════════════════════════════════════════════

class DemoPlanner:
    """无 API 的 Demo 模式，用预设逻辑模拟规划过程"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.tool_log: list[dict] = []
        self._last_plan_data: dict = {}   # 存储最近一次plan的结构化上下文供share()使用

    def _log(self, msg: str, style: str = "info"):
        if not self.verbose:
            return
        colors = {
            "info": "\033[36m",
            "tool": "\033[33m",
            "result": "\033[32m",
            "plan": "\033[35m",
            "reset": "\033[0m",
        }
        c = colors.get(style, colors["info"])
        print(f"{c}{msg}{colors['reset']}")

    def _call_and_log(self, tool_name: str, args: dict) -> dict:
        self._log(f"  → 调用工具: {tool_name}({json.dumps(args, ensure_ascii=False)})", "tool")
        result = call_tool(tool_name, args)
        self._log(f"  ← 返回: {json.dumps(result, ensure_ascii=False)[:120]}...", "result")
        self.tool_log.append({"tool": tool_name, "args": args, "result": result})
        return result

    def _parse_constraints(self, user_input: str) -> dict:
        """从自然语言中提取结构化约束"""
        import re

        c = {
            "is_family": False,
            "is_friends": False,
            "is_couple": False,
            "party_size": 2,
            "scene": "",
            "dietary": [],            # 所有饮食约束的标签
            "individual_diets": [],   # [{person, constraint}]
            "time_deadline": None,    # "18:00" or None
            "time_window_hours": None, # 2.5 or None
            "distance_limit_km": 5.0,
            "budget_total": None,
            "budget_per_person": None,
            "occasion": None,
            "special_requests": [],
            "poi_category": "",       # 用户明确想要的POI类型
            "child_age": None,        # 儿童年龄
            "gender_mix": "",         # 性别组合，如"2男2女"
        }

        # ── 场景 / 人数 ──
        if any(kw in user_input for kw in ["孩子", "家人", "家庭", "亲子", "带娃"]):
            c["is_family"] = True
            c["party_size"] = 3
            c["scene"] = "亲子"
        if any(kw in user_input for kw in ["朋友", "哥们", "闺蜜", "聚会", "聚一下", "团队", "团建"]):
            c["is_friends"] = True
            c["party_size"] = max(c["party_size"], 4)
            c["scene"] = "朋友聚会"
        # couple 不覆盖 family 的人数
        if any(kw in user_input for kw in ["女朋友", "约会", "纪念日", "情侣"]):
            if not c["is_family"]:
                c["is_couple"] = True
                c["party_size"] = 2
        # "老婆"单独出现（无孩子相关词）→ couple
        if "老婆" in user_input and not c["is_family"]:
            c["is_couple"] = True
            c["party_size"] = 2

        # 显式人数：X个人 / X人 / X位
        m = re.search(r'(\d+)\s*(个)?[人位]', user_input)
        if m:
            c["party_size"] = int(m.group(1))

        # 儿童年龄："孩子X岁" / "X岁孩子" / "小孩X岁"
        m = re.search(r'(?:孩子|小孩|宝宝)\s*(\d+)\s*岁|(\d+)\s*岁\s*(?:的?孩子|小孩|宝宝)', user_input)
        if m:
            age = int(m.group(1) or m.group(2))
            if 0 < age < 18:
                c["child_age"] = age

        # 性别组合："X男X女" / "X个男生X个女生"
        m = re.search(r'(\d+)\s*男\s*(\d+)\s*女|(\d+)\s*个?男生\s*(\d+)\s*个?女生', user_input)
        if m:
            males = int(m.group(1) or m.group(3))
            females = int(m.group(2) or m.group(4))
            c["gender_mix"] = f"{males}男{females}女"
            # 混合性别组→偏好中性活动
            if males > 0 and females > 0 and not c["poi_category"]:
                c["poi_category"] = "体验"  # 手作/DIY类最中性

        # ── 饮食约束 ──
        diet_map = [
            (["素食", "吃素", "不吃肉", "只吃素"], "素食"),
            (["海鲜过敏", "不能吃海鲜", "不吃海鲜", "无海鲜"], "无海鲜"),
            (["不吃辣", "不能吃辣", "怕辣", "不要辣"], "无辣"),
            (["不吃碳水", "低碳", "戒碳水"], "无碳水"),
            (["减肥", "低卡", "轻食", "健康餐", "减脂"], "低卡"),
            (["不吃牛肉", "不吃羊肉"], "无红肉"),
        ]
        for keywords, tag in diet_map:
            if any(kw in user_input for kw in keywords):
                c["dietary"].append(tag)

        # 个体饮食：匹配 "XXX吃素" / "XXX海鲜过敏" / "XXX不吃辣"
        person_diet_patterns = [
            (r'(\S{1,4})(吃素|只吃素)', "素食"),
            (r'(\S{1,4})海鲜过敏', "无海鲜"),
            (r'(\S{1,4})(不吃辣|不能吃辣|怕辣)', "无辣"),
            (r'(\S{1,4})(不吃碳水|低碳)', "无碳水"),
            (r'(\S{1,4})(不吃牛肉|不吃羊肉)', "无红肉"),
        ]
        for pattern, tag in person_diet_patterns:
            for m in re.finditer(pattern, user_input):
                person = m.group(1)
                if person not in ["可以", "想要", "喜欢", "需要"]:
                    c["individual_diets"].append({"person": person, "constraint": tag})
                    if tag not in c["dietary"]:
                        c["dietary"].append(tag)

        # ── 时间约束 ──
        # 截止时间："X点前" / "X点必须" / "赶X点" / "X点之前"
        deadline_patterns = [
            r'(\d{1,2})点(?:之前|前|必须|之?前)',
            r'赶(\d{1,2})点',
            r'(\d{1,2})点(?:的|要)',
        ]
        for pat in deadline_patterns:
            m = re.search(pat, user_input)
            if m:
                hour = int(m.group(1))
                if 1 <= hour <= 24:
                    # 如果是1-6点，可能是下午/晚上，+12
                    if hour <= 6:
                        hour += 12
                    c["time_deadline"] = f"{hour:02d}:00"
                break

        # 时间窗口："X个小时" / "X个半小时" / "X.5小时"
        m = re.search(r'(\d+)(?:\.5|个半|个半小)?小?时(?:间|空闲)?', user_input)
        if m:
            if "半" in user_input[m.start():m.end()] or ".5" in user_input[m.start():m.end()]:
                c["time_window_hours"] = int(m.group(1)) + 0.5
            else:
                c["time_window_hours"] = float(m.group(1))

        # ── 距离约束 ──
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:公里|km|千米)', user_input, re.IGNORECASE)
        if m:
            c["distance_limit_km"] = float(m.group(1))
        if any(kw in user_input for kw in ["步行", "走路", "不远", "近一点"]):
            c["distance_limit_km"] = min(c["distance_limit_km"], 2.0)
        if any(kw in user_input for kw in ["不想走远", "家附近", "不要太远", "别太远"]):
            c["distance_limit_km"] = min(c["distance_limit_km"], 1.0)
        if any(kw in user_input for kw in ["不能离太远", "离太远"]):
            c["distance_limit_km"] = min(c["distance_limit_km"], 3.0)

        # ── 预算 ──
        # 人均预算
        m = re.search(r'人均\s*(\d+)', user_input)
        if m:
            c["budget_per_person"] = int(m.group(1))
        # 总预算
        for pat in [r'预算\s*(\d+)', r'总预算\s*(\d+)', r'不超过\s*(\d+)', r'控制在\s*(\d+)']:
            m = re.search(pat, user_input)
            if m:
                c["budget_total"] = int(m.group(1))
                break

        # ── 特殊场景 ──
        if any(kw in user_input for kw in ["纪念日", "周年"]):
            c["occasion"] = "纪念日"
        elif any(kw in user_input for kw in ["生日"]):
            c["occasion"] = "生日"
        elif any(kw in user_input for kw in ["约会"]):
            c["occasion"] = "约会"
        elif any(kw in user_input for kw in ["团建"]):
            c["occasion"] = "团建"

        # ── 用户明确想要的POI类型 ──
        if any(kw in user_input for kw in ["展览", "看展", "逛展", "艺术"]):
            c["poi_category"] = "展览"
        elif any(kw in user_input for kw in ["手工", "DIY", "手作", "陶艺"]):
            c["poi_category"] = "体验"
        elif any(kw in user_input for kw in ["密室", "逃脱", "剧本杀"]):
            c["poi_category"] = "娱乐"
        elif any(kw in user_input for kw in ["电影", "影院", "看电影"]):
            c["poi_category"] = "电影"
        elif any(kw in user_input for kw in ["蹦床", "运动"]):
            c["poi_category"] = "运动"
        elif any(kw in user_input for kw in ["安静", "看书", "书店", "读书"]):
            c["poi_category"] = "书店"
        elif any(kw in user_input for kw in ["唱歌", "KTV", "ktv"]):
            c["poi_category"] = "娱乐"
        elif any(kw in user_input for kw in ["小吃", "citywalk", "逛街", "夜市"]):
            c["poi_category"] = "街区"

        if "鲜花" in user_input or "花束" in user_input:
            c["special_requests"].append("鲜花")
        if "蛋糕" in user_input:
            c["special_requests"].append("蛋糕")
        if any(kw in user_input for kw in ["优惠券", "团购", "折扣", "省钱", "便宜", "学生", "预算有限", "穷游"]):
            c["special_requests"].append("团购优先")

        return c

    def chat(self, user_input: str) -> str:
        """多轮对话：将历史上下文拼接后重新规划"""
        self._chat_history = getattr(self, "_chat_history", [])
        self._chat_history.append(user_input)
        # 拼接所有历史输入作为上下文
        full_input = " · ".join(self._chat_history)
        return self.plan(full_input)

    def plan(self, user_input: str) -> str:
        """模拟规划过程 — 基于结构化约束推理"""
        self.tool_log = []
        self._chat_history = []  # 单轮：重置历史
        constraints = self._parse_constraints(user_input)

        self._log(f"\n{'='*60}")
        self._log(f"  用户: {user_input}", "info")
        self._log(f"  约束: party={constraints['party_size']} "
                 f"dietary={constraints['dietary']} "
                 f"deadline={constraints['time_deadline']} "
                 f"window={constraints['time_window_hours']}h "
                 f"dist<={constraints['distance_limit_km']}km "
                 f"budget={constraints['budget_total']} "
                 f"occasion={constraints['occasion']}", "info")
        self._log(f"{'='*60}\n")

        dist = constraints["distance_limit_km"]

        # ── 第1轮：搜索 POI ──
        self._log("--- 第 1 轮思考 ---", "info")
        poi_args = {"distance_limit": dist}
        if constraints["is_family"] or "亲子" in constraints["scene"]:
            poi_args["suitable_for"] = "亲子"
            self._log("  思考: 家庭出游，搜索亲子友好POI...", "plan")
        elif constraints["gender_mix"]:
            self._log(f"  思考: 混合性别组({constraints['gender_mix']})，搜索中性活动...", "plan")
            poi_args["category"] = constraints.get("poi_category", "体验")
        elif constraints["is_friends"] or constraints["occasion"] == "团建":
            self._log("  思考: 朋友聚会，搜索团建/娱乐类POI...", "plan")
            poi_args["category"] = "娱乐"
        elif constraints["is_couple"] or constraints["occasion"] in ("纪念日", "约会"):
            self._log("  思考: 约会场景，搜索拍照/文艺类POI...", "plan")
            poi_args["category"] = "展览"
        elif constraints["poi_category"]:
            self._log(f"  思考: 用户指定类型 [{constraints['poi_category']}]...", "plan")
            poi_args["category"] = constraints["poi_category"]
        else:
            self._log("  思考: 搜索周边POI...", "plan")

        pois = self._call_and_log("search_poi", poi_args)

        # 指定category搜索为空时，退化到无过滤搜索
        if not pois and "category" in poi_args:
            self._log("  思考: 指定类型无结果，扩大搜索范围...", "plan")
            fallback_args = {"distance_limit": dist}
            if "suitable_for" in poi_args:
                fallback_args["suitable_for"] = poi_args["suitable_for"]
            pois = self._call_and_log("search_poi", fallback_args)

        # 儿童年龄过滤：剔除不适龄 POI
        if constraints["child_age"] and pois:
            age = constraints["child_age"]
            filtered = [p for p in pois
                        if p.get("min_age", 0) <= age <= p.get("max_age", 99)]
            if filtered:
                if len(filtered) < len(pois):
                    self._log(f"  思考: {age}岁儿童，过滤掉{len(pois)-len(filtered)}个不适龄POI...", "plan")
                pois = filtered
            # 如果全部被过滤，保留原列表（至少有个选项）

        # ── 第2轮：搜索餐厅（约束推理核心） ──
        self._log("\n--- 第 2 轮思考 ---", "info")
        tags = list(constraints["dietary"])
        if constraints["is_family"] and "亲子" not in tags:
            tags.append("亲子")

        if tags:
            # 多饮食约束时，优先匹配包含最多标签的餐厅
            tag_str = " + ".join(tags)
            self._log(f"  思考: 饮食约束 [{tag_str}]，搜索匹配餐厅...", "plan")
        elif constraints["occasion"] in ("纪念日", "约会", "生日"):
            tags = ["精致", "约会"]
            self._log("  思考: 特殊场合，搜索精致/约会类餐厅...", "plan")
        elif constraints["is_friends"]:
            tags = ["聚会"]
            self._log("  思考: 朋友聚会，搜索适合聚餐的餐厅...", "plan")
        else:
            self._log("  思考: 搜索附近热门餐厅...", "plan")

        # 多标签时放宽搜索：逐个尝试直到有结果
        restaurants = []
        if tags:
            restaurants = self._call_and_log("search_restaurant", {
                "tags": tags,
                "party_size": constraints["party_size"],
                "distance_limit": dist,
            })
            # 如果多标签无结果，逐个降级搜索
            if not restaurants and len(tags) > 1:
                for t in tags:
                    self._log(f"  思考: 多标签无结果，降级搜索 tags=[{t}]...", "plan")
                    restaurants = self._call_and_log("search_restaurant", {
                        "tags": [t],
                        "party_size": constraints["party_size"],
                        "distance_limit": dist,
                    })
                    if restaurants:
                        break
        else:
            restaurants = self._call_and_log("search_restaurant", {
                "party_size": constraints["party_size"],
                "distance_limit": dist,
            })

        # ── 第3轮：查排队 ──
        self._log("\n--- 第 3 轮思考 ---", "info")
        if restaurants:
            top_rest = restaurants[0]
            self._log(f"  思考: {top_rest['name']} 最佳匹配，查排队...", "plan")
            self._call_and_log("check_waitlist", {"restaurant_id": top_rest["id"]})

        # ── 第4轮：查活动（时间宽裕时才查，时间紧跳过） ──
        events = []
        if constraints["time_window_hours"] and constraints["time_window_hours"] <= 2.5:
            self._log("\n--- 第 4 轮思考 ---", "info")
            self._log("  思考: 时间窗口紧，跳过活动查询，优先保证核心动线...", "plan")
        else:
            self._log("\n--- 第 4 轮思考 ---", "info")
            self._log("  思考: 查今天活动...", "plan")
            events = self._call_and_log("check_event", {"date": "2026-05-17"})

        # ── 第5轮：配送需求 ──
        if constraints["special_requests"]:
            self._log("\n--- 第 5 轮思考 ---", "info")
            for req in constraints["special_requests"]:
                if req in ("鲜花", "蛋糕"):
                    self._log(f"  思考: 用户需要{req}，搜索配送...", "plan")
                    self._call_and_log("search_delivery", {"tags": [req]})

        # ── 第6轮：团购/优惠券 ──
        coupons_found = []
        if "团购优先" in constraints["special_requests"]:
            self._log("\n--- 第 6 轮思考 ---", "info")
            self._log("  思考: 用户预算敏感，搜索团购/优惠券...", "plan")
            # 为已选的POI和餐厅查找优惠券
            if restaurants:
                rest_id = restaurants[0]["id"]
                rest_coupons = self._call_and_log("search_coupon", {
                    "scope_type": "restaurant", "scope_id": rest_id,
                    "min_party": constraints["party_size"],
                })
                coupons_found.extend(rest_coupons)
            if pois:
                poi_id = pois[0]["id"]
                poi_coupons = self._call_and_log("search_coupon", {
                    "scope_type": "poi", "scope_id": poi_id,
                    "min_party": constraints["party_size"],
                })
                coupons_found.extend(poi_coupons)
            if coupons_found:
                total_saving = sum(c.get("saving", 0) for c in coupons_found)
                self._log(f"  思考: 找到{len(coupons_found)}个优惠，共可省{total_saving}元", "result")

        # ── 生成方案 ──
        self._log("\n  ✓ 方案生成完毕\n", "result")
        best_poi = pois[0] if pois else None
        best_rest = restaurants[0] if restaurants else None
        self._last_plan_data = {
            "constraints": constraints,
            "best_poi": best_poi,
            "best_rest": best_rest,
            "events": events,
            "coupons": coupons_found,
        }
        plan_text = self._format_plan(constraints, pois, restaurants, events, coupons_found)
        return plan_text

    def _format_plan(self, constraints: dict, pois: list, restaurants: list, events: list, coupons: list = None) -> str:
        """基于约束格式化方案输出"""
        coupons = coupons or []
        best_poi = pois[0] if pois else None
        best_rest = restaurants[0] if restaurants else None
        party_size = constraints["party_size"]
        dietary = constraints["dietary"]
        individual = constraints["individual_diets"]

        # ── 时间线计算 ──
        start_h, start_m = 14, 0

        if constraints["time_deadline"]:
            try:
                dl_h, dl_m = map(int, constraints["time_deadline"].split(":"))
                dl_total = dl_h * 60 + dl_m
                poi_dur = int(best_poi["avg_duration_hours"] * 60) if best_poi else 0
                rest_dur = 60
                start_total = dl_total - poi_dur - rest_dur - 45  # 含路程
                start_h = max(12, start_total // 60)
                start_m = start_total % 60
            except:
                pass
        elif constraints["time_window_hours"]:
            window = constraints["time_window_hours"]
            window_min = int(window * 60)
            if window <= 2.5 and not constraints["poi_category"]:
                best_poi = None
                start_h, start_m = 16, 0
            elif window <= 2.5 and best_poi:
                start_h, start_m = 14, 30

        # 计算 POI 结束时间
        if best_poi:
            poi_dur_min = int(best_poi["avg_duration_hours"] * 60)
            end_minutes = start_h * 60 + start_m + poi_dur_min + 15
            end_h, end_m = end_minutes // 60, end_minutes % 60
        else:
            end_h, end_m = start_h, start_m

        # 餐厅缓冲：时间紧用60min，宽裕用90min
        rest_buffer = 90
        if constraints["time_window_hours"]:
            used = (end_h * 60 + end_m) - (start_h * 60 + start_m)
            remaining = int(constraints["time_window_hours"] * 60) - used
            rest_buffer = min(90, max(40, remaining))
        if constraints["time_deadline"]:
            try:
                dl_total = int(constraints["time_deadline"].split(":")[0]) * 60 + int(constraints["time_deadline"].split(":")[1])
                max_rest = dl_total - (end_h * 60 + end_m) - 15
                rest_buffer = min(rest_buffer, max(40, max_rest))
            except:
                pass

        def fmt_time(h, m):
            return f"{h:02d}:{m:02d}"

        lines = []
        lines.append("📋 为您规划的活动方案：")
        lines.append("")

        # 约束摘要
        constraint_parts = []
        if dietary:
            constraint_parts.append(f"饮食: {'+'.join(dietary)}")
        if constraints["time_deadline"]:
            constraint_parts.append(f"截止: {constraints['time_deadline']}")
        if constraints["time_window_hours"]:
            constraint_parts.append(f"时长: {constraints['time_window_hours']}h")
        if constraints["budget_total"]:
            constraint_parts.append(f"预算: ≤{constraints['budget_total']}元")
        if constraints["distance_limit_km"] < 5.0:
            constraint_parts.append(f"范围: ≤{constraints['distance_limit_km']}km")
        if constraints["child_age"]:
            constraint_parts.append(f"儿童: {constraints['child_age']}岁")
        if constraints["gender_mix"]:
            constraint_parts.append(f"组合: {constraints['gender_mix']}")
        if constraint_parts:
            lines.append(f"  🎯 约束: {' | '.join(constraint_parts)}")
        if individual:
            for ind in individual:
                lines.append(f"     👤 {ind['person']}: {ind['constraint']}")
        lines.append("")

        # ── POI ──
        if best_poi:
            t1 = fmt_time(start_h, start_m)
            lines.append(f"  {t1}  出发 → {best_poi['name']}（{best_poi['distance_km']}km）")
            lines.append(f"         {best_poi['category']} · 评分 {best_poi['rating']} · 预计 {best_poi['avg_duration_hours']}h")
            if best_poi.get("tags"):
                lines.append(f"         标签: {' · '.join(best_poi['tags'])}")
            lines.append(f"         价格: {best_poi['price_range']}")
            lines.append("")
            end_minutes = start_h * 60 + start_m + int(best_poi["avg_duration_hours"] * 60) + 15
            end_h, end_m = end_minutes // 60, end_minutes % 60
        else:
            end_h, end_m = start_h, start_m

        # ── 餐厅 ──
        if best_rest:
            t2 = fmt_time(end_h, end_m)
            lines.append(f"  {t2}  前往 {best_rest['name']}（{best_rest['distance_km']}km）")
            lines.append(f"         {best_rest['cuisine']} · 评分 {best_rest['rating']} · 人均 {best_rest['avg_price']}元")
            if best_rest.get("tags"):
                lines.append(f"         标签: {' · '.join(best_rest['tags'])}")

            # 饮食约束匹配说明
            matched_tags = [t for t in dietary if any(t in rt for rt in best_rest.get("tags", []))]
            if matched_tags:
                lines.append(f"         ✓ 已匹配: {' · '.join(matched_tags)}")
            elif dietary:
                lines.append(f"         ⚠ 部分约束未精确匹配 (餐厅标签: {', '.join(best_rest.get('tags', []))})")

            wait = best_rest.get("current_wait", 0)
            wait_min = best_rest.get("wait_minutes", 0)
            if wait > 5:
                lines.append(f"         ⚠ 当前排队 {wait} 桌（约{wait_min}分钟），建议提前排号")
            elif wait > 0:
                lines.append(f"         当前排队 {wait} 桌，预计等待 {wait_min} 分钟")
            lines.append("")

        # ── 活动（仅时间充裕时展示） ──
        if events and best_poi:
            evt = events[0]
            lines.append(f"  顺便看看: {evt['name']}")
            lines.append(f"         {evt['location']} · {evt['time']} · {evt['price']}")
            lines.append("")

        # ── 收尾时间 ──
        if best_rest:
            end_total = end_h * 60 + end_m + rest_buffer
            end_h2, end_m2 = end_total // 60, end_total % 60
        else:
            end_h2, end_m2 = end_h, end_m

        if constraints["time_deadline"]:
            lines.append(f"  {fmt_time(end_h2, end_m2)}  返程（截止时间 {constraints['time_deadline']}）")
        elif constraints["time_window_hours"]:
            lines.append(f"  {fmt_time(end_h2, end_m2)}  结束 · 总耗时约{constraints['time_window_hours']}h")
        else:
            lines.append(f"  {fmt_time(end_h2, end_m2)}  附近散步消食")
            end_h2 += 1
            lines.append(f"  {fmt_time(end_h2, 0)}  返程")
        lines.append("")

        # ── 预算 ──
        poi_cost = 0
        if best_poi and "免费" not in best_poi.get("price_range", ""):
            try:
                poi_cost = int(best_poi["price_range"].split("-")[0].replace("元/人", "").replace("元", ""))
            except:
                poi_cost = 50
        rest_cost = best_rest["avg_price"] if best_rest else 0
        total = (poi_cost + rest_cost) * party_size

        budget_ok = True
        if constraints["budget_total"]:
            budget_ok = total <= constraints["budget_total"]
        elif constraints["budget_per_person"]:
            budget_ok = (poi_cost + rest_cost) <= constraints["budget_per_person"]

        budget_flag = "" if budget_ok else " ⚠ 超预算"

        # ── 团购优惠 ──
        if coupons:
            total_saving = sum(c.get("saving", 0) for c in coupons)
            after_coupon = max(0, total - total_saving)
            lines.append(f"💰 预估总费用: 约 {total} 元（{party_size}人）{budget_flag}")
            lines.append(f"   🎫 可用优惠: {' · '.join(c['name'] for c in coupons)}")
            lines.append(f"   💡 使用优惠后: 约 {after_coupon} 元（省 {total_saving} 元）")
        else:
            lines.append(f"💰 预估总费用: 约 {total} 元（{party_size}人）{budget_flag}")
            if "团购优先" in constraints.get("special_requests", []):
                lines.append(f"   ⚠ 当前无可用优惠券/团购，建议到店查看美团App")

        lines.append("")
        lines.append("确认方案后，我可以帮您：")
        if best_poi:
            lines.append(f"  ✓ 购买 {best_poi['name']} 门票")
        if best_rest:
            lines.append(f"  ✓ {best_rest['name']} 排号/预订")
        if constraints["special_requests"]:
            for req in constraints["special_requests"]:
                if req in ("鲜花", "蛋糕"):
                    lines.append(f"  ✓ 下单配送{req}")
                elif req == "团购优先":
                    lines.append(f"  ⚠ 团购/优惠券功能待接入美团API")
        else:
            lines.append("  ✓ 下单配送（蛋糕/鲜花等，如需要）")

        return "\n".join(lines)

    def execute(self, confirmations: list[dict] = None) -> list[dict]:
        """执行下单"""
        if not confirmations:
            return []
        results = []
        for action in confirmations:
            tool_name = action.get("tool")
            args = action.get("args", {})
            self._log(f"  ⚡ 执行: {tool_name}({json.dumps(args, ensure_ascii=False)})", "tool")
            result = call_tool(tool_name, args)
            self._log(f"  ✓ 结果: {json.dumps(result, ensure_ascii=False)[:100]}", "result")
            results.append({"tool": tool_name, "args": args, "result": result})
        return results

    def get_executable_actions(self) -> list[dict]:
        """返回最近一次方案对应的可执行动作"""
        return build_executable_actions(self._last_plan_data, self.tool_log)

    def share(self) -> str:
        """生成可转发的分享消息（微信/飞书风格）"""
        data = self._last_plan_data
        if not data:
            return "还没有生成方案，请先说你的需求。"

        constraints = data.get("constraints", {})
        best_poi = data.get("best_poi")
        best_rest = data.get("best_rest")
        events = data.get("events", [])
        party_size = constraints.get("party_size", 2)

        # ── 时间线提取 ──
        start_h, start_m = 14, 0
        if constraints.get("time_deadline"):
            try:
                dl_h, dl_m = map(int, constraints["time_deadline"].split(":"))
                dl_total = dl_h * 60 + dl_m
                poi_dur = int(best_poi["avg_duration_hours"] * 60) if best_poi else 0
                start_total = dl_total - poi_dur - 60 - 45
                start_h = max(12, start_total // 60)
                start_m = start_total % 60
            except:
                pass
        elif constraints.get("time_window_hours") and constraints["time_window_hours"] <= 2.5:
            start_h, start_m = 14, 30 if best_poi else 16

        parts = [f"搞定了！下午{start_h}点{dstext(start_m)}出发"]

        if best_poi:
            parts.append(f"先去{best_poi['name']}（{best_poi['category']}，{best_poi['distance_km']}km，评分{best_poi['rating']}）")

        if best_rest:
            wait = best_rest.get("wait_minutes", 0)
            wait_text = f"，建议提前排号（约等{wait}分钟）" if wait > 10 else ""
            parts.append(f"然后去{best_rest['name']}吃饭（{best_rest['cuisine']}，人均{best_rest['avg_price']}元{wait_text}）")

        if events:
            evt = events[0]
            parts.append(f"顺路可以看看「{evt['name']}」（{evt['time']}，{evt['price']}）")

        # 收尾时间
        end_text = ""
        if best_rest:
            if best_poi:
                poi_dur = int(best_poi["avg_duration_hours"] * 60)
                end_min = start_h * 60 + start_m + poi_dur + 15 + 60
            else:
                end_min = start_h * 60 + start_m + 60
            eh, em = end_min // 60, end_min % 60
            end_text = f"预计{eh}点{dstext(em)}结束"

        if end_text:
            parts.append(end_text)

        # 预算
        poi_cost = 0
        if best_poi and "免费" not in best_poi.get("price_range", ""):
            try:
                poi_cost = int(best_poi["price_range"].split("-")[0].replace("元/人", "").replace("元", ""))
            except:
                poi_cost = 50
        rest_cost = best_rest["avg_price"] if best_rest else 0
        total = (poi_cost + rest_cost) * party_size
        parts.append(f"人均约{total // party_size}元，总共{total}元以内～")

        # 约束提示
        if constraints.get("dietary"):
            parts.append(f"已适配{'、'.join(constraints['dietary'])}需求")
        if constraints.get("child_age"):
            parts.append(f"活动适合{constraints['child_age']}岁小朋友")

        return "，".join(parts) + "。"


def dstext(m: int) -> str:
    """分钟→中文"""
    return f"{m:02d}分" if m > 0 else "整"


# ══════════════════════════════════════════════════════════════
# 工厂函数
# ══════════════════════════════════════════════════════════════

def create_planner(mode: str = "demo", verbose: bool = True) -> Planner | DemoPlanner:
    """
    创建规划器
    mode: "demo" | "claude" | "openai" | "deepseek"
    """
    if mode == "claude":
        backend = ClaudeBackend()
        return Planner(backend, verbose)
    elif mode == "deepseek":
        backend = DeepSeekBackend()
        return Planner(backend, verbose)
    elif mode == "openai":
        backend = OpenAIBackend()
        return Planner(backend, verbose)
    else:
        return DemoPlanner(verbose)
