"""
CLI Help system for LLM providers and models.

This module provides comprehensive help information about available
LLM providers, models, pricing, and usage recommendations.
"""

from typing import Dict, List, Any
from tabulate import tabulate
from .factory import LLMProviderFactory
from .base import ModelInfo


class LLMCLIHelp:
    """CLI help system for LLM providers."""
    
    @staticmethod
    def format_cost(cost: float) -> str:
        """Format cost for display."""
        if cost >= 1.0:
            return f"${cost:.3f}"
        elif cost >= 0.001:
            return f"${cost:.4f}"
        else:
            return f"${cost:.5f}"
    
    @staticmethod
    def format_tokens(tokens: int) -> str:
        """Format token count for display."""
        if tokens >= 1000000:
            return f"{tokens//1000:.0f}K"
        elif tokens >= 1000:
            return f"{tokens//1000:.0f}K"
        else:
            return str(tokens)
    
    @classmethod
    def print_provider_overview(cls) -> None:
        """Print overview of available providers."""
        print("\n🤖 **LLM PROVIDERS OVERVIEW**")
        print("=" * 60)
        
        providers = LLMProviderFactory.get_available_providers()
        
        for provider in providers:
            validation = LLMProviderFactory.validate_provider_setup(provider)
            status = "✅ Ready" if validation['api_key_found'] else "❌ API Key Missing"
            
            print(f"\n**{provider.upper()}**")
            print(f"Status: {status}")
            
            if provider == 'anthropic':
                print("API Key: Set ANTHROPIC_API_KEY environment variable")
                print("Models: Claude 3.5 Sonnet, Claude 3 Haiku, Claude 3 Opus")
            elif provider == 'openai':
                print("API Key: Set OPENAI_API_KEY environment variable") 
                print("Models: GPT-4, GPT-4 Turbo, GPT-4.1 series, GPT-3.5 series")
    
    @classmethod
    def print_models_table(cls, provider: str = None) -> None:
        """Print comprehensive models table."""
        print("\n🎯 **SUPPORTED MODELS & PRICING**")
        print("=" * 120)
        
        all_models = LLMProviderFactory.get_all_models()
        
        # Prepare table data
        table_data = []
        headers = [
            "Provider", "Model", "Context", "Output", 
            "Input Cost", "Output Cost", "RPM", "Best For"
        ]
        
        for provider_name, models in all_models.items():
            if provider and provider.lower() != provider_name.lower():
                continue
                
            for model in models:
                # Calculate estimated cost for 10K input + 1K output tokens
                sample_cost = model.estimate_cost(10000, 1000)
                
                table_data.append([
                    provider_name.upper(),
                    model.name,
                    cls.format_tokens(model.context_limit),
                    cls.format_tokens(model.output_limit),
                    cls.format_cost(model.cost_per_1k_input),
                    cls.format_cost(model.cost_per_1k_output),
                    str(model.rpm_limit),
                    ", ".join(model.recommended_for[:2])  # Show first 2 recommendations
                ])
        
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print(f"\n💡 **Cost shown per 1K tokens** | Sample cost (10K input + 1K output): varies by model")
    
    @classmethod
    def print_cost_comparison(cls) -> None:
        """Print cost comparison for common validation scenarios."""
        print("\n💰 **COST COMPARISON FOR PIPELINE VALIDATION**")
        print("=" * 80)
        
        # Typical validation scenarios
        scenarios = [
            ("Small Pipeline", 5000, 500, "5-10 modules, basic validation"),
            ("Medium Pipeline", 15000, 1500, "20-50 modules, comprehensive validation"),
            ("Large Pipeline", 50000, 3000, "100+ modules, full analysis"),
            ("Enterprise Pipeline", 100000, 5000, "Complex enterprise pipeline")
        ]
        
        all_models = LLMProviderFactory.get_all_models()
        
        for scenario_name, input_tokens, output_tokens, description in scenarios:
            print(f"\n**{scenario_name}** ({description})")
            print(f"Estimated tokens: {input_tokens:,} input + {output_tokens:,} output")
            print("-" * 60)
            
            costs = []
            for provider_name, models in all_models.items():
                for model in models[:3]:  # Show top 3 models per provider
                    cost = model.estimate_cost(input_tokens, output_tokens)
                    costs.append((f"{provider_name.upper()}: {model.name}", cost))
            
            # Sort by cost
            costs.sort(key=lambda x: x[1])
            
            for model_name, cost in costs[:6]:  # Show 6 cheapest options
                print(f"  {model_name:<35} ${cost:.4f}")
    
    @classmethod
    def print_recommendations(cls) -> None:
        """Print model recommendations for different use cases."""
        print("\n🎯 **MODEL RECOMMENDATIONS**")
        print("=" * 60)
        
        recommendations = LLMProviderFactory.get_model_recommendations()
        
        for use_case, rec in recommendations.items():
            print(f"\n**{use_case.replace('_', ' ').title()}**")
            print(f"Description: {rec['description']}")
            print(f"Anthropic: {rec['anthropic']}")
            print(f"OpenAI: {rec['openai']}")
    
    @classmethod
    def print_setup_guide(cls) -> None:
        """Print setup guide for LLM providers."""
        print("\n⚙️ **SETUP GUIDE**")
        print("=" * 50)
        
        print("\n**1. Choose Your Provider**")
        print("   • Anthropic: Claude models, excellent reasoning")
        print("   • OpenAI: GPT models, wide variety of options")
        
        print("\n**2. Get API Key**")
        print("   • Anthropic: https://console.anthropic.com/")
        print("   • OpenAI: https://platform.openai.com/api-keys")
        
        print("\n**3. Set Environment Variable**")
        print("   • Anthropic: export ANTHROPIC_API_KEY='your-key-here'")
        print("   • OpenAI: export OPENAI_API_KEY='your-key-here'")
        
        print("\n**4. Install Dependencies**")
        print("   • Anthropic: pip install anthropic")
        print("   • OpenAI: pip install openai")
        
        print("\n**5. Run Validation**")
        print("   • python main.py --provider anthropic --model claude-3-haiku-20240307")
        print("   • python main.py --provider openai --model gpt-4.1-mini")
    
    @classmethod
    def print_usage_examples(cls) -> None:
        """Print usage examples."""
        print("\n📖 **USAGE EXAMPLES**")
        print("=" * 50)
        
        examples = [
            ("Cost-effective validation", "python main.py --provider anthropic --model claude-3-haiku-20240307"),
            ("Balanced performance", "python main.py --provider openai --model gpt-4-turbo"),
            ("Highest quality", "python main.py --provider anthropic --model claude-3-opus-20240229"),
            ("Large pipeline", "python main.py --provider openai --model gpt-4.1-long-context"),
            ("Budget-friendly", "python main.py --provider openai --model gpt-4.1-nano"),
            ("With custom API key", "python main.py --provider openai --model gpt-4 --api-key your-key"),
            ("Output to file", "python main.py --provider anthropic --output report.html"),
        ]
        
        for description, command in examples:
            print(f"\n**{description}:**")
            print(f"  {command}")
    
    @classmethod
    def print_full_help(cls) -> None:
        """Print comprehensive help information."""
        cls.print_provider_overview()
        cls.print_models_table()
        cls.print_cost_comparison()
        cls.print_recommendations()
        cls.print_setup_guide()
        cls.print_usage_examples()
        
        print("\n" + "=" * 80)
        print("🚀 **Ready to validate your Nextflow pipelines with AI!**")
        print("For more help: python main.py --help")
        print("=" * 80)
    
    @classmethod
    def print_provider_help(cls, provider: str) -> None:
        """Print help for a specific provider."""
        provider_lower = provider.lower()
        
        if provider_lower not in LLMProviderFactory.get_available_providers():
            print(f"❌ Provider '{provider}' not supported")
            return
        
        print(f"\n🤖 **{provider.upper()} PROVIDER HELP**")
        print("=" * 60)
        
        # Provider-specific information
        if provider_lower == 'anthropic':
            print("**Anthropic Claude Models**")
            print("• Claude 3.5 Sonnet: Most capable, best for complex analysis")
            print("• Claude 3 Haiku: Fast and cost-effective")
            print("• Claude 3 Opus: Highest quality reasoning")
            print("\n**Setup:**")
            print("1. Get API key: https://console.anthropic.com/")
            print("2. Set: export ANTHROPIC_API_KEY='your-key'")
            print("3. Install: pip install anthropic")
            
        elif provider_lower == 'openai':
            print("**OpenAI GPT Models**")
            print("• GPT-4 Turbo: Large context, balanced cost")
            print("• GPT-4.1 Mini: Cost-effective with good performance")
            print("• GPT-4.1 Nano: Ultra cost-effective")
            print("• GPT-4.5 Preview: Cutting-edge capabilities")
            print("\n**Setup:**")
            print("1. Get API key: https://platform.openai.com/api-keys")
            print("2. Set: export OPENAI_API_KEY='your-key'")
            print("3. Install: pip install openai")
        
        # Show models table for this provider
        cls.print_models_table(provider)


def main():
    """Main CLI help function."""
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'models':
            LLMCLIHelp.print_models_table()
        elif command == 'costs':
            LLMCLIHelp.print_cost_comparison()
        elif command == 'setup':
            LLMCLIHelp.print_setup_guide()
        elif command == 'examples':
            LLMCLIHelp.print_usage_examples()
        elif command in ['anthropic', 'openai']:
            LLMCLIHelp.print_provider_help(command)
        else:
            LLMCLIHelp.print_full_help()
    else:
        LLMCLIHelp.print_full_help()


if __name__ == '__main__':
    main()
