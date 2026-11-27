# -*- coding: utf-8 -*-
"""LLM 流水线：信息提取补全 → 产品分析 → 中英口播文案 → 质量自检。

所有调用走 OpenAI 兼容接口（默认 DeepSeek），全部使用 JSON 输出，
对解析失败做重试与容错，保证流水线不因单次格式问题中断。
"""
import json
import re

from openai import OpenAI

import config

_client = None
_client_vl = None


def text_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.TEXT_LLM_READY:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 .env 或环境变量中填写")
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    return _client


def chat_json(system: str, user: str, temperature: float = 0.4, max_tokens: int = 3000,
              retries: int = 2) -> dict:
    """调用文本模型并强制 JSON 输出；带格式容错重试。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = text_client().chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0 if attempt > 0 else temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return parse_json(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"LLM 调用失败: {last_err}")


def parse_json(text: str) -> dict:
    if not text:
        raise ValueError("空响应")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ================================================================ 1. 信息提取

EXTRACT_SYSTEM = """你是电商产品数据专家。从 Amazon 页面文本中提取结构化商品信息。
规则：
- 只依据给定文本提取，禁止编造；文本中不存在的字段填 null 或空数组；
- price 只填数字字符串（不含货币符号），currency 用 ISO 代码（USD/GBP/EUR/JPY/CAD 等）；
- bullets 为产品核心功能卖点（保持英文原文，最多 8 条）；
- specs 为规格键值对（尺寸/材质/重量/颜色/包装清单等）；
- 用 JSON 输出：{"title": str, "category": str, "price": str|null, "currency": str|null,
  "rating": str|null, "reviews_count": str|null, "bullets": [str], "description": str|null,
  "specs": {k: v}, "brand": str|null}"""


def extract_product_info(raw_text: str) -> dict:
    user = f"Amazon 页面文本如下：\n\n{raw_text[:9000]}"
    return chat_json(EXTRACT_SYSTEM, user, temperature=0.1)


def merge_product(dom: dict, llm_extract: dict) -> dict:
    """DOM 硬字段优先（防幻觉），LLM 结果补缺。"""
    merged = dict(llm_extract or {})
    for k in ("title", "category", "price", "currency", "rating", "reviews_count", "description", "brand"):
        if dom.get(k) and not merged.get(k):
            merged[k] = dom[k]
    if dom.get("bullets") and len(dom.get("bullets", [])) >= len(merged.get("bullets") or []):
        merged["bullets"] = dom["bullets"]
    if dom.get("specs"):
        specs = dict(merged.get("specs") or {})
        specs.update(dom["specs"])
        merged["specs"] = specs
    merged["images"] = dom.get("images") or []
    return merged


# ================================================================ 2. 产品分析

ANALYZE_SYSTEM = """你是资深电商产品分析师与消费洞察专家，服务于跨境电商选品与内容营销团队。
基于给定的商品结构化信息，输出一份深入、具体、可落地的产品分析（全部用中文）。
要求：
- 洞察必须由商品信息推导而来，可引用具体功能/规格/价格作为论据；
- 分析要有商业视角：能判断产品定位档次、竞争策略、适合的营销人群；
- 避免空话套话（如"质量好、性价比高"），每条洞察都要具体到这个产品本身；
- 若信息不足以支撑某个维度，如实说明而不是编造。
JSON 输出：
{
  "positioning": "一句话产品定位（档次/差异点）",
  "target_users": [{"segment": "人群", "reason": "为什么适合，引用产品特征"}],
  "use_scenarios": [{"scenario": "场景", "detail": "具体使用方式与产品对应功能"}],
  "pain_points": ["该产品解决的用户痛点（推导自其功能设计）"],
  "selling_points": [{"point": "核心卖点", "evidence": "支撑证据（功能/规格/价格/评分）", "copy_angle": "可衍生的营销角度"}],
  "pricing_insight": "价格带分析与价值感知",
  "risks_concerns": ["客观风险或顾虑，如评分依据不足、信息缺失等"],
  "image_insights": ["（若有图片分析结果，融合进来的视觉卖点；没有则空数组）"]
}"""


def analyze_product(product: dict, image_analysis: list | None = None) -> dict:
    payload = {
        "title": product.get("title"), "brand": product.get("brand"),
        "category": product.get("category"), "price": product.get("price"),
        "currency": product.get("currency"), "rating": product.get("rating"),
        "reviews_count": product.get("reviews_count"),
        "bullets": product.get("bullets"), "description": product.get("description"),
        "specs": product.get("specs"),
    }
    user = f"商品结构化信息：\n{json.dumps(payload, ensure_ascii=False)}"
    if image_analysis:
        user += f"\n\n商品图片视觉分析结果（可作为补充证据）：\n{json.dumps(image_analysis, ensure_ascii=False)}"
    return chat_json(ANALYZE_SYSTEM, user, temperature=0.5, max_tokens=3500)


# ================================================================ 3. 口播文案

COPY_SYSTEM = """你是抖音/TikTok 头部带货短视频编导，擅长写高转化的中文口播带货文案。
为给定产品写一段短视频口播文案，硬性要求：
1. 全文（含标点）不超过 150 个汉字；
2. 开头 5 秒（约前 25 字）必须有强钩子——用冲突、悬念、反常识或直击痛点的方式，
   让用户忍不住继续看，禁止用"家人们""大家好"这类开场白；
