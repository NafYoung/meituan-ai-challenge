"""美团AI挑战赛 · 赛道6 · Web UI"""

import streamlit as st
import os

# 加载 .env
_ENV = os.path.dirname(os.path.abspath(__file__)) + "/.env"
if os.path.exists(_ENV):
    for _line in open(_ENV):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from planner import create_planner

st.set_page_config(page_title="美团AI · 短时活动规划", page_icon="", layout="centered")

# ── 样式 ──
st.markdown("""
<style>
    .stApp { background: #0f0f14; }
    .stChatMessage { background: transparent !important; }
    section[data-testid="stSidebar"] { background: #0a0a0f; }
    .stChatInput textarea { background: #1a1a26 !important; border: 1px solid #2a2a3a !important; }
    div[data-testid="stVerticalBlock"] > div:has(.stChatInput) { position: sticky; bottom: 0; background: #0f0f14; padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# ── session 初始化 ──
if "msgs" not in st.session_state:
    st.session_state.msgs = []  # [{role, content, meta}]
if "mode" not in st.session_state:
    st.session_state.mode = "demo"

# ── 侧边栏 ──
with st.sidebar:
    st.title(" 美团AI")
    st.caption("赛道6 · 短时活动规划 Agent")
    st.divider()

    prev_mode = st.session_state.mode
    st.session_state.mode = st.selectbox(
        "运行模式", ["demo", "deepseek"],
        index=0 if prev_mode == "demo" else 1,
        help="Demo=规则引擎(秒回) | DeepSeek=LLM推理(需Key)"
    )
    st.caption("Demo模式无需API Key，LLM模式需配置.env")

    st.divider()
    st.caption("快捷输入：")
    examples = [
        "下午带老婆孩子出去玩，孩子5岁，老婆在减肥",
        "4个朋友团建，2男2女，预算人均150",
        "周末约会，要有鲜花和蛋糕，她最近吃素",
        "只有2个半小时，想吃饭+逛展，别太远",
    ]
    for ex in examples:
        if st.button(ex, key=f"btn_{hash(ex) % 10000}"):
            st.session_state.pending = ex
            st.rerun()

    # 执行记录（从 orders.json 读取）
    st.divider()
    st.caption("📋 执行记录")
    try:
        from mock_data import list_orders
        all_orders = list_orders()
        if all_orders:
            for o in all_orders[:10]:
                otype = o.get("type", "?")
                if otype == "ticket":
                    label = f"🎫 {o.get('venue','?')}"
                elif otype == "restaurant_reservation":
                    label = f"🍽️ {o.get('restaurant','?')}"
                elif otype == "delivery":
                    label = f"📦 {o.get('item','?')}"
                else:
                    label = f"📌 {o.get('order_id','?')}"
                st.caption(f"{label} — {o.get('created_at','')[:16]}")
        else:
            st.caption("暂无记录 · 执行下单后自动保存")
    except Exception:
        st.caption("暂无记录")

# ── 主区域标题 ──
st.markdown("<h2 style='text-align:center;color:#00e676'>短时活动规划 Agent</h2>", unsafe_allow_html=True)
st.caption("从一句话到可执行方案 — 输入自然语言，帮你把下午安排明白")

# ── 消息历史（上到下） ──
for i, msg in enumerate(st.session_state.msgs):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["content"])
        elif msg["role"] == "assistant":
            st.markdown(msg["content"])
        if msg.get("meta"):
            st.caption(msg["meta"])

# ── 输入框（底部） ──
user_input = st.chat_input("用自然语言描述你下午想怎么过，例如：下午带老婆孩子出去玩……")

# 快捷输入按钮触发
if st.session_state.get("pending"):
    user_input = st.session_state.pop("pending")

if user_input:
    st.session_state.msgs.append({"role": "user", "content": user_input, "meta": ""})

    # 复用 or 新建 planner
    planner = st.session_state.get("planner")
    if planner is None or st.session_state.get("_last_mode") != st.session_state.mode:
        planner = create_planner(mode=st.session_state.mode, verbose=False)
        st.session_state.planner = planner
        st.session_state._last_mode = st.session_state.mode
        st.session_state._turn = 0
    st.session_state._turn += 1

    is_first_turn = (st.session_state._turn == 1)

    with st.spinner(f"正在规划（{st.session_state.mode}模式）……"):
        try:
            if is_first_turn:
                plan_text = planner.plan(user_input)
            else:
                plan_text = planner.chat(user_input)
            tool_calls = [t["tool"] for t in planner.tool_log]
            share_msg = planner.share()
        except Exception as e:
            plan_text = f"❌ 规划出错: {e}"
            tool_calls = []
            share_msg = ""

    # 拼接输出内容
    out = plan_text
    out += f"\n\n---\n\n📤 **分享消息**\n\n> {share_msg}"
    out += f"\n\n⚡ *模式:{st.session_state.mode} · 第{st.session_state._turn}轮 · 调用{len(tool_calls)}个工具 · {', '.join(tool_calls[:5])}*"

    st.session_state.msgs.append({"role": "assistant", "content": out, "meta": ""})
    st.session_state.last_planner = planner
    st.rerun()

# ── 确认执行（最后一条消息是 assistant 时显示） ──
if st.session_state.msgs and st.session_state.msgs[-1]["role"] == "assistant":
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ 一键执行所有下单", use_container_width=True, type="primary"):
            planner = st.session_state.get("last_planner")
            if planner:
                actions = planner.get_executable_actions()
                if actions:
                    results = planner.execute(actions)
                    for r in results:
                        res = r.get("result", {})
                        if "error" not in res:
                            name = res.get("venue") or res.get("restaurant") or res.get("item", "")
                            st.success(f"✅ {name} — {res.get('status', '成功')} ({res.get('order_id', '?')})")
                        else:
                            st.error(f"❌ {r['tool']} — {res['error']}")
                else:
                    st.info("无需执行操作")
    with c2:
        if st.button("🔄 清空对话", use_container_width=True):
            st.session_state.msgs = []
            st.session_state.planner = None
            st.session_state._turn = 0
            st.rerun()

st.caption("美团AI挑战赛 2026 · 赛道6 · 所有下单均为模拟")
