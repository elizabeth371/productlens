# -*- coding: utf-8 -*-
"""LLM 流水线：信息提取补全 → 产品分析 → 中英口播文案 → 质量自检。

所有调用走 OpenAI 兼容接口（默认 DeepSeek），全部使用 JSON 输出，
对解析失败做重试与容错，保证流水线不因单次格式问题中断。
"""
import json
import re
import time

from openai import OpenAI

import config

_client = None
_client_vl = None


def text_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.TEXT_LLM_READY:
            raise RuntimeError("未配置 LLM_API_KEY，请在 .env 或环境变量中填写")
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def chat_json(system: str, user: str, temperature: float = 0.4, max_tokens: int = 3000,
              retries: int = 2) -> dict:
    """调用文本模型并强制 JSON 输出；带格式容错重试与退避。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = text_client().chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0 if attempt > 0 else temperature,
                max_tokens=max_tokens,
                timeout=180,
                response_format={"type": "json_object"},
            )
            return parse_json(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(3 * (attempt + 1))  # 端点瞬断/限流时退避重试
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

COPY_SYSTEM = """你是抖音/TikTok 头部带货短视频编导，写出来的口播像真人在镜头前说话，
绝不能有 AI 说明书味。为给定产品写一段短视频口播文案。

【结构模板】
1. 前 5 秒（约 25 字）强钩子：痛点、反常识或冲突，禁止"家人们""大家好"式开场；
2. 场景代入：用"你"+一个具体画面把观众拉进使用场景；
3. 卖点最多挑 2 个，把参数翻译成体感（如"续航 36 小时"→"充一次，用它一周"；
   体感解释不得超出参数本意）；
4. 价格口语化报出（如 USD 67.99 →"六十七块九"，或"67 刀 9"），可加价值锚点
   （"一顿火锅钱"），锚点不得与价格差距悬殊；
5. 结尾明确 CTA（点击下方链接 / 左下角小黄车）。

【语言规则——反 AI 味】
- 短句为主，一句说一件事，多用句号逗号，禁止连续两个以上分号排比；
- 禁用词：此外/同时/不仅…还/总之/堪称/为您/贴心/卓越/极致/赋能/一站式/焕新/青睐；
- 允许适度语气词让句子像人话：说实话/你敢信/别小看/讲真（每篇至多 2 个）；
- 形容词最多留一个，其余用数字、动作和画面代替；
- 念出来必须顺口——写完自己默读一遍，拗口就改。

【对照示例】（同一款 $39.99 智能音箱，4.7 分）
死板版（禁止这样写）："这款智能音箱音质出色，搭载前置扬声器，支持语音助手，
功能丰富，操作简单，性价比高，快来购买吧。"
口播版（照这个感觉写）："39块9，请回家一个不顶嘴的室友。你瘫在沙发上喊一嗓子，
它就把灯关了、音乐放了。前代用户打出4.7分，差评最多的一条是——小孩跟它聊天
停不下来。左下角小黄车，39块9，也就一顿外卖钱。"

【硬约束】
- 全文（含标点）不超过 150 字；
- 只能使用给定商品信息中的事实，禁止编造功能、价格、评分与效果；
- 禁止夸大与绝对化用语（第一/最/治愈/根治等）。
JSON 输出：
{"hook_5s": "前5秒钩子单独摘出", "script": "完整口播文案",
 "char_count": 字数, "shot_suggestion": "一句话画面建议"}"""


COPY_EN_SYSTEM = """You are a top TikTok/Reels UGC scriptwriter. Your scripts sound like a real
person talking to camera, never like AI ad copy. Write a spoken voiceover for the given product.

[Structure]
1. First 5 seconds (~20 words): a hook via pain point / counter-intuition / conflict.
   No "hey guys" openings.
2. Drop the viewer into one concrete scene using "you".
3. Pick at most 2 benefits; translate specs into felt experience
   ("36-hour battery" -> "charge it once, use it all week") without overstating the spec.
4. Say the price out loud in a casual way, with a value anchor (e.g. "less than a takeout run").
5. Clear CTA at the end.

