# -*- coding: utf-8 -*-
"""Amazon 商品页抓取模块。

策略：
1. 直连请求（仿真浏览器头）+ BeautifulSoup DOM 解析；
2. 直连被拦截（验证码/超时/结构解析失败）时，回退到 r.jina.ai 阅读代理获取 Markdown。

设计原则：DOM 解析只做 best-effort，用于拿到价格、标题等可交叉验证的硬字段；
最终交给 LLM 的还有清洗后的页面文本，保证对任意品类、任意站点泛化。
"""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

BLOCK_MARKS = (
    "captcha", "robot check", "automated access", "enter the characters",
    "api services", "sorry, something went wrong",
)

ASIN_RE = re.compile(r"(?:/dp/|/gp/product/|/product/)([A-Z0-9]{10})", re.I)
IMG_DYNAMIC_RE = re.compile(r"data-a-dynamic-image=\"([^\"]+)\"")
HIRES_RE = re.compile(r'"hiRes"\s*:\s*"(https://[^"]+)"')
LARGE_RE = re.compile(r'"large"\s*:\s*"(https://[^"]+)"')


def extract_asin(url: str) -> str | None:
    m = ASIN_RE.search(url)
    return m.group(1).upper() if m else None


def validate_amazon_url(url: str) -> str | None:
    """校验并规整 URL，返回错误信息或 None。"""
    url = (url or "").strip()
    if not url:
        return "请输入商品链接"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "amazon." not in url:
        return "目前仅支持 Amazon 商品链接"
    if not extract_asin(url):
        return "链接中未找到商品 ASIN（需要包含 /dp/XXXXXXXXXX）"
    return None


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


_AD_IDS = {"sp_detail", "sp_detail_filtered", "related_ads_wrapper", "dpads-ac-parent", "sponsoredProducts2"}
_AD_CLASSES = ("p13n-sc-uncoverable-faceout", "s-result-item", "s-sponsored", "ad1000")


def _in_ads(el) -> bool:
    """判断元素是否位于推荐广告/轮播容器内（p13n、sims、sponsored 都可能展示别家商品价格）。"""
    p = el
    while p is not None and getattr(p, "name", None) not in (None, "[document]"):
        pid = p.get("id") or ""
        if pid in _AD_IDS or pid.startswith("sims") or "CardInstance" in pid:
            return True
        cls = " ".join(p.get("class") or [])
        if any(c in cls for c in _AD_CLASSES):
            return True
        p = p.parent
    return False


def _looks_blocked(html: str) -> bool:
    low = html[:4000].lower()
    title_m = re.search(r"<title[^>]*>(.*?)</title>", low, re.S)
    title = title_m.group(1) if title_m else ""
    if any(k in title for k in BLOCK_MARKS) or any(k in low for k in BLOCK_MARKS):
        return True
    return len(html) < 50000  # 正常商品页远大于这个体积


# ---------------------------------------------------------------- DOM 解析

