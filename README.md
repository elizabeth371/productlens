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

> AI 工程师实习生笔试项目 · Flask + DeepSeek + 可插拔视觉模型

## 使用

1. 在 Space 的 **Settings → Variables and secrets** 中添加：
   - `DEEPSEEK_API_KEY`（必填，[platform.deepseek.com](https://platform.deepseek.com) 申请）
   - `VL_API_KEY`（可选，启用商品图片理解；默认对接阿里云百炼 `qwen-vl-plus`，可用任意 OpenAI 兼容视觉端点替换 `VL_BASE_URL` / `VL_MODEL`）
   - `JINA_API_KEY`（可选，提升抓取兜底稳定性）
2. 粘贴任意 Amazon 商品链接（`/dp/XXXXXXXXXX` 格式），点击「开始分析」。

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
python app.py          # http://127.0.0.1:5000
```
