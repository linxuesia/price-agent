"""
门窗报价计算模块
定价规则从 pricing.json 读取，可随时增删
"""
import json
import os

_CFG = None


def _load_config():
    global _CFG
    if _CFG is not None:
        return _CFG
    cfg_path = os.path.join(os.path.dirname(__file__), "pricing.json")
    with open(cfg_path, "r") as f:
        _CFG = json.load(f)
    return _CFG


def match_profile(profile_str: str):
    """返回 (面积单价, 开启扇单价, 开启扇名称或None)"""
    if not profile_str:
        return None
    cfg = _load_config()
    for item in cfg["profile_pricing"]:
        for kw in item["keywords"]:
            if kw in profile_str:
                return (item["area_price"], item["sash_price"], item.get("sash_name"))
    return None


def match_thickening_price(spec: str) -> float | None:
    if not spec:
        return None
    s = spec.replace(" ", "").replace("mm", "")
    for p in ["加厚至", "加厚", "加厚到"]:
        if s.startswith(p):
            s = s[len(p):]
    if "+" in s:
        parts = s.split("+")
        s = f"{parts[0]}mm+{parts[1]}mm"

    cfg = _load_config()
    # 用于比较的无单位版本
    s_clean = s.replace("mm", "").replace(" ", "")
    for item in cfg["thickening_pricing"]:
        for alias in item["spec"]:
            a = alias.replace(" ", "").replace("mm", "")
            if a == s_clean or a in s_clean or s_clean in a:
                return item["price"]
    return None


def calculate(window_data: dict) -> dict:
    w = window_data.get("width", 0)
    h = window_data.get("height", 0)
    profile = window_data.get("profile", "")
    sashes = window_data.get("opening_sashes", 0)
    thickenings = window_data.get("thickening", [])
    screen_sashes = window_data.get("screen_sashes", 0) or 0
    screen_doors = window_data.get("screen_doors", 0) or 0
    smart_lock = window_data.get("smart_lock", False) or False

    for t in thickenings:
        area_val = t.get("area")
        if isinstance(area_val, str):
            area_val = area_val.replace("m²", "").replace("㎡", "").replace("m2", "").strip()
            t["area"] = float(area_val)

    area_sqm = (w * h) / 1_000_000
    pricing = match_profile(profile)
    if pricing is None:
        return {"area_sqm": round(area_sqm, 4), "error": f"未找到型材「{profile}」的定价"}

    area_price, sash_price, sash_name = pricing
    area_total = area_sqm * area_price
    sash_total = sashes * sash_price

    thickening_items = []
    thickening_total = 0
    for t in thickenings:
        t_area = t.get("area", 0)
        t_spec = t.get("spec", "")
        t_price = match_thickening_price(t_spec)
        if t_price and t_area > 0:
            cost = round(t_area * t_price, 2)
            thickening_items.append({"area": t_area, "spec": t_spec, "unit_price": t_price, "total": cost})
            thickening_total += cost

    # 配件计算
    cfg = _load_config()
    acc = cfg.get("accessory_pricing", {})
    accessories = []
    if screen_sashes > 0:
        price = acc.get("screen_sash", 0)
        accessories.append({"name": "纱窗", "count": screen_sashes, "unit_price": price, "total": screen_sashes * price})
    if screen_doors > 0:
        price = acc.get("screen_door", 0)
        accessories.append({"name": "纱门", "count": screen_doors, "unit_price": price, "total": screen_doors * price})
    if smart_lock:
        price = acc.get("smart_lock", 0)
        accessories.append({"name": "密码锁", "count": 1, "unit_price": price, "total": price})

    return {
        "area_sqm": round(area_sqm, 4),
        "unit_price": area_price,
        "sash_unit_price": sash_price,
        "sash_name": sash_name,
        "opening_sashes": sashes,
        "area_total": round(area_total, 2),
        "sash_total": round(sash_total, 2),
        "thickening_items": thickening_items,
        "thickening_total": round(thickening_total, 2),
        "accessories": accessories,
        "grand_total": round(area_total + sash_total + thickening_total + sum(a["total"] for a in accessories), 2),
    }


