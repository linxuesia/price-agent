"""
飞书门窗报价机器人
用户发送 PDF → 自动识别 → 返回报价单图片

部署前准备：
1. 飞书开发者后台 (open.feishu.cn) 创建自建应用
2. 应用权限: im:message, im:resource, im:message:send_as_bot
3. 发布上线（仅自己可见即可）
4. 设置环境变量或直接修改下方配置：
   FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_VERIFY_TOKEN
5. 启动: python3 feishu_bot.py
6. ngrok 暴露: ngrok http 8080
7. 飞书后台「事件订阅」填 ngrok URL + /feishu/event
"""

import base64
import json
import os
import re
import traceback
import httpx
import pypdfium2 as pdfium
from fastapi import FastAPI, Request, Response
import uvicorn
from pathlib import Path

# 加载 .env 文件
def _load_dotenv():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ============================================================
# 配置（修改为你自己的飞书应用信息）
# ============================================================
APP_ID = os.getenv("FEISHU_APP_ID", "你的APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "你的APP_SECRET")
VERIFY_TOKEN = os.getenv("FEISHU_VERIFY_TOKEN", "你的VERIFY_TOKEN")

# 智谱 API
ZHIPU_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

PROMPT = """你是资深门窗造价工程师。提取这张门窗图纸的数据，输出紧凑JSON。
{"window_id":"窗号","width":总宽度mm,"height":总高度mm,"profile":"型材系列","glass":"玻璃规格","opening_sashes":开启扇数,"fixed_sashes":固定扇数,"thickening":[{"area":面积,"spec":"Xmm+Xmm"}]}
严格规则：
1. 窗号：在图纸右下角标题栏/图注中找，格式如"C3一楼卫生间"。不要用A1、F1等扇编号
2. 宽度：水平方向最外侧尺寸标注，取整数。窄高窗宽度小于高度是正常的，不要颠倒
3. 高度：垂直方向最外侧尺寸标注，取整数。取所有高度数字中最大的那个（总高度）
4. 玻璃加厚：找红色字"X.X㎡加厚至Y"，面积只写数字不带单位，规格如"12mm+12mm"，不要前缀
只输出JSON，不要代码块，不要解释。"""

# ============================================================
# 飞书 API 工具
# ============================================================
FEISHU_BASE = "https://open.feishu.cn/open-apis"

_token = None
_token_expire = 0


def _get_tenant_token() -> str:
    global _token, _token_expire
    import time
    if _token and time.time() < _token_expire - 60:
        return _token
    resp = httpx.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"飞书 token 失败: {data}")
    _token = data["tenant_access_token"]
    _token_expire = time.time() + data.get("expire", 7200)
    return _token


