"""
LM Studio Provider

支持本地 LM Studio 服务
"""

import json
import logging
import sys
import typing

from neurova.llm.providers.base import BaseProvider
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None
try:
    import aiohttp
except ImportError:
    aiohttp = None

# llm imports
import neurova.llm.providers.base

class LMStudioProvider:
    """
    LMStudioProvider
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
