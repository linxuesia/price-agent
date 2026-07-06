"""将报价单渲染为图片"""
import json
from calc import calculate, generate_quotation

with open("results_final.json") as f:
    results = json.load(f)

# 生成纯文本报价单（用于参考）
text = generate_quotation(results)

# 构建 HTML 表格
rows = []
sash_groups = {}
thick_groups = {}
acc_groups = {}

for item in results:
    if item.get("skip") or "error" in item:
        continue
    d = item["data"]
    p = item["price"]
    if "error" in p:
        continue

    prof = d.get("profile", "?").replace("侧压", "测压")
    wid = item.get("window_id") or d.get("window_id", "?")

    rows.append({
        "label": wid,
        "profile": prof,
        "glass": d.get("glass", ""),
        "unit_price": p["unit_price"],
        "width": d.get("width", 0),
        "height": d.get("height", 0),
        "area": p["area_sqm"],
        "area_total": p["area_total"],
        "type": "main",
    })

    if p["opening_sashes"] > 0 and p["sash_unit_price"] > 0:
        pk = d.get("profile", "")
        name = p.get("sash_name")
        if not name:
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

grand_total = sum(r["area_total"] for r in rows)
cfg = json.load(open("pricing.json"))

# 合并同类项
for name in sorted(sash_groups):
    info = sash_groups[name]
    rows.append({
        "label": name,
        "profile": "",
        "glass": "",
        "unit_price": info["price"],
        "width": "",
        "height": "",
        "area": info["count"],
        "area_total": info["count"] * info["price"],
        "type": "sash",
    })
    grand_total += info["count"] * info["price"]

for spec in sorted(thick_groups):
    info = thick_groups[spec]
    rows.append({
        "label": f"玻璃加厚至{spec}",
        "profile": "",
        "glass": "",
        "unit_price": info["price"],
        "width": "",
        "height": "",
        "area": info["area"],
        "area_total": info["total"],
        "type": "thick",
    })
    grand_total += info["total"]

for name in sorted(acc_groups):
    info = acc_groups[name]
    rows.append({
        "label": name,
        "profile": "",
        "glass": "",
        "unit_price": info["price"],
        "width": "",
        "height": "",
        "area": info["count"],
        "area_total": info["total"],
        "type": "accessory",
    })
    grand_total += info["total"]

# 生成 HTML
html_parts = []
html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page { size: auto; margin: 0; }
  body {
    font-family: "PingFang SC", "Heiti SC", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    margin: 30px;
    background: #fff;
    color: #000;
  }
  h2 { text-align: center; margin-bottom: 5px; font-size: 20px; }
  .subtitle { text-align: center; color: #666; font-size: 12px; margin-bottom: 15px; }
  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
  }
  th, td {
    border: 1px solid #333;
    padding: 4px 6px;
    text-align: center;
    white-space: nowrap;
  }
  th { background: #f0f0f0; font-weight: bold; }
  td.label { text-align: left; }
  td.right { text-align: right; }
  td.profile { text-align: left; }
  td.glass { text-align: left; font-size: 11px; }
  tr.sash td { background: #fafafa; }
  tr.thick td { background: #fafafa; }
  tr.accessory td { background: #fafafa; }
  tr.total td { font-weight: bold; font-size: 15px; background: #e8e8e8; }
  td.empty { color: #ccc; }
</style>
</head>
<body>
<h2>浏阳尚学府 门窗销售明细表</h2>
<p class="subtitle">AI 自动生成</p>
<table>
<thead>
<tr>
  <th>编号</th><th>安装位置</th><th>型材系列</th><th>颜色</th><th>玻璃规格</th>
  <th>单价</th><th>宽</th><th>高</th><th>数量/面积</th><th>合计</th>
</tr>
</thead>
<tbody>
""")

line_no = 0
for r in rows:
    line_no += 1
    row_class = ""
    if r["type"] == "sash":
        row_class = "sash"
    elif r["type"] == "thick":
        row_class = "thick"
    elif r["type"] == "accessory":
        row_class = "accessory"

    area_display = f'{r["area"]:.2f}' if isinstance(r["area"], float) else str(r["area"])
    total_display = f'{r["area_total"]:.2f}'

    html_parts.append(f'<tr class="{row_class}">')
    html_parts.append(f'<td>{line_no}</td>')
    html_parts.append(f'<td class="label">{r["label"]}</td>')
    html_parts.append(f'<td class="profile">{r["profile"]}</td>')
    html_parts.append(f'<td>{cfg["default_color"]}</td>')
    html_parts.append(f'<td class="glass">{r["glass"]}</td>')
    html_parts.append(f'<td class="right">{r["unit_price"]}</td>')
    html_parts.append(f'<td>{r["width"]}</td>')
    html_parts.append(f'<td>{r["height"]}</td>')
    html_parts.append(f'<td class="right">{area_display}</td>')
    html_parts.append(f'<td class="right">{total_display}</td>')
    html_parts.append(f'</tr>')

# 总计行
html_parts.append(f'<tr class="total">')
html_parts.append(f'<td colspan="9">总计</td>')
html_parts.append(f'<td class="right">{grand_total:.2f}</td>')
html_parts.append(f'</tr>')

html_parts.append("</tbody></table></body></html>")

html = "\n".join(html_parts)

html_path = "/tmp/quotation.html"
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

# 用 Playwright 渲染为图片
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(f"file://{html_path}")
    page.wait_for_timeout(500)
    # 获取内容实际高度
    content = page.locator("body")
    bbox = content.bounding_box()
    if bbox:
        page.set_viewport_size({"width": 1400, "height": int(bbox["height"]) + 10})
    output_path = "/Users/shanlisi/sia/price-agent/浏阳尚学府报价单_AI生成.png"
    page.screenshot(path=output_path, full_page=True)
    browser.close()

print(f"已导出: {output_path}")
print(f"总价: {grand_total:.2f}")