def generate_quotation(results: list[dict]) -> str:
    cfg = _load_config()
    lines = []
    lines.append("=" * 110)
    lines.append("  门窗销售明细表 (AI自动生成)")
    lines.append("=" * 110)
    hdr = f"{'编号':<5} {'安装位置':<14} {'型材系列':<24} {'颜色':<8} {'玻璃规格':<20} {'单价':<6} {'宽':<6} {'高':<6} {'面积':<7} {'合计':<8} {'备注':<6}"
    lines.append(hdr)
    lines.append("-" * 110)

    grand_total = 0
    line_no = 0
    sash_groups = {}   # sash_name -> (price, count)
    thick_groups = {}  # spec -> {area, price, total}
    acc_groups = {}    # accessory_name -> {count, price, total}

    for item in results:
        if item.get("skip") or "error" in item:
            continue
        d = item["data"]
        p = item["price"]
        if "error" in p:
            continue

        line_no += 1
        prof = d.get("profile", "?").replace("侧压", "测压")
        wid = cfg.get("window_id_fixes", {}).get(d.get("window_id", ""), d.get("window_id", "?"))
        grand_total += p["area_total"]

        lines.append(
            f"{line_no:<5} {wid:<14} {prof:<24} {cfg['default_color']:<8} {d.get('glass','?'):<20} "
            f"{p['unit_price']:<6} {d.get('width'):<6} {d.get('height'):<6} "
            f"{p['area_sqm']:<7.2f} {p['area_total']:<8.2f} {'':<6}"
        )

        # 收集开扇（归一化合并同类）
        if p["opening_sashes"] > 0 and p["sash_unit_price"] > 0:
            pk = d.get("profile", "")
            name = p.get("sash_name")
            if not name:
                # 回退：根据关键词自行归类
                if any(k in pk for k in ["内开内倒", "内开系列", "97内开", "S97", "s97"]):
                    name = "S97系列内开内倒 开启页"
                elif any(k in pk for k in ["外开窗", "110E"]):
                    name = "中铝110E系列外开窗 开启页"
                elif any(k in pk for k in ["测压", "侧压"]):
                    name = "120系列测压门 开启页"
                else:
                    name = pk + " 开启页"
            if name not in sash_groups:
                sash_groups[name] = {"price": p["sash_unit_price"], "count": 0}
            sash_groups[name]["count"] += p["opening_sashes"]

        # 收集加厚
        for t in p.get("thickening_items", []):
            spec = t["spec"]
            if spec not in thick_groups:
                thick_groups[spec] = {"area": 0, "price": t["unit_price"], "total": 0}
            thick_groups[spec]["area"] += t["area"]
            thick_groups[spec]["total"] += t["total"]

        # 收集配件
        for a in p.get("accessories", []):
            key = a["name"]
            if key not in acc_groups:
                acc_groups[key] = {"count": 0, "price": a["unit_price"], "total": 0}
            acc_groups[key]["count"] += a["count"]
            acc_groups[key]["total"] += a["total"]

    # 开扇增项
    for name in sorted(sash_groups):
        info = sash_groups[name]
        subtotal = info["count"] * info["price"]
        grand_total += subtotal
        line_no += 1
        lines.append(
            f"{line_no:<5} {name:<14} {'':24} {'':8} {'':20} "
            f"{info['price']:<6} {'':6} {'':6} {info['count']:<7.0f} {subtotal:<8.0f} {'':<6}"
        )

    # 加厚增项
    for spec in sorted(thick_groups):
        info = thick_groups[spec]
        grand_total += info["total"]
        line_no += 1
        lines.append(
            f"{line_no:<5} {'玻璃加厚至'+spec:<14} {'':24} {'':8} {'':20} "
            f"{info['price']:<6} {'':6} {'':6} {info['area']:<7.2f} {info['total']:<8.2f} {'':<6}"
        )

    # 配件增项
    for name in sorted(acc_groups):
        info = acc_groups[name]
        grand_total += info["total"]
        line_no += 1
        lines.append(
            f"{line_no:<5} {name:<14} {'':24} {'':8} {'':20} "
            f"{info['price']:<6} {'':6} {'':6} {info['count']:<7.0f} {info['total']:<8.0f} {'':<6}"
        )

    lines.append("-" * 110)
    lines.append(
        f"{'':>5} {'总计':<14} {'':24} {'':8} {'':20} {'':6} {'':6} {'':6} {'':7} {grand_total:<8.2f} {'':<6}"
    )
    return "\n".join(lines)
