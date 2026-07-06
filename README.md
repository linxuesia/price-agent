# 门窗报价助手

<p align="center">
  <strong>AI 驱动的门窗报价自动化工具</strong><br/>
  上传 PDF 图纸 → AI 识别门窗 → 自动生成报价单
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue" alt="python"/>
  <img src="https://img.shields.io/badge/framework-FastAPI-green" alt="fastapi"/>
  <img src="https://img.shields.io/badge/AI-智谱_GLM-red" alt="zhipu"/>
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="license"/>
</p>

<p align="center">
  <a href="https://linxuesia.github.io/price-agent/">
    <img src="https://img.shields.io/badge/demo-在线演示-blue?style=for-the-badge" alt="在线演示"/>
  </a>
</p>

---

## 项目简介

**门窗报价助手** 是一款面向门窗行业的 AI 报价自动化工具。用户只需上传 PDF 门窗图纸，AI 自动识别每扇门窗的尺寸、型材系列、玻璃规格等信息，一键生成专业的报价单。

### 核心能力

- **PDF 图纸解析**：自动提取 PDF 中的门窗立面图，渲染为高清图片
- **AI 视觉识别**：调用智谱 GLM-4V 多模态大模型，识别门窗尺寸、型号、玻璃规格
- **自动报价计算**：根据预设单价，自动计算面积、开启扇、玻璃加厚、纱窗、密码锁等费用
- **Web 可视化**：美观的聊天式交互界面，支持实时查看识别进度和报价详情
- **导出报价单**：一键导出为高清 PNG 图片
- **定价配置**：网页侧边栏可实时修改单价，保存后即时生效

### 演示截图

上传 PDF 门窗图纸后，AI 自动逐页识别：

```
┌──────────────────────────────────┐
│  📄 sample.pdf (示例图纸)         │
│  共 2 页                          │
├──────────────────────────────────┤
│  ✅ 第 1 页: C1 - Living Room     │
│     Panoramic Sliding Door 4020×2550│
│     💰 面积 10.25㎡ × 980 = ¥10046│
│  ✅ 第 2 页: C3 - Master Bedroom  │
│     S97 Inward Tilt-Turn 3480×2335│
│     💰 面积 8.13㎡ × 799 = ¥6493 │
│  ...                              │
│  📊 汇总: 4扇门窗 / 总价 ¥23,580  │
└──────────────────────────────────┘
```

> 仓库包含脱敏示例图纸 [sample.pdf](./sample.pdf)，可直接用于测试。

---

## 技术架构

```
┌─────────────────────────────────────────────┐
│                  浏览器 (chat.html)           │
│  拖拽上传 PDF / 查看进度 / 下载报价单          │
└──────────────────┬──────────────────────────┘
                   │ HTTP/SSE
┌──────────────────▼──────────────────────────┐
│               FastAPI (app.py)               │
│  PDF 解析 → 图片渲染 → AI 识别 → 报价计算     │
└──────┬──────────────┬───────────────────────┘
       │              │
┌──────▼──────┐  ┌────▼──────────────┐
│  pypdfium2  │  │  智谱 GLM-4V      │
│  PDF → PNG  │  │  图片 → JSON 数据  │
└─────────────┘  └───────────────────┘
```

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 UI | HTML5 + CSS3 + vanilla JS | 聊天式交互界面，SSE 实时进度 |
| 后端框架 | FastAPI + uvicorn | 异步 HTTP 服务，本地部署 |
| PDF 处理 | pypdfium2 + Pillow | 逐页渲染为高清图片 |
| AI 识别 | 智谱 GLM-4V (zhipu AI) | 多模态大模型，图片 → 结构化数据 |
| 报价计算 | calc.py | 面积/开启扇/加厚/配件 自动计算 |
| 部署 | setup.sh / setup.bat | 跨平台一键安装脚本 |

---

## 报价逻辑

### 总价 = 面积价格 + 开启扇价格 + 玻璃加厚价格 + 配件价格

**面积价格** = 宽度(m) × 高度(m) × 型材面积单价  
**开启扇价格** = 开启扇数量 × 开启扇单价  
**玻璃加厚价格** = 加厚面积 × 对应规格单价  
**配件价格** = 纱窗数量 × 500 + 纱门数量 × 480 + 密码锁 × 1580

### 默认定价表

| 型材系列 | 面积单价(元/㎡) | 开启扇单价(元) |
|---------|:----------:|:----------:|
| 全景平移门/天域200 | 980 | 1680 |
| 安能推拉窗 | 599 | 0 |
| 中铝110E 外开窗 | 580 | 580 |
| S97 内开内倒 | 799 | 899 |
| 120系列测压门 | 880 | 880 |

| 玻璃加厚 | 单价(元/㎡) |
|---------|:--------:|
| 6mm+6mm | 128 |
| 8mm+8mm | 428 |
| 10mm+10mm | 628 |
| 12mm+12mm | 780 |

| 配件 | 单价(元) |
|-----|:-----:|
| 纱窗 | 500 |
| 纱门 | 480 |
| 密码锁 | 1580 |

> 所有价格均可在网页「定价配置」面板中实时修改。

---

## 快速开始

### 环境要求

- Python 3.8+
- 网络连接（访问智谱 AI API）

### 安装

```bash
# 克隆仓库
git clone git@github.com:linxuesia/price-agent.git
cd price-agent

# 安装依赖
pip install -r requirements.txt

# 设置 API Key
export ZHIPU_API_KEY="你的智谱API密钥"
```

### 启动

```bash
python app.py
# 浏览器打开 http://localhost:8080
```

### 使用

1. 浏览器打开 `http://localhost:8080`
2. 上传 PDF 门窗图纸（拖拽或点击）
3. AI 自动逐页识别门窗信息
4. 查看报价单，点击下载

---

## 客户部署

为客户提供一键部署脚本：

| 系统 | 安装脚本 | 启动脚本 |
|------|---------|---------|
| macOS | `setup.sh` | `启动.command` |
| Windows | `setup.bat` | `run.bat` |

详细步骤见 [部署指南.md](./部署指南.md)。

---

## 项目结构

```
price-agent/
├── app.py                # 主程序（FastAPI 服务 + PDF 处理 + AI 调用）
├── calc.py               # 报价计算模块
├── analyze.py            # 批量分析脚本
├── feishu_bot.py         # 飞书 Bot 集成（可选）
├── export_quotation.py   # 报价单导出工具
├── chat.html             # 聊天式 Web 界面
├── pricing.html          # 定价配置面板
├── pricing.json          # 定价数据（可在线修改）
├── prompt_v4.txt         # AI 提示词模板
├── requirements.txt      # Python 依赖
├── build.sh              # 构建脚本
├── setup.sh / setup.bat  # 一键安装脚本
├── run.bat / 启动.command # 启动器
├── deploy/               # 客户部署包
└── 部署指南.md            # 客户部署说明
```

---

## 可选功能

### 飞书 Bot 集成

配置环境变量后，可通过飞书 Bot 发送 PDF 图纸，自动返回报价：

```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
export FEISHU_VERIFY_TOKEN="your_verify_token"
```

---

## License

MIT
