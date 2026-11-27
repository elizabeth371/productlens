# -*- coding: utf-8 -*-
"""可选视觉模型模块：对商品图片做多模态分析。

DeepSeek 为纯文本模型，因此视觉能力做成可插拔插槽（默认 Qwen-VL，
任意 OpenAI 兼容视觉端点均可）。未配置 VL_API_KEY 时优雅降级，
不影响主流程——这是刻意的工程取舍，写进了 README 的设计说明。
"""
import base64

import requests
from openai import OpenAI

import config

_client = None

VISION_SYSTEM = """你是电商视觉分析专家。分析这些商品图片，输出视觉层面的营销洞察（中文）：
1. 产品外观、材质与工艺观感；
2. 图中展示的使用场景/人群线索；
3. 最适合用于短视频封面的画面与拍摄建议；
4. 图片与文案卖点相互印证的视觉证据。
只描述图片中真实可见的内容，不要猜测看不见的信息。
JSON 输出：{"visual_selling_points": [str], "scene_clues": [str], "cover_suggestion": str}"""


def available() -> bool:
    return config.VISION_READY


def _client_vl() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.VL_API_KEY, base_url=config.VL_BASE_URL)
    return _client


def _to_data_url(url: str, max_bytes: int = 2_500_000) -> str | None:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200 or len(resp.content) > max_bytes:
            return None
        b64 = base64.b64encode(resp.content).decode()
        ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        return f"data:{ctype};base64,{b64}"
    except requests.RequestException:
        return None


def analyze_images(image_urls: list[str], max_images: int = 3) -> list | None:
    """返回视觉分析结果；未配置或失败时返回 None（调用方降级）。"""
    if not available() or not image_urls:
        return None
    content: list = [{"type": "text", "text": VISION_SYSTEM}]
    added = 0
    for u in image_urls:
        if added >= max_images:
            break
        data_url = _to_data_url(u)
        if data_url:
            content.append({"type": "image_url", "image_url": {"url": data_url}})
            added += 1
    if added == 0:
        return None
    try:
        resp = _client_vl().chat.completions.create(
            model=config.VL_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=1200,
        )
        from llm import parse_json
        parsed = parse_json(resp.choices[0].message.content)
        items = []
        for k in ("visual_selling_points", "scene_clues"):
            items.extend(parsed.get(k) or [])
        cover = parsed.get("cover_suggestion")
        if cover:
            items.append(f"封面建议：{cover}")
        return items or None
    except Exception:  # noqa: BLE001 —— 视觉失败不影响主流程
        return None