3. 中段用 1-2 个最抓人的卖点，讲"用户能得到什么"而不是罗列参数；
4. 结尾有明确的行动号召（点击下方链接/左下角小黄车等）；
5. 口语化、有节奏感、适合真人出镜念出来；禁止夸大与绝对化用语（第一/最/治愈等）；
6. 只能使用给定商品信息中的事实，禁止编造功能、价格与效果。
JSON 输出：
{"hook_5s": "前5秒钩子单独摘出", "script": "完整口播文案",
 "char_count": 字数, "shot_suggestion": "一句话画面建议"}"""


def generate_copy_zh(product: dict, analysis: dict) -> dict:
    facts = {
        "title": product.get("title"), "price": product.get("price"),
        "currency": product.get("currency"), "rating": product.get("rating"),
        "bullets": (product.get("bullets") or [])[:6],
        "selling_points": analysis.get("selling_points"),
        "target_users": analysis.get("target_users"),
        "use_scenarios": analysis.get("use_scenarios"),
    }
    user = f"商品事实信息（文案只能基于这些事实）：\n{json.dumps(facts, ensure_ascii=False)}"
    return chat_json(COPY_SYSTEM, user, temperature=0.8, max_tokens=1200)


COPY_EN_SYSTEM = COPY_SYSTEM.replace(
    "你是抖音/TikTok 头部带货短视频编导，擅长写高转化的中文口播带货文案。",
    "You are a top TikTok/Reels UGC scriptwriter for high-converting product videos."
).replace(
    """为给定产品写一段短视频口播文案，硬性要求：
1. 全文（含标点）不超过 150 个汉字；
2. 开头 5 秒（约前 25 字）必须有强钩子——用冲突、悬念、反常识或直击痛点的方式，
   让用户忍不住继续看，禁止用"家人们""大家好"这类开场白；
3. 中段用 1-2 个最抓人的卖点，讲"用户能得到什么"而不是罗列参数；
4. 结尾有明确的行动号召（点击下方链接/左下角小黄车等）；
5. 口语化、有节奏感、适合真人出镜念出来；禁止夸大与绝对化用语（第一/最/治愈等）；
6. 只能使用给定商品信息中的事实，禁止编造功能、价格与效果。
JSON 输出：
{"hook_5s": "前5秒钩子单独摘出", "script": "完整口播文案",
 "char_count": 字数, "shot_suggestion": "一句话画面建议"}""",
    """Write a spoken voiceover script in English. Hard rules:
1. Max 110 words total; 2. First 5 seconds (~20 words) must contain a strong hook
(conflict / suspense / counter-intuitive / pain point), no "hey guys" openings;
3. Middle: 1-2 most compelling benefits, not spec lists; 4. Clear CTA at the end;
5. Conversational, rhythmic, made to be spoken on camera; no exaggeration or absolute claims;
6. Only use facts from the given product data; never invent features or prices.
JSON output: {"hook_5s": str, "script": str, "char_count": int, "shot_suggestion": str}"""
)


def generate_copy_en(product: dict, analysis: dict) -> dict:
    facts = {
        "title": product.get("title"), "price": product.get("price"),
        "bullets": (product.get("bullets") or [])[:6],
        "selling_points": analysis.get("selling_points"),
    }
    user = f"Product facts (script must be based ONLY on these):\n{json.dumps(facts, ensure_ascii=False)}"
    return chat_json(COPY_EN_SYSTEM, user, temperature=0.8, max_tokens=1200)


# ================================================================ 4. 质量自检

QC_SYSTEM = """你是 AI 内容质检官，负责拦住"幻觉、夸大、不符合场景"的输出。
你将收到：商品事实（ground truth）、中文口播文案、英文口播文案。逐项检查：
A. 事实一致性：文案中的价格、功能、规格、评分是否都能在商品事实中找到依据？
   有任何一处无依据或与事实矛盾，即为幻觉，必须修正；
B. 夸大检查：是否出现"第一/最/顶级/神奇/根治/绝对"等绝对化或疗效暗示用语？
C. 钩子检查：中文文案前 25 字是否有真正的钩子（冲突/悬念/痛点/反常识），
   而不是普通开场白；
D. 字数检查：中文文案（含标点）是否 ≤150 字；
E. 场景感检查：是否像真实带货口播（有行动号召、口语节奏），而非产品说明书。
发现问题直接输出修正后的完整文案；没有问题则原样保留。
JSON 输出：
{
  "verdict": "pass" 或 "fixed",
  "checks": [{"item": "A事实一致性", "status": "pass|fail", "note": "具体说明"}],
  "issues_found": ["发现的问题"],
  "final_copy_zh": {"hook_5s": str, "script": str, "char_count": int},
  "final_copy_en": {"hook_5s": str, "script": str, "char_count": int}
}"""


def quality_check(product: dict, copy_zh: dict, copy_en: dict) -> dict:
    facts = {
        "title": product.get("title"), "price": product.get("price"),
        "currency": product.get("currency"), "rating": product.get("rating"),
        "bullets": (product.get("bullets") or [])[:8],
        "specs_keys": list((product.get("specs") or {}).keys()),
    }
    user = (
        "商品事实（ground truth）：\n" + json.dumps(facts, ensure_ascii=False)
        + "\n\n中文口播文案：\n" + json.dumps(copy_zh, ensure_ascii=False)
        + "\n\n英文口播文案：\n" + json.dumps(copy_en, ensure_ascii=False)
    )
    result = chat_json(QC_SYSTEM, user, temperature=0.2, max_tokens=2500)
    # 兜底：修正后的文案缺失时回退原文案
    result.setdefault("final_copy_zh", copy_zh)
    result.setdefault("final_copy_en", copy_en)
    return result


def count_zh_chars(text: str) -> int:
    return len(re.sub(r"\s", "", text or ""))