def parse_amazon_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    data = {
        "title": None, "price": None, "currency": None, "rating": None,
        "reviews_count": None, "category": None, "bullets": [],
        "description": None, "specs": {}, "images": [],
    }

    el = soup.select_one("#productTitle")
    if el:
        data["title"] = _clean_text(el.get_text())

    el = soup.select_one("#wayfinding-breadcrumbs_feature_div")
    if el:
        crumbs = [_clean_text(a.get_text()) for a in el.select("a") if _clean_text(a.get_text())]
        if crumbs:
            data["category"] = " > ".join(crumbs)

    # 价格：优先买盒专用容器；否则全页找价但排除推荐广告位（p13n/sponsored）
    price_raw = None
    for sel in (
        "#corePrice_feature_div .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#apex_desktop .a-offscreen",
        "#centerCol .a-price .a-offscreen",
        "#priceblock_ourprice",
        "#newBuyBoxPrice",
    ):
        el = soup.select_one(sel)
        if el:
            t = _clean_text(el.get_text())
            if re.search(r"\d", t):
                price_raw = t
                break
    if not price_raw:
        for el in soup.select(".a-price .a-offscreen"):
            if _in_ads(el):
                continue
            t = _clean_text(el.get_text())
            if re.search(r"\d", t):
                price_raw = t
                break
    if not price_raw:
        # Amazon 页面内嵌 JSON 的兜底通道
        m = re.search(r'"priceAmount"\s*:\s*([\d.]+)', html)
        if m:
            price_raw = m.group(1)
    if price_raw:
        m = re.search(r"([\d,]+(?:\.\d+)?)", price_raw)
        cur_m = re.search(r"US\$|\$|£|€|CDN\$|CNY|JPY|MXN", price_raw)
        if m:
            data["price"] = m.group(1)
            sym = cur_m.group(0) if cur_m else "$"
            data["currency"] = {
                "US$": "USD", "$": "USD", "£": "GBP", "€": "EUR",
                "CDN$": "CAD", "CNY": "CNY", "JPY": "JPY", "MXN": "MXN",
            }.get(sym, "USD")

    rating_el = soup.select_one("#acrPopover .a-icon-alt, span[data-hook='rating-out-of-text']")
    if rating_el:
        m = re.search(r"([\d.]+)\s*out of\s*5|([\d.]+)\s*星", rating_el.get_text(), re.I)
        data["rating"] = m.group(1) or m.group(2) if m else _clean_text(rating_el.get_text())[:20]

    reviews_el = soup.select_one("#acrCustomerReviewText")
    if reviews_el:
        m = re.search(r"([\d,]+)", reviews_el.get_text())
        data["reviews_count"] = m.group(1) if m else _clean_text(reviews_el.get_text())[:30]

    data["bullets"] = [
        _clean_text(li.get_text())
        for li in soup.select("#feature-bullets li span.a-list-item")
        if _clean_text(li.get_text()) and "see more" not in li.get_text().lower()
    ][:10]

    desc_el = soup.select_one("#productDescription")
    if desc_el:
        data["description"] = _clean_text(desc_el.get_text())[:1500]

    # 规格表（两种常见结构都尝试）
    for row in soup.select("#productOverview_feature_div tr, #detailBullets_feature_div li, #productDetails_techSpec_section_1 tr"):
        th = row.select_one("th, .a-text-bold")
        td = row.select_one("td, span:not(.a-text-bold)")
        if th and td:
            k, v = _clean_text(th.get_text()), _clean_text(td.get_text())
            if k and v and len(k) < 60:
                data["specs"][k] = v[:200]
        if len(data["specs"]) >= 15:
            break

    # 图片：hiRes / data-a-dynamic-image / data-old-hires
    imgs: list[str] = []
    for m in HIRES_RE.finditer(html):
        imgs.append(m.group(1).replace("\\u002F", "/"))
    for m in IMG_DYNAMIC_RE.finditer(html):
        try:
            obj = json.loads(m.group(1).replace("&quot;", '"'))
            imgs.extend(sorted(obj.keys(), key=lambda k: -obj[k]))
        except Exception:
            pass
    for img in soup.select("#landingImage, #imgTagWrapperId img, .a-dynamic-image"):
        for attr in ("data-old-hires", "src"):
            v = img.get(attr)
            if v and v.startswith("https://"):
                imgs.append(v)
    seen = set()
    for u in imgs:
        u = u.split("|")[0]
        if u.startswith("https://") and u not in seen and "sprite" not in u:
            seen.add(u)
            data["images"].append(u)
        if len(data["images"]) >= 8:
            break

    return data


# ---------------------------------------------------------------- 文本清洗

