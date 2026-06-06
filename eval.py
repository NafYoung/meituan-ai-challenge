#!/usr/bin/env python3
"""评测模块 — 10 个 hard case，验证方案合理性、约束满足、执行安全"""

import json
import sys
from dataclasses import dataclass, field
from planner import create_planner
from tools import call_tool


# ══════════════════════════════════════════════════════════════
# 评测用例定义
# ══════════════════════════════════════════════════════════════

@dataclass
class EvalCase:
    id: str
    name: str
    user_input: str
    difficulty: str                    # "basic" | "medium" | "hard"
    category: str                      # "冲突约束" | "复合场景" | "边界压力" | "美团特色" | "交互迭代"
    description: str
    checks: list[dict] = field(default_factory=list)
    # 每个 check: {"name": str, "type": str, "target": str, "desc": str}
    # type: "poi_match" | "restaurant_match" | "diet_match" | "budget_limit" |
    #       "family_match" | "distance_limit" | "timeline_reasonable" |
    #       "multi_constraint" | "failover" | "delivery_match"


EVAL_CASES = [
    # ── 冲突约束类 ──
    EvalCase(
        id="C01",
        name="预算硬约束：3人200元封顶",
        user_input="3个人下午出去玩，总预算不能超过200块，要包含吃和玩",
        difficulty="medium",
        category="冲突约束",
        description="用户明确给了预算上限，需要找免费/低价POI + 便宜餐厅，总费用不能超200",
        checks=[
            {"name": "total_budget_under_200", "type": "budget_limit", "target": "200", "desc": "3人总费用应≤200元"},
            {"name": "has_poi", "type": "poi_match", "desc": "方案应包含至少一个POI"},
            {"name": "has_restaurant", "type": "restaurant_match", "desc": "方案应包含至少一个餐厅"},
            {"name": "low_cost_poi", "type": "poi_match", "target": "免费|翠湖|[0-5][0-9]元", "desc": "POI应为免费或50元以下"},
        ],
    ),
    EvalCase(
        id="C02",
        name="多人饮食冲突",
        user_input="和2个朋友聚一下午，一个小王吃素，一个老李海鲜过敏，吃完饭还要赶6点的飞机，时间紧",
        difficulty="hard",
        category="冲突约束",
        description="三组冲突约束：素食者+海鲜过敏者+限时2.5小时。餐厅必须同时避开荤菜和海鲜",
        checks=[
            {"name": "time_window_tight", "type": "timeline_reasonable", "target": "2.5", "desc": "时间线应压缩在约2.5小时内"},
            {"name": "vegetarian_option", "type": "diet_match", "target": "素食|低卡|轻食|沙拉", "desc": "餐厅应适配素食需求"},
            {"name": "no_seafood", "type": "restaurant_match", "target": "!日料|!刺身|!海鲜", "desc": "不应推荐含海鲜/刺身的餐厅"},
            {"name": "party_size_3", "type": "multi_constraint", "desc": "方案应正确识别3人"},
        ],
    ),
    EvalCase(
        id="C03",
        name="带娃+减肥+午睡三重约束",
        user_input="下午带孩子出去玩，老婆在减肥，孩子4点必须午睡，要赶在3点半前回家",
        difficulty="medium",
        category="冲突约束",
        description="经典复合约束：亲子+低卡+时间硬截止（15:30前到家）",
        checks=[
            {"name": "family_poi", "type": "family_match", "desc": "POI应为亲子友好场所"},
            {"name": "diet_restaurant", "type": "diet_match", "target": "低卡|轻食|减肥|健康", "desc": "餐厅应匹配减肥/低卡需求"},
            {"name": "end_before_1530", "type": "timeline_reasonable", "target": "15:30", "desc": "方案应在15:30前结束（含返程）"},
            {"name": "child_friendly", "type": "family_match", "target": "儿童|亲子", "desc": "活动应适合儿童"},
        ],
    ),
    EvalCase(
        id="C04",
        name="极端距离约束：1km步行圈",
        user_input="周末不想走远，就想在家附近1公里内找个地方坐着喝点东西，顺便逛逛",
        difficulty="hard",
        category="冲突约束",
        description="极严格的距离约束（1km），数据中符合条件的选项可能很少",
        checks=[
            {"name": "within_1km", "type": "distance_limit", "target": "1.0", "desc": "推荐的POI/餐厅应在1km范围内"},
            {"name": "has_option", "type": "poi_match", "desc": "至少找到一个可用选项"},
            {"name": "walkable", "type": "timeline_reasonable", "desc": "方案应提及步行可达"},
        ],
    ),

    # ── 复合场景类 ──
    EvalCase(
        id="C05",
        name="纪念日惊喜套餐",
        user_input="结婚纪念日，晚上想给老婆一个惊喜，要有鲜花、蛋糕，吃顿好的，但老婆最近只吃素食",
        difficulty="medium",
        category="复合场景",
        description="纪念日=鲜花配送+蛋糕配送+精致餐厅+素食约束，需要调用 search_delivery + 下单",
        checks=[
            {"name": "special_restaurant", "type": "restaurant_match", "target": "精致|日料|粤菜|约会", "desc": "餐厅应为精致/约会型"},
            {"name": "vegetarian_compatible", "type": "diet_match", "target": "素食|沙拉|轻食", "desc": "应有素食选项"},
            {"name": "flowers_requested", "type": "delivery_match", "target": "鲜花", "desc": "应搜配送，包含鲜花"},
            {"name": "cake_requested", "type": "delivery_match", "target": "蛋糕", "desc": "应搜配送，包含蛋糕"},
        ],
    ),
    EvalCase(
        id="C06",
        name="团建方案：8人众口难调",
        user_input="团队8个人下午团建，预算人均150，要有活动有晚饭。有人不吃辣，有人恐高",
        difficulty="hard",
        category="复合场景",
        description="多人团建场景，人数多+预算限制+饮食禁忌+活动限制",
        checks=[
            {"name": "group_activity", "type": "poi_match", "target": "团建|解谜|团队", "desc": "POI应适合团建/多人活动"},
            {"name": "no_spicy", "type": "restaurant_match", "target": "!川菜|!麻辣", "desc": "不推荐麻辣/川菜（有人不吃辣）"},
            {"name": "party_size_8", "type": "multi_constraint", "desc": "方案应识别8人聚餐"},
            {"name": "budget_150pp", "type": "budget_limit", "target": "150", "desc": "人均预算应在150元左右"},
            {"name": "no_heights", "type": "poi_match", "target": "!蹦床|!高空", "desc": "不考虑恐高人群无法参与的活动"},
        ],
    ),

    # ── 边界压力类 ──
    EvalCase(
        id="C07",
        name="极端时间窗口：2.5小时搞定一切",
        user_input="我只有2个半小时空闲，想吃个饭再逛个有意思的展览，不能离太远",
        difficulty="hard",
        category="边界压力",
        description="时间极紧：2.5小时要覆盖吃饭+逛展+路程。方案必须精打细算",
        checks=[
            {"name": "total_time_2_5h", "type": "timeline_reasonable", "target": "2.5", "desc": "活动+路程应在2.5小时内"},
            {"name": "exhibition_poi", "type": "poi_match", "target": "展览|手工|体验", "desc": "POI应为展览/体验类"},
            {"name": "nearby_pairing", "type": "distance_limit", "target": "3.0", "desc": "POI和餐厅应距离较近（≤3km）"},
        ],
    ),
    EvalCase(
        id="C08",
        name="全部满座：排队超限",
        user_input="晚上想吃老王烧烤，几个人聚一下",
        difficulty="medium",
        category="边界压力",
        description="老王烧烤当前排队8桌/30分钟。如果是LLM模式应该察觉并给出备选；Demo模式应至少检查排队",
        checks=[
            {"name": "check_waitlist_called", "type": "multi_constraint", "target": "check_waitlist", "desc": "工具调用应包含check_waitlist"},
            {"name": "wait_info_shown", "type": "multi_constraint", "target": "排队|等待", "desc": "方案应展示排队信息"},
            {"name": "has_restaurant", "type": "restaurant_match", "desc": "方案应包含餐厅"},
        ],
    ),
    EvalCase(
        id="C09",
        name="POI命中率为零：冷门需求",
        user_input="我想找个能玩滑板的地方，附近要有安静的茶馆可以看书",
        difficulty="hard",
        category="边界压力",
        description="滑板场地不在mock数据中，茶馆也未覆盖。系统应优雅降级，给出最近似推荐",
        checks=[
            {"name": "graceful_fallback", "type": "multi_constraint", "desc": "无精确匹配时应给出近似推荐，而非空白"},
            {"name": "at_least_one_poi", "type": "poi_match", "desc": "即使无精确匹配，至少推荐一个可用POI"},
            {"name": "at_least_one_rest", "type": "restaurant_match", "desc": "即使无茶馆，至少推荐一个安静型餐厅"},
        ],
    ),

    # ── 美团特色类 ──
    EvalCase(
        id="C10",
        name="美团特色：团购优惠优先",
        user_input="下午带女朋友出去玩，我们都是学生预算有限，想看看有没有优惠券或者团购活动",
        difficulty="medium",
        category="美团特色",
        description="美团团购/优惠券场景。当前数据层缺少团购字段，这个case暴露缺口",
        checks=[
            {"name": "budget_aware", "type": "budget_limit", "target": "100", "desc": "方案应体现代价意识，优先低价选项"},
            {"name": "coupon_mention", "type": "multi_constraint", "target": "优惠|团购|折扣", "desc": "方案应提及优惠/团购可能性（暴露数据层缺口）"},
            {"name": "student_friendly", "type": "poi_match", "target": "免费|翠湖|[3-6][0-9]元", "desc": "推荐免费或低价POI"},
        ],
    ),
]

