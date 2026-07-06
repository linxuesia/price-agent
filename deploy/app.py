"""
门窗报价助手 - 本地部署版
启动方式: python3 app.py
浏览器打开: http://localhost:8080

支持两种交互：
1. 浏览器网页聊天（默认）
2. 飞书 Bot（可选，配置 FEISHU_APP_ID 后启用）
"""

import asyncio
import base64
import io
import json
import os
import re
import sys
import threading
import tempfile
import queue
import traceback
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

from calc import calculate, generate_quotation, _load_config

# ============================================================
# 加载 .env 文件
# ============================================================
def _load_dotenv():
    """从项目根目录 .env 文件加载环境变量（不覆盖已有环境变量）"""
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
# 配置
# ============================================================
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
VERIFY_TOKEN = os.getenv("FEISHU_VERIFY_TOKEN", "")

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

PROJECT_DIR = Path(__file__).parent

# ============================================================
# PDF 处理管线
# ============================================================
async def process_pdf(pdf_bytes: bytes, progress_queue: queue.Queue = None, api_key: str = None):
    """处理 PDF（在后台线程中运行，通过 queue 报告进度）"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _process_pdf_sync, pdf_bytes, progress_queue, api_key
    )


def _safely_call(fn, msg):
    """在线程中安全调用回调"""
    if fn:
        try:
            fn(msg)
        except:
            pass


def _process_pdf_sync(pdf_bytes: bytes, progress_queue: queue.Queue = None, api_key: str = None):
    """同步版本的 PDF 处理"""
    def _progress(msg):
        if progress_queue:
            progress_queue.put(msg)

    key = api_key or ZHIPU_KEY

    import tempfile as tmpfile_mod
    tmpdir = tmpfile_mod.mkdtemp(dir=PROJECT_DIR)
    pages_dir = os.path.join(tmpdir, "pages")
    os.makedirs(pages_dir)

    try:
        # 1. 渲染 PNG
        pdf = pdfium.PdfDocument(pdf_bytes)
        total = len(pdf)
        _progress(f"共 {total} 页，开始渲染…")

        for i in range(total):
            bitmap = pdf[i].render(scale=2)
            bitmap.to_pil().save(os.path.join(pages_dir, f"page_{i+1:02d}.png"))
        pdf.close()

        _progress(f"渲染完成，开始识别 {total} 页…")

        # 2. 逐页识别
        results = []
        with httpx.Client(timeout=120) as client:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

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

                try:
                    resp = client.post(ZHIPU_URL, json=body, headers=headers)
                    content = ""
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]

                    text = re.sub(r"```\w*\s*", "", content).strip()
                    match = re.search(r"\{[\s\S]*\"window_id\"[\s\S]*\}", text)
                    parsed = None
                    if match:
                        text = match.group()
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
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

                    # 提取窗号用于进度提示
                    wid = parsed.get("window_id", f"第{i+1}页") if parsed else f"第{i+1}页"
                    _progress(f"✓ {wid} ({i+1}/{total})")
                except Exception as e:
                    results.append({"page": i + 1, "data": None, "error": str(e)})
                    _progress(f"✗ 第{i+1}页 识别失败: {e}")

        # 3. 计算价格
        for item in results:
            d = item.get("data")
            if d and isinstance(d, dict) and "width" in d:
                t = d.get("thickening", [])
                d["thickening"] = [x for x in t if isinstance(x.get("area"), (int, float)) and x["area"] > 0]
                item["price"] = calculate(d)

        _progress("计算完成，生成报价单…")

        quotation_text = generate_quotation(results)

        # 4. 生成图片
        cfg = _load_config()
        rows = []
        sash_groups = {}
        thick_groups = {}

        for item in results:
            if item.get("skip") or item.get("data") is None:
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

        # HTML
        html = _build_html(rows, grand_total, cfg)
        html_path = os.path.join(tmpdir, "quotation.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        # 截图
        from playwright.sync_api import sync_playwright
        img_path = os.path.join(tmpdir, "quotation.png")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(f"file://{html_path}")
            page.wait_for_timeout(500)
            page.screenshot(path=img_path, full_page=True)
            browser.close()

        # 读取图片返回
        with open(img_path, "rb") as f:
            img_bytes = f.read()

        # 摘要
        lines = quotation_text.strip().split("\n")
        summary = "\n".join(lines[-3:]) if len(lines) > 3 else quotation_text

        return img_bytes, summary

    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir)
        except:
            pass


def _build_html(rows, grand_total, cfg):
    """构建报价单 HTML"""
    parts = ["""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
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

        parts.append(f'<tr class="{rc}"><td>{line_no}</td>')
        parts.append(f'<td class="label">{r["label"]}</td>')
        parts.append(f'<td class="profile">{r["profile"]}</td>')
        parts.append(f'<td>{cfg["default_color"]}</td>')
        parts.append(f'<td class="glass">{r["glass"]}</td>')
        parts.append(f'<td class="right">{r["unit_price"]}</td>')
        parts.append(f'<td>{r["width"]}</td><td>{r["height"]}</td>')
        parts.append(f'<td class="right">{area_disp}</td>')
        parts.append(f'<td class="right">{r["area_total"]:.2f}</td></tr>')

    parts.append(f'<tr class="total"><td colspan="9">总计</td><td class="right">{grand_total:.2f}</td></tr>')
    parts.append("</tbody></table></body></html>")
    return "\n".join(parts)


# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(title="门窗报价助手")

# 存储处理状态（简单内存存储）
sessions = {}


@app.get("/")
async def index():
    """聊天网页界面"""
    return HTMLResponse((PROJECT_DIR / "chat.html").read_text(encoding="utf-8"))


