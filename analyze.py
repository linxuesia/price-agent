import base64
import json
import httpx
import os
import re
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

API_KEY = os.getenv("ZHIPU_API_KEY", "")
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

PROMPT = """你是资深门窗造价工程师。提取这张门窗图纸的数据，输出紧凑JSON。
{"window_id":"窗号","width":总宽度mm,"height":总高度mm,"profile":"型材系列","glass":"玻璃规格","opening_sashes":开启扇数,"fixed_sashes":固定扇数,"thickening":[{"area":面积,"spec":"Xmm+Xmm"}],"screen_sashes":纱窗数量,"screen_doors":纱门数量,"smart_lock":有无密码锁}
严格规则：
1. 窗号：在图纸右下角标题栏/图注中找，格式如"C3一楼卫生间"。不要用A1、F1等扇编号
2. 宽度：水平方向最外侧尺寸标注，取整数。窄高窗宽度小于高度是正常的，不要颠倒
3. 高度：垂直方向最外侧尺寸标注，取整数。取所有高度数字中最大的那个（总高度）
4. 玻璃加厚：找红色字"X.X㎡加厚至Y"，面积只写数字不带单位，规格如"12mm+12mm"，不要前缀
5. 纱窗：在立面图/剖面图中找"不锈钢纱扇""纱扇""纱窗""金刚网纱窗"标注，有几个写几个（通常与玻璃扇配套，一个开扇配一个纱扇）。没标就写0
6. 纱门：找"纱门"标注，有几个写几个。没标就写0
7. 密码锁：找"密码锁""指纹锁""智能锁"标注，有为true没有为false
只输出JSON，不要代码块，不要解释。"""


def analyze_page(image_path, page_num):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    body = {
        "model": "glm-4v-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    print(f"\n{'='*60}")
    print(f"正在分析第 {page_num} 页...")
    print(f"{'='*60}")

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(API_URL, json=body, headers=headers)
            if resp.status_code == 200:
                result = resp.json()
                content = result["choices"][0]["message"]["content"]
                usage = result.get("usage", {})
                print(content)
                print(f"[Token: prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}]")

                # 提取 JSON
                text = re.sub(r'```\w*\s*', '', content)
                text = text.strip()
                json_match = re.search(r"\{[\s\S]*\"window_id\"[\s\S]*\}", text)
                if json_match:
                    text = json_match.group()
                    try:
                        parsed = json.loads(text)
                        return parsed
                    except json.JSONDecodeError:
                        # 尝试修复截断的 JSON
                        text = text.rstrip()
                        while text and text[-1] not in ']}':
                            text = text[:-1]
                        open_brackets = text.count('{') - text.count('}')
                        open_arrays = text.count('[') - text.count(']')
                        text += '}' * open_brackets + ']' * open_arrays
                        try:
                            parsed = json.loads(text)
                            return parsed
                        except:
                            pass
                return {"raw": content}
            else:
                print(f"API 错误: {resp.status_code} - {resp.text[:300]}")
                return None
    except Exception as e:
        print(f"异常: {e}")
        return None


if __name__ == "__main__":
    pages_dir = "/Users/shanlisi/sia/price-agent/pages"
    all_results = []

    for i in range(1, 15):
        image_path = os.path.join(pages_dir, f"page_{i:02d}.png")
        if os.path.exists(image_path):
            result = analyze_page(image_path, i)
            all_results.append({"page": i, "data": result})

    # 保存汇总结果
    output_path = "/Users/shanlisi/sia/price-agent/results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'='*60}")
    print("汇总结果:")
    print(f"{'='*60}")
    for item in all_results:
        r = item["data"]
        if r and "width" in r:
            print(f"第{item['page']:02d}页: {r.get('window_id','?')} | {r.get('width','?')}x{r.get('height','?')}mm | 玻璃:{r.get('glass','?')} | 型材:{r.get('profile','?')} | 开扇:{r.get('opening_sashes',0)} 固扇:{r.get('fixed_sashes',0)} | 纱窗:{r.get('screen_sashes',0)} 纱门:{r.get('screen_doors',0)} 密码锁:{r.get('smart_lock',False)}")
        elif r and "raw" in r:
            print(f"第{item['page']:02d}页: {r['raw'][:100]}...")
        else:
            print(f"第{item['page']:02d}页: 识别失败")

    print(f"\n详细结果已保存到: {output_path}")