def html_to_text(html: str, limit: int = 12000) -> str:
    """把整页 HTML 压成纯文本，喂给 LLM 兜底提取。"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "form"]):
        tag.decompose()
    main = soup.find(id="dp-container") or soup.find(id="centerCol") or soup.body or soup
    text = main.get_text(separator="\n")
    lines = [_clean_text(l) for l in text.splitlines()]
    lines = [l for l in lines if len(l) > 1]
    return "\n".join(lines)[:limit]


def md_to_text(md: str, limit: int = 12000) -> str:
    """jina reader 返回的 Markdown，去掉图片标记后作为 LLM 输入。"""
    md = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", md)
    lines = [_clean_text(l) for l in md.splitlines()]
    lines = [l for l in lines if l and not l.startswith(("[", "](http"))]
    return "\n".join(lines)[:limit]


def extract_images_from_markdown(md: str) -> list[str]:
    urls = re.findall(r"https://m\.media-amazon\.com/images/I/[^)\s\"',]+?\.(?:jpg|jpeg|png|webp)", md)
    seen, out = set(), []
    for u in urls:
        if u not in seen and ("_SX" in u or "AC_" in u):
            seen.add(u)
            out.append(u)
    return out[:8]


# ---------------------------------------------------------------- 抓取入口

# 强制美元计价，避免中国 IP 访问时页面被本地化为 CNY 价格
COOKIES = {"i18n-prefs": "USD"}


def _new_session() -> requests.Session:
    """建立会话并设置美国配送地址：否则部分商品（如 Amazon 自营设备）
    会因“不可配送”而不渲染买盒价格。"""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.cookies.update(COOKIES)
    try:
        s.post(
            "https://www.amazon.com/gp/delivery/ajax/address-change.html",
            data={
                "locationType": "LOCATION_INPUT", "zipCode": "10001",
                "storeContext": "generic", "deviceType": "web",
                "pageType": "Detail", "actionSource": "glow",
            },
            timeout=12,
        )
    except requests.RequestException:
        pass
    return s


def fetch_direct(url: str) -> tuple[int | None, str | None]:
    """直连抓取（带美国地址会话），返回 (status, html)。"""
    try:
        resp = _new_session().get(url, timeout=25, allow_redirects=True)
        if "html" in resp.headers.get("Content-Type", ""):
            return resp.status_code, resp.text
        return resp.status_code, None
    except requests.RequestException:
        return None, None


def fetch_proxy_html(url: str) -> str | None:
    """allorigins 公共代理（服务端抓取原始 HTML），作为直连被拦时的兜底。"""
    try:
        resp = requests.get(
            "https://api.allorigins.win/raw",
            params={"url": url, "charset": "UTF-8"},
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=40,
        )
        if resp.status_code == 200 and len(resp.text) > 50000 and not _looks_blocked(resp.text):
            return resp.text
    except requests.RequestException:
        pass
    return None


def fetch_reader(url: str) -> str | None:
    """r.jina.ai 阅读代理，返回 Markdown（国内网络可能不可达，海外部署可用）。"""
    headers = dict(HEADERS)
    headers["X-Return-Format"] = "markdown"
    if config.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {config.JINA_API_KEY}"
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 800:
            return resp.text
    except requests.RequestException:
        pass
    return None


def fetch_product(url: str) -> dict:
    """返回统一结构；三种来源都尽量给出 raw_text 供 LLM 兜底。"""
    asin = extract_asin(url)
    result = {
        "url": url, "asin": asin, "source": None,
        "title": None, "price": None, "currency": None, "rating": None,
        "reviews_count": None, "category": None, "bullets": [],
        "description": None, "specs": {}, "images": [], "raw_text": None,
    }
    tried = []

    # 1) 直连
    status, html = fetch_direct(url)
    if html and status == 200 and not _looks_blocked(html):
        result.update(parse_amazon_html(html, url))
        result["source"] = "direct"
        if not result["title"]:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
            result["title"] = _clean_text(m.group(1))[:200] if m else None
        result["raw_text"] = html_to_text(html)
        return result
    tried.append(f"direct:{status}")
    if status == 404:
        raise RuntimeError(
            "该商品页面不存在（Amazon 返回 404），可能已下架或链接有误，请更换商品链接。"
        )

    # 2) allorigins 服务端代理（HTML）
    html = fetch_proxy_html(url)
    if html:
        result.update(parse_amazon_html(html, url))
        result["source"] = "proxy"
        if not result["title"]:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
            result["title"] = _clean_text(m.group(1))[:200] if m else None
        result["raw_text"] = html_to_text(html)
        return result
    tried.append("proxy:fail")

    # 3) jina reader（Markdown）
    md = fetch_reader(url)
    if md:
        result["source"] = "reader"
        m = re.search(r"^Title:\s*(.+)$", md, re.M) or re.search(r"^#\s*(.+)$", md, re.M)
        result["title"] = _clean_text(m.group(1))[:200] if m else None
        result["images"] = extract_images_from_markdown(md)
        result["raw_text"] = md_to_text(md)
        if result["title"] or len(result["raw_text"]) > 500:
            return result
    tried.append("reader:fail")

    raise RuntimeError(
        "商品页面抓取失败（直连/代理均被拦截或不可达）。"
        "Amazon 对部分请求返回了验证码，请稍后重试或更换链接。"
        f" [tried: {', '.join(tried)}]"
    )


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.amazon.com/dp/B0CXT9RSGQ"
    t0 = time.time()
    d = fetch_product(url)
    print("耗时 %.1fs | 来源: %s" % (time.time() - t0, d["source"]))
    print("标题:", d["title"])
    print("价格:", d["currency"], d["price"], "| 评分:", d["rating"], "| 评论数:", d["reviews_count"])
    print("品类:", d["category"])
    print("要点数:", len(d["bullets"]), "| 图片数:", len(d["images"]), "| 规格数:", len(d["specs"]))
    print("raw_text 前 300 字:")
    print((d["raw_text"] or "")[:300])
