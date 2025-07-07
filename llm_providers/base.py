"""
Base LLM Provider classes and interfaces.

This module defines the abstract base class for LLM providers and
common data structures used across all providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import time
import random


@dataclass
class ModelInfo:
    """Information about a specific LLM model."""
    name: str
    context_limit: int
    output_limit: int
    cost_per_1k_input: float  # Cost per 1000 input tokens
    cost_per_1k_output: float  # Cost per 1000 output tokens
    rpm_limit: int  # Requests per minute limit
    description: str
    recommended_for: List[str]
    
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for given token usage."""
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost


@dataclass
class LLMResponse:
    """Response from LLM provider with token usage information."""
    content: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost: Optional[float] = None
    model: Optional[str] = None


@dataclass
class LLMConfig:
    """Configuration for LLM provider."""
    provider: str
    model: str
    api_key: str
    max_retries: int = 3
    timeout: int = 60
    temperature: float = 0.1
    max_tokens: Optional[int] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = None
        self._request_count = 0
        self._last_request_time = 0
        
    @abstractmethod
    def initialize_client(self) -> None:
        """Initialize the LLM client."""
        pass
    
    @abstractmethod
    def validate_rule(self, rule: Dict, context: Dict, prompt: str) -> LLMResponse:
        """
        Validate a rule using the LLM.
        
        Args:
            rule: Rule definition dictionary
            context: Validation context
            prompt: Formatted prompt for the LLM
            
        Returns:
            LLMResponse with content and token usage information
        """
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[ModelInfo]:
        """Get list of available models for this provider."""
        pass
    
    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for given text."""
        pass
    
    @abstractmethod
    def handle_rate_limit(self, attempt: int) -> float:
        """
        Handle rate limiting with provider-specific backoff.
        
        Args:
            attempt: Current retry attempt number
            
        Returns:
            Sleep duration in seconds
        """
        pass
    
    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """Get information about a specific model."""
        models = self.get_available_models()
        model_name_lower = model_name.lower()
        
        # First try exact matches
        for model in models:
            if model_name == model.name or model_name_lower == model.name.lower():
                return model
        
        # Then try partial matches
        for model in models:
            if (model_name_lower in model.name.lower() or 
                any(part in model.name.lower() for part in model_name_lower.split('-'))):
                return model
        
        return None
    
    def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting based on model specifications."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        model_info = self.get_model_info(self.config.model)
        if model_info and model_info.rpm_limit:
            min_interval = 60.0 / model_info.rpm_limit  # Minimum seconds between requests
            
            if time_since_last < min_interval:
                sleep_time = min_interval - time_since_last
                time.sleep(sleep_time)
        
        self._last_request_time = time.time()
        self._request_count += 1
    
    def _exponential_backoff(self, attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
        """
        Calculate exponential backoff delay with jitter.
        
        Args:
            attempt: Current retry attempt (0-based)
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            
        Returns:
            Delay in seconds
        """
        delay = min(base_delay * (2 ** attempt), max_delay)
        # Add jitter to prevent thundering herd
        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter
    
    def validate_config(self) -> bool:
        """Validate the provider configuration."""
        if not self.config.api_key:
            raise ValueError(f"API key required for {self.config.provider}")
        
        if not self.config.model:
            raise ValueError(f"Model name required for {self.config.provider}")
        
        # Check if model is supported
        model_info = self.get_model_info(self.config.model)
        if not model_info:
            available_models = [m.name for m in self.get_available_models()]
            raise ValueError(
                f"Model '{self.config.model}' not supported by {self.config.provider}. "
                f"Available models: {', '.join(available_models)}"
            )
        
        return True
    
    def get_provider_stats(self) -> Dict[str, Any]:
        """Get provider usage statistics."""
        return {
            'provider': self.config.provider,
            'model': self.config.model,
            'request_count': self._request_count,
            'last_request_time': self._last_request_time
        }
