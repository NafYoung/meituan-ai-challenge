#!/usr/bin/env python3
"""
美团AI挑战赛 · 赛道6 · 短时活动规划 Agent
CLI 交互入口

用法:
  python main.py                # Demo 模式（不需要 API key）
  python main.py --mode deepseek  # 使用 DeepSeek API（需要 DEEPSEEK_API_KEY）
  python main.py --mode claude    # 使用 Claude API
  python main.py --mode openai    # 使用 OpenAI API
"""

import sys
import json
import os
import argparse
import readline  # 修复 macOS 退格键/方向键问题
from planner import create_planner
from tools import call_tool

# 自动加载项目 .env
_ENV = os.path.dirname(os.path.abspath(__file__)) + "/.env"
if os.path.exists(_ENV):
    for _line in open(_ENV):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


# ── 颜色工具 ──────────────────────────────────────────────────

class C:
    """终端颜色"""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    WHITE = "\033[97m"


def banner():
    print(f"""
{C.CYAN}{C.BOLD}
  ╔══════════════════════════════════════════════════════════╗
  ║                                                          ║
  ║    美团 AI 挑战赛 · 赛道6                                ║
  ║    短时活动规划 Agent                                     ║
  ║                                                          ║
  ║    输入一句话，帮你把下午安排得明明白白                     ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
{C.RESET}""")


def show_examples():
    print(f"""
{C.DIM}  示例输入：{C.RESET}
{C.YELLOW}
  • 今天下午带老婆孩子出去玩，老婆在减肥
  • 和4个朋友下午聚一下，想找点有意思的
  • 周末想和女朋友约会，要有惊喜
  • 孩子5岁，想找个能玩一下午的地方
{C.RESET}
{C.DIM}  输入 {C.WHITE}quit{C.DIM} 退出，输入 {C.WHITE}help{C.DIM} 查看帮助{C.RESET}
""")


def show_help():
    print(f"""
{C.CYAN}  帮助：{C.RESET}
  {C.WHITE}直接输入{C.RESET}  用自然语言描述你的需求
  {C.WHITE}quit{C.RESET}       退出程序
  {C.WHITE}help{C.RESET}       显示帮助
  {C.WHITE}examples{C.RESET}   显示示例输入
  {C.WHITE}orders{C.RESET}     查看已生成的订单
  {C.WHITE}share{C.RESET}      生成可转发的分享消息
  {C.WHITE}tools{C.RESET}      查看可用工具列表
""")


def show_tools():
    from tools import TOOL_SCHEMAS
    print(f"\n{C.CYAN}  可用工具：{C.RESET}")
    for t in TOOL_SCHEMAS:
        params = ", ".join(t["parameters"].get("properties", {}).keys())
        print(f"  {C.YELLOW}{t['name']}{C.RESET}({params})")
        print(f"    {C.DIM}{t['description']}{C.RESET}")
    print()


def show_orders():
    from mock_data import list_orders
    orders = list_orders()
    if not orders:
        print(f"\n{C.DIM}  暂无订单{C.RESET}\n")
        return
    print(f"\n{C.CYAN}  已生成的订单：{C.RESET}")
    for o in orders:
        print(f"  {C.GREEN}✓{C.RESET} [{o.get('type', '?')}] {json.dumps({k: v for k, v in o.items() if k not in ('created_at',)}, ensure_ascii=False)[:100]}")
    print()


def parse_execute_actions(plan_text: str, tool_log: list[dict]) -> list[dict]:
    """从工具调用日志中提取可执行的动作"""
    actions = []
    for log in tool_log:
        tool = log["tool"]
        if tool in ("reserve_table", "buy_ticket", "order_delivery"):
            actions.append({"tool": tool, "args": log["args"]})
    return actions