# 附加：交互迭代场景（需要多轮对话，单独处理）
INTERACTIVE_CASE = {
    "id": "C11",
    "name": "连续修改：3轮方案迭代",
    "initial": "下午带老婆孩子出去玩",
    "rounds": [
        {"input": "孩子4点要睡觉，3点半之前必须到家", "check": "end_before_1530"},
        {"input": "老婆不吃碳水，换家餐厅", "check": "low_carb_switch"},
        {"input": "预算减半，控制在150以内", "check": "budget_halved"},
    ],
    "category": "交互迭代",
    "difficulty": "hard",
    "description": "3轮修改，测试方案修复而非重生成能力",
}


# ══════════════════════════════════════════════════════════════
# 评测执行引擎
# ══════════════════════════════════════════════════════════════

class EvalRunner:
    def __init__(self, mode: str = "demo", verbose: bool = False):
        self.mode = mode
        self.verbose = verbose
        self.results = []

    def run_all(self) -> list[dict]:
        self.results = []
        for case in EVAL_CASES:
            result = self._run_case(case)
            self.results.append(result)
        return self.results

    def _run_case(self, case: EvalCase) -> dict:
        planner = create_planner(mode=self.mode, verbose=False)

        # 运行规划
        try:
            plan_text = planner.plan(case.user_input)
            tool_log = list(planner.tool_log)  # 深拷贝
        except Exception as e:
            plan_text = ""
            tool_log = []
            error_msg = str(e)
        else:
            error_msg = None

        # 运行检查
        checks = []
        for c in case.checks:
            passed, detail = self._run_check(c, plan_text, tool_log, case)
            checks.append({"name": c["name"], "passed": passed, "detail": detail})

        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)

        return {
            "id": case.id,
            "name": case.name,
            "difficulty": case.difficulty,
            "category": case.category,
            "description": case.description,
            "plan_text": plan_text[:500],
            "tool_calls": [t["tool"] for t in tool_log],
            "checks": checks,
            "score": f"{passed_count}/{total}",
            "passed": passed_count,
            "total": total,
            "error": error_msg,
        }

    def _run_check(self, check: dict, plan_text: str, tool_log: list[dict], case: EvalCase) -> tuple[bool, str]:
        check_type = check.get("type", "")
        target = check.get("target", "")

        try:
            if check_type == "budget_limit":
                return self._check_budget(plan_text, target)
            elif check_type == "poi_match":
                return self._check_poi(plan_text, tool_log, target)
            elif check_type == "restaurant_match":
                return self._check_restaurant(plan_text, tool_log, target)
            elif check_type == "diet_match":
                return self._check_diet(plan_text, tool_log, target)
            elif check_type == "family_match":
                return self._check_family(plan_text, tool_log, target)
            elif check_type == "distance_limit":
                return self._check_distance(tool_log, target)
            elif check_type == "timeline_reasonable":
                return self._check_timeline(plan_text, target)
            elif check_type == "delivery_match":
                return self._check_delivery(plan_text, tool_log, target)
            elif check_type == "multi_constraint":
                return self._check_multi(plan_text, tool_log, target)
            else:
                return True, "跳过（未知检查类型）"
        except Exception as e:
            return False, f"检查异常: {e}"

    def _check_budget(self, plan_text: str, target_budget: str) -> tuple[bool, str]:
        """检查预算是否在限制内"""
        import re
        limit = int(target_budget)
        # 提取方案中的总费用数字
        nums = re.findall(r'(\d+)\s*元', plan_text)
        for n in nums:
            if int(n) <= limit:
                return True, f"✓ 预估值{int(n)}元 ≤ {limit}元"
        if nums:
            return False, f"✗ 预估值{int(nums[0])}元 > {limit}元"
        return False, "✗ 未找到预算估算"

    def _check_poi(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查POI推荐"""
        # 检查是否有 search_poi 调用
        has_poi_call = any("search_poi" in t["tool"] for t in tool_log)
        if not has_poi_call and not target:
            return False, "✗ 未调用search_poi"

        # 如果有target，检查是否匹配
        if target:
            import re
            if target.startswith("!"):
                # 排除型：不应出现某些关键词
                exclude_keywords = target[1:].split("|")
                for kw in exclude_keywords:
                    if kw in plan_text:
                        return False, f"✗ 不应出现'{kw}'但出现了"
                return True, f"✓ 未出现排除关键词"
            else:
                # 包含型：应出现某些关键词
                keywords = target.split("|")
                for kw in keywords:
                    if re.search(kw, plan_text):
                        return True, f"✓ 匹配关键词'{kw}'"
                return False, f"✗ 未匹配任何关键词: {target}"

        return True, "✓ 有POI搜索"

    def _check_restaurant(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查餐厅推荐"""
        has_rest_call = any("search_restaurant" in t["tool"] for t in tool_log)
        if not has_rest_call and not target:
            return False, "✗ 未调用search_restaurant"

        if target:
            import re
            if target.startswith("!"):
                exclude_kw = target[1:].split("|")
                for kw in exclude_kw:
                    if kw in plan_text:
                        return False, f"✗ 不应出现'{kw}'但出现了"
                return True, f"✓ 未出现排除关键词"
            else:
                keywords = target.split("|")
                for kw in keywords:
                    if re.search(kw, plan_text):
                        return True, f"✓ 餐厅匹配'{kw}'"
                return False, f"✗ 餐厅未匹配: {target}"

        return True, "✓ 有餐厅搜索"

    def _check_diet(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查饮食约束是否满足"""
        keywords = target.split("|")
        # 检查plan文本
        for kw in keywords:
            if kw in plan_text:
                return True, f"✓ 饮食匹配'{kw}'"
        # 检查tool调用参数
        for t in tool_log:
            if "search_restaurant" in t["tool"]:
                args = t.get("args", {})
                tags = args.get("tags", [])
                for kw in keywords:
                    if any(kw in tag for tag in tags):
                        return True, f"✓ 餐厅搜索标签含'{kw}'"
        return False, f"✗ 饮食约束未满足: {target}"

    def _check_family(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查亲子友好度"""
        # 检查POI搜索参数
        for t in tool_log:
            if "search_poi" in t["tool"]:
                args = t.get("args", {})
                if args.get("suitable_for") in ("亲子", "儿童"):
                    return True, "✓ POI搜索指定了suitable_for=亲子"
        # 检查plan文本
        for kw in ["亲子", "儿童", "孩子", "家庭"]:
            if kw in plan_text:
                return True, f"✓ 方案提及'{kw}'"
        return False, "✗ 未体现亲子考虑"

    def _check_distance(self, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查距离限制"""
        limit = float(target)
        # 检查tool调用中的distance_limit参数
        for t in tool_log:
            args = t.get("args", {})
            dl = args.get("distance_limit", 999)
            if isinstance(dl, (int, float)) and dl <= limit:
                return True, f"✓ distance_limit={dl} ≤ {limit}km"
        return False, f"✗ 未设置distance_limit ≤ {limit}km"

    def _check_timeline(self, plan_text: str, target: str) -> tuple[bool, str]:
        """检查时间线合理性"""
        import re
        # 提取时间点
        times = re.findall(r'(\d{1,2}):(\d{2})', plan_text)
        if not times:
            return False, "✗ 方案中无时间点"

        if target.isdigit() or "." in target:
            # 检查总时长
            limit_hours = float(target)
            if times:
                try:
                    first_time = int(times[0][0]) * 60 + int(times[0][1])
                    last_time = int(times[-1][0]) * 60 + int(times[-1][1])
                    duration = (last_time - first_time) / 60
                    if duration <= limit_hours + 0.5:  # 允许0.5h缓冲
                        return True, f"✓ 总时长约{duration:.1f}h ≤ {limit_hours}h"
                    return False, f"✗ 总时长约{duration:.1f}h > {limit_hours}h"
                except:
                    pass
        else:
            # 检查截止时间
            target_time = target  # e.g. "15:30"
            try:
                target_minutes = int(target_time.split(":")[0]) * 60 + int(target_time.split(":")[1])
                for h, m in times:
                    t_minutes = int(h) * 60 + int(m)
                    if t_minutes <= target_minutes:
                        return True, f"✓ 结束时间{h}:{m} ≤ {target_time}"
                return False, f"✗ 结束时间晚于{target_time}"
            except:
                pass

        return True, "✓ 有时间线"

    def _check_delivery(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """检查配送/商品搜索"""
        has_delivery_call = any("delivery" in t["tool"] for t in tool_log)
        if target in plan_text:
            return True, f"✓ 方案提及'{target}'"
        if has_delivery_call:
            return True, f"✓ 调用了配送相关工具"
        return False, f"✗ 未涉及'{target}'配送"

    def _check_multi(self, plan_text: str, tool_log: list[dict], target: str) -> tuple[bool, str]:
        """通用检查，支持 | 分隔的多个关键词"""
        import re
        if target:
            keywords = target.split("|")
            for kw in keywords:
                if re.search(kw, plan_text):
                    return True, f"✓ 方案提及'{kw}'"
                if any(kw in t["tool"] for t in tool_log):
                    return True, f"✓ 调用了'{kw}'工具"
            return False, f"✗ 未满足: {target}"
        return True, "✓ 通过"

    def report(self) -> str:
        """生成评测报告"""
        if not self.results:
            return "无评测结果"

        lines = []
        lines.append("")
        lines.append("=" * 64)
        lines.append("  Hard Case 评测报告")
        lines.append("=" * 64)
        lines.append(f"  运行模式: {self.mode}")
        lines.append(f"  用例总数: {len(self.results)}")
        lines.append("")

        total_passed = sum(r["passed"] for r in self.results)
        total_checks = sum(r["total"] for r in self.results)

        # 按难度分组统计
        by_difficulty = {}
        for r in self.results:
            d = r["difficulty"]
            if d not in by_difficulty:
                by_difficulty[d] = {"passed": 0, "total": 0}
            by_difficulty[d]["passed"] += r["passed"]
            by_difficulty[d]["total"] += r["total"]

        lines.append("  整体得分: {}/{} ({:.0f}%)".format(
            total_passed, total_checks,
            total_passed / total_checks * 100 if total_checks else 0))
        lines.append("")
        for d in ["basic", "medium", "hard"]:
            if d in by_difficulty:
                stats = by_difficulty[d]
                pct = stats["passed"] / stats["total"] * 100 if stats["total"] else 0
                bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                lines.append(f"  {d:8s} [{bar}] {stats['passed']}/{stats['total']} ({pct:.0f}%)")
        lines.append("")

        # 逐用例详情
        for r in self.results:
            status = "✓" if r["passed"] == r["total"] else ("⚠" if r["passed"] > 0 else "✗")
            lines.append(f"  [{status}] {r['id']} {r['name']} [{r['difficulty']}] 得分:{r['score']}")
            if r["error"]:
                lines.append(f"        ❌ 执行错误: {r['error']}")
            for c in r["checks"]:
                mark = "✓" if c["passed"] else "✗"
                lines.append(f"        {mark} {c['name']}: {c['detail']}")
            # 显示调用了哪些tool
            if r["tool_calls"]:
                lines.append(f"        🔧 调用工具: {', '.join(r['tool_calls'])}")
            lines.append("")

        lines.append("=" * 64)
        lines.append("  数据层缺口（mock_data.py 缺失字段）：")
        lines.append("  - POI 无 is_open 字段 → 无法模拟'今天不营业'降级")
        lines.append("  - 餐厅无 has_window_seat / 素食标记 → C05 只能靠标签近似")
        lines.append("  - 无 天气数据 来源 → 雨天应急case无法评测")
        lines.append("=" * 64)

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hard Case 评测套件")
    parser.add_argument("--mode", choices=["demo", "deepseek", "claude", "openai"], default="demo",
                        help="运行模式（默认demo，即规则引擎基线）")
    parser.add_argument("--case", type=str, help="仅运行指定case，如 C01")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    runner = EvalRunner(mode=args.mode, verbose=args.verbose)

    if args.case:
        # 单用例
        case = next((c for c in EVAL_CASES if c.id == args.case), None)
        if not case:
            print(f"未找到用例: {args.case}")
            sys.exit(1)
        runner.results = [runner._run_case(case)]
    else:
        runner.run_all()

    print(runner.report())

    # 输出 JSON 供 CI/脚本解析
    if not args.case:
        json_path = "/tmp/eval_results.json"
        with open(json_path, "w") as f:
            json.dump(runner.results, f, ensure_ascii=False, indent=2)
        print(f"\n  JSON 结果已保存: {json_path}")


if __name__ == "__main__":
    main()
