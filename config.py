# -*- coding: utf-8 -*-
"""集中读取配置：.env（本地）或环境变量（HF Spaces Secrets）。"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

VL_API_KEY = os.getenv("VL_API_KEY", "").strip()
VL_BASE_URL = os.getenv("VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
VL_MODEL = os.getenv("VL_MODEL", "qwen-vl-plus").strip()

JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()

TEXT_LLM_READY = bool(DEEPSEEK_API_KEY)
VISION_READY = bool(VL_API_KEY)
