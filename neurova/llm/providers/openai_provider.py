from __future__ import annotations

"""
OpenAI Provider

Support OpenAI API compatible providers
"""

import datetime
import json
import logging
import time
import typing

from neurova.llm.providers.base import BaseProvider
from neurova.llm.providers.types import (
    ConnectionResult, ModelInfo, ProbeResult, ProviderCapability, ProviderType
)
from typing import TYPE_CHECKING
import http

# llm imports
import neurova.llm.providers.base
import neurova.llm.providers.multimodal_prober
import neurova.llm.providers.types

# llm_client imports
import neurova.llm_client

class OpenAIProvider:
    """
    OpenAIProvider
    """
    def __init__(self, *args, **kwargs):
        pass
    def get_available_models(self, *args, **kwargs):
        pass
    def _get_default_models(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _detect_capabilities(self, *args, **kwargs):
        pass
    def create_chat_model(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def test_connection(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _make_headers(self, *args, **kwargs):
        pass
    def fetch_models(self, *args, **kwargs):
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
    def get_llm_config(self, *args, **kwargs):
        pass