@app.post("/api/upload")
async def api_upload(file: UploadFile, request: Request):
    """上传 PDF，返回处理结果"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"error": "请上传 PDF 文件"}

    # 优先使用客户端传入的 API Key
    custom_key = request.headers.get("X-Zhipu-Key", "")
    api_key = custom_key if custom_key else ZHIPU_KEY

    pdf_bytes = await file.read()

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'text': f'收到「{file.filename}」，共 {len(pdf_bytes)/1024:.0f} KB'})}\n\n"

            q: queue.Queue = queue.Queue()
            loop = asyncio.get_event_loop()

            # 在后台线程中处理
            task = loop.run_in_executor(None, _process_pdf_sync, pdf_bytes, q, api_key)

            # 轮询进度
            while not task.done():
                try:
                    msg = q.get(timeout=0.5)
                    yield f"data: {json.dumps({'type': 'status', 'text': msg})}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.3)

            # 收尾
            while True:
                try:
                    msg = q.get_nowait()
                    yield f"data: {json.dumps({'type': 'status', 'text': msg})}\n\n"
                except queue.Empty:
                    break

            img_bytes, summary = task.result()

            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            yield f"data: {json.dumps({'type': 'image', 'src': f'data:image/png;base64,{img_b64}'})}\n\n"
            yield f"data: {json.dumps({'type': 'status', 'text': summary})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/pricing")
async def pricing_page():
    """定价配置页面"""
    pricing_html = PROJECT_DIR / "pricing.html"
    if pricing_html.exists():
        return HTMLResponse(pricing_html.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>配置页面未找到</h1>", status_code=404)


@app.get("/api/pricing")
async def api_get_pricing():
    """获取当前定价配置"""
    cfg = _load_config()
    return cfg


@app.post("/api/pricing")
async def api_save_pricing(data: dict):
    """保存定价配置"""
    import calc
    cfg_path = PROJECT_DIR / "pricing.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    calc._CFG = None
    return {"ok": True}


# ============================================================
# 飞书 Bot（可选）
# ============================================================
if APP_ID and APP_ID != "你的APP_ID":
    print(f"[飞书] Bot 已启用")

    @app.post("/feishu/event")
    async def feishu_event(req: Request):
        body = await req.json()

        if body.get("type") == "url_verification":
            return Response(json.dumps({"challenge": body["challenge"]}), media_type="application/json")

        header = body.get("header", {})
        event = body.get("event", {})

        if header.get("event_type") == "im.message.receive_v1":
            msg = event.get("message", {})
            msg_type = msg.get("message_type", "")
            message_id = msg.get("message_id", "")

            if msg_type == "file":
                content_json = json.loads(msg.get("content", "{}"))
                file_key = content_json.get("file_key", "")
                file_name = content_json.get("file_name", "图纸.pdf")

                if not file_name.lower().endswith(".pdf"):
                    await _feishu_reply(message_id, "请发送 PDF 格式的图纸文件。")
                    return {"code": 0}

                await _feishu_reply(message_id, f"收到「{file_name}」，开始处理…")

                try:
                    token = _get_feishu_token()
                    resp = httpx.get(
                        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}",
                        params={"type": "file"},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=60,
                    )
                    resp.raise_for_status()

                    img_bytes, summary = await process_pdf(resp.content)

                    # 上传图片到飞书
                    img_buf = io.BytesIO(img_bytes)
                    upload_resp = httpx.post(
                        "https://open.feishu.cn/open-apis/im/v1/images",
                        headers={"Authorization": f"Bearer {_get_feishu_token()}"},
                        files={"image": ("quotation.png", img_buf, "image/png")},
                        data={"image_type": "message"},
                        timeout=30,
                    )
                    img_data = upload_resp.json()
                    if img_data.get("code") == 0:
                        image_key = img_data["data"]["image_key"]
                        httpx.post(
                            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                            headers={
                                "Authorization": f"Bearer {_get_feishu_token()}",
                                "Content-Type": "application/json",
                            },
                            json={"content": json.dumps({"image_key": image_key}), "msg_type": "image"},
                            timeout=10,
                        )

                    await _feishu_reply(message_id, summary)

                except Exception as e:
                    traceback.print_exc()
                    await _feishu_reply(message_id, f"处理出错：{e}")
            else:
                await _feishu_reply(message_id, "请直接发送门窗 PDF 图纸文件，我将自动生成报价单。")

        return {"code": 0}


_feishu_token_cache = {"token": None, "expire": 0}


def _get_feishu_token() -> str:
    import time
    if _feishu_token_cache["token"] and time.time() < _feishu_token_cache["expire"] - 60:
        return _feishu_token_cache["token"]
    resp = httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"飞书认证失败: {data}")
    _feishu_token_cache["token"] = data["tenant_access_token"]
    _feishu_token_cache["expire"] = time.time() + data.get("expire", 7200)
    return _feishu_token_cache["token"]


async def _feishu_reply(message_id: str, text: str):
    httpx.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        headers={
            "Authorization": f"Bearer {_get_feishu_token()}",
            "Content-Type": "application/json",
        },
        json={"content": json.dumps({"text": text})},
        timeout=10,
    )
if __name__ == "__main__":
    has_feishu = APP_ID and APP_ID != "你的APP_ID"
    port = int(os.getenv("PORT", "8080"))
    print(f"""
╔══════════════════════════════════════════╗
║        门窗报价助手 v1.0                ║
╠══════════════════════════════════════════╣
║  地址:   http://0.0.0.0:{port:<5}        ║
║  飞书:   {'已启用' if has_feishu else '未配置（纯浏览器模式）'}  ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
