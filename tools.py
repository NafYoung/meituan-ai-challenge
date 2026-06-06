"""Tool 层 — 10 个核心 Tool 的实现，每个 Tool 模拟真实 API 调用"""

from mock_data import (
    POIS, RESTAURANTS, EVENTS, DELIVERY_ITEMS, COUPONS,
    generate_order_id, save_order,
)


# ══════════════════════════════════════════════════════════════
# 查询类 Tool
# ══════════════════════════════════════════════════════════════

def search_poi(category: str = "", distance_limit: float = 10.0,
               suitable_for: str = "") -> list[dict]:
    """搜索周边 POI（景点、乐园、公园等）"""
    results = []
    for poi in POIS:
        if poi["distance_km"] > distance_limit:
            continue
        if category and category not in poi["category"] and category not in " ".join(poi["tags"]):
            continue
        if suitable_for and suitable_for not in " ".join(poi["suitable_for"]):
            continue
        results.append({
            "id": poi["id"],
            "name": poi["name"],
            "category": poi["category"],
            "rating": poi["rating"],
            "distance_km": poi["distance_km"],
            "price_range": poi["price_range"],
            "avg_duration_hours": poi["avg_duration_hours"],
            "tags": poi["tags"],
            "min_age": poi.get("min_age", 0),
            "max_age": poi.get("max_age", 99),
        })
    results.sort(key=lambda x: x["rating"], reverse=True)
    return results


def get_poi_detail(poi_id: str) -> dict | None:
    """获取 POI 详情"""
    for poi in POIS:
        if poi["id"] == poi_id:
            return poi
    return None


def search_restaurant(tags: list[str] = None, location: str = "",
                      party_size: int = 2, distance_limit: float = 10.0) -> list[dict]:
    """搜索餐厅，支持标签筛选（低卡、亲子、烧烤等）"""
    results = []
    for rest in RESTAURANTS:
        if rest["distance_km"] > distance_limit:
            continue
        if tags:
            tag_str = " ".join(rest["tags"])
            if not any(t in tag_str for t in tags):
                continue
        results.append({
            "id": rest["id"],
            "name": rest["name"],
            "cuisine": rest["cuisine"],
            "rating": rest["rating"],
            "distance_km": rest["distance_km"],
            "avg_price": rest["avg_price"],
            "tags": rest["tags"],
            "current_wait": rest["current_wait"],
            "wait_minutes": rest["wait_minutes"],
        })
    results.sort(key=lambda x: x["rating"], reverse=True)
    return results


def check_waitlist(restaurant_id: str) -> dict | None:
    """查询餐厅实时排队情况"""
    for rest in RESTAURANTS:
        if rest["id"] == restaurant_id:
            return {
                "id": rest["id"],
                "name": rest["name"],
                "current_wait_groups": rest["current_wait"],
                "estimated_wait_minutes": rest["wait_minutes"],
                "capacity": rest["capacity"],
                "status": "可排号" if rest["current_wait"] < 10 else "较拥挤",
            }
    return None


def check_event(location: str = "", date: str = "2026-05-17") -> list[dict]:
    """查询当天活动（展览、市集、演出等）"""
    results = []
    for evt in EVENTS:
        if date not in evt["date"]:
            continue
        results.append({
            "id": evt["id"],
            "name": evt["name"],
            "location": evt["location"],
            "time": evt["time"],
            "price": evt["price"],
            "description": evt["description"],
            "suitable_for": evt["suitable_for"],
        })
    return results


def search_delivery(category: str = "", tags: list[str] = None) -> list[dict]:
    """搜索可配送商品（蛋糕、鲜花、饮品等）"""
    results = []
    for item in DELIVERY_ITEMS:
        if category and category not in item["category"]:
            continue
        if tags:
            item_tags = " ".join(item["tags"])
            if not any(t in item_tags for t in tags):
                continue
        results.append(item)
    return results


def search_coupon(scope_type: str = "", scope_id: str = "", min_party: int = 0) -> list[dict]:
    """搜索团购/优惠券（美团团购、满减券、折扣券、秒杀券）"""
    results = []
    for cp in COUPONS:
        if scope_type and cp["scope_type"] != scope_type:
            continue
        if scope_id and cp["scope_id"] != scope_id:
            continue
        if min_party and cp["min_party"] > min_party:
            continue
        results.append({
            "id": cp["id"],
            "type": cp["type"],
            "scope_type": cp["scope_type"],
            "scope_id": cp["scope_id"],
            "name": cp["name"],
            "original_price": cp["original_price"],
            "price": cp["price"],
            "description": cp["description"],
            "min_party": cp["min_party"],
            "saving": cp["saving"],
        })
    return results


def get_coupons_for_target(scope_type: str, scope_id: str, party_size: int = 0) -> list[dict]:
    """获取特定POI/餐厅的可用优惠券"""
    return [c for c in COUPONS
            if c["scope_type"] == scope_type and c["scope_id"] == scope_id
            and c["min_party"] <= party_size]


# ══════════════════════════════════════════════════════════════
# 执行类 Tool
# ══════════════════════════════════════════════════════════════

def reserve_table(restaurant_id: str, time: str, party_size: int) -> dict:
    """餐厅预订/排号"""
    for rest in RESTAURANTS:
        if rest["id"] == restaurant_id:
            order_id = generate_order_id("RST")
            save_order(order_id, {
                "type": "restaurant_reservation",
                "restaurant": rest["name"],
                "time": time,
                "party_size": party_size,
            })
            return {
                "order_id": order_id,
                "restaurant": rest["name"],
                "time": time,
                "party_size": party_size,
                "status": "预订成功",
                "queue_number": f"A{rest['current_wait'] + 1}",
            }
    return {"error": "餐厅不存在"}


