"""
Anthropic Claude provider implementation.

This module provides the Anthropic Claude LLM provider with support for
all Claude models including 3.5 Sonnet, 3 Haiku, and 3 Opus.
"""

import os
import time
from typing import Dict, List, Optional, Any
from .base import LLMProvider, ModelInfo, LLMConfig, LLMResponse


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation."""
    
    # Based on current Anthropic pricing (corrected from user feedback)
    MODELS = {
        'claude-3-5-sonnet-20241022': ModelInfo(
            name='Claude 3.5 Sonnet',
            context_limit=200000,
            output_limit=8192,
            cost_per_1k_input=0.003,   # $3.00 per 1M = $0.003 per 1K
            cost_per_1k_output=0.015,  # $15.00 per 1M = $0.015 per 1K
            rpm_limit=4000,
            description='Most capable model for complex analysis',
            recommended_for=['complex_validation', 'detailed_reasoning', 'large_pipelines']
        ),
        'claude-3-haiku-20240307': ModelInfo(
            name='Claude 3 Haiku',
            context_limit=200000,
            output_limit=4096,
            cost_per_1k_input=0.00025, # $0.25 per 1M = $0.00025 per 1K
            cost_per_1k_output=0.00125, # $1.25 per 1M = $0.00125 per 1K
            rpm_limit=4000,
            description='Fast and cost-effective for simple tasks',
            recommended_for=['quick_validation', 'batch_processing', 'cost_effective']
        ),
        'claude-3-opus-20240229': ModelInfo(
            name='Claude 3 Opus',
            context_limit=200000,
            output_limit=4096,
            cost_per_1k_input=0.015,   # $15.00 per 1M = $0.015 per 1K
            cost_per_1k_output=0.075,  # $75.00 per 1M = $0.075 per 1K
            rpm_limit=4000,
            description='Highest quality reasoning and analysis',
            recommended_for=['highest_quality', 'critical_validation', 'complex_reasoning']
        )
    }
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.validate_config()
    
    def initialize_client(self) -> None:
        """Initialize the Anthropic client."""
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.config.api_key)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            )
    
    def validate_rule(self, rule: Dict, context: Dict, prompt: str) -> LLMResponse:
        """Validate a rule using Anthropic Claude API."""
        try:
            model_info = self.get_model_info()
            
            # Make API call with retry logic
            response = self._make_api_call_sync(prompt, model_info)
            
            return response
            
        except Exception as e:
            return LLMResponse(
                content=f"Anthropic API error: {str(e)}",
                input_tokens=None,
                output_tokens=None,
                cost=None,
                model=self.config.model
            )
    
    def _make_api_call_sync(self, prompt: str, model_info: ModelInfo) -> LLMResponse:
        if not self.client:
            self.initialize_client()
        
        self._enforce_rate_limit()
        
        # Debug logging
        print(f"\n🔍 DEBUG: Anthropic API Call")
        print(f"🔍 Model: {self.config.model}")
        print(f"🔍 Prompt length: {len(prompt)} characters")
        print(f"🔍 Max tokens: {self.config.max_tokens or 4096}")
        print(f"🔍 Temperature: {self.config.temperature}")
        
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens or 4096,
                    temperature=self.config.temperature,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    timeout=self.config.timeout
                )
                
                # Debug logging for successful response
                print(f"\n✅ DEBUG: Anthropic API Response Received")
                print(f"✅ Response type: {type(response)}")
                print(f"✅ Response content length: {len(response.content[0].text) if hasattr(response, 'content') else 'N/A'} characters")
                print(f"✅ Response first 100 chars: {response.content[0].text[:100] if hasattr(response, 'content') else 'N/A'}...")
                
                # Extract token usage information
                usage = response.usage if hasattr(response, 'usage') else None
                input_tokens = usage.input_tokens if usage else None
                output_tokens = usage.output_tokens if usage else None
                
                # Calculate cost if token usage is available
                cost = None
                if input_tokens and output_tokens:
                    cost = model_info.estimate_cost(input_tokens, output_tokens)
                
                return LLMResponse(
                    content=response.content[0].text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    model=self.config.model
                )
                
            except Exception as e:
                # Debug logging for errors
                print(f"\n❌ DEBUG: Anthropic API Error on attempt {attempt+1}/{self.config.max_retries}")
                print(f"❌ Error type: {type(e)}")
                print(f"❌ Error message: {str(e)}")
                
                # Check for rate limit errors specifically
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    if attempt < self.config.max_retries - 1:
                        # Try to extract wait time from error message if available
                        wait_time = None
                        try:
                            import re
                            # Common patterns in rate limit errors
                            wait_match = re.search(r'try again in ([0-9.]+)s', str(e))
                            if not wait_match:
                                wait_match = re.search(r'retry after ([0-9.]+) seconds', str(e))
                            if wait_match:
                                wait_time = float(wait_match.group(1)) + 0.5  # Add a small buffer
                        except:
                            pass
                        
                        # Use suggested wait time or calculate exponential backoff
                        if wait_time:
                            sleep_time = wait_time
                        else:
                            sleep_time = self.handle_rate_limit(attempt)
                            
                        print(f"⚠️ Rate limit hit, waiting {sleep_time:.2f}s before retry...")
                        time.sleep(sleep_time)
                        continue
                
                if attempt == self.config.max_retries - 1:
                    raise Exception(f"Anthropic API failed after {self.config.max_retries} attempts: {str(e)}")
                
                # Exponential backoff for other errors
                sleep_time = self._exponential_backoff(attempt)
                time.sleep(sleep_time)
        
        raise Exception("Max retries exceeded")
    
    def get_available_models(self) -> List[ModelInfo]:
        """Get list of available Anthropic models."""
        return list(self.MODELS.values())
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for Anthropic models.
        
        Anthropic uses approximately 3.5-4 characters per token.
        This is a rough estimate - actual tokenization may vary.
        """
        return len(text) // 4
    
    def handle_rate_limit(self, attempt: int) -> float:
        """
        Handle Anthropic rate limiting with exponential backoff.
        
        Anthropic typically uses 429 status codes for rate limiting.
        """
        base_delay = 2.0  # Start with 2 seconds
        max_delay = 120.0  # Max 2 minutes
        
        return self._exponential_backoff(attempt, base_delay, max_delay)
    
    def get_model_by_name(self, model_name: str) -> Optional[str]:
        """Get the full model identifier by partial name."""
        model_name_lower = model_name.lower()
        
        # Direct match
        if model_name in self.MODELS:
            return model_name
        
        # Partial matches
        for model_id, model_info in self.MODELS.items():
            if (model_name_lower in model_info.name.lower() or 
                model_name_lower in model_id.lower()):
                return model_id
        
        return None
    
    @classmethod
    def get_default_model(cls) -> str:
        """Get the default Anthropic model."""
        return 'claude-3-5-sonnet-20241022'
    
    @classmethod
    def get_cheapest_model(cls) -> str:
        """Get the most cost-effective Anthropic model."""
        return 'claude-3-haiku-20240307'
    
    @classmethod
    def get_most_capable_model(cls) -> str:
        """Get the most capable Anthropic model."""
        return 'claude-3-opus-20240229'
