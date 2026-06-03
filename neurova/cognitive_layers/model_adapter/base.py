"""
BaseModelAdapter — 模型适配器基类

所有模型适配器的统一抽象接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import typing

from abc import ABC
from typing import AsyncIterator
from abc import abstractmethod

"""
ToolCall
"""
def ToolCall(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

"""
AdapterCapabilities
"""
def AdapterCapabilities(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

class BaseModelAdapter:
    """
    BaseModelAdapter
    """
    def __annotate__(self, *args, **kwargs):
        pass
    def __init__(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _declare_capabilities(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def format_prompt(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def generate(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def generate_stream(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def parse_tool_call(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def extract_content(self, *args, **kwargs):
        pass
    def get_llm_client(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def __repr__(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
