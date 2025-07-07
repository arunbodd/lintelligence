"""
LLM Provider abstraction layer for Nextflow Pipeline Validator.

This module provides a unified interface for different LLM providers
(Anthropic, OpenAI) with support for multiple models and configurations.
"""

from .base import LLMProvider, ModelInfo, LLMConfig
from .factory import LLMProviderFactory
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider

__all__ = [
    'LLMProvider',
    'ModelInfo', 
    'LLMConfig',
    'LLMProviderFactory',
    'AnthropicProvider',
    'OpenAIProvider'
]
