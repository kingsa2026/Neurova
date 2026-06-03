from __future__ import annotations

"""
OpenRouter Provider

支持 OpenRouter API（访问多个模型）
"""

import json
import logging
import sys
import time
import typing

from neurova.llm.providers.base import BaseProvider
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None
from neurova.llm.providers.types import ConnectionResult
from neurova.llm_client import LLMConfig
from typing import TYPE_CHECKING
try:
    import aiohttp
except ImportError:
    aiohttp = None
from neurova.llm.providers.multimodal_prober import _is_media_keyword_error

# llm imports
import neurova.llm.providers.base
import neurova.llm.providers.multimodal_prober
import neurova.llm.providers.types

# llm_client imports
import neurova.llm_client

class OpenRouterProvider:
    """
    OpenRouterProvider
    """
    def __annotate__(self, *args, **kwargs):
        pass
    def __init__(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def get_available_models(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _detect_capabilities(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def create_chat_model(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def test_connection(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def fetch_models(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _get_default_pydantic_models(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def check_model_connection(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def probe_model_multimodal(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def get_llm_config(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _make_headers(self, *args, **kwargs):
        pass