[Anti-AI-flavor rules]
- Short sentences, one idea each. No stacked semicolons or parallel clause lists.
- Banned words: moreover / furthermore / in conclusion / cutting-edge / revolutionary /
  elevate / seamless / unmatched / elevate your lifestyle.
- Keep at most one adjective per claim; prefer numbers, actions, images.
- Read it aloud in your head — if it sounds stiff, rewrite it.

[Hard rules]
- Max 110 words total; only use facts from the given product data; never invent
  features, prices or ratings; no exaggeration or absolute claims.
JSON output: {"hook_5s": str, "script": str, "char_count": int, "shot_suggestion": str}"""


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
D. 字数检查：逐字重数中文文案（含标点、不含空格）是否 ≤150 字；若超长，
   必须压缩重写至 ≤150 字以内，同时保留前 5 秒钩子与结尾行动号召；
E. AI 味检查：是否像真人带货口播（有场景、有节奏、念着顺口）？若出现分号排比
   堆砌、书面连接词（此外/同时/堪称/极致/赋能/一站式）、形容词空转等
   "产品说明书腔"，必须按口语化标准重写。
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
    final_zh = result.get("final_copy_zh") or copy_zh
    final_en = result.get("final_copy_en") or copy_en

    # 代码级硬约束：中文文案 ≤150 字（LLM 质检可能漏判字数）
    n = count_zh_chars(final_zh.get("script") or "")
    if n > 150:
        issues = result.setdefault("issues_found", [])
        issues.append(f"中文文案 {n} 字超出 150 字硬限制，已自动压缩")
        result["verdict"] = "fixed"
        try:
            final_zh = compress_copy_zh(final_zh["script"])
        except Exception:  # noqa: BLE001 —— 压缩失败则确定性截断
            final_zh = {"hook_5s": final_zh.get("hook_5s", ""),
                        "script": hard_truncate_zh(final_zh["script"], 150),
                        "char_count": 150}
        if count_zh_chars(final_zh["script"]) > 150:
            final_zh["script"] = hard_truncate_zh(final_zh["script"], 150)
        final_zh["char_count"] = count_zh_chars(final_zh["script"])

    # 质检重写可能丢掉画面建议等字段，从原文案回补
    for key in ("shot_suggestion",):
        if not final_zh.get(key) and copy_zh.get(key):
            final_zh[key] = copy_zh[key]
        if not final_en.get(key) and copy_en.get(key):
            final_en[key] = copy_en[key]

    result["final_copy_zh"] = final_zh
    result["final_copy_en"] = final_en
    return result


COMPRESS_SYSTEM = """你是短视频文案编辑。给定的中文口播文案超过了 150 字硬性上限。
将其压缩到 150 字以内（含标点，不含空格），要求：
- 保留原文案的前 5 秒钩子与结尾行动号召；
- 只能删减与压缩表达，不得新增任何事实（价格/功能均须来自原文）；
- 压缩后仍要口语化、有节奏感。
JSON 输出：{"hook_5s": str, "script": str, "char_count": int}"""


def compress_copy_zh(script: str) -> dict:
    out = chat_json(COMPRESS_SYSTEM, f"超长文案：\n{script}",
                    temperature=0.2, max_tokens=800)
    return {
        "hook_5s": out.get("hook_5s") or script[:25],
        "script": out.get("script") or script,
        "char_count": count_zh_chars(out.get("script") or script),
    }


def hard_truncate_zh(text: str, limit: int) -> str:
    """确定性兜底：保证 ≤limit 字，优先在句末标点处收口。"""
    if count_zh_chars(text) <= limit:
        return text
    last_end, n = 0, 0
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        n += 1
        if ch in "。！？!?；;":
            last_end = i + 1
        if n >= limit:
            break
    if last_end and count_zh_chars(text[:last_end]) <= limit:
        return text[:last_end]
    out, k = [], 0
    for ch in text:
        if ch == " ":
            continue
        out.append(ch)
        k += 1
        if k >= limit:
            break
    return "".join(out)


def count_zh_chars(text: str) -> int:
    return len(re.sub(r"\s", "", text or ""))
