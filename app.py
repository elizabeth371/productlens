# -*- coding: utf-8 -*-
"""AI 产品分析助手 - Flask 后端。

提交分析：POST /api/analyze 校验链接后立即返回任务 ID，
流水线在后台线程执行（规避部署平台的单请求超时限制）；
进度查询：GET /api/job/<id> 返回分阶段进度与最终结果。
"""
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request

import config
import llm
import scraper
import vision

app = Flask(__name__)

STAGE_NAMES = [
    "抓取商品页面",
    "AI 提取信息 + 图片理解",
    "产品深度分析",
    "生成口播文案",
    "质量自检",
]

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 30


def _create_job(url: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        if len(JOBS) >= MAX_JOBS:  # 淘汰最早的已完成任务
            for old_id in sorted(JOBS, key=lambda k: JOBS[k]["started_at"]):
                if JOBS[old_id]["status"] != "running":
                    del JOBS[old_id]
                    break
        JOBS[job_id] = {
            "url": url,
            "status": "running",
            "stages": [
                {"name": n, "status": "pending", "seconds": None, "detail": ""}
                for n in STAGE_NAMES
            ],
            "result": None,
            "error": None,
            "elapsed": None,
            "started_at": time.time(),
        }
    return job_id


def _stage_begin(job: dict, idx: int):
    job["stages"][idx]["status"] = "running"
    job["_t0"] = time.time()


def _stage_done(job: dict, idx: int, detail: str = ""):
    st = job["stages"][idx]
    st["status"] = "done"
    st["seconds"] = round(time.time() - job.get("_t0", time.time()), 1)
    st["detail"] = detail


def _run_pipeline(job: dict):
    url = job["url"]
    steps = job["stages"]
    try:
        # 1. 抓取
        _stage_begin(job, 0)
        page = scraper.fetch_product(url)
        _stage_done(job, 0, f"来源: {'直连' if page['source'] == 'direct' else '代理/reader'}")

        # 2. 信息提取 ∥ 图片理解
        _stage_begin(job, 1)
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
        _stage_done(job, 1, f"{len(product.get('bullets') or [])} 条卖点 · 视觉: {vision_detail}")

        # 3. 产品分析
        _stage_begin(job, 2)
        analysis = llm.analyze_product(product, image_insights)
        if image_insights:
            analysis["image_insights"] = image_insights
        _stage_done(job, 2)

        # 4. 中英文案并行
        _stage_begin(job, 3)
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_zh = ex.submit(llm.generate_copy_zh, product, analysis)
            fut_en = ex.submit(llm.generate_copy_en, product, analysis)
            copy_zh, copy_en = fut_zh.result(), fut_en.result()
        _stage_done(job, 3, "中文 + 英文（并行）")

        # 5. 质量自检
        _stage_begin(job, 4)
        qc = llm.quality_check(product, copy_zh, copy_en)
        _stage_done(job, 4, f"结论: {qc.get('verdict', 'pass')}")

        job["result"] = {
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
            "steps": [
                {"name": s["name"], "seconds": s["seconds"], "detail": s["detail"]}
                for s in steps if s["status"] == "done"
            ],
            "elapsed": round(time.time() - job["started_at"], 1),
            "model": config.LLM_MODEL,
        }
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        job["error"] = str(e)
        job["status"] = "error"
    finally:
        job["elapsed"] = round(time.time() - job["started_at"], 1)


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

    job_id = _create_job(url)
    threading.Thread(target=_run_pipeline, args=(JOBS[job_id],), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/job/<job_id>")
def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify({
        "status": job["status"],
        "stages": job["stages"],
        "elapsed": job["elapsed"],
        "result": job["result"],
        "error": job["error"],
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
