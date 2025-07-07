"""
LLM Provider Factory for creating and managing LLM providers.

This module provides a factory pattern for creating LLM providers
and utilities for provider discovery and configuration.
"""

import os
from typing import Dict, List, Optional, Type, Any
from .base import LLMProvider, LLMConfig, ModelInfo
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider


class LLMProviderFactory:
    """Factory for creating and managing LLM providers."""
    
    # Registry of available providers
    PROVIDERS: Dict[str, Type[LLMProvider]] = {
        'anthropic': AnthropicProvider,
        'openai': OpenAIProvider,
    }
    
    @classmethod
    def create_provider(cls, config: LLMConfig) -> LLMProvider:
        """
        Create an LLM provider instance.
        
        Args:
            config: LLM configuration
            
        Returns:
            Configured LLM provider instance
            
        Raises:
            ValueError: If provider is not supported
        """
        provider_name = config.provider.lower()
        
        if provider_name not in cls.PROVIDERS:
            available = ', '.join(cls.PROVIDERS.keys())
            raise ValueError(
                f"Provider '{config.provider}' not supported. "
                f"Available providers: {available}"
            )
        
        provider_class = cls.PROVIDERS[provider_name]
        return provider_class(config)
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available provider names."""
        return list(cls.PROVIDERS.keys())
    
    @classmethod
    def get_all_models(cls) -> Dict[str, List[ModelInfo]]:
        """
        Get all available models from all providers.
        
        Returns:
            Dictionary mapping provider names to their model lists
        """
        all_models = {}
        
        for provider_name, provider_class in cls.PROVIDERS.items():
            try:
                # Access models directly from class attributes for display purposes
                if hasattr(provider_class, 'MODELS'):
                    all_models[provider_name] = list(provider_class.MODELS.values())
                else:
                    all_models[provider_name] = []
            except Exception:
                all_models[provider_name] = []
        
        return all_models
    
    @classmethod
    def find_model(cls, model_name: str) -> Optional[tuple[str, ModelInfo]]:
        """
        Find a model by name across all providers.
        
        Args:
            model_name: Model name to search for
            
        Returns:
            Tuple of (provider_name, model_info) if found, None otherwise
        """
        model_name_lower = model_name.lower()
        
        for provider_name, provider_class in cls.PROVIDERS.items():
            dummy_config = LLMConfig(
                provider=provider_name,
                model='dummy',
                api_key='dummy'
            )
            
            try:
                provider = provider_class(dummy_config)
                models = provider.get_available_models()
                
                for model in models:
                    if (model_name_lower in model.name.lower() or
                        model_name_lower == model.name.lower()):
                        return provider_name, model
                        
            except Exception:
                continue
        
        return None
    
    @classmethod
    def get_model_recommendations(cls) -> Dict[str, Dict[str, str]]:
        """
        Get model recommendations for different use cases.
        
        Returns:
            Dictionary with recommendations for different scenarios
        """
        return {
            'cost_effective': {
                'anthropic': AnthropicProvider.get_cheapest_model(),
                'openai': OpenAIProvider.get_cheapest_model(),
                'description': 'Most cost-effective models for budget-conscious validation'
            },
            'balanced': {
                'anthropic': AnthropicProvider.get_default_model(),
                'openai': OpenAIProvider.get_default_model(),
                'description': 'Balanced performance and cost for general use'
            },
            'highest_quality': {
                'anthropic': AnthropicProvider.get_most_capable_model(),
                'openai': OpenAIProvider.get_most_capable_model(),
                'description': 'Highest quality models for critical validation'
            },
            'large_pipelines': {
                'anthropic': 'claude-3-5-sonnet-20241022',
                'openai': 'gpt-4-turbo',
                'description': 'Models with large context windows for complex pipelines'
            }
        }
    
    @classmethod
    def create_from_env(cls, provider: str, model: Optional[str] = None) -> LLMProvider:
        """
        Create provider from environment variables.
        
        Args:
            provider: Provider name ('anthropic' or 'openai')
            model: Optional model name (uses default if not specified)
            
        Returns:
            Configured LLM provider
            
        Raises:
            ValueError: If required environment variables are missing
        """
        provider_lower = provider.lower()
        
        # Get API key from environment
        if provider_lower == 'anthropic':
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY environment variable required for Anthropic provider"
                )
            default_model = AnthropicProvider.get_default_model()
            
        elif provider_lower == 'openai':
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable required for OpenAI provider"
                )
            default_model = OpenAIProvider.get_default_model()
            
        else:
            raise ValueError(f"Unsupported provider: {provider}")
        
        # Use provided model or default
        selected_model = model or default_model
        
        config = LLMConfig(
            provider=provider_lower,
            model=selected_model,
            api_key=api_key
        )
        
        return cls.create_provider(config)
    
    @classmethod
    def validate_provider_setup(cls, provider: str) -> Dict[str, Any]:
        """
        Validate that a provider is properly set up.
        
        Args:
            provider: Provider name to validate
            
        Returns:
            Dictionary with validation results
        """
        result = {
            'provider': provider,
            'available': False,
            'api_key_found': False,
            'models_accessible': False,
            'error': None
        }
        
        try:
            provider_lower = provider.lower()
            
            # Check if provider is supported
            if provider_lower not in cls.PROVIDERS:
                result['error'] = f"Provider '{provider}' not supported"
                return result
            
            result['available'] = True
            
            # Check for API key
            if provider_lower == 'anthropic':
                api_key = os.getenv('ANTHROPIC_API_KEY')
            elif provider_lower == 'openai':
                api_key = os.getenv('OPENAI_API_KEY')
            else:
                result['error'] = f"Unknown provider: {provider}"
                return result
            
            if api_key:
                result['api_key_found'] = True
                
                # Try to create provider and get models
                try:
                    provider_instance = cls.create_from_env(provider_lower)
                    models = provider_instance.get_available_models()
                    if models:
                        result['models_accessible'] = True
                except Exception as e:
                    result['error'] = f"Failed to access models: {str(e)}"
            else:
                result['error'] = f"API key not found in environment"
        
        except Exception as e:
            result['error'] = str(e)
        
        return result
