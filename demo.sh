#!/usr/bin/env bash
# 演示脚本 — 一条命令展示完整流程
cd "$(dirname "$0")"

echo "========================================"
echo "  美团AI挑战赛 · 赛道6 · 演示"
echo "========================================"
echo ""

# 1. Demo模式
echo ">>> 1. Demo 模式：官方家庭场景"
python3 -c "
from planner import DemoPlanner
p = DemoPlanner(verbose=False)
print(p.plan('今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，孩子5岁，老婆最近在减肥'))
print()
print('【分享消息】')
print(p.share())
"
echo ""
echo "---"

# 2. 评测报告
echo ">>> 2. Hard Case 评测报告"
python3 eval.py 2>&1 | head -30
echo ""

# 3. DeepSeek对比（如果有key）
if [ -n "$DEEPSEEK_API_KEY" ] || grep -q "sk-" .env 2>/dev/null; then
    echo ">>> 3. Demo vs DeepSeek 对比（C03）"
    python3 compare.py --case C03 2>&1 | head -50
else
    echo ">>> 3. DeepSeek对比：跳过（需配置.env中的API Key）"
fi

echo ""
echo "========================================"
echo "  演示完毕"
echo "========================================"
