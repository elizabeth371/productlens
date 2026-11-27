# -*- coding: utf-8 -*-
"""AI 产品分析助手 - Flask 后端。

流水线：抓取页面 → 硬字段解析 → LLM 补全提取 →（可选）图片理解
      → 产品分析 → 中/英口播文案 → 质量自检 → 汇总返回。
"""
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request

import config
import llm
import scraper
import vision

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "text_model": config.LLM_MODEL if config.TEXT_LLM_READY else None,
        "vision_enabled": config.VISION_READY,
    })


@app.post("/api/analyze")
def analyze():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    err = scraper.validate_amazon_url(url)
    if err:
        return jsonify({"error": err}), 400

    steps: list[dict] = []
    t_start = time.time()

    def step(name: str, t0: float, detail: str = ""):
        steps.append({"name": name, "seconds": round(time.time() - t0, 1), "detail": detail})

    try:
        # 1. 抓取
        t0 = time.time()
        page = scraper.fetch_product(url)
        step("抓取商品页面", t0, f"来源: {'直连' if page['source'] == 'direct' else '代理/reader'}")

        # 2. 信息提取 ∥ 图片理解（互不依赖，并行执行）
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_extract = ex.submit(llm.extract_product_info, page["raw_text"] or "")
            fut_vision = (
                ex.submit(vision.analyze_images, page.get("images") or [])
                if vision.available() and page.get("images") else None
            )
            extracted = fut_extract.result()
            product = llm.merge_product(page, extracted)
            product["url"], product["asin"] = page["url"], page["asin"]
            image_insights = fut_vision.result() if fut_vision else None
        vision_detail = (
            "已启用" if image_insights
            else ("图片下载或模型调用失败，已跳过" if fut_vision else "未配置视觉模型，已跳过")
        )
        step("AI 提取信息 + 图片理解", t0,
             f"{len(product.get('bullets') or [])} 条卖点 · 视觉: {vision_detail}")

        # 3. 产品分析
        t0 = time.time()
        analysis = llm.analyze_product(product, image_insights)
        if image_insights:
            analysis["image_insights"] = image_insights
        step("产品深度分析", t0)

        # 4. 中英文案并行生成
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_zh = ex.submit(llm.generate_copy_zh, product, analysis)
            fut_en = ex.submit(llm.generate_copy_en, product, analysis)
            copy_zh, copy_en = fut_zh.result(), fut_en.result()
        step("生成口播文案", t0, "中文 + 英文（并行）")

        # 6. 质量自检
        t0 = time.time()
        qc = llm.quality_check(product, copy_zh, copy_en)
        step("质量自检", t0, f"结论: {qc.get('verdict', 'pass')}")

        return jsonify({
            "ok": True,
            "product": {
                k: product.get(k) for k in (
                    "url", "asin", "title", "brand", "category", "price", "currency",
                    "rating", "reviews_count", "bullets", "description", "specs", "images",
                )
            },
            "fetch_source": page["source"],
            "analysis": analysis,
            "copy_zh": qc.get("final_copy_zh") or copy_zh,
            "copy_en": qc.get("final_copy_en") or copy_en,
            "raw_copy_zh": copy_zh,
            "raw_copy_en": copy_en,
            "quality_check": {
                "verdict": qc.get("verdict"),
                "checks": qc.get("checks") or [],
                "issues_found": qc.get("issues_found") or [],
            },
            "vision_enabled": bool(image_insights),
            "steps": steps,
            "elapsed": round(time.time() - t_start, 1),
            "model": config.LLM_MODEL,
        })

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"{e}", "steps": steps}), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
