# -*- coding: utf-8 -*-
"""集中读取配置：.env（本地）或环境变量（HF Spaces Secrets）。

文本与视觉模型均走 OpenAI 兼容协议；视觉配置缺省时自动复用文本配置，
因此单个支持视觉的端点只需一套 key。
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 文本模型
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus").strip()

# 视觉模型（缺省复用文本端点与 key）
VL_API_KEY = os.getenv("VL_API_KEY", "").strip() or LLM_API_KEY
VL_BASE_URL = os.getenv("VL_BASE_URL", "").strip() or LLM_BASE_URL
VL_MODEL = os.getenv("VL_MODEL", "qwen3-vl-plus").strip()

JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()

TEXT_LLM_READY = bool(LLM_API_KEY)
VISION_READY = bool(VL_API_KEY)