def interactive_confirm(planner, plan_text: str, tool_log: list[dict]) -> bool:
    """交互式确认方案"""
    print(f"\n{C.CYAN}{'─'*50}{C.RESET}")
    print(f"{C.BOLD}  方案确认{C.RESET}")
    print(f"{C.CYAN}{'─'*50}{C.RESET}")

    while True:
        print(f"\n  {C.WHITE}确认执行？{C.RESET}")
        print(f"    {C.GREEN}y{C.RESET}  — 确认，一键执行所有下单")
        print(f"    {C.YELLOW}n{C.RESET}  — 不执行，返回")
        print(f"    {C.BLUE}m{C.RESET}  — 修改需求，重新规划")

        choice = input(f"\n  {C.BOLD}>{C.RESET} ").strip().lower()

        if choice == "y":
            actions = planner.get_executable_actions()

            if actions:
                print(f"\n{C.GREEN}  ⚡ 正在执行 {len(actions)} 个下单操作...{C.RESET}\n")
                results = planner.execute(actions)

                print(f"\n{C.GREEN}{C.BOLD}  ═══ 执行结果 ═══{C.RESET}")
                for r in results:
                    res = r["result"]
                    if "error" not in res:
                        status = res.get("status", "成功")
                        oid = res.get("order_id", "?")
                        name = res.get("venue") or res.get("restaurant") or res.get("item", "?")
                        print(f"  {C.GREEN}✓{C.RESET} {name} — {status} (订单号: {oid})")
                    else:
                        print(f"  {C.RED}✗{C.RESET} {r['tool']} — {res['error']}")
                print()
            else:
                print(f"\n{C.DIM}  无需执行的操作{C.RESET}\n")

            return True

        elif choice == "n":
            print(f"\n{C.DIM}  已取消{C.RESET}\n")
            return False

        elif choice == "m":
            return False

        else:
            print(f"  {C.DIM}请输入 y/n/m{C.RESET}")


# ── 主循环 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="美团AI挑战赛 · 赛道6 · 短时活动规划 Agent")
    parser.add_argument("--mode", choices=["demo", "claude", "openai", "deepseek"], default="demo",
                        help="运行模式: demo(默认) | deepseek | claude | openai")
    parser.add_argument("--quiet", action="store_true", help="静默模式，不显示工具调用过程")
    args = parser.parse_args()

    banner()
    print(f"  {C.DIM}当前模式: {C.WHITE}{args.mode}{C.RESET}")
    show_examples()

    planner = create_planner(mode=args.mode, verbose=not args.quiet)

    while True:
        try:
            user_input = input(f"{C.BOLD}{C.CYAN}  你>{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{C.DIM}  再见！{C.RESET}\n")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd == "quit" or cmd == "exit":
            print(f"\n{C.DIM}  再见！{C.RESET}\n")
            break
        elif cmd == "help":
            show_help()
            continue
        elif cmd == "examples":
            show_examples()
            continue
        elif cmd == "orders":
            show_orders()
            continue
        elif cmd == "tools":
            show_tools()
            continue
        elif cmd == "share":
            msg = planner.share()
            print(f"\n{C.MAGENTA}  📤 分享消息：{C.RESET}")
            print(f"  {msg}\n")
            continue

        # ── 规划 ──
        try:
            plan_text = planner.plan(user_input)
        except Exception as e:
            print(f"\n{C.RED}  规划出错: {e}{C.RESET}\n")
            continue

        # ── 展示方案 ──
        print(f"\n{C.GREEN}{C.BOLD}  ════════════════════════════════════════{C.RESET}")
        print(f"{C.GREEN}{C.BOLD}  为您规划的方案{C.RESET}")
        print(f"{C.GREEN}{C.BOLD}  ════════════════════════════════════════{C.RESET}\n")

        for line in plan_text.split("\n"):
            print(f"  {line}")

        # ── 确认执行 ──
        interactive_confirm(planner, plan_text, planner.tool_log)

        print(f"{C.DIM}{'─'*50}{C.RESET}")


if __name__ == "__main__":
    main()
