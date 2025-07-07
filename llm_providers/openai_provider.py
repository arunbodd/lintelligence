"""
OpenAI GPT provider implementation.

This module provides the OpenAI GPT LLM provider with support for
all GPT models including GPT-4, GPT-4 Turbo, GPT-4.1 series, and GPT-3.5.
"""

import os
import time
import json
import re
import asyncio
from typing import Dict, List, Optional, Any
from .base import LLMProvider, ModelInfo, LLMConfig, LLMResponse


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider implementation."""
    
    # Based on official OpenAI pricing (January 2025)
    MODELS = {
        # GPT-4 Series
        'gpt-4': ModelInfo(
            name='GPT-4',
            context_limit=8192,
            output_limit=4096,
            cost_per_1k_input=0.03,    # $30 per 1M = $0.03 per 1K
            cost_per_1k_output=0.06,   # $60 per 1M = $0.06 per 1K
            rpm_limit=500,
            description='Original GPT-4 model with high quality reasoning',
            recommended_for=['quality_validation', 'complex_reasoning']
        ),
        'gpt-4-0613': ModelInfo(
            name='GPT-4 (June 13)',
            context_limit=8192,
            output_limit=4096,
            cost_per_1k_input=0.03,
            cost_per_1k_output=0.06,
            rpm_limit=500,
            description='GPT-4 snapshot from June 13',
            recommended_for=['stable_features', 'consistent_results']
        ),
        'gpt-4-32k': ModelInfo(
            name='GPT-4 32K',
            context_limit=32768,
            output_limit=4096,
            cost_per_1k_input=0.06,    # $60 per 1M = $0.06 per 1K
            cost_per_1k_output=0.12,   # $120 per 1M = $0.12 per 1K
            rpm_limit=200,
            description='GPT-4 with extended 32K context window',
            recommended_for=['large_pipelines', 'comprehensive_analysis']
        ),
        'gpt-4-32k-0613': ModelInfo(
            name='GPT-4 32K (June 13)',
            context_limit=32768,
            output_limit=4096,
            cost_per_1k_input=0.06,
            cost_per_1k_output=0.12,
            rpm_limit=200,
            description='GPT-4 32K snapshot from June 13',
            recommended_for=['stable_large_context', 'reliable_analysis']
        ),
        'gpt-4-turbo': ModelInfo(
            name='GPT-4 Turbo',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,    # $10 per 1M = $0.01 per 1K
            cost_per_1k_output=0.03,   # $30 per 1M = $0.03 per 1K
            rpm_limit=800,
            description='GPT-4 Turbo with improved efficiency and larger context',
            recommended_for=['efficient_validation', 'large_context', 'cost_effective']
        ),
        'gpt-4-turbo-2024-04-09': ModelInfo(
            name='GPT-4 Turbo (Apr 9, 2024)',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            rpm_limit=800,
            description='GPT-4 Turbo snapshot from April 9, 2024',
            recommended_for=['stable_turbo_features', 'production_use']
        ),
        'gpt-4-0125-preview': ModelInfo(
            name='GPT-4 Preview (Jan 25)',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            rpm_limit=800,
            description='GPT-4 preview from January 25',
            recommended_for=['preview_features', 'testing']
        ),
        'gpt-4-1106-preview': ModelInfo(
            name='GPT-4 Preview (Nov 6)',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            rpm_limit=800,
            description='GPT-4 preview from November 6',
            recommended_for=['json_mode', 'function_calling']
        ),
        'gpt-4-vision-preview': ModelInfo(
            name='GPT-4 Vision Preview',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            rpm_limit=800,
            description='GPT-4 with vision capabilities',
            recommended_for=['multimodal_analysis', 'experimental']
        ),
        'gpt-4-1106-vision-preview': ModelInfo(
            name='GPT-4 Vision (Nov 6)',
            context_limit=128000,
            output_limit=4096,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            rpm_limit=800,
            description='GPT-4 Vision snapshot from November 6',
            recommended_for=['stable_vision_features', 'multimodal_production']
        ),
        
        # GPT-4.1 Series
        'gpt-4.1': ModelInfo(
            name='GPT-4.1',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.03,    # $30 per 1M = $0.03 per 1K
            cost_per_1k_output=0.12,   # $120 per 1M = $0.12 per 1K
            rpm_limit=600,
            description='Enhanced GPT-4.1 with improved capabilities',
            recommended_for=['advanced_reasoning', 'complex_validation', 'latest_features']
        ),
        'gpt-4.1-2025-04-14': ModelInfo(
            name='GPT-4.1 (Apr 14, 2025)',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.03,
            cost_per_1k_output=0.12,
            rpm_limit=600,
            description='GPT-4.1 snapshot from April 14, 2025',
            recommended_for=['stable_advanced_features', 'production_ready']
        ),
        'gpt-4.1-mini': ModelInfo(
            name='GPT-4.1 Mini',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.003,   # $3 per 1M = $0.003 per 1K
            cost_per_1k_output=0.012,  # $12 per 1M = $0.012 per 1K
            rpm_limit=1500,
            description='Efficient GPT-4.1 Mini for cost-effective validation',
            recommended_for=['cost_effective', 'high_volume', 'balanced_performance']
        ),
        'gpt-4.1-mini-2025-04-14': ModelInfo(
            name='GPT-4.1 Mini (Apr 14, 2025)',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.012,
            rpm_limit=1500,
            description='GPT-4.1 Mini snapshot from April 14, 2025',
            recommended_for=['stable_mini_features', 'production_efficiency']
        ),
        
        # GPT-4o Series (Latest and most efficient)
        'gpt-4o': ModelInfo(
            name='GPT-4o',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.005,   # $5 per 1M = $0.005 per 1K
            cost_per_1k_output=0.015,  # $15 per 1M = $0.015 per 1K
            rpm_limit=1000,
            description='Latest GPT-4o model with optimal performance and efficiency',
            recommended_for=['general_validation', 'balanced_performance', 'latest_features']
        ),
        'gpt-4o-mini': ModelInfo(
            name='GPT-4o Mini',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.00015, # $0.15 per 1M = $0.00015 per 1K
            cost_per_1k_output=0.0006, # $0.60 per 1M = $0.0006 per 1K
            rpm_limit=1000,
            description='Most cost-effective GPT-4 class model, ideal for budget-conscious validation',
            recommended_for=['budget_validation', 'high_volume', 'cost_effective']
        ),
        'gpt-4o-2024-08-06': ModelInfo(
            name='GPT-4o (Aug 6, 2024)',
            context_limit=128000,
            output_limit=16384,
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            rpm_limit=1000,
            description='GPT-4o snapshot from August 6, 2024',
            recommended_for=['stable_features', 'production_use']
        ),
        
        # GPT-4.5 Series
        'gpt-4.5-preview': ModelInfo(
            name='GPT-4.5 Preview',
            context_limit=400000,
            output_limit=32768,
            cost_per_1k_input=0.05,    # $50 per 1M = $0.05 per 1K
            cost_per_1k_output=0.20,   # $200 per 1M = $0.20 per 1K
            rpm_limit=200,
            description='Cutting-edge GPT-4.5 preview with maximum capabilities',
            recommended_for=['research', 'highest_quality', 'experimental_features']
        ),
        
        # GPT-3.5 Series
        'gpt-3.5-turbo': ModelInfo(
            name='GPT-3.5 Turbo',
            context_limit=16385,
            output_limit=4096,
            cost_per_1k_input=0.0005,  # $0.50 per 1M = $0.0005 per 1K
            cost_per_1k_output=0.0015, # $1.50 per 1M = $0.0015 per 1K
            rpm_limit=3500,
            description='Fast and efficient GPT-3.5 Turbo',
            recommended_for=['quick_validation', 'cost_effective', 'high_throughput']
        ),
        'gpt-3.5-turbo-0125': ModelInfo(
            name='GPT-3.5 Turbo (Jan 25)',
            context_limit=16385,
            output_limit=4096,
            cost_per_1k_input=0.0005,
            cost_per_1k_output=0.0015,
            rpm_limit=3500,
            description='GPT-3.5 Turbo snapshot from January 25',
            recommended_for=['stable_turbo_features', 'reliable_performance']
        ),
        'gpt-3.5-turbo-1106': ModelInfo(
            name='GPT-3.5 Turbo (Nov 6)',
            context_limit=16385,
            output_limit=4096,
            cost_per_1k_input=0.001,   # $1.00 per 1M = $0.001 per 1K
            cost_per_1k_output=0.002,  # $2.00 per 1M = $0.002 per 1K
            rpm_limit=3500,
            description='GPT-3.5 Turbo snapshot from November 6',
            recommended_for=['json_mode', 'function_calling']
        ),
        'gpt-3.5-turbo-instruct': ModelInfo(
            name='GPT-3.5 Turbo Instruct',
            context_limit=4096,
            output_limit=4096,
            cost_per_1k_input=0.0015,  # $1.50 per 1M = $0.0015 per 1K
            cost_per_1k_output=0.002,  # $2.00 per 1M = $0.002 per 1K
            rpm_limit=3500,
            description='GPT-3.5 Turbo optimized for instruction following',
            recommended_for=['instruction_following', 'completion_tasks']
        ),
        
        # O1 Series
        'o1-preview': ModelInfo(
            name='O1 Preview',
            context_limit=128000,
            output_limit=32768,
            cost_per_1k_input=0.015,   # $15 per 1M = $0.015 per 1K
            cost_per_1k_output=0.06,   # $60 per 1M = $0.06 per 1K
            rpm_limit=200,
            description='Advanced reasoning model with enhanced problem-solving',
            recommended_for=['complex_reasoning', 'advanced_analysis', 'research']
        ),
        'o1-mini': ModelInfo(
            name='O1 Mini',
            context_limit=128000,
            output_limit=65536,
            cost_per_1k_input=0.003,   # $3 per 1M = $0.003 per 1K
            cost_per_1k_output=0.012,  # $12 per 1M = $0.012 per 1K
            rpm_limit=1000,
            description='Efficient reasoning model for cost-effective analysis',
            recommended_for=['balanced_reasoning', 'cost_effective_analysis']
        ),
        
        # O3 Series
        'o3-mini': ModelInfo(
            name='O3 Mini',
            context_limit=128000,
            output_limit=65536,
            cost_per_1k_input=0.001,   # $1 per 1M = $0.001 per 1K
            cost_per_1k_output=0.004,  # $4 per 1M = $0.004 per 1K
            rpm_limit=1500,
            description='Latest generation efficient reasoning model',
            recommended_for=['next_gen_reasoning', 'efficient_analysis', 'production_ready']
        )
    }
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.validate_config()
    
    def initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.config.api_key)
        except ImportError:
            raise ImportError("OpenAI library not installed. Install with: pip install openai")
    
    def validate_config(self) -> None:
        """Validate OpenAI-specific configuration."""
        if not self.config.api_key:
            raise ValueError("OpenAI API key is required")
        
        if self.config.model not in self.MODELS:
            available_models = list(self.MODELS.keys())
            raise ValueError(f"Unsupported OpenAI model: {self.config.model}. Available models: {available_models}")
    
    def get_model_info(self, model_name: str = None) -> ModelInfo:
        """Get information about a specific model or the current configured model."""
        if model_name is None:
            # Return current configured model info
            return self.MODELS[self.config.model]
        else:
            # Return info for specified model (delegate to parent implementation)
            return super().get_model_info(model_name)
    
    def get_available_models(self) -> List[ModelInfo]:
        """Get list of available models for this provider."""
        return list(self.MODELS.values())
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for given text using simple approximation."""
        # Simple approximation: ~4 characters per token for English text
        # This is a rough estimate; for production use, consider using tiktoken
        return len(text) // 4
    
    def handle_rate_limit(self, attempt: int) -> float:
        """Handle rate limiting with exponential backoff."""
        base_delay = 1.0
        max_delay = 60.0
        delay = min(base_delay * (2 ** attempt), max_delay)
        return delay
    
    def validate_rule(self, rule: Dict, context: Dict, prompt: str) -> LLMResponse:
        """Validate a rule using OpenAI API."""
        try:
            model_info = self.get_model_info()
            
            # Make API call with retry logic
            response = self._make_api_call_sync(prompt, model_info)
            
            return response
            
        except Exception as e:
            return LLMResponse(
                content=f"OpenAI API error: {str(e)}",
                input_tokens=None,
                output_tokens=None,
                cost=None,
                model=self.config.model
            )
    
    def generate_response(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.1) -> str:
        """Generate a response using OpenAI API - unified interface method."""
        try:
            model_info = self.get_model_info()
            
            # Override max_tokens and temperature if provided
            call_params = {
                'max_tokens': min(max_tokens, model_info.output_limit),
                'temperature': temperature
            }
            
            # Make API call with custom parameters
            response = self._make_api_call_sync(prompt, model_info, **call_params)
            
            return response
            
        except Exception as e:
            return f"OpenAI API error: {str(e)}"
    
    def _build_prompt(self, rule: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Build the validation prompt for OpenAI."""
        prompt_parts = [
            f"You are a Nextflow pipeline validation expert. Analyze the following rule:",
            f"\nRule: {rule.get('description', 'No description')}",
            f"Category: {rule.get('category', 'Unknown')}",
            f"Subcategory: {rule.get('subcategory', 'Unknown')}",
            f"Severity: {rule.get('severity', 'Unknown')}",
        ]
        
        # Add context information
        if 'pipeline_files' in context:
            prompt_parts.append(f"\nPipeline files: {list(context['pipeline_files'].keys())}")
        
        if 'main_workflow' in context:
            prompt_parts.append(f"\nMain workflow content:\n{context['main_workflow']}")
        
        if 'modules' in context:
            prompt_parts.append(f"\nModules found: {list(context['modules'].keys())}")
        
        prompt_parts.extend([
            "\nPlease validate this rule and respond in the following JSON format:",
            "{",
            '  "status": "pass|fail|warning",',
            '  "message": "Brief explanation of the validation result",',
            '  "line_number": null or line number if applicable,',
            '  "reasoning": "Detailed reasoning in bullet points",',
            '  "solution": "Proposed fix or improvement",',
            '  "suggested_files": ["list of files to modify or check"]',
            "}"
        ])
        
        return "\n".join(prompt_parts)
    
    def _make_api_call_sync(self, prompt: str, model_info: ModelInfo, **kwargs) -> LLMResponse:
        """Make synchronous API call to OpenAI with retry logic."""
        max_retries = 3
        base_delay = 1
        
        # Extract parameters with defaults
        max_tokens = kwargs.get('max_tokens', min(4096, model_info.output_limit))
        temperature = kwargs.get('temperature', 0.1)
        
        # Debug logging for API call
        print(f"\n🔍 DEBUG: OpenAI API Call")
        print(f"🔍 Model: {self.config.model}")
        print(f"🔍 Prompt length: {len(prompt)} characters")
        print(f"🔍 Max tokens: {max_tokens}")
        print(f"🔍 Temperature: {temperature}")
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": "You are a Nextflow pipeline validation expert."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                # Debug logging for successful response
                print(f"\n✅ DEBUG: OpenAI API Response Received")
                print(f"✅ Response type: {type(response)}")
                content = response.choices[0].message.content
                print(f"✅ Response content length: {len(content)} characters")
                print(f"✅ Response first 100 chars: {content[:100]}...")
                
                # Extract token usage information
                usage = response.usage if hasattr(response, 'usage') else None
                input_tokens = usage.prompt_tokens if usage else None
                output_tokens = usage.completion_tokens if usage else None
                
                # Calculate cost if token usage is available
                cost = None
                if input_tokens and output_tokens:
                    cost = model_info.estimate_cost(input_tokens, output_tokens)
                
                return LLMResponse(
                    content=response.choices[0].message.content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    model=self.config.model
                )
                
            except Exception as e:
                # Debug logging for errors
                print(f"\n❌ DEBUG: OpenAI API Error on attempt {attempt+1}/{max_retries}")
                print(f"❌ Error type: {type(e)}")
                print(f"❌ Error message: {str(e)}")
                
                # Check for rate limit errors specifically
                if isinstance(e, openai.RateLimitError) or "rate_limit" in str(e).lower() or "429" in str(e):
                    # Extract wait time if available in the error message
                    wait_time = None
                    try:
                        import re
                        wait_match = re.search(r'try again in ([0-9.]+)s', str(e))
                        if wait_match:
                            wait_time = float(wait_match.group(1)) + 0.5  # Add a small buffer
                    except:
                        pass
                    
                    # Use suggested wait time or calculate exponential backoff with jitter
                    if wait_time:
                        delay = wait_time
                    else:
                        # More aggressive backoff for rate limits
                        delay = base_delay * (3 ** attempt) + random.uniform(1, 3)
                    
                    print(f"⚠️ Rate limit hit, waiting {delay:.2f}s before retry...")
                    time.sleep(delay)
                    continue
                
                # For other errors
                if attempt == max_retries - 1:
                    raise e
                
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    
    async def _make_api_call(self, prompt: str, model_info: ModelInfo) -> str:
        """Make API call to OpenAI with retry logic."""
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": "You are a Nextflow pipeline validation expert."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=min(4096, model_info.output_limit),
                    temperature=0.1
                )
                
                return response.choices[0].message.content
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
    
    def _parse_response(self, response: str, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Parse OpenAI response into validation result dictionary."""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
            else:
                # Fallback parsing
                result_data = {
                    "status": "warning",
                    "message": "Could not parse AI response",
                    "reasoning": response[:500],
                    "solution": "Manual review required",
                    "suggested_files": []
                }
            
            return {
                'rule_id': rule.get('id'),
                'status': result_data.get('status', 'warning'),
                'message': result_data.get('message', 'No message provided'),
                'line_number': result_data.get('line_number'),
                'category': rule.get('category'),
                'subcategory': rule.get('subcategory'),
                'ai_reasoning': result_data.get('reasoning', 'No reasoning provided'),
                'ai_solution': result_data.get('solution', 'No solution provided'),
                'suggested_files': result_data.get('suggested_files', [])
            }
            
        except Exception as e:
            return {
                'rule_id': rule.get('id'),
                'status': 'warning',
                'message': f"Failed to parse AI response: {str(e)}",
                'line_number': None,
                'category': rule.get('category'),
                'subcategory': rule.get('subcategory'),
                'ai_reasoning': "Response parsing failed",
                'ai_solution': "Manual review required",
                'suggested_files': []
            }
