---
title: ProductLens - AI 产品分析助手
emoji: 🔍
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# ProductLens · AI 产品分析助手

输入一个 Amazon 商品链接，自动完成：**商品信息整理 → 产品深度分析 → 短视频口播文案（中/英）→ AI 质量自检**。

> AI 工程师实习生笔试项目 · Flask + Qwen（OpenAI 兼容端点，可切 DeepSeek）+ 可插拔视觉模型

## 使用

1. 在 Space 的 **Settings → Variables and secrets** 中添加：
   - `LLM_API_KEY`（必填，任意 OpenAI 兼容端点的 key）
   - `LLM_BASE_URL`（默认阿里云百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`；DeepSeek 为 `https://api.deepseek.com`）
   - `LLM_MODEL`（默认 `qwen-plus`）
   - `VL_MODEL`（可选，默认 `qwen3-vl-plus`；视觉 key/端点缺省复用 `LLM_*`，端点不支持视觉时自动跳过图片理解）
   - `JINA_API_KEY`（可选，提升抓取兜底稳定性）
2. 粘贴任意 Amazon 商品链接（`/dp/XXXXXXXXXX` 格式），点击「开始分析」。

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 LLM_API_KEY
python app.py          # http://127.0.0.1:5000
```
