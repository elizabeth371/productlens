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

## 实测可用的测试链接

以下链接均通过完整流水线（真实抓取 + LLM 生成 + 质检）验证（2026-11-27）：

| 品类 | 链接 | 备注 |
|---|---|---|
| 智能音箱 | `https://www.amazon.com/dp/B09B8V1LZ3` | Echo Dot 5 |
| 高端耳机 | `https://www.amazon.com/dp/B0BDHWDR12` | AirPods Pro 2，质检修正过幻觉 |
| 露营椅 | `https://www.amazon.com/VTOY-Chairs%EF%BC%8CCamping-Foldable-Shadefor-Camping/dp/B0CXT9RSGQ` | 完整 slug 格式 |
| 蓝牙音箱 | `https://www.amazon.com/dp/B07QK2SPP7` | JBL Flip 5 |
| 电子书阅读器 | `https://www.amazon.com/dp/B08KTZ8249` | 无买盒价页面，验证容错 |
| 美妆小商品 | `https://www.amazon.com/dp/B09BC4FCL2` | 廉价非电子品类 |
| URL 形态 | `https://www.amazon.com/gp/product/B0CXT9RSGQ` | `/gp/product/` 格式 |

批量回归测试：`python tests/batch_verify.py`（轻量抓取筛选）→ `python tests/batch_full.py`（完整流水线）。

> 笔试原文示例 `B0F6YQ96L5` 已在 Amazon 下架（真实 404），系统会正确提示"商品不存在"。
