#!/usr/bin/env python3
"""Demo vs DeepSeek 对比评测 — 同样的输入，两种模式，差异一目了然"""

import sys, json, os, time
from planner import create_planner
from eval import EVAL_CASES

# 自动加载项目 .env
_ENV = os.path.dirname(os.path.abspath(__file__)) + "/.env"
if os.path.exists(_ENV):
    for _line in open(_ENV):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

COMPARE_CASES = ["C02", "C03", "C05", "C07", "C10"]  # 最有区分度的5个case


def run_one(case_id: str, mode: str) -> dict:
    case = next(c for c in EVAL_CASES if c.id == case_id)
    planner = create_planner(mode=mode, verbose=False)
    t0 = time.time()
    try:
        plan = planner.plan(case.user_input)
        ok = True
        err = None
    except Exception as e:
        plan = ""
        ok = False
        err = str(e)
    elapsed = time.time() - t0
    return {
        "case_id": case_id,
        "case_name": case.name,
        "mode": mode,
        "input": case.user_input,
        "plan": plan[:600],
        "tools": [t["tool"] for t in planner.tool_log],
        "tool_count": len(planner.tool_log),
        "ok": ok,
        "error": err,
        "elapsed": round(elapsed, 1),
    }


def run_comparison() -> list[dict]:
    results = []
    for case_id in COMPARE_CASES:
        # Demo
        r_demo = run_one(case_id, "demo")
        results.append(r_demo)
        # DeepSeek
        r_ds = run_one(case_id, "deepseek")
        results.append(r_ds)
    return results


def report(results: list[dict]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 64)
    lines.append("  Demo vs DeepSeek 对比评测")
    lines.append("=" * 64)
    lines.append("")

    # Group by case
    for case_id in COMPARE_CASES:
        pair = [r for r in results if r["case_id"] == case_id]
        if len(pair) < 2:
            continue
        demo = next(r for r in pair if r["mode"] == "demo")
        ds = next(r for r in pair if r["mode"] == "deepseek")

        case_name = demo["case_name"]
        lines.append(f"  {'─'*58}")
        lines.append(f"  📋 {case_id} {case_name}")
        lines.append(f"  {'─'*58}")
        lines.append(f"  输入: {demo['input']}")
        lines.append("")
        lines.append(f"  [Demo · 规则引擎]  {demo['elapsed']}s · {demo['tool_count']} tools")
        lines.append(f"  {'  ' + demo['plan'].strip()[:300]}")
        lines.append("")
        lines.append(f"  [DeepSeek · LLM]   {ds['elapsed']}s · {ds['tool_count']} tools")
        if ds["ok"]:
            lines.append(f"  {'  ' + ds['plan'].strip()[:300]}")
        else:
            lines.append(f"  ❌ 失败: {ds['error']}")
        lines.append("")

    lines.append("=" * 64)
    lines.append("  对比要点：")
    lines.append("  - Demo 速度快但约束推理靠关键词，复杂场景易漏")
    lines.append("  - DeepSeek 慢但能理解隐含语义（'赶飞机'→时间紧）")
    lines.append("  - 工具调用次数：DeepSeek 通常会调用更多轮")
    lines.append("  - LLM模式能处理 Demo 规则覆盖不到的边界")
    lines.append("=" * 64)

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Demo vs DeepSeek 对比评测")
    parser.add_argument("--case", type=str, help="仅对比指定case")
    args = parser.parse_args()

    global COMPARE_CASES
    if args.case:
        COMPARE_CASES = [args.case]

    print("\n  正在运行对比评测（需要 DeepSeek API）...\n")
    results = run_comparison()
    print(report(results))


if __name__ == "__main__":
    main()