def _download_file(message_id: str, file_key: str) -> bytes:
    token = _get_tenant_token()
    resp = httpx.get(
        f"{FEISHU_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
        params={"type": "file"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def _upload_image(image_path: str) -> str:  # 返回 image_key
    token = _get_tenant_token()
    import io
    from PIL import Image

    img = Image.open(image_path)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    resp = httpx.post(
        f"{FEISHU_BASE}/im/v1/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("quotation.png", buf, "image/png")},
        data={"image_type": "message"},
        timeout=30,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"上传图片失败: {data}")
    return data["data"]["image_key"]


def reply_message(message_id: str, content: str):
    token = _get_tenant_token()
    resp = httpx.post(
        f"{FEISHU_BASE}/im/v1/messages/{message_id}/reply",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": json.dumps({"text": content})},
        timeout=10,
    )
    return resp.json()


def reply_image(message_id: str, image_key: str):
    token = _get_tenant_token()
    resp = httpx.post(
        f"{FEISHU_BASE}/im/v1/messages/{message_id}/reply",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": json.dumps({"image_key": image_key}), "msg_type": "image"},
        timeout=10,
    )
    return resp.json()


# ============================================================
# PDF 处理管线（复用现有逻辑）
# ============================================================
def process_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """处理 PDF，返回 (报价单文本, 报价单图片路径)"""
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()

    try:
        # 1. 渲染 PNG
        pages_dir = os.path.join(tmpdir, "pages")
        os.makedirs(pages_dir)
        pdf = pdfium.PdfDocument(pdf_bytes)
        total = len(pdf)
        for i in range(total):
            bitmap = pdf[i].render(scale=2)
            bitmap.to_pil().save(os.path.join(pages_dir, f"page_{i+1:02d}.png"))
        pdf.close()

        # 2. 逐页识别
        results = []
        client = httpx.Client(timeout=120)
        headers = {"Authorization": f"Bearer {ZHIPU_KEY}", "Content-Type": "application/json"}

        for i in range(total):
            img_path = os.path.join(pages_dir, f"page_{i+1:02d}.png")
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            body = {
                "model": "glm-4v-flash",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": PROMPT},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 1024,
            }
            resp = client.post(ZHIPU_URL, json=body, headers=headers)
            content = ""
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]

            # 解析 JSON
            text = re.sub(r"```\w*\s*", "", content).strip()
            match = re.search(r"\{[\s\S]*\"window_id\"[\s\S]*\}", text)
            parsed = None
            if match:
                text = match.group()
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    # 修复截断
                    text = text.rstrip()
                    while text and text[-1] not in "]}":
                        text = text[:-1]
                    text += "}" * (text.count("{") - text.count("}"))
                    text += "]" * (text.count("[") - text.count("]"))
                    try:
                        parsed = json.loads(text)
                    except:
                        pass

            results.append({"page": i + 1, "data": parsed})

        client.close()

        # 3. 计算价格
        from calc import calculate, generate_quotation

        for item in results:
            d = item.get("data")
            if d and isinstance(d, dict) and "width" in d:
                t = d.get("thickening", [])
                d["thickening"] = [x for x in t if isinstance(x.get("area"), (int, float)) and x["area"] > 0]
                item["price"] = calculate(d)

        # 保存结果
        with open(os.path.join(tmpdir, "results.json"), "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        quotation_text = generate_quotation(results)

        # 4. 生成图片
        from calc import _load_config as load_cfg
        import playwright_env  # noqa

        cfg = load_cfg()
        # 构建 HTML 表格
        rows = []
        sash_groups = {}
        thick_groups = {}

        for item in results:
            if item.get("skip") or "error" in item:
                continue
            d = item["data"]
            p = item["price"]
            if "error" in p:
                continue

            prof = d.get("profile", "?").replace("侧压", "测压")
            wid = cfg.get("window_id_fixes", {}).get(d.get("window_id", ""), d.get("window_id", "?"))

            rows.append({
                "label": wid, "profile": prof, "glass": d.get("glass", ""),
                "unit_price": p["unit_price"],
                "width": d.get("width", 0), "height": d.get("height", 0),
                "area": p["area_sqm"], "area_total": p["area_total"], "type": "main",
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

        grand_total = sum(r["area_total"] for r in rows)

        for name in sorted(sash_groups):
            info = sash_groups[name]
            rows.append({
                "label": name, "profile": "", "glass": "",
                "unit_price": info["price"], "width": "", "height": "",
                "area": info["count"], "area_total": info["count"] * info["price"],
                "type": "sash",
            })
            grand_total += info["count"] * info["price"]

        for spec in sorted(thick_groups):
            info = thick_groups[spec]
            rows.append({
                "label": f"玻璃加厚至{spec}", "profile": "", "glass": "",
                "unit_price": info["price"], "width": "", "height": "",
                "area": info["area"], "area_total": info["total"],
                "type": "thick",
            })
            grand_total += info["total"]

        html_parts = ["""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
body{font-family:"PingFang SC","Heiti SC","Microsoft YaHei",sans-serif;font-size:13px;margin:20px;background:#fff;color:#000}
h2{text-align:center;margin-bottom:2px;font-size:18px}
.subtitle{text-align:center;color:#999;font-size:11px;margin-bottom:12px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid #333;padding:3px 5px;text-align:center;white-space:nowrap}
th{background:#f0f0f0;font-weight:bold}
td.label{text-align:left}td.right{text-align:right}td.profile{text-align:left}td.glass{text-align:left;font-size:10px}
tr.sash td{background:#fafafa}tr.thick td{background:#fafafa}
tr.total td{font-weight:bold;font-size:14px;background:#e8e8e8}
</style></head><body>
<h2>门窗销售明细表</h2><p class="subtitle">AI 自动生成</p>
<table><thead><tr><th>编号</th><th>安装位置</th><th>型材系列</th><th>颜色</th><th>玻璃规格</th>
<th>单价</th><th>宽</th><th>高</th><th>数量/面积</th><th>合计</th></tr></thead><tbody>"""]

        line_no = 0
        for r in rows:
            line_no += 1
            rc = "sash" if r["type"] == "sash" else ("thick" if r["type"] == "thick" else "")
            area_disp = f'{r["area"]:.2f}' if isinstance(r["area"], float) else str(r["area"])
            total_disp = f'{r["area_total"]:.2f}'

            html_parts.append(f'<tr class="{rc}">')
            html_parts.append(f'<td>{line_no}</td>')
            html_parts.append(f'<td class="label">{r["label"]}</td>')
            html_parts.append(f'<td class="profile">{r["profile"]}</td>')
            html_parts.append(f'<td>{cfg["default_color"]}</td>')
            html_parts.append(f'<td class="glass">{r["glass"]}</td>')
            html_parts.append(f'<td class="right">{r["unit_price"]}</td>')
            html_parts.append(f'<td>{r["width"]}</td>')
            html_parts.append(f'<td>{r["height"]}</td>')
            html_parts.append(f'<td class="right">{area_disp}</td>')
            html_parts.append(f'<td class="right">{total_disp}</td>')
            html_parts.append(f'</tr>')

        html_parts.append(f'<tr class="total"><td colspan="9">总计</td><td class="right">{grand_total:.2f}</td></tr>')
        html_parts.append("</tbody></table></body></html>")

        html_path = os.path.join(tmpdir, "quotation.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        # Playwright 截图
        from playwright.sync_api import sync_playwright

        img_output = os.path.join(tmpdir, "quotation.png")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(f"file://{html_path}")
            page.wait_for_timeout(500)
            page.screenshot(path=img_output, full_page=True)
            browser.close()

        return quotation_text, img_output

    finally:
        pass  # 保留临时文件方便调试，生产环境可 shutil.rmtree(tmpdir)


# ============================================================
# FastAPI 服务
# ============================================================
app = FastAPI()


@app.get("/ping")
def ping():
    return {"ok": True}


@app.post("/feishu/event")
async def feishu_event(req: Request):
    body = await req.json()

    # URL 验证
    if body.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": body["challenge"]}),
            media_type="application/json",
        )

    # 消息事件
    header = body.get("header", {})
    event = body.get("event", {})

    if header.get("event_type") == "im.message.receive_v1":
        msg_type = event.get("message", {}).get("message_type", "")
        message_id = event.get("message", {}).get("message_id", "")
        chat_type = event.get("message", {}).get("chat_type", "")

        # 只在单聊中回复
        if chat_type != "p2p":
            return {"code": 0}

        if msg_type == "text":
            text = json.loads(event["message"]["content"]).get("text", "")
            reply_message(message_id, f"你好！请直接发送门窗 PDF 图纸，我将自动生成报价单。")

        elif msg_type == "file":
            file_name = event["message"]["content"]
            try:
                content_json = json.loads(file_name)
                file_key = content_json.get("file_key", "")
                file_name = content_json.get("file_name", "图纸.pdf")
            except:
                file_key = ""
                file_name = "图纸.pdf"

            if not file_key or not file_name.lower().endswith(".pdf"):
                reply_message(message_id, "请发送 PDF 格式的门窗图纸文件。")
                return {"code": 0}

            reply_message(message_id, f"收到「{file_name}」，开始处理…")

            try:
                # 1. 下载
                pdf_bytes = _download_file(message_id, file_key)
                reply_message(message_id, f"已下载 {len(pdf_bytes)/1024:.0f} KB，正在识别…")

                # 2. 处理
                text, img_path = process_pdf(pdf_bytes)

                # 3. 上传图片
                image_key = _upload_image(img_path)

                # 4. 回复图片
                reply_image(message_id, image_key)

                # 5. 回复文字摘要
                lines = text.strip().split("\n")
                summary_lines = lines[-4:] if len(lines) > 4 else lines
                reply_message(message_id, "\n".join(summary_lines))

            except Exception as e:
                traceback.print_exc()
                reply_message(message_id, f"处理出错：{e}")

        else:
            reply_message(message_id, "请发送门窗 PDF 图纸文件。")

    return {"code": 0}


if __name__ == "__main__":
    print(f"飞书报价机器人启动: http://0.0.0.0:8080")
    print(f"Webhook: http://localhost:8080/feishu/event")
    uvicorn.run(app, host="0.0.0.0", port=8080)