def buy_ticket(venue_id: str, quantity: int) -> dict:
    """购买门票"""
    for poi in POIS:
        if poi["id"] == venue_id:
            order_id = generate_order_id("TKT")
            price_str = poi["price_range"]
            # 简化价格提取
            try:
                if "免费" in price_str:
                    unit_price = 0
                elif "-" in price_str:
                    unit_price = int(price_str.split("-")[0].replace("元/人", "").replace("元", ""))
                else:
                    unit_price = int(price_str.replace("元/人", "").replace("元", ""))
            except ValueError:
                unit_price = 50  # 默认价

            total = unit_price * quantity
            save_order(order_id, {
                "type": "ticket",
                "venue": poi["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "total": total,
            })
            return {
                "order_id": order_id,
                "venue": poi["name"],
                "quantity": quantity,
                "total_price": f"{total}元" if total > 0 else "免费",
                "status": "购票成功",
                "qr_code": f"https://mock.qr/{order_id}",
            }
    return {"error": "场馆不存在"}


def order_delivery(item_id: str, address: str, delivery_time: str = "尽快") -> dict:
    """下单配送"""
    for item in DELIVERY_ITEMS:
        if item["id"] == item_id:
            order_id = generate_order_id("DLV")
            save_order(order_id, {
                "type": "delivery",
                "item": item["name"],
                "shop": item["shop"],
                "address": address,
                "delivery_time": delivery_time,
                "price": item["price"],
                "delivery_fee": item["delivery_fee"],
            })
            return {
                "order_id": order_id,
                "item": item["name"],
                "shop": item["shop"],
                "price": f"{item['price']}元",
                "delivery_fee": f"{item['delivery_fee']}元",
                "estimated_delivery": f"约{item['eta_minutes']}分钟",
                "status": "下单成功",
            }
    return {"error": "商品不存在"}


# ══════════════════════════════════════════════════════════════
# Tool Schema（供 LLM 使用）
# ══════════════════════════════════════════════════════════════

TOOL_SCHEMAS = [
    {
        "name": "search_coupon",
        "description": "搜索团购、优惠券、满减券、折扣券等美团优惠。按scope_type筛选（restaurant/poi），可按scope_id指定目标",
        "parameters": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "优惠目标类型: restaurant 或 poi"},
                "scope_id": {"type": "string", "description": "目标ID，如rest_001、poi_006"},
                "min_party": {"type": "number", "description": "最小适用人数"},
            },
        },
    },

    {
        "name": "search_poi",
        "description": "搜索周边景点、乐园、公园等 POI。返回评分排序的结果列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "分类关键词，如：亲子乐园、公园、展览、运动"},
                "distance_limit": {"type": "number", "description": "最大距离(km)，默认10"},
                "suitable_for": {"type": "string", "description": "适合人群，如：亲子、朋友、情侣"},
            },
        },
    },
    {
        "name": "get_poi_detail",
        "description": "获取某个 POI 的详细信息（地址、营业时间、适合人群等）",
        "parameters": {
            "type": "object",
            "properties": {
                "poi_id": {"type": "string", "description": "POI ID"},
            },
            "required": ["poi_id"],
        },
    },
    {
        "name": "search_restaurant",
        "description": "搜索餐厅，支持标签筛选（低卡、亲子、烧烤等）",
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}, "description": "筛选标签，如：['低卡','健康']"},
                "party_size": {"type": "number", "description": "用餐人数"},
                "distance_limit": {"type": "number", "description": "最大距离(km)"},
            },
        },
    },
    {
        "name": "check_waitlist",
        "description": "查询餐厅实时排队情况",
        "parameters": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "string", "description": "餐厅 ID"},
            },
            "required": ["restaurant_id"],
        },
    },
    {
        "name": "check_event",
        "description": "查询当天/近期活动（展览、市集、演出等）",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "reserve_table",
        "description": "预订餐厅或排号",
        "parameters": {
            "type": "object",
            "properties": {
                "restaurant_id": {"type": "string", "description": "餐厅 ID"},
                "time": {"type": "string", "description": "用餐时间，如 17:00"},
                "party_size": {"type": "number", "description": "用餐人数"},
            },
            "required": ["restaurant_id", "time", "party_size"],
        },
    },
    {
        "name": "buy_ticket",
        "description": "购买景点/活动门票",
        "parameters": {
            "type": "object",
            "properties": {
                "venue_id": {"type": "string", "description": "场馆/景点 ID"},
                "quantity": {"type": "number", "description": "购票数量"},
            },
            "required": ["venue_id", "quantity"],
        },
    },
    {
        "name": "search_delivery",
        "description": "搜索可配送商品（蛋糕、鲜花、饮品等）",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "商品分类，如：蛋糕、鲜花、饮品"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "筛选标签，如：['低糖','生日']"},
            },
        },
    },
    {
        "name": "order_delivery",
        "description": "下单配送商品（蛋糕、鲜花、饮品等）",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "商品 ID"},
                "address": {"type": "string", "description": "配送地址"},
                "delivery_time": {"type": "string", "description": "期望送达时间"},
            },
            "required": ["item_id", "address"],
        },
    },
]

# Tool 函数映射
TOOL_FUNCTIONS = {
    "search_coupon": search_coupon,
    "search_poi": search_poi,
    "get_poi_detail": get_poi_detail,
    "search_restaurant": search_restaurant,
    "check_waitlist": check_waitlist,
    "check_event": check_event,
    "reserve_table": reserve_table,
    "buy_ticket": buy_ticket,
    "order_delivery": order_delivery,
    "search_delivery": search_delivery,
}


def call_tool(name: str, args: dict) -> any:
    """统一调用入口"""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return {"error": f"未知工具: {name}"}
    try:
        return func(**args)
    except Exception as e:
        return {"error": str(e)}
