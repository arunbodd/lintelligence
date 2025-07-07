#!/usr/bin/env python3
"""
Smart Nextflow Pipeline Validator with LLM-powered context understanding.

This validator uses AI to understand pipeline context and make intelligent
validation decisions rather than naive file-based checks.
"""

import os
import sys
import json
import yaml
import asyncio
import time
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime
import argparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from functools import partial
from validation_cache import ValidationCache
# LLM Provider imports
from llm_providers.factory import LLMProviderFactory
from llm_providers.base import LLMProvider, LLMConfig, LLMResponse
# Local imports will be defined below
from validation_cache import ValidationCache
from pipeline_detector import PipelineDetector
from rate_limiter import RateLimitManager

# Load environment variables
load_dotenv(Path.home() / '.env')

# Define missing enums and classes
from enum import Enum

class PipelineType(Enum):
    """Enum for different pipeline types."""
    NEXTFLOW_DSL2_NFCORE = "nextflow_dsl2_nfcore"
    NEXTFLOW_DSL2_CUSTOM = "nextflow_dsl2_custom"
    NEXTFLOW_DSL1 = "nextflow_dsl1"
    NEXTFLOW_MIXED = "nextflow_mixed"
    SHELL_BASED = "shell_based"
    PYTHON_BASED = "python_based"
    R_BASED = "r_based"
    PERL_BASED = "perl_based"
    UNKNOWN = "unknown"

class PipelineDetector:
    """Simple pipeline detector for different pipeline types."""
    
    def detect_pipeline_type(self, pipeline_path: Path) -> Tuple[PipelineType, Dict[str, Any]]:
        """Detect pipeline type and return metadata."""
        pipeline_path = Path(pipeline_path)
        
        # First check for standard Nextflow files in root
        main_nf = pipeline_path / 'main.nf'
        nextflow_config = pipeline_path / 'nextflow.config'
        
        # Search for .nf files recursively up to 5 levels deep
        nf_files = []
        for level in range(6):  # 0 to 5 levels deep
            pattern = '/'.join(['*'] * level) + '/*.nf' if level > 0 else '*.nf'
            nf_files.extend(list(pipeline_path.glob(pattern)))
        
        if main_nf.exists() or nf_files:
            # Determine which file to analyze for DSL version
            analysis_file = main_nf if main_nf.exists() else nf_files[0]
            
            try:
                content = analysis_file.read_text()
                
                # Determine DSL version
                if 'nextflow.enable.dsl=2' in content or 'nextflow.enable.dsl = 2' in content:
                    dsl_version = 'DSL2'
                elif 'nextflow.enable.dsl=1' in content or 'nextflow.enable.dsl = 1' in content:
                    dsl_version = 'DSL1'
                else:
                    # Check for DSL2 syntax patterns
                    if 'workflow {' in content and ('include {' in content or 'process ' in content):
                        dsl_version = 'DSL2'
                    else:
                        dsl_version = 'DSL1'
                
                # Determine pipeline type based on structure
                if main_nf.exists():
                    # Standard structure with main.nf in root
                    if (pipeline_path / 'modules').exists() and (pipeline_path / 'workflows').exists():
                        pipeline_type = PipelineType.NEXTFLOW_DSL2_NFCORE if dsl_version == 'DSL2' else PipelineType.NEXTFLOW_DSL1
                    else:
                        pipeline_type = PipelineType.NEXTFLOW_DSL2_CUSTOM if dsl_version == 'DSL2' else PipelineType.NEXTFLOW_DSL1
                else:
                    # Nextflow files found in subdirectories - custom structure
                    pipeline_type = PipelineType.NEXTFLOW_DSL2_CUSTOM if dsl_version == 'DSL2' else PipelineType.NEXTFLOW_DSL1
                
                # Check for mixed DSL
                mixed_dsl_indicators = 0
                for nf_file in nf_files[:5]:  # Check first 5 files to avoid performance issues
                    try:
                        file_content = nf_file.read_text()
                        if ('nextflow.enable.dsl=1' in file_content and 'nextflow.enable.dsl=2' in file_content) or \
                           ('workflow {' in file_content and 'Channel.' in file_content):
                            mixed_dsl_indicators += 1
                    except Exception:
                        continue
                
                if mixed_dsl_indicators > 0:
                    pipeline_type = PipelineType.NEXTFLOW_MIXED
                
                # Build metadata
                detected_files = [str(f.relative_to(pipeline_path)) for f in nf_files[:10]]  # Limit to first 10
                if main_nf.exists() and 'main.nf' not in detected_files:
                    detected_files.insert(0, 'main.nf')
                
                metadata = {
                    'dsl_version': dsl_version,
                    'detected_files': detected_files,
                    'validation_strategy': 'nextflow_aware',
                    'nf_file_count': len(nf_files),
                    'has_main_nf': main_nf.exists(),
                    'analysis_file': str(analysis_file.relative_to(pipeline_path))
                }
                
                if nextflow_config.exists():
                    metadata['detected_files'].append('nextflow.config')
                    metadata['has_nextflow_config'] = True
                else:
                    metadata['has_nextflow_config'] = False
                
                return pipeline_type, metadata
                
            except Exception as e:
                print(f"Error reading Nextflow file {analysis_file}: {e}")
        
        # Check for shell-based pipeline
        shell_files = list(pipeline_path.glob('*.sh')) + list(pipeline_path.glob('*.bash'))
        if shell_files:
            return PipelineType.SHELL_BASED, {
                'main_scripts': [f.name for f in shell_files[:5]],
                'detected_files': [f.name for f in shell_files],
                'validation_strategy': 'shell_aware'
            }
        
        # Check for Python-based pipeline
        python_files = list(pipeline_path.rglob('*pipeline*.py')) + list(pipeline_path.rglob('*Pipeline*.py'))
        if python_files:
            return PipelineType.PYTHON_BASED, {
                'detected_files': [str(f.relative_to(pipeline_path)) for f in python_files],
                'validation_strategy': 'python_aware'
            }
        
        # Check for R-based pipeline
        r_files = list(pipeline_path.rglob('*.R')) + list(pipeline_path.rglob('*.r'))
        r_pipeline_files = [f for f in r_files if 'pipeline' in f.name.lower() or any(keyword in f.name.lower() for keyword in ['workflow', 'analysis', 'process'])]
        if r_pipeline_files:
            return PipelineType.R_BASED, {
                'detected_files': [str(f.relative_to(pipeline_path)) for f in r_pipeline_files],
                'validation_strategy': 'r_aware'
            }
        
        # Check for Perl-based pipeline
        perl_files = list(pipeline_path.rglob('*.pl')) + list(pipeline_path.rglob('*.pm'))
        perl_pipeline_files = [f for f in perl_files if 'pipeline' in f.name.lower() or any(keyword in f.name.lower() for keyword in ['workflow', 'analysis', 'process'])]
        if perl_pipeline_files:
            return PipelineType.PERL_BASED, {
                'detected_files': [str(f.relative_to(pipeline_path)) for f in perl_pipeline_files],
                'validation_strategy': 'perl_aware'
            }
        
        # Unknown pipeline type
        return PipelineType.UNKNOWN, {
            'detected_files': [],
            'validation_strategy': 'basic'
        }
    
    def get_validation_recommendations(self, pipeline_type: PipelineType, metadata: Dict) -> Dict:
        """Get validation recommendations based on pipeline type."""
        recommendations = {
            'special_considerations': [],
            'focus_areas': [],
            'skip_categories': []
        }
        
        if pipeline_type == PipelineType.NEXTFLOW_DSL1:
            recommendations['special_considerations'].append('DSL1 migration recommended')
            recommendations['focus_areas'].extend(['Documentation', 'General'])
        elif pipeline_type == PipelineType.NEXTFLOW_MIXED:
            recommendations['special_considerations'].append('Mixed DSL detected - standardization needed')
        elif pipeline_type in [PipelineType.SHELL_BASED, PipelineType.PYTHON_BASED]:
            recommendations['special_considerations'].append('Legacy pipeline - modernization recommended')
            recommendations['focus_areas'].extend(['Documentation', 'General'])
            recommendations['skip_categories'].extend(['Module', 'Subworkflow'])
        
        return recommendations

@dataclass
class ValidationResult:
    """Smart validation result with context."""
    rule_id: str
    rule_title: str
    category: str
    subcategory: str
    status: str  # 'pass', 'fail', 'warning', 'not_applicable'
    message: str
    confidence: float  # AI confidence score 0-1
    reasoning: Union[str, List[str]]  # AI reasoning for the decision (bulleted list or string)
    proposed_solution: Optional[str] = None  # AI-proposed solution for failed/warning rules
    suggested_files: Optional[List[str]] = None  # Files that need to be created/modified
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    # Token tracking for cost calculation
    input_tokens: Optional[int] = None  # Number of input tokens used
    output_tokens: Optional[int] = None  # Number of output tokens generated
    cost: Optional[float] = None  # Actual cost for this rule validation

@dataclass
class ComplianceReport:
    """Smart compliance report with AI insights."""
    pipeline_path: str
    total_score: float
    weighted_score: float
    grade: str
    critical_failures: int
    results: List[ValidationResult]
    rule_set_scores: Dict[str, Dict[str, Any]]
    ai_summary: str  # Overall AI assessment

@dataclass
class SmartComplianceReport:
    """Enhanced compliance report for adaptive validation."""
    pipeline_path: str
    total_score: float
    weighted_score: float
    grade: str
    critical_failures: int
    results: List[ValidationResult]
    rule_set_scores: Dict[str, Dict[str, Any]]
    ai_summary: str  # Overall AI assessment

class SmartNextflowValidator:
    """LLM-powered validator that understands pipeline context."""
    
    def __init__(self, rules_dir: str = "rules", max_workers: int = 4, 
             llm_provider: str = "anthropic", llm_model: str = None, llm_api_key: str = None,
             use_cache: bool = True, cache_dir: str = None):
        """Initialize validator with rule files and LLM provider.
        
        Args:
            rules_dir: Directory containing rule YAML files
            max_workers: Number of parallel workers for rule validation
            llm_provider: LLM provider to use ('openai' or 'anthropic')
            llm_model: Specific model to use (optional, uses provider default)
            llm_api_key: API key for the LLM provider
            use_cache: Whether to use caching for validation results
            cache_dir: Custom cache directory (optional)
        """
        from llm_providers.factory import LLMProviderFactory
        
        self.rules_dir = Path(rules_dir)
        self.rules = self._load_rules()
        self.max_workers = max_workers
        self.thread_lock = threading.Lock()
        
        # Initialize pipeline detector for multi-pipeline support
        self.pipeline_detector = PipelineDetector()
        
        # Initialize LLM provider
        try:
            from llm_providers.base import LLMConfig
            config = LLMConfig(
                provider=llm_provider,
                api_key=llm_api_key,
                model=llm_model
            )
            self.llm_provider = LLMProviderFactory.create_provider(config)
            # Validate configuration and initialize client
            self.llm_provider.validate_config()
            self.llm_provider.initialize_client()
            print(f"🤖 Smart validator initialized with {llm_provider.upper()} ({llm_model}) - {max_workers} workers")
        except Exception as e:
            raise ValueError(f"Failed to initialize LLM provider '{llm_provider}': {e}")
        
        # Initialize caching
        self.use_cache = use_cache
        self.cache_dir = cache_dir
        self.cache = None  # Will be initialized per pipeline
        
        # Initialize rate limit manager
        self.rate_limiter = RateLimitManager()
        
        # Rule set weights
        self.rule_set_weights = {
            'ph_core_requirements': 0.45,
            'ph_core_recommendations': 0.35, 
            'amdp_prerequisites': 0.20
        }
    
    def _load_rules(self) -> Dict[str, List[Dict]]:
        """Load validation rules from YAML files."""
        rules = {}
        
        rule_files = {
            'ph_core_requirements': 'ph_core_requirements.yml',
            'ph_core_recommendations': 'ph_core_recommendations.yml',
            'amdp_prerequisites': 'amdp_prerequisites.yml'
        }
        
        for rule_set, filename in rule_files.items():
            rule_file = self.rules_dir / filename
            if rule_file.exists():
                with open(rule_file, 'r') as f:
                    data = yaml.safe_load(f)
                    rules[rule_set] = data.get('rules', [])
                    print(f"✅ Loaded {len(rules[rule_set])} rules from {filename}")
            else:
                print(f"⚠️  Rule file not found: {rule_file}")
                rules[rule_set] = []
        
        return rules
    
    def _analyze_pipeline_structure(self, pipeline_path: Path) -> Dict[str, Any]:
        """Analyze pipeline structure and gather context."""
        context = {
            'pipeline_path': str(pipeline_path),  # Add pipeline path to context
            'has_main_nf': (pipeline_path / 'main.nf').exists(),
            'has_nextflow_config': (pipeline_path / 'nextflow.config').exists(),  # Fixed typo
            'has_readme': len(list(pipeline_path.glob('README*'))) > 0,
            'has_modules_dir': (pipeline_path / 'modules').exists(),
            'has_subworkflows_dir': (pipeline_path / 'subworkflows').exists(),
            'has_workflows_dir': (pipeline_path / 'workflows').exists(),
            # Check for all standard nf-core directories
            'has_assets_dir': (pipeline_path / 'assets').exists(),
            'has_bin_dir': (pipeline_path / 'bin').exists(),
            'has_conf_dir': (pipeline_path / 'conf').exists(),
            'has_docs_dir': (pipeline_path / 'docs').exists(),
            'has_libs_dir': (pipeline_path / 'libs').exists(),
            'has_data_dir': (pipeline_path / 'data').exists(),
            'has_test_dir': (pipeline_path / 'test').exists(),
            # Find all .nf files recursively throughout the entire pipeline directory
            'all_nf_files': list(pipeline_path.rglob('**/*.nf')),
            # Standard directory-specific files (for backward compatibility)
            'module_files': list(pipeline_path.rglob('modules/**/*.nf')),
            'workflow_files': list(pipeline_path.rglob('workflows/**/*.nf')),
            'subworkflow_files': list(pipeline_path.rglob('subworkflows/**/*.nf')),
            # Find all config files recursively
            'config_files': list(pipeline_path.rglob('**/*.config')),
            'test_files': list(pipeline_path.rglob('test*/**/*.nf')),
        }
        
        # Read key files for content analysis
        key_files = {}
        
        # Read main.nf
        main_nf = pipeline_path / 'main.nf'
        if main_nf.exists():
            try:
                key_files['main.nf'] = main_nf.read_text()[:5000]  # First 5k chars
            except Exception as e:
                key_files['main.nf'] = f"Error reading: {e}"
        
        # Read nextflow.config
        config_file = pipeline_path / 'nextflow.config'
        if config_file.exists():
            try:
                key_files['nextflow.config'] = config_file.read_text()[:3000]  # First 3k chars
            except Exception as e:
                key_files['nextflow.config'] = f"Error reading: {e}"
        
        # Read README
        readme_files = list(pipeline_path.glob('README*'))
        if readme_files:
            try:
                key_files['README'] = readme_files[0].read_text()[:2000]  # First 2k chars
            except Exception as e:
                key_files['README'] = f"Error reading: {e}"
        
        context['key_files'] = key_files
        context['file_counts'] = {
            'all_nf_files': len(context['all_nf_files']),  # Total .nf files found recursively
            'modules': len(context['module_files']),
            'workflows': len(context['workflow_files']),
            'subworkflows': len(context['subworkflow_files']),
            'configs': len(context['config_files']),
            'tests': len(context['test_files'])
        }
        
        return context
    
    def _validate_rule_with_ai(self, rule: Dict, context: Dict[str, Any], rule_set_name: str) -> ValidationResult:
        """Use AI to validate a rule with full pipeline context and retry logic."""
        rule_id = rule.get('id', 'unknown')
        rule_title = rule.get('title', 'Unknown Rule')
        category = rule.get('category', 'General')
        subcategory = rule.get('subcategory', 'General')
        description = rule.get('description', '')
        requirement = rule.get('requirement', '')
        
        # Check cache first if enabled
        if self.use_cache and self.cache:
            cached_result = self.cache.get_cached_result(rule_id)
            if cached_result:
                with self.thread_lock:
                    print(f"💾 {rule_id}: Using cached result")
                return cached_result
        
        # Enhanced context for module-related rules
        # Determine context strategy based on rule criticality
        context_strategy = self._get_context_strategy(rule)
        enhanced_context = self._enhance_context_for_rule(rule, context, context_strategy)
        
        # Log context strategy for monitoring
        with self.thread_lock:
            strategy_emoji = "🎯" if context_strategy == "full_context" else "📋"
            print(f"{strategy_emoji} {rule_id}: Using {context_strategy} strategy")
        
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # Add delay between requests to avoid rate limiting
                if attempt > 0:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                
                # Create AI prompt for validation
                prompt = f"""
You are an expert Nextflow pipeline validator. Analyze this pipeline against the following rule:

RULE: {rule_id} - {rule_title}
CATEGORY: {category} / {subcategory}
DESCRIPTION: {description}
REQUIREMENT: {requirement}

PIPELINE CONTEXT:
- Has main.nf: {enhanced_context['has_main_nf']}
- Has nextflow.config: {enhanced_context['has_nextflow_config']}
- Has README: {enhanced_context['has_readme']}
- Has modules directory: {enhanced_context['has_modules_dir']}
- Has subworkflows directory: {enhanced_context['has_subworkflows_dir']}
- Has workflows directory: {enhanced_context['has_workflows_dir']}
- Has assets directory: {enhanced_context['has_assets_dir']}
- Has bin directory: {enhanced_context['has_bin_dir']}
- Has conf directory: {enhanced_context['has_conf_dir']}
- Has docs directory: {enhanced_context['has_docs_dir']}
- Has libs directory: {enhanced_context['has_libs_dir']}
- Has data directory: {enhanced_context['has_data_dir']}
- Has test directory: {enhanced_context['has_test_dir']}
- Total .nf files found (recursive): {enhanced_context['file_counts']['all_nf_files']}
- Module count: {enhanced_context['file_counts']['modules']}
- Workflow count: {enhanced_context['file_counts']['workflows']}
- Subworkflow count: {enhanced_context['file_counts']['subworkflows']}
- Config count: {enhanced_context['file_counts']['configs']}

KEY FILE CONTENTS:
{json.dumps(enhanced_context['key_files'], indent=2)}

ENHANCED ANALYSIS:
{enhanced_context.get('module_analysis', '')}
{enhanced_context.get('subworkflow_analysis', '')}
{enhanced_context.get('workflow_analysis', '')}
{enhanced_context.get('config_analysis', '')}
{enhanced_context.get('docs_analysis', '')}
{enhanced_context.get('test_analysis', '')}
{enhanced_context.get('software_specs_analysis', '')}
{enhanced_context.get('general_analysis', '')}

Based on this context, determine the appropriate status for this rule. Follow this logic:

**STATUS DETERMINATION:**
1. **not_applicable**: Use when the rule fundamentally doesn't apply to this pipeline type
   - Pipeline lacks core Nextflow files (main.nf, nextflow.config) for Nextflow-specific rules
   - Rule requires specific pipeline framework that this pipeline doesn't use
   - Rule is about features/components that don't exist in this pipeline architecture

2. **pass**: Use when the rule applies AND the requirement is satisfied
   - Pipeline meets the rule's requirements
   - Required files/features are present and correct

3. **fail**: Use when the rule applies BUT the requirement is not satisfied
   - Pipeline should meet this rule but doesn't
   - Required files/features are missing or incorrect

4. **warning**: Use for minor issues or recommendations that don't prevent functionality

Respond with a JSON object containing:
{{
"status": "pass|fail|warning|not_applicable",
"confidence": 0.0-1.0,
"reasoning": ["• Bullet point 1", "• Bullet point 2", "• Bullet point 3"],
"message": "Brief summary for the user"
}}

IMPORTANT:
- NEVER use 'pass' for rules that don't apply - use 'not_applicable' instead
- Keep reasoning concise and bulleted (3 bullet points max)
- Be thorough and context-aware. Don't make assumptions based on simple file presence/absence.
- Provide clear explanations in the reasoning section.
"""
                
                # Query AI using the configured LLM provider
                llm_response = self.llm_provider.validate_rule(rule, context, prompt)
                
                # Parse AI response and add token usage information
                result = self._parse_ai_response(rule, llm_response.content)
                
                # Add token usage information to the result
                result.input_tokens = llm_response.input_tokens
                result.output_tokens = llm_response.output_tokens
                result.cost = llm_response.cost
                
                # Check for token limit indicators
                token_limit_indicators = [
                    "I apologize, but I've reached the token limit",
                    "I'll have to stop here due to token constraints",
                    "I've reached the maximum output length",
                    "maximum context length",
                    "maximum token limit"
                ]
                
                is_truncated = any(indicator in llm_response.content for indicator in token_limit_indicators)
                
                # If truncated, add a note to the reasoning
                if is_truncated and hasattr(result, 'reasoning'):
                    if isinstance(result.reasoning, list):
                        result.reasoning.append("⚠️ Note: LLM response was truncated due to token limit")
                    else:
                        result.reasoning = [result.reasoning, "⚠️ Note: LLM response was truncated due to token limit"]
                
                return result
                
            except Exception as e:
                error_str = str(e)
                if "rate_limit" in error_str.lower() or "429" in error_str or "rate limit" in error_str.lower():
                    # Use rate limiter to calculate backoff
                    provider_name = self.llm_provider.__class__.__name__.lower()
                    backoff = self.rate_limiter.handle_rate_limit_error(e, provider_name)
                    
                    if attempt < max_retries - 1:
                        with self.thread_lock:
                            print(f"⏳ Rate limit hit for {rule_id}, backing off for {backoff:.1f}s (attempt {attempt + 1}/{max_retries})")
                            
                            # Show warning for multiple rate limits
                            if self.rate_limiter._consecutive_errors > 3:
                                print(f"⚠️ Multiple rate limits detected ({self.rate_limiter._consecutive_errors}). Consider:")
                                print(f"   1. Using a smaller pipeline or subset of rules")
                                print(f"   2. Increasing your API rate limits")
                                print(f"   3. Running with fewer parallel workers (--max-workers)")
                        
                        time.sleep(backoff)
                        
                        # If this is the second retry, try with limited context
                        if attempt == 1:
                            context_strategy = "limited_context"
                            enhanced_context = self._enhance_context_for_rule(rule, context, context_strategy)
                            with self.thread_lock:
                                print(f"📋 {rule_id}: Reducing to limited_context due to rate limits")
                        
                        continue
                elif "context_length_exceeded" in error_str.lower() or "token limit" in error_str.lower():
                    # Handle token limit errors gracefully
                    with self.thread_lock:
                        print(f"⚠️ {rule_id}: Token limit exceeded, using simplified context")
                    
                    # Try again with simplified context
                    if attempt < max_retries - 1:
                        # Reduce context and try again
                        simplified_prompt = self._prepare_rule_prompt(rule, context, "limited_context")
                        try:
                            llm_response = self.llm_provider.query(simplified_prompt)
                            result = self._parse_ai_response(rule, llm_response.response_text, True)
                            result.input_tokens = llm_response.input_tokens
                            result.output_tokens = llm_response.output_tokens
                            result.cost = llm_response.cost
                            
                            # Add note about reduced context
                            if isinstance(result.reasoning, list):
                                result.reasoning.append("⚠️ Note: Using reduced context due to token limit")
                            else:
                                result.reasoning = [result.reasoning, "⚠️ Note: Using reduced context due to token limit"]
                                
                            return result
                        except Exception:
                            # If simplified context also fails, continue to fallback
                            pass
                elif attempt == max_retries - 1:
                    # Last attempt failed, create a fallback result
                    with self.thread_lock:
                        print(f"❌ {rule_id}: All retries failed - {str(e)}")
                    
                    return ValidationResult(
                        rule_id=rule_id,
                        rule_title=rule.get('title', 'Unknown Rule'),
                        category=rule.get('category', 'General'),
                        subcategory=rule.get('subcategory', 'General'),
                        status='warning',
                        message=f"Validation error: {str(e)}",
                        confidence=0.0,
                        reasoning=["Rule validation failed due to error", f"Error: {str(e)}"] 
                    )
                else:
                    # Re-raise other exceptions
                    raise
        
        return ValidationResult(
            rule_id=rule_id,
            rule_title=rule_title,
            category=category,
            subcategory=subcategory,
            status='warning',
            message='AI validation unavailable, manual review needed',
            confidence=0.0,
            reasoning=['AI service error after retries']
        )
    
    # Class-level rate limiting variables
    _rate_limit_backoff = 0  # Current backoff time in seconds
    _rate_limit_last_error_time = 0  # Last time a rate limit error occurred
    _consecutive_rate_limit_errors = 0  # Count of consecutive rate limit errors
    _rate_limit_lock = threading.Lock()  # Lock for updating rate limit variables
    
    # Note: The main __init__ method is defined above at line ~226
    # This duplicate constructor was causing initialization errors
        
    def validate_pipeline_adaptive(self, pipeline_path: str, output_file: str = None, output_format: str = 'json') -> SmartComplianceReport:
        """Enhanced validation that adapts to different pipeline types and structures.
        
        Args:
            pipeline_path: Path to the pipeline to validate
            output_file: Optional output filename (without extension)
            output_format: Output format ('json', 'html', 'cli', 'all')
        """
        pipeline_path = Path(pipeline_path)
        
        # Initialize cache for this pipeline if caching is enabled
        if self.use_cache:
            self.cache = ValidationCache(str(pipeline_path), self.cache_dir)
            with self.thread_lock:
                cache_stats = self.cache.get_cache_stats()
                if cache_stats['total_cached_rules'] > 0:
                    print(f"💾 Cache found: {cache_stats['total_cached_rules']} cached results")
                else:
                    print("💾 Cache initialized - results will be saved for future runs")
        
        # Step 1: Detect pipeline type and get recommendations
        pipeline_type, detection_metadata = self.pipeline_detector.detect_pipeline_type(pipeline_path)
        validation_recommendations = self.pipeline_detector.get_validation_recommendations(pipeline_type, detection_metadata)
        
        with self.thread_lock:
            print(f"\n🔍 Pipeline Detection Results:")
            print(f"   Type: {pipeline_type.value}")
            print(f"   DSL Version: {detection_metadata.get('dsl_version', 'N/A')}")
            print(f"   Validation Strategy: {detection_metadata.get('validation_strategy', 'N/A')}")
            if detection_metadata.get('detected_files'):
                print(f"   Key Files: {detection_metadata['detected_files'][:3]}...")
        
        # Step 2: Filter and adapt rules based on pipeline type
        applicable_rules = self._get_applicable_rules_for_pipeline_type(pipeline_type, validation_recommendations)
        
        with self.thread_lock:
            print(f"\n📋 Rule Adaptation:")
            print(f"   Total Available Rules: {sum(len(rules) for rules in self.rules.values())}")
            print(f"   Applicable Rules: {len(applicable_rules)}")
            print(f"   Rule Sets: {list(set(rule['rule_set_name'] for rule in applicable_rules))}")
        
        # Step 3: Analyze pipeline structure with enhanced context for detected type
        context = self._analyze_pipeline_structure_adaptive(pipeline_path, pipeline_type, detection_metadata)
        
        # Step 4: Run validation with caching support
        results = []
        cached_count = 0
        fresh_validations = 0
        cost_saved = 0.0
        
        # Separate cached and non-cached rules
        rules_to_validate = []
        for rule in applicable_rules:
            rule_id = rule.get('id', '')
            rule_set_name = rule['rule_set_name']
            
            if self.use_cache and self.cache:
                cached_result = self.cache.get_cached_result(rule_id, rule_set_name)
                if cached_result:
                    results.append(cached_result)
                    cached_count += 1
                    # Estimate cost saved (approximate)
                    cost_saved += self._estimate_rule_cost(rule, context)
                else:
                    rules_to_validate.append((rule, rule_set_name))
            else:
                rules_to_validate.append((rule, rule_set_name))
        
        # Display cache statistics
        if self.use_cache and cached_count > 0:
            with self.thread_lock:
                print(f"\n💾 Cache Hit: {cached_count}/{len(applicable_rules)} rules loaded from cache")
                if cost_saved > 0:
                    print(f"💰 Estimated cost saved: ${cost_saved:.4f}")
        
        # Validate remaining rules with AI
        if rules_to_validate:
            with self.thread_lock:
                print(f"\n🤖 AI Validation: {len(rules_to_validate)} rules to validate")
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit validation tasks
                future_to_rule = {}
                for rule, rule_set_name in rules_to_validate:
                    future = executor.submit(self._validate_rule_with_ai_cached, rule, context, rule_set_name)
                    future_to_rule[future] = (rule, rule_set_name)
                
                # Collect results
                for future in as_completed(future_to_rule):
                    rule, rule_set_name = future_to_rule[future]
                    try:
                        result = future.result()
                        results.append(result)
                        fresh_validations += 1
                        
                        # Cache the result if caching is enabled
                        if self.use_cache and self.cache:
                            self.cache.cache_result(rule.get('id', ''), rule_set_name, result)
                            
                    except Exception as e:
                        with self.thread_lock:
                            print(f"⚠️  Error validating rule {rule.get('id', 'unknown')}: {e}")
        
        # Display final validation statistics
        with self.thread_lock:
            print(f"\n📊 Validation Complete:")
            print(f"   Total Rules: {len(results)}")
            if self.use_cache:
                print(f"   Cached Results: {cached_count}")
                print(f"   Fresh Validations: {fresh_validations}")
                if cost_saved > 0:
                    print(f"   Cost Saved: ${cost_saved:.4f}")
        
        # Step 5: Generate adaptive compliance report
        report = self._generate_adaptive_compliance_report(
            pipeline_path, results, pipeline_type, detection_metadata, validation_recommendations
        )
        
        # Step 6: Write output files if requested
        if output_file:
            self._write_output_files(report, output_file, output_format, pipeline_path)
        
        return report
    
    def _write_output_files(self, report: SmartComplianceReport, output_file: str, output_format: str, pipeline_path: Path):
        """Write validation results to output files in specified format(s)."""
        import json
        from datetime import datetime
        import os
        
        def _ensure_extension(filename: str, extension: str) -> str:
            """Ensure filename has the correct extension without duplication."""
            if filename.endswith(extension):
                return filename
            return f"{filename}{extension}"
        
        try:
            if output_format.lower() == 'json' or output_format.lower() == 'all':
                json_file = _ensure_extension(output_file, '.json')
                json_content = self._generate_json_output(report)
                with open(json_file, 'w') as f:
                    f.write(json_content)
                print(f"JSON report written to: {json_file}")
            
            if output_format.lower() == 'html' or output_format.lower() == 'all':
                html_file = _ensure_extension(output_file, '.html')
                html_content = self._generate_html_output(report)
                with open(html_file, 'w') as f:
                    f.write(html_content)
                print(f"HTML report written to: {html_file}")
            
            if output_format.lower() == 'cli' or output_format.lower() == 'all':
                cli_file = _ensure_extension(output_file, '.txt')
                cli_content = self._generate_cli_output(report)
                with open(cli_file, 'w') as f:
                    f.write(cli_content)
                print(f"CLI report written to: {cli_file}")
                
        except Exception as e:
            print(f"Error writing output files: {e}")
    
    def _format_reasoning_for_html(self, message: str, proposed_solution: str = '', suggested_files: list = None) -> str:
        """Format AI reasoning and solution for HTML display with meaningful bullet points."""
        if suggested_files is None:
            suggested_files = []
        
        
        output_data = {
            "pipeline_path": report.pipeline_path,
            "validation_timestamp": datetime.now().isoformat(),
            "pipeline_type": getattr(report, 'pipeline_type', 'unknown'),
            "total_score": report.total_score,
            "grade": report.grade,
            "critical_failures": report.critical_failures,
            "summary": {
                "total_rules": len(report.results),
                "passed": len([r for r in report.results if r.status == 'pass']),
                "failed": len([r for r in report.results if r.status == 'fail']),
                "warnings": len([r for r in report.results if r.status == 'warning']),
                "not_applicable": len([r for r in report.results if r.status == 'not_applicable']),
            },
            "ai_summary": getattr(report, 'ai_summary', ''),
            "results": []
        }
        
        for result in report.results:
            output_data["results"].append({
                "rule_id": result.rule_id,
                "rule_title": result.rule_title,
                "category": result.category,
                "subcategory": result.subcategory,
                "status": result.status,
                "message": result.message,
                "confidence": getattr(result, 'confidence', 0.0),
                "reasoning": getattr(result, 'reasoning', '')
            })
        
        return json.dumps(output_data, indent=2)
    
    def _generate_rule_set_chart_data(self, results: List[ValidationResult]) -> Dict[str, Dict[str, int]]:
        """Generate chart data for rule set breakdowns."""
        rule_set_data = {}
        
        # Group results by rule set
        for result in results:
            # Determine rule set from rule_id prefix or lookup in rules
            rule_set_name = 'Unknown'
            for rule_set, rules in self.rules.items():
                if any(rule['id'] == result.rule_id for rule in rules):
                    rule_set_name = rule_set
                    break
            
            if rule_set_name not in rule_set_data:
                rule_set_data[rule_set_name] = {
                    'pass': 0,
                    'fail': 0,
                    'warning': 0,
                    'not_applicable': 0
                }
            
            rule_set_data[rule_set_name][result.status] += 1
        
        return rule_set_data
    
    def _generate_html_output(self, report: SmartComplianceReport) -> str:
        """Generate HTML format output with diagrammatic representations."""
        from datetime import datetime
        
        # Count results by status
        passed = len([r for r in report.results if r.status == 'pass'])
        failed = len([r for r in report.results if r.status == 'fail'])
        warnings = len([r for r in report.results if r.status == 'warning'])
        not_applicable = len([r for r in report.results if r.status == 'not_applicable'])
        
        # Generate rule set breakdowns for charts
        rule_set_data = self._generate_rule_set_chart_data(report.results)
        
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nextflow Pipeline Validation Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .score {{ font-size: 2em; font-weight: bold; color: {'#28a745' if report.total_score >= 80 else '#ffc107' if report.total_score >= 60 else '#dc3545'}; }}
        .summary {{ display: flex; justify-content: space-around; margin: 20px 0; }}
        .summary-item {{ text-align: center; padding: 15px; border-radius: 5px; }}
        .pass {{ background-color: #d4edda; color: #155724; }}
        .fail {{ background-color: #f8d7da; color: #721c24; }}
        .warning {{ background-color: #fff3cd; color: #856404; }}
        .not-applicable {{ background-color: #e2e3e5; color: #383d41; }}
        .charts-section {{ margin: 30px 0; }}
        .chart-container {{ display: flex; justify-content: space-around; flex-wrap: wrap; margin: 20px 0; }}
        .chart-item {{ width: 45%; min-width: 400px; margin: 10px; padding: 20px; background: #f8f9fa; border-radius: 8px; }}
        .chart-title {{ text-align: center; font-size: 1.2em; font-weight: bold; margin-bottom: 15px; }}
        .results {{ margin-top: 30px; }}
        .results-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .results-table th, .results-table td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        .results-table th {{ background-color: #f8f9fa; font-weight: bold; position: sticky; top: 0; }}
        .results-table tr:hover {{ background-color: #f5f5f5; }}
        .status-pass {{ color: #28a745; font-weight: bold; }}
        .status-fail {{ color: #dc3545; font-weight: bold; }}
        .status-warning {{ color: #ffc107; font-weight: bold; }}
        .status-not_applicable {{ color: #6c757d; font-weight: bold; }}
        .rule-id {{ font-family: monospace; background-color: #f8f9fa; padding: 2px 6px; border-radius: 3px; }}
        .reasoning {{ max-width: 300px; word-wrap: break-word; }}
        .reasoning ul {{ margin: 0; padding-left: 20px; }}
        .reasoning li {{ margin: 2px 0; }}
        .ai-summary {{ background-color: #e9ecef; padding: 15px; border-radius: 5px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Nextflow Pipeline Validation Report</h1>
            <p><strong>Pipeline:</strong> {report.pipeline_path}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <div class="score">Score: {report.total_score:.1f}% (Grade: {report.grade})</div>
        </div>
        
        <div class="summary">
            <div class="summary-item pass">
                <h3>{passed}</h3>
                <p>Passed</p>
            </div>
            <div class="summary-item fail">
                <h3>{failed}</h3>
                <p>Failed</p>
            </div>
            <div class="summary-item warning">
                <h3>{warnings}</h3>
                <p>Warnings</p>
            </div>
            <div class="summary-item not-applicable">
                <h3>{not_applicable}</h3>
                <p>Not Applicable</p>
            </div>
        </div>
        
        <div class="charts-section">
            <h2> Rule Set Compliance Overview</h2>
            <div class="chart-container">
                <div class="chart-item">
                    <div class="chart-title">Overall Status Distribution</div>
                    <canvas id="overallChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-item">
                    <div class="chart-title">Rule Set Breakdown</div>
                    <canvas id="ruleSetChart" width="400" height="300"></canvas>
                </div>
            </div>
        </div>
        
        {f'<div class="ai-summary"><h3> AI Summary</h3><p>{getattr(report, "ai_summary", "")}</p></div>' if getattr(report, 'ai_summary', '') else ''}
        
        <div class="results">
            <h2>Detailed Results</h2>
            <table class="results-table">
                <thead>
                    <tr>
                        <th>Rule ID</th>
                        <th>Title</th>
                        <th>Category</th>
                        <th>Status</th>
                        <th>Reasoning</th>
                    </tr>
                </thead>
                <tbody>
"""
        
        for result in report.results:
            status_class = f"status-{result.status}"
            
            # Format reasoning
            reasoning_html = ''
            if hasattr(result, 'reasoning') and result.reasoning:
                if isinstance(result.reasoning, list):
                    reasoning_html = '<ul>'
                    for item in result.reasoning:
                        reasoning_html += f'<li>{item}</li>'
                    reasoning_html += '</ul>'
                else:
                    reasoning_html = result.reasoning
            else:
                reasoning_html = result.message
            
            html_content += f"""
                    <tr>
                        <td><span class="rule-id">{result.rule_id}</span></td>
                        <td>{result.rule_title}</td>
                        <td>{result.category} / {result.subcategory}</td>
                        <td><span class="{status_class}">{result.status.upper()}</span></td>
                        <td class="reasoning">{reasoning_html}</td>
                    </tr>
"""
        
        html_content += """
                </tbody>
            </table>
        </div>"""
        
        # Generate JavaScript for charts
        chart_js_code = f"""
<script>
// Chart.js configuration
Chart.defaults.font.family = 'Roboto, sans-serif';

// Overall status distribution pie chart
const overallCtx = document.getElementById('overallChart').getContext('2d');
const overallChart = new Chart(overallCtx, {{
    type: 'pie',
    data: {{
        labels: ['Passed', 'Failed', 'Warnings', 'Not Applicable'],
        datasets: [{{
            data: [{passed}, {failed}, {warnings}, {not_applicable}],
            backgroundColor: [
                '#28a745',  // Green for passed
                '#dc3545',  // Red for failed
                '#ffc107',  // Yellow for warnings
                '#6c757d'   // Gray for not applicable
            ],
            borderWidth: 2,
            borderColor: '#fff'
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{
                position: 'bottom',
                labels: {{
                    padding: 20,
                    usePointStyle: true
                }}
            }},
            tooltip: {{
                callbacks: {{
                    label: function(context) {{
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const percentage = ((context.parsed / total) * 100).toFixed(1);
                        return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                    }}
                }}
            }}
        }}
    }}
}});

// Rule set breakdown horizontal bar chart
const ruleSetCtx = document.getElementById('ruleSetChart').getContext('2d');
const ruleSetData = {json.dumps(rule_set_data)};

const ruleSetLabels = Object.keys(ruleSetData);
const passedData = ruleSetLabels.map(label => ruleSetData[label].pass || 0);
const failedData = ruleSetLabels.map(label => ruleSetData[label].fail || 0);
const warningData = ruleSetLabels.map(label => ruleSetData[label].warning || 0);
const notApplicableData = ruleSetLabels.map(label => ruleSetData[label].not_applicable || 0);

const ruleSetChart = new Chart(ruleSetCtx, {{
    type: 'bar',
    data: {{
        labels: ruleSetLabels,
        datasets: [
            {{
                label: 'Passed',
                data: passedData,
                backgroundColor: '#28a745',
                borderColor: '#1e7e34',
                borderWidth: 1
            }},
            {{
                label: 'Failed',
                data: failedData,
                backgroundColor: '#dc3545',
                borderColor: '#c82333',
                borderWidth: 1
            }},
            {{
                label: 'Warnings',
                data: warningData,
                backgroundColor: '#ffc107',
                borderColor: '#e0a800',
                borderWidth: 1
            }},
            {{
                label: 'Not Applicable',
                data: notApplicableData,
                backgroundColor: '#6c757d',
                borderColor: '#545b62',
                borderWidth: 1
            }}
        ]
    }},
    options: {{
        responsive: true,
        scales: {{
            x: {{
                stacked: true,
                title: {{
                    display: true,
                    text: 'Number of Rules'
                }}
            }},
            y: {{
                stacked: true,
                title: {{
                    display: true,
                    text: 'Rule Sets'
                }}
            }}
        }},
        plugins: {{
            legend: {{
                position: 'top',
                labels: {{
                    padding: 20,
                    usePointStyle: true
                }}
            }},
            tooltip: {{
                mode: 'index',
                intersect: false
            }}
        }}
    }}
}});
</script>
"""
        
        html_content += chart_js_code
        html_content += """
        </div>
    </div>
</body>
</html>
"""
        return html_content
    
    def _generate_cli_output(self, report: SmartComplianceReport) -> str:
        """Generate CLI format output."""
        from datetime import datetime
        
        # Count results by status
        passed = len([r for r in report.results if r.status == 'pass'])
        failed = len([r for r in report.results if r.status == 'fail'])
        warnings = len([r for r in report.results if r.status == 'warning'])
        
        output = f"""
NEXTFLOW PIPELINE VALIDATION REPORT
{'=' * 50}

Pipeline: {Path(report.pipeline_path).name}
Generated: {datetime.now().strftime('%Y-%m-%d')}
Pipeline Type: {getattr(report, 'pipeline_type', 'unknown')}

OVERALL SCORE
{'-' * 20}
Score: {report.total_score:.1f}%
Grade: {report.grade}
Critical Failures: {report.critical_failures}

SUMMARY
{'-' * 20}
Total Rules: {len(report.results)}
✅ Passed: {passed}
❌ Failed: {failed}
⚠️  Warnings: {warnings}
"""
        
        if getattr(report, 'ai_summary', ''):
            output += f"""

AI SUMMARY
{'-' * 20}
{report.ai_summary}
"""
        
        output += f"""

DETAILED RESULTS
{'-' * 20}
"""
        
        for result in report.results:
            status_icon = {'pass': '✅', 'fail': '❌', 'warning': '⚠️', 'not_applicable': '➖'}.get(result.status, '❓')
            output += f"""
{status_icon} {result.rule_id}: {result.rule_title}
   Category: {result.category} / {result.subcategory}
   Status: {result.status.upper()}
   Message: {result.message}

"""
        
        return output
    
    def _convert_to_standard_report(self, smart_report: SmartComplianceReport):
        """Convert SmartComplianceReport to standard ComplianceReport for compatibility."""
        from models import ComplianceReport, ValidationResult
        
        # Convert SmartValidationResults to standard ValidationResults
        standard_results = []
        for result in smart_report.results:
            standard_result = ValidationResult(
                rule_id=result.rule_id,
                rule_title=result.rule_title,
                category=result.category,
                subcategory=result.subcategory,
                status=result.status,
                message=result.message,
                line_number=getattr(result, 'line_number', None),
                file_path=getattr(result, 'file_path', None)
            )
            standard_results.append(standard_result)
        
        # Create standard ComplianceReport
        standard_report = ComplianceReport(
            pipeline_path=smart_report.pipeline_path,
            total_score=smart_report.total_score,
            grade=smart_report.grade,
            critical_failures=smart_report.critical_failures,
            results=standard_results
        )
        
        # Add additional fields if they exist
        if hasattr(smart_report, 'rule_set_scores'):
            standard_report.rule_set_scores = smart_report.rule_set_scores
        if hasattr(smart_report, 'category_scores'):
            standard_report.category_scores = smart_report.category_scores
            
        return standard_report
    
    def _get_context_strategy(self, rule: Dict) -> str:
        """Determine context strategy based on rule criticality.
        
        Smart Hybrid Approach:
        - Critical rules (ph-core requirements): Full context
        - High priority rules (Module/Workflow/Config): Full context  
        - Medium priority rules (Documentation/Testing/General): Limited context
        """
        rule_set = rule.get('rule_set_name', '').lower()
        severity = rule.get('rule_set_severity', '').lower()
        category = rule.get('category', '').lower()
        
        # Critical: ph-core requirements (mandatory compliance)
        if 'requirement' in rule_set or severity == 'critical':
            return 'full_context'
        
        # High Priority: Module, Configuration, Workflow rules (need full context)
        elif category in ['module', 'configuration', 'workflow', 'subworkflow', 'testing', 'test data', 'documentation', 'containerization', 'software specifications']:
            return 'full_context'
        
        # Medium Priority: Everything else (basic context sufficient)
        else:
            return 'limited_context'
    
    def _enhance_context_for_rule(self, rule: Dict, context: Dict[str, Any], context_strategy: str) -> Dict[str, Any]:
        """Enhance context with targeted file analysis based on rule category and subcategory."""
        enhanced_context = context.copy()
        category = rule.get('category', '').lower()
        subcategory = rule.get('subcategory', '').lower()
        rule_id = rule.get('id', '')
        
        pipeline_path = Path(context['pipeline_path'])
        
        if context_strategy == 'full_context':
            # Category-based file analysis
            if category == 'module':
                enhanced_context.update(self._analyze_modules_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'subworkflow':
                enhanced_context.update(self._analyze_subworkflows_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'workflow':
                enhanced_context.update(self._analyze_workflows_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'configuration':
                enhanced_context.update(self._analyze_config_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'documentation':
                enhanced_context.update(self._analyze_docs_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'testing':
                enhanced_context.update(self._analyze_tests_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'software specifications':
                enhanced_context.update(self._analyze_software_specs_for_rule(pipeline_path, subcategory, rule_id))
            elif category == 'general':
                enhanced_context.update(self._analyze_general_for_rule(pipeline_path, subcategory, rule_id))
        elif context_strategy == 'limited_context':
            # Basic context analysis - minimal file sampling for cost efficiency
            enhanced_context.update(self._analyze_basic_context(pipeline_path, category))
        
        return enhanced_context
    
    def _get_applicable_rules_for_pipeline_type(self, pipeline_type: PipelineType, recommendations: Dict) -> List[Dict]:
        """Filter and adapt rules based on detected pipeline type."""
        applicable_rules = []
        
        if pipeline_type == PipelineType.NEXTFLOW_DSL2_NFCORE:
            # Standard nf-core pipeline - all rules apply
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    applicable_rules.append(rule)
        
        elif pipeline_type == PipelineType.NEXTFLOW_DSL2_CUSTOM:
            # Custom DSL2 - focus on core requirements and adaptable recommendations
            priority_categories = ['Module', 'Workflow', 'Configuration', 'Subworkflow']
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    # Include all requirements and high-priority recommendations
                    if (rule_set_name == 'ph_core_requirements' or 
                        rule.get('category') in priority_categories):
                        applicable_rules.append(rule)
        
        elif pipeline_type == PipelineType.NEXTFLOW_DSL1:
            # DSL1 pipeline - adapted rules focusing on general best practices
            adaptable_categories = ['General', 'Documentation', 'Configuration']
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    # Focus on general and documentation rules that apply to DSL1
                    if (rule.get('category') in adaptable_categories or
                        'documentation' in rule.get('subcategory', '').lower() or
                        'general' in rule.get('subcategory', '').lower()):
                        applicable_rules.append(rule)
        
        elif pipeline_type == PipelineType.NEXTFLOW_MIXED:
            # Mixed DSL - comprehensive analysis with migration focus
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    applicable_rules.append(rule)
        
        elif pipeline_type in [PipelineType.SHELL_BASED, PipelineType.PYTHON_BASED]:
            # Legacy pipelines - focus on documentation and general best practices
            general_categories = ['Documentation', 'General']
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    if (rule.get('category') in general_categories or
                        'documentation' in rule.get('title', '').lower() or
                        'readme' in rule.get('title', '').lower()):
                        applicable_rules.append(rule)
        
        else:
            # Unknown pipeline type - basic analysis
            basic_categories = ['Documentation', 'General']
            for rule_set_name, rules in self.rules.items():
                for rule in rules:
                    rule['rule_set_name'] = rule_set_name
                    if rule.get('category') in basic_categories:
                        applicable_rules.append(rule)
        
        return applicable_rules
    
    def _analyze_pipeline_structure_adaptive(self, pipeline_path: Path, pipeline_type: PipelineType, metadata: Dict) -> Dict[str, Any]:
        """Analyze pipeline structure with adaptations for different pipeline types."""
        
        if pipeline_type in [PipelineType.NEXTFLOW_DSL2_NFCORE, PipelineType.NEXTFLOW_DSL2_CUSTOM, 
                           PipelineType.NEXTFLOW_DSL1, PipelineType.NEXTFLOW_MIXED]:
            # Use standard Nextflow analysis
            context = self._analyze_pipeline_structure(pipeline_path)
            
            # Add DSL-specific context
            context['pipeline_type'] = pipeline_type.value
            context['dsl_version'] = metadata.get('dsl_version', 'unknown')
            context['detected_nextflow_files'] = metadata.get('detected_files', [])
            
            return context
        
        elif pipeline_type == PipelineType.SHELL_BASED:
            # Analyze pipeline based on detected type
            if pipeline_type == PipelineType.NEXTFLOW_DSL2_NFCORE:
                context = self._analyze_nfcore_pipeline(pipeline_path, metadata)
            elif pipeline_type in [PipelineType.NEXTFLOW_DSL2_CUSTOM, PipelineType.NEXTFLOW_DSL1, PipelineType.NEXTFLOW_MIXED]:
                context = self._analyze_nextflow_pipeline(pipeline_path, metadata)
            elif pipeline_type == PipelineType.SHELL_BASED:
                context = self._analyze_shell_pipeline(pipeline_path, metadata)
            elif pipeline_type == PipelineType.PYTHON_BASED:
                context = self._analyze_python_pipeline(pipeline_path, metadata)
            elif pipeline_type == PipelineType.R_BASED:
                context = self._analyze_r_pipeline(pipeline_path, metadata)
            elif pipeline_type == PipelineType.PERL_BASED:
                context = self._analyze_perl_pipeline(pipeline_path, metadata)
            else:
                context = self._analyze_unknown_pipeline(pipeline_path, metadata)
            
            return context
        
        elif pipeline_type == PipelineType.PYTHON_BASED:
            # Analyze Python-based pipeline
            return self._analyze_python_pipeline(pipeline_path, metadata)
        
        elif pipeline_type == PipelineType.R_BASED:
            # Analyze R-based pipeline
            return self._analyze_r_pipeline(pipeline_path, metadata)
        
        elif pipeline_type == PipelineType.PERL_BASED:
            # Analyze Perl-based pipeline
            return self._analyze_perl_pipeline(pipeline_path, metadata)
        
        else:
            # Basic analysis for unknown types
            return self._analyze_unknown_pipeline(pipeline_path, metadata)
    
    def _analyze_shell_pipeline(self, pipeline_path: Path, metadata: Dict) -> Dict[str, Any]:
        """Analyze shell-based pipeline structure."""
        context = {
            'pipeline_path': str(pipeline_path),
            'pipeline_type': 'shell_based',
            'main_scripts': metadata.get('main_scripts', []),
            'detected_files': metadata.get('detected_files', []),
        }
        
        # Read main shell scripts
        shell_content = []
        for script_path in metadata.get('main_scripts', [])[:3]:
            full_path = pipeline_path / script_path
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding='utf-8')[:2000]
                    shell_content.append(f"=== SCRIPT: {script_path} ===\n{content}")
                except Exception as e:
                    shell_content.append(f"=== SCRIPT: {script_path} ===\nError reading: {e}")
        
        context['shell_scripts'] = "\n\n".join(shell_content) if shell_content else "No shell scripts found"
        
        # Look for documentation
        doc_files = ['README.md', 'README.txt', 'INSTALL.md', 'USAGE.md']
        doc_content = []
        for doc_file in doc_files:
            doc_path = pipeline_path / doc_file
            if doc_path.exists():
                try:
                    content = doc_path.read_text(encoding='utf-8')[:1500]
                    doc_content.append(f"=== DOC: {doc_file} ===\n{content}")
                except Exception as e:
                    doc_content.append(f"=== DOC: {doc_file} ===\nError reading: {e}")
        
        context['documentation'] = "\n\n".join(doc_content) if doc_content else "No documentation found"
        
        return context
    
    def _analyze_python_pipeline(self, pipeline_path: Path, metadata: Dict) -> Dict[str, Any]:
        """Analyze Python-based pipeline structure."""
        context = {
            'pipeline_path': str(pipeline_path),
            'pipeline_type': 'python_based',
            'detected_files': metadata.get('detected_files', []),
        }
        
        # Read main Python pipeline files
        python_files = list(pipeline_path.rglob('*pipeline*.py')) + list(pipeline_path.rglob('*Pipeline*.py'))
        python_content = []
        for py_file in python_files[:3]:
            try:
                content = py_file.read_text(encoding='utf-8')[:2000]
                python_content.append(f"=== PYTHON: {py_file.relative_to(pipeline_path)} ===\n{content}")
            except Exception as e:
                python_content.append(f"=== PYTHON: {py_file.relative_to(pipeline_path)} ===\nError reading: {e}")
        
        context['python_scripts'] = "\n\n".join(python_content) if python_content else "No Python scripts found"
        
        # Look for requirements and setup files
        setup_files = ['requirements.txt', 'setup.py', 'environment.yml', 'Pipfile']
        setup_content = []
        for setup_file in setup_files:
            setup_path = pipeline_path / setup_file
            if setup_path.exists():
                try:
                    content = setup_path.read_text(encoding='utf-8')
                    setup_content.append(f"=== SETUP: {setup_file} ===\n{content}")
                except Exception as e:
                    setup_content.append(f"=== SETUP: {setup_file} ===\nError reading: {e}")
        
        context['setup_files'] = "\n\n".join(setup_content) if setup_content else "No setup files found"
        
        return context
    
    def _analyze_r_pipeline(self, pipeline_path: Path, metadata: Dict) -> Dict[str, Any]:
        """Analyze R-based pipeline structure."""
        context = {
            'pipeline_path': str(pipeline_path),
            'pipeline_type': 'r_based',
            'detected_files': metadata.get('detected_files', []),
        }
        
        # Read main R pipeline files
        r_files = list(pipeline_path.rglob('*.R')) + list(pipeline_path.rglob('*.r'))
        r_pipeline_files = [f for f in r_files if 'pipeline' in f.name.lower() or 
                          any(keyword in f.name.lower() for keyword in ['workflow', 'analysis', 'process'])]
        
        r_content = []
        for r_file in r_pipeline_files[:3]:
            try:
                content = r_file.read_text(encoding='utf-8')[:2000]
                r_content.append(f"=== R: {r_file.relative_to(pipeline_path)} ===\n{content}")
            except Exception as e:
                r_content.append(f"=== R: {r_file.relative_to(pipeline_path)} ===\nError reading: {e}")
        
        context['r_scripts'] = "\n\n".join(r_content) if r_content else "No R scripts found"
        
        # Look for R-specific dependency files
        r_dep_files = ['DESCRIPTION', 'renv.lock', 'packrat.lock', 'install.R']
        r_dep_content = []
        for dep_file in r_dep_files:
            dep_path = pipeline_path / dep_file
            if dep_path.exists():
                try:
                    content = dep_path.read_text(encoding='utf-8')
                    r_dep_content.append(f"=== R DEPENDENCY: {dep_file} ===\n{content}")
                except Exception as e:
                    r_dep_content.append(f"=== R DEPENDENCY: {dep_file} ===\nError reading: {e}")
        
        context['r_dependencies'] = "\n\n".join(r_dep_content) if r_dep_content else "No R dependency files found"
        
        return context
    
    def _analyze_perl_pipeline(self, pipeline_path: Path, metadata: Dict) -> Dict[str, Any]:
        """Analyze Perl-based pipeline structure."""
        context = {
            'pipeline_path': str(pipeline_path),
            'pipeline_type': 'perl_based',
            'detected_files': metadata.get('detected_files', []),
        }
        
        # Read main Perl pipeline files
        perl_files = list(pipeline_path.rglob('*.pl')) + list(pipeline_path.rglob('*.pm'))
        perl_pipeline_files = [f for f in perl_files if 'pipeline' in f.name.lower() or 
                             any(keyword in f.name.lower() for keyword in ['workflow', 'analysis', 'process'])]
        
        perl_content = []
        for perl_file in perl_pipeline_files[:3]:
            try:
                content = perl_file.read_text(encoding='utf-8')[:2000]
                perl_content.append(f"=== PERL: {perl_file.relative_to(pipeline_path)} ===\n{content}")
            except Exception as e:
                perl_content.append(f"=== PERL: {perl_file.relative_to(pipeline_path)} ===\nError reading: {e}")
        
        context['perl_scripts'] = "\n\n".join(perl_content) if perl_content else "No Perl scripts found"
        
        # Look for Perl-specific dependency files
        perl_dep_files = ['cpanfile', 'Makefile.PL', 'META.yml', 'META.json']
        perl_dep_content = []
        for dep_file in perl_dep_files:
            dep_path = pipeline_path / dep_file
            if dep_path.exists():
                try:
                    content = dep_path.read_text(encoding='utf-8')
                    perl_dep_content.append(f"=== PERL DEPENDENCY: {dep_file} ===\n{content}")
                except Exception as e:
                    perl_dep_content.append(f"=== PERL DEPENDENCY: {dep_file} ===\nError reading: {e}")
        
        context['perl_dependencies'] = "\n\n".join(perl_dep_content) if perl_dep_content else "No Perl dependency files found"
        
        return context
    
    def _analyze_unknown_pipeline(self, pipeline_path: Path, metadata: Dict) -> Dict[str, Any]:
        """Basic analysis for unknown pipeline types."""
        context = {
            'pipeline_path': str(pipeline_path),
            'pipeline_type': 'unknown',
            'detected_files': metadata.get('detected_files', []),
        }
        
        # Look for any documentation
        doc_patterns = ['README*', '*.md', '*.txt']
        doc_content = []
        for pattern in doc_patterns:
            for doc_file in pipeline_path.glob(pattern):
                if doc_file.is_file():
                    try:
                        content = doc_file.read_text(encoding='utf-8')[:1000]
                        doc_content.append(f"=== {doc_file.name} ===\n{content}")
                        if len(doc_content) >= 3:  # Limit to 3 files
                            break
                    except Exception:
                        continue
        
        context['available_documentation'] = "\n\n".join(doc_content) if doc_content else "No documentation found"
        
        return context
    
    def _generate_adaptive_compliance_report(self, pipeline_path: Path, results: List[ValidationResult], 
                                           pipeline_type: PipelineType, metadata: Dict, 
                                           recommendations: Dict) -> SmartComplianceReport:
        """Generate compliance report adapted for the detected pipeline type."""
        
        # Calculate scores with pipeline-type awareness
        total_rules = len(results)
        passed_rules = len([r for r in results if r.status == "pass"])
        failed_rules = len([r for r in results if r.status == "fail"])
        warning_rules = len([r for r in results if r.status == "warning"])
        
        # Adjust scoring based on pipeline type
        if pipeline_type in [PipelineType.SHELL_BASED, PipelineType.PYTHON_BASED, PipelineType.UNKNOWN]:
            # For legacy/unknown pipelines, be more lenient with scoring
            base_score = (passed_rules / total_rules * 100) if total_rules > 0 else 0
            # Bonus for having any documentation or structure
            if any('documentation' in r.rule_title.lower() for r in results if r.status == 'pass'):
                base_score = min(100, base_score + 10)  # 10% bonus for documentation
        else:
            # Standard scoring for Nextflow pipelines
            base_score = (passed_rules / total_rules * 100) if total_rules > 0 else 0
        
        # Generate grade
        if base_score >= 95: grade = "A+"
        elif base_score >= 90: grade = "A"
        elif base_score >= 85: grade = "A-"
        elif base_score >= 80: grade = "B+"
        elif base_score >= 75: grade = "B"
        elif base_score >= 70: grade = "B-"
        elif base_score >= 65: grade = "C+"
        elif base_score >= 60: grade = "C"
        elif base_score >= 55: grade = "C-"
        elif base_score >= 50: grade = "D"
        else: grade = "F"
        
        # Generate AI summary with pipeline-type context
        ai_summary = self._generate_adaptive_ai_summary(pipeline_type, results, metadata, recommendations)
        
        return SmartComplianceReport(
            pipeline_path=str(pipeline_path),
            total_score=base_score,
            weighted_score=base_score,  # For now, use same as total_score
            grade=grade,
            critical_failures=failed_rules,
            results=results,
            rule_set_scores={},  # Could be enhanced later
            ai_summary=ai_summary
        )
    
    def _generate_adaptive_ai_summary(self, pipeline_type: PipelineType, results: List[ValidationResult], 
                                    metadata: Dict, recommendations: Dict) -> str:
        """Generate AI summary adapted for the pipeline type."""
        
        passed = len([r for r in results if r.status == 'pass'])
        failed = len([r for r in results if r.status == 'fail'])
        warnings = len([r for r in results if r.status == 'warning'])
        
        summary_parts = [
            f"Pipeline Type: {pipeline_type.value.replace('_', ' ').title()}",
            f"Validation Results: {passed} passed, {failed} failed, {warnings} warnings"
        ]
        
        if pipeline_type == PipelineType.NEXTFLOW_DSL2_NFCORE:
            summary_parts.append("This is a standard nf-core DSL2 pipeline. All validation rules were applied.")
        elif pipeline_type == PipelineType.NEXTFLOW_DSL2_CUSTOM:
            summary_parts.append("This is a custom DSL2 pipeline. Core requirements and high-priority rules were emphasized.")
        elif pipeline_type == PipelineType.NEXTFLOW_DSL1:
            summary_parts.append("This is a DSL1 pipeline. Consider migrating to DSL2 for better maintainability and features.")
        elif pipeline_type == PipelineType.NEXTFLOW_MIXED:
            summary_parts.append("This pipeline contains mixed DSL1/DSL2 syntax. Migration to pure DSL2 is recommended.")
        elif pipeline_type in [PipelineType.SHELL_BASED, PipelineType.PYTHON_BASED]:
            summary_parts.append("This is a legacy pipeline. Consider modernizing with a workflow manager like Nextflow.")
        else:
            summary_parts.append("Pipeline type could not be determined. Manual analysis recommended.")
        
        # Add specific recommendations
        if recommendations.get('special_considerations'):
            summary_parts.append(f"Special Considerations: {', '.join(recommendations['special_considerations'])}")
        
        return " ".join(summary_parts)
    
    def _analyze_basic_context(self, pipeline_path: Path, subcategory: str) -> Dict[str, str]:
        """Basic context analysis for limited context strategy - minimal file sampling."""
        context = {}
        
        # Sample 1-2 files from each category for basic validation
        modules_dir = pipeline_path / 'modules'
        if modules_dir.exists():
            module_files = list(modules_dir.rglob('*.nf'))[:2]
            if module_files:
                sample_content = []
                for file_path in module_files:
                    try:
                        content = file_path.read_text(encoding='utf-8')[:1000]  # First 1000 chars
                        sample_content.append(f"File: {file_path.name}\n{content}")
                    except Exception:
                        continue
                context['module_analysis'] = "\n\n".join(sample_content) if sample_content else "No module files found"
            else:
                context['module_analysis'] = "No module files found"
        else:
            context['module_analysis'] = "No modules directory found"
        
        # Basic workflow analysis
        workflows_dir = pipeline_path / 'workflows'
        if workflows_dir.exists():
            workflow_files = list(workflows_dir.rglob('*.nf'))[:1]
            if workflow_files:
                try:
                    content = workflow_files[0].read_text(encoding='utf-8')[:1000]
                    context['workflow_analysis'] = f"File: {workflow_files[0].name}\n{content}"
                except Exception:
                    context['workflow_analysis'] = "Error reading workflow files"
            else:
                context['workflow_analysis'] = "No workflow files found"
        else:
            context['workflow_analysis'] = "No workflows directory found"
        
        # Basic config analysis
        config_files = ['nextflow.config', 'conf/base.config']
        config_content = []
        for config_file in config_files:
            config_path = pipeline_path / config_file
            if config_path.exists():
                try:
                    content = config_path.read_text(encoding='utf-8')[:500]
                    config_content.append(f"File: {config_file}\n{content}")
                except Exception:
                    continue
        context['config_analysis'] = "\n\n".join(config_content) if config_content else "No config files found"
        
        # Set other analyses to basic placeholders
        context['subworkflow_analysis'] = "Basic subworkflow analysis"
        context['docs_analysis'] = "Basic documentation analysis"
        context['test_analysis'] = "Basic test analysis"
        context['software_specs_analysis'] = "Basic software specs analysis"
        
        return context
    
    def _analyze_modules_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze module files with full context for critical/high-priority rules."""
        context = {}
        modules_dir = pipeline_path / 'modules'
        
        if not modules_dir.exists():
            context['module_analysis'] = "No modules directory found."
            return context
        
        module_files = list(modules_dir.rglob('*.nf'))
        if not module_files:
            context['module_analysis'] = "No module files found in modules directory."
            return context
        
        # Full context analysis - read entire files for comprehensive validation
        module_contents = []
        sample_size = min(5, len(module_files))  # Increased sample for full context
        
        for module_file in module_files[:sample_size]:
            try:
                content = module_file.read_text(encoding='utf-8')
                module_contents.append(f"=== MODULE: {module_file.relative_to(pipeline_path)} ===\n{content}")
            except Exception as e:
                module_contents.append(f"=== MODULE: {module_file.relative_to(pipeline_path)} ===\nError reading file: {e}")
        
        context['module_analysis'] = "\n\n".join(module_contents)
        return context
    

    

    

    

    
    def _analyze_subworkflows_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze subworkflow files with full context for critical/high-priority rules."""
        context = {}
        subworkflows_dir = pipeline_path / 'subworkflows'
        
        if not subworkflows_dir.exists():
            context['subworkflow_analysis'] = "No subworkflows directory found."
            return context
        
        subworkflow_files = list(subworkflows_dir.rglob('*.nf'))
        if not subworkflow_files:
            context['subworkflow_analysis'] = "No subworkflow files found."
            return context
        
        # Full context analysis - read entire subworkflow files
        subworkflow_contents = []
        sample_size = min(3, len(subworkflow_files))  # Increased sample for full context
        
        for subworkflow_file in subworkflow_files[:sample_size]:
            try:
                content = subworkflow_file.read_text(encoding='utf-8')
                subworkflow_contents.append(f"=== SUBWORKFLOW: {subworkflow_file.relative_to(pipeline_path)} ===\n{content}")
            except Exception as e:
                subworkflow_contents.append(f"=== SUBWORKFLOW: {subworkflow_file.relative_to(pipeline_path)} ===\nError reading file: {e}")
        
        context['subworkflow_analysis'] = "\n\n".join(subworkflow_contents)
        return context
    

    
    def _analyze_workflows_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze workflow files with full context for critical/high-priority rules."""
        context = {}
        
        # Check main.nf and workflows directory
        main_nf = pipeline_path / 'main.nf'
        workflows_dir = pipeline_path / 'workflows'
        
        workflow_content = []
        
        # Full context analysis - read entire workflow files
        if main_nf.exists():
            try:
                content = main_nf.read_text(encoding='utf-8')
                workflow_content.append(f"=== MAIN.NF ===\n{content}")
            except Exception as e:
                workflow_content.append(f"=== MAIN.NF ===\nError reading file: {e}")
                pass
        
        if workflows_dir.exists():
            workflow_files = list(workflows_dir.rglob('*.nf'))
            sample_size = min(3, len(workflow_files))  # Increased sample for full context
            for wf_file in workflow_files[:sample_size]:
                try:
                    content = wf_file.read_text(encoding='utf-8')
                    workflow_content.append(f"=== WORKFLOW: {wf_file.relative_to(pipeline_path)} ===\n{content}")
                except Exception as e:
                    workflow_content.append(f"=== WORKFLOW: {wf_file.relative_to(pipeline_path)} ===\nError reading file: {e}")
        
        context['workflow_analysis'] = "\n\n".join(workflow_content) if workflow_content else "No workflow content found."
        return context
    
    def _analyze_config_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze configuration files with full context for critical/high-priority rules."""
        context = {}
        config_files = ['nextflow.config', 'conf/base.config', 'conf/modules.config', 'conf/test.config']
        
        config_content = []
        for config_file in config_files:
            config_path = pipeline_path / config_file
            if config_path.exists():
                try:
                    content = config_path.read_text(encoding='utf-8')
                    config_content.append(f"=== CONFIG: {config_file} ===\n{content}")
                except Exception as e:
                    config_content.append(f"=== CONFIG: {config_file} ===\nError reading file: {e}")
        
        context['config_analysis'] = "\n\n".join(config_content) if config_content else "No config files found."
        return context
    
    def _analyze_docs_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze documentation files with full context for critical/high-priority rules."""
        context = {}
        doc_files = ['README.md', 'docs/README.md', 'CHANGELOG.md', 'docs/usage.md', 'docs/output.md']
        
        doc_content = []
        for doc_file in doc_files:
            doc_path = pipeline_path / doc_file
            if doc_path.exists():
                try:
                    content = doc_path.read_text(encoding='utf-8')
                    doc_content.append(f"=== DOC: {doc_file} ===\n{content}")
                except Exception as e:
                    doc_content.append(f"=== DOC: {doc_file} ===\nError reading file: {e}")
        
        context['docs_analysis'] = "\n\n".join(doc_content) if doc_content else "No documentation files found."
        return context
    
    def _analyze_tests_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze test files and directories with full context for critical/high-priority rules."""
        context = {}
        test_dirs = ['Testdata', 'testdata', 'tests', 'test']  # Prioritize Testdata folders
        
        test_content = []
        for test_dir in test_dirs:
            test_path = pipeline_path / test_dir
            if test_path.exists():
                test_files = list(test_path.rglob('*.nf'))
                sample_size = min(5, len(test_files))  # Increased sample for full context
                for test_file in test_files[:sample_size]:
                    try:
                        content = test_file.read_text(encoding='utf-8')
                        test_content.append(f"=== TEST: {test_file.relative_to(pipeline_path)} ===\n{content}")
                    except Exception as e:
                        test_content.append(f"=== TEST: {test_file.relative_to(pipeline_path)} ===\nError reading file: {e}")
        
        context['test_analysis'] = "\n\n".join(test_content) if test_content else "No test files found."
        return context
    
    def _analyze_software_specs_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze software specification files with full context for critical/high-priority rules."""
        context = {}
        spec_files = ['environment.yml', 'conda.yml', 'Dockerfile', 'containers.config', 'conf/modules.config']
        
        spec_content = []
        for spec_file in spec_files:
            spec_path = pipeline_path / spec_file
            if spec_path.exists():
                try:
                    content = spec_path.read_text(encoding='utf-8')
                    spec_content.append(f"=== SPEC: {spec_file} ===\n{content}")
                except Exception as e:
                    spec_content.append(f"=== SPEC: {spec_file} ===\nError reading file: {e}")
        
        context['software_specs_analysis'] = "\n\n".join(spec_content) if spec_content else "No software specification files found."
        return context
    
    def _analyze_general_for_rule(self, pipeline_path: Path, subcategory: str, rule_id: str) -> Dict[str, str]:
        """Analyze general pipeline structure and files with full context for critical/high-priority rules."""
        context = {}
        
        # Look at key structural files
        key_files = ['main.nf', 'nextflow.config', 'README.md', 'CHANGELOG.md']
        general_content = []
        
        for key_file in key_files:
            file_path = pipeline_path / key_file
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding='utf-8')
                    general_content.append(f"=== FILE: {key_file} ===\n{content}")
                except Exception as e:
                    general_content.append(f"=== FILE: {key_file} ===\nError reading file: {e}")
        
        context['general_analysis'] = "\n\n".join(general_content) if general_content else "No key files found."
        return context
    
    # Helper methods for specific analysis types
    def _parse_ai_response(self, rule: Dict, ai_text: str) -> ValidationResult:
        """Parse AI response and create ValidationResult with improved JSON extraction."""
        rule_id = rule.get('id', 'unknown')
        rule_title = rule.get('title', 'Unknown Rule')
        category = rule.get('category', 'General')
        subcategory = rule.get('subcategory', 'General')
        
        # Try multiple JSON extraction methods
        ai_response = None
        
        try:
            # Method 1: Try to parse the entire response as JSON
            ai_response = json.loads(ai_text.strip())
        except json.JSONDecodeError:
            try:
                # Method 2: Extract JSON block from response
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', ai_text, re.DOTALL)
                if json_match:
                    ai_response = json.loads(json_match.group())
            except json.JSONDecodeError:
                try:
                    # Method 3: Look for key-value patterns and construct JSON
                    status_match = re.search(r'"status"\s*:\s*"([^"]+)"', ai_text)
                    confidence_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', ai_text)
                    message_match = re.search(r'"message"\s*:\s*"([^"]+)"', ai_text)
                    
                    # More robust reasoning extraction - try multiple patterns
                    reasoning_match = None
                    # Try to match reasoning as array
                    reasoning_array_match = re.search(r'"reasoning"\s*:\s*\[([^\[\]]+)\]', ai_text)
                    if reasoning_array_match:
                        # Extract array items
                        items_text = reasoning_array_match.group(1)
                        items = re.findall(r'"([^"]+)"', items_text)
                        if items:
                            reasoning_match = items
                    else:
                        # Try to match reasoning as string
                        reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]+)"', ai_text)
                        if reasoning_match:
                            reasoning_match = reasoning_match.group(1)
                    
                    # Extract suggested files
                    suggested_files_match = re.search(r'"suggested_files"\s*:\s*\[([^\[\]]+)\]', ai_text)
                    suggested_files = None
                    if suggested_files_match:
                        files_text = suggested_files_match.group(1)
                        files = re.findall(r'"([^"]+)"', files_text)
                        if files:
                            suggested_files = files
                    
                    if status_match:
                        ai_response = {
                            'status': status_match.group(1),
                            'confidence': float(confidence_match.group(1)) if confidence_match else 0.5,
                            'message': message_match.group(1) if message_match else 'AI analysis completed',
                            'reasoning': reasoning_match if reasoning_match else 'Partial parsing from AI response',
                            'suggested_files': suggested_files
                        }
                except (ValueError, AttributeError):
                    pass
        
        # If we successfully parsed AI response, create ValidationResult
        if ai_response and isinstance(ai_response, dict):
            try:
                # Handle reasoning as either list or string
                reasoning = ai_response.get('reasoning', 'No reasoning provided')
                if isinstance(reasoning, list):
                    reasoning = reasoning  # Keep as list for bulleted format
                elif isinstance(reasoning, str):
                    reasoning = reasoning  # Keep as string for backward compatibility
                
                # Extract suggested files
                suggested_files = ai_response.get('suggested_files', [])
                if isinstance(suggested_files, str):
                    suggested_files = [suggested_files]  # Convert single string to list
                
                result = ValidationResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    category=category,
                    subcategory=subcategory,
                    status=ai_response.get('status', 'warning'),
                    message=ai_response.get('message', 'AI analysis completed'),
                    confidence=float(ai_response.get('confidence', 0.5)),
                    reasoning=reasoning,
                    suggested_files=suggested_files if suggested_files else None
                )
                
                # Cache the result if caching is enabled
                if self.use_cache and self.cache:
                    self.cache.cache_result(rule_id, result)
                
                return result
            except (KeyError, ValueError, TypeError):
                pass
        
        # Fallback: Try to extract meaningful info from raw text
        import re  # Ensure re is imported for regex operations
        status = 'warning'
        confidence = 0.3
        
        # Try to extract a meaningful message from the raw text instead of truncating
        message = 'AI analysis completed - manual review recommended'
        
        # Extract reasoning from the raw text
        reasoning_text = []
        
        # Look for bullet points or numbered lists
        bullet_points = re.findall(r'[•\*\-]\s*([^\n]+)', ai_text)
        if bullet_points:
            reasoning_text = bullet_points
        else:
            # Look for numbered points
            numbered_points = re.findall(r'\d+\.\s*([^\n]+)', ai_text)
            if numbered_points:
                reasoning_text = numbered_points
            else:
                # Extract sentences that might contain reasoning
                sentences = re.findall(r'([^.!?]+[.!?])', ai_text)
                # Filter to sentences that seem like they contain analysis
                analysis_sentences = [s.strip() for s in sentences if re.search(r'\b(analysis|found|detected|observed|review|check|rule|requirement|recommend)\b', s.lower())]
                if analysis_sentences:
                    reasoning_text = analysis_sentences[:5]  # Limit to 5 sentences
                else:
                    # Just take a few sentences if nothing else works
                    reasoning_text = [s.strip() for s in sentences[:3]] if sentences else ['AI response could not be parsed as JSON']
        
        # Clean up the reasoning text
        reasoning = []
        for item in reasoning_text:
            # Remove any JSON formatting artifacts
            clean_item = re.sub(r'["\\]', '', item).strip()
            if clean_item:
                reasoning.append(clean_item)
        
        # If we couldn't extract anything useful, use a default message
        if not reasoning:
            reasoning = ['AI response could not be parsed as JSON']
        
        suggested_files = None
        
        # Simple heuristics for status detection
        if re.search(r'\b(pass|satisfied|compliant|meets)\b', ai_text.lower()):
            status = 'pass'
            confidence = 0.5
        elif re.search(r'\b(fail|failed|not compliant|does not meet|violation)\b', ai_text.lower()):
            status = 'fail'
            confidence = 0.5
        elif re.search(r'\b(not applicable|doesn\'t apply|irrelevant)\b', ai_text.lower()):
            status = 'not_applicable'
            confidence = 0.6
        
        # Try to extract reasoning using common patterns
        reasoning_section = None
        
        # Look for reasoning section with common headers
        reasoning_headers = ['reasoning:', 'reasoning', 'analysis:', 'analysis', 'explanation:']
        for header in reasoning_headers:
            pattern = f"{header}\s*([\s\S]+?)(?:proposed solution:|solution:|suggested files:|$)"
            match = re.search(pattern, ai_text.lower(), re.IGNORECASE)
            if match:
                reasoning_section = match.group(1).strip()
                break
        
        if reasoning_section:
            # Clean up the reasoning text
            reasoning = reasoning_section
            # Convert bullet points to a list if present
            if '•' in reasoning or '*' in reasoning or '-' in reasoning:
                bullet_items = re.findall(r'[•\*-]\s*([^•\*\-\n]+)', reasoning)
                if bullet_items:
                    reasoning = bullet_items
        else:
            # Fallback to sentence extraction
            if len(ai_text) > 50:
                sentences = ai_text.split('. ')
                meaningful_sentences = [s.strip() for s in sentences if len(s.strip()) > 20 and not s.strip().startswith('{')]
                if meaningful_sentences:
                    reasoning = '. '.join(meaningful_sentences[:3])  # Take first 3 meaningful sentences
                else:
                    reasoning = f'AI provided analysis but format was unclear.'
        
        # Try to extract solution
        solution_headers = ['proposed solution:', 'solution:', 'recommended action:', 'fix:']
        for header in solution_headers:
            pattern = f"{header}\s*([\s\S]+?)(?:suggested files:|$)"
            match = re.search(pattern, ai_text.lower(), re.IGNORECASE)
            if match:
                proposed_solution = match.group(1).strip()
                break
        
        # Try to extract suggested files
        files_headers = ['suggested files:', 'files to modify:', 'relevant files:']
        for header in files_headers:
            pattern = f"{header}\s*([\s\S]+?)(?:$)"
            match = re.search(pattern, ai_text.lower(), re.IGNORECASE)
            if match:
                files_text = match.group(1).strip()
                # Extract file names from text
                file_candidates = re.findall(r'[\w.-]+\.[\w]+', files_text)
                if file_candidates:
                    suggested_files = file_candidates
                break
        
        return ValidationResult(
            rule_id=rule_id,
            rule_title=rule_title,
            category=category,
            subcategory=subcategory,
            status=status,
            message=message,
            confidence=confidence,
            reasoning=reasoning,
            suggested_files=suggested_files
        )
    
    def _validate_rules_parallel(self, rules: List[Dict], context: Dict[str, Any], rule_set_name: str) -> List[ValidationResult]:
        """Validate rules in parallel using ThreadPoolExecutor."""
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all rule validation tasks
            future_to_rule = {
                executor.submit(self._validate_rule_with_ai, rule, context, rule_set_name): rule 
                for rule in rules
            }
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_rule):
                rule = future_to_rule[future]
                completed += 1
                
                try:
                    result = future.result()
                    results.append(result)
                    
                    # Thread-safe progress reporting
                    with self.thread_lock:
                        status_icon = "✅" if result.status == "pass" else "❌" if result.status == "fail" else "⚠️"
                        confidence_bar = "🟢" if result.confidence > 0.8 else "🟡" if result.confidence > 0.5 else "🔴"
                        print(f"  [{completed}/{len(rules)}] {status_icon} {confidence_bar} {result.rule_id}: {result.message}")
                        
                except Exception as e:
                    print(f"  ❌ Error validating rule {rule.get('id', 'unknown')}: {e}")
                    # Create a failed result for the rule
                    results.append(ValidationResult(
                        rule_id=rule.get('id', 'unknown'),
                        rule_title=rule.get('title', 'Unknown'),
                        category=rule.get('category', 'General'),
                        subcategory=rule.get('subcategory', 'General'),
                        status='fail',
                        message=f'Validation error: {str(e)}',
                        confidence=0.0,
                        reasoning='Rule validation failed due to error',
                        suggested_files=None
                    ))
        
        return results
    
    def _validate_rule_with_ai_cached(self, rule: Dict, context: Dict[str, Any], rule_set_name: str) -> ValidationResult:
        """Validate a single rule with AI and return result for caching."""
        return self._validate_rule_with_ai(rule, context, rule_set_name)
    
    def _estimate_rule_cost(self, rule: Dict, context: Dict[str, Any]) -> float:
        """Estimate the cost of validating a rule based on context size and model pricing."""
        try:
            # Estimate token count (rough approximation: 1 token ≈ 4 characters)
            context_text = str(context)
            rule_text = str(rule)
            estimated_tokens = (len(context_text) + len(rule_text)) // 4
            
            # Add typical AI response tokens (estimated)
            estimated_tokens += 200  # Typical response size
            
            # Get current model pricing from LLM provider
            if hasattr(self, 'llm_provider') and self.llm_provider:
                try:
                    # Get input cost per 1M tokens
                    model_info = self.llm_provider.get_model_info()
                    input_cost_per_1m = model_info.get('input_cost_per_1m_tokens', 0.0)
                    output_cost_per_1m = model_info.get('output_cost_per_1m_tokens', 0.0)
                    
                    # Calculate cost
                    input_cost = (estimated_tokens * input_cost_per_1m) / 1_000_000
                    output_cost = (200 * output_cost_per_1m) / 1_000_000  # Estimated response tokens
                    
                    return input_cost + output_cost
                except:
                    # Fallback to average cost estimate
                    return estimated_tokens * 0.000015  # Rough average cost per token
            else:
                # Fallback cost estimation
                return estimated_tokens * 0.000015
                
        except Exception:
            # Conservative fallback
            return 0.01  # $0.01 per rule as rough estimate
    
    def validate_pipeline(self, pipeline_path: str) -> ComplianceReport:
        """Validate pipeline with AI-powered analysis."""
        pipeline_path = Path(pipeline_path)
        
        print(f"\n🧬 Smart AI-Powered Pipeline Validation: {pipeline_path}")
        print("=" * 70)
        
        if not pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline path not found: {pipeline_path}")
        
        # Analyze pipeline structure
        print("🔍 Analyzing pipeline structure...")
        context = self._analyze_pipeline_structure(pipeline_path)
        
        # Collect all results
        all_results = []
        rule_set_scores = {}
        
        # Validate each rule set with AI (parallelized)
        for rule_set_name, rules in self.rules.items():
            print(f"\n🤖 AI-analyzing {rule_set_name.replace('_', ' ').title()} ({len(rules)} rules) - Parallel processing...")
            
            results = self._validate_rules_parallel(rules, context, rule_set_name)
            all_results.extend(results)
            
            # Calculate rule set score (exclude not_applicable rules)
            passed = sum(1 for r in results if r.status == "pass")
            applicable_results = [r for r in results if r.status != "not_applicable"]
            total = len(applicable_results)
            score = (passed / total * 100) if total > 0 else 0
            
            rule_set_scores[rule_set_name] = {
                'score': score,
                'passed': passed,
                'total': total,
                'weight': self.rule_set_weights.get(rule_set_name, 0),
                'avg_confidence': sum(r.confidence for r in results) / len(results) if results else 0
            }
        
        # Calculate overall scores
        weighted_score = sum(
            scores['score'] * scores['weight'] 
            for scores in rule_set_scores.values()
        )
        
        # Calculate overall score (exclude not_applicable rules)
        total_passed = sum(1 for r in all_results if r.status == "pass")
        applicable_rules = [r for r in all_results if r.status != "not_applicable"]
        total_rules = len(applicable_rules)
        total_score = (total_passed / total_rules * 100) if total_rules > 0 else 0
        
        # Calculate grade
        grade = self._calculate_grade(weighted_score)
        
        # Count critical failures
        critical_failures = sum(
            1 for r in all_results 
            if r.status == "fail" and any(
                rule['id'] == r.rule_id and rule.get('severity') == 'critical'
                for rule_set in self.rules.values()
                for rule in rule_set
            )
        )
        
        # Generate AI summary
        ai_summary = self._generate_ai_summary(all_results, context, weighted_score)
        
        return ComplianceReport(
            pipeline_path=str(pipeline_path),
            total_score=total_score,
            weighted_score=weighted_score,
            grade=grade,
            critical_failures=critical_failures,
            results=all_results,
            rule_set_scores=rule_set_scores,
            ai_summary=ai_summary
        )
    
    def _generate_ai_summary(self, results: List[ValidationResult], context: Dict[str, Any], score: float) -> str:
        """Generate AI-powered overall assessment."""
        failed_rules = [r for r in results if r.status == 'fail']
        
        prompt = f"""
Provide a brief executive summary of this Nextflow pipeline validation:

OVERALL SCORE: {score:.1f}%
FAILED RULES: {len(failed_rules)} out of {len(results)}

PIPELINE STRUCTURE:
- Modules: {context['file_counts']['modules']}
- Workflows: {context['file_counts']['workflows']}  
- Subworkflows: {context['file_counts']['subworkflows']}

KEY FAILURES:
{chr(10).join([f"- {r.rule_id}: {r.message}" for r in failed_rules[:5]])}

Provide a 2-3 sentence executive summary focusing on:
1. Overall pipeline quality assessment
2. Main areas for improvement
3. Compliance readiness
"""
        
        try:
            response = self.llm_provider.generate_response(
                prompt=prompt,
                max_tokens=1000,
                temperature=0.1
            )
            return response.strip()
        except Exception as e:
            return f"AI summary unavailable: {e}"
    
    def _calculate_grade(self, score: float) -> str:
        """Calculate letter grade from score."""
        if score >= 97: return "A+"
        elif score >= 93: return "A"
        elif score >= 90: return "A-"
        elif score >= 87: return "B+"
        elif score >= 83: return "B"
        elif score >= 80: return "B-"
        elif score >= 77: return "C+"
        elif score >= 73: return "C"
        elif score >= 70: return "C-"
        elif score >= 67: return "D+"
        elif score >= 63: return "D"
        elif score >= 60: return "D-"
        else: return "F"
    
    def generate_report(self, report: ComplianceReport, output_format: str = 'cli') -> str:
        """Generate smart validation report."""
        if output_format == 'json':
            return self._generate_json_report(report)
        elif output_format == 'html':
            return self._generate_html_report(report)
        else:
            return self._generate_cli_report(report)
    
    def _generate_cli_report(self, report: ComplianceReport) -> str:
        """Generate enhanced CLI report with AI insights."""
        lines = []
        lines.append(f"\n🤖 SMART AI-POWERED NEXTFLOW VALIDATION REPORT")
        lines.append("=" * 70)
        lines.append(f"Pipeline: {report.pipeline_path}")
        lines.append(f"Validation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # AI Summary
        lines.append("🧠 AI EXECUTIVE SUMMARY")
        lines.append("-" * 25)
        lines.append(report.ai_summary)
        lines.append("")
        
        # Overall scores
        lines.append("📊 OVERALL SCORES")
        lines.append("-" * 20)
        lines.append(f"Weighted Score: {report.weighted_score:.1f}%")
        lines.append(f"Total Score: {report.total_score:.1f}%")
        lines.append(f"Grade: {report.grade}")
        lines.append(f"Critical Failures: {report.critical_failures}")
        lines.append("")
        
        # Rule set breakdown with confidence
        lines.append("📋 RULE SET BREAKDOWN (with AI Confidence)")
        lines.append("-" * 45)
        for rule_set, scores in report.rule_set_scores.items():
            name = rule_set.replace('_', ' ').title()
            confidence = scores.get('avg_confidence', 0) * 100
            lines.append(f"{name}: {scores['score']:.1f}% ({scores['passed']}/{scores['total']}) [Weight: {scores['weight']*100:.0f}%, Confidence: {confidence:.0f}%]")
        
        lines.append("")
    
        # Token usage summary
        total_input_tokens = sum(getattr(r, 'input_tokens', 0) or 0 for r in report.results)
        total_output_tokens = sum(getattr(r, 'output_tokens', 0) or 0 for r in report.results)
        
        if total_input_tokens > 0:
            lines.append("🔢 TOKEN USAGE SUMMARY")
            lines.append("-" * 30)
            lines.append(f"Total Input Tokens: {total_input_tokens:,}")
            lines.append(f"Total Output Tokens: {total_output_tokens:,}")
            
            # Add cache savings if available
            if hasattr(self, 'cache') and self.cache:
                cache_stats = self.cache.get_cache_stats()
                if cache_stats.get('estimated_cost_saved', 0) > 0:
                    lines.append(f"Cache Hit Rate: {cache_stats['total_cached_rules']}/{len(report.results)} rules")
            
            lines.append("")
        
        # Failed rules with AI reasoning
        failed_results = [r for r in report.results if r.status == 'fail']
        if failed_results:
            lines.append("❌ FAILED RULES (with AI Analysis)")
            lines.append("-" * 35)
            for result in failed_results:
                confidence_indicator = "🟢" if result.confidence > 0.8 else "🟡" if result.confidence > 0.5 else "🔴"
                lines.append(f"• {result.rule_id}: {result.rule_title} {confidence_indicator}")
                lines.append(f"  Category: {result.category} / {result.subcategory}")
                lines.append(f"  Status: {result.message}")
                
                # Handle bulleted reasoning
                if isinstance(result.reasoning, list):
                    lines.append(f"  AI Reasoning:")
                    for reason in result.reasoning:
                        lines.append(f"    {reason}")
                else:
                    lines.append(f"  AI Reasoning: {result.reasoning}")
                
                # Add proposed solution if available
                if result.proposed_solution:
                    lines.append(f"  💡 Proposed Solution: {result.proposed_solution}")
                
                # Add suggested files if available
                if result.suggested_files:
                    files_str = ", ".join(result.suggested_files)
                    lines.append(f"  📁 Suggested Files: {files_str}")
                
                lines.append("")
        
        return "\n".join(lines)
    
    def _generate_json_report(self, report: ComplianceReport) -> str:
        """Generate enhanced JSON report with AI data."""
        data = {
            'pipeline_path': report.pipeline_path,
            'validation_date': datetime.now().isoformat(),
            'ai_summary': report.ai_summary,
            'scores': {
                'weighted_score': report.weighted_score,
                'total_score': report.total_score,
                'grade': report.grade,
                'critical_failures': report.critical_failures
            },
            'rule_sets': report.rule_set_scores,
            'results': [
                {
                    'rule_id': r.rule_id,
                    'rule_title': r.rule_title,
                    'category': r.category,
                    'subcategory': r.subcategory,
                    'status': r.status,
                    'message': r.message,
                    'confidence': r.confidence,
                    'reasoning': r.reasoning,
                    'suggested_files': r.suggested_files,
                    'file_path': r.file_path,
                    'line_number': r.line_number
                }
                for r in report.results
            ]
        }
        return json.dumps(data, indent=2)
    
    def _generate_html_report(self, report: ComplianceReport) -> str:
        """Generate enhanced HTML report with AI insights."""
        # Enhanced HTML template with AI features
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Smart AI-Powered Nextflow Validation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; }}
        .ai-summary {{ background: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0; }}
        .score {{ font-size: 24px; font-weight: bold; color: #2e7d32; }}
        .failed {{ color: #d32f2f; }}
        .passed {{ color: #2e7d32; }}
        .confidence-high {{ color: #2e7d32; }}
        .confidence-medium {{ color: #f57c00; }}
        .confidence-low {{ color: #d32f2f; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .reasoning {{ font-style: italic; color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Smart AI-Powered Nextflow Validation Report</h1>
        <p><strong>Pipeline:</strong> {report.pipeline_path}</p>
        <p><strong>Validation Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p class="score">Grade: {report.grade} (Weighted Score: {report.weighted_score:.1f}%)</p>
    </div>
    
    <div class="ai-summary">
        <h3>🧠 AI Executive Summary</h3>
        <p>{report.ai_summary}</p>
    </div>
    
    <h2>📊 Rule Set Scores (with AI Confidence)</h2>
    <table>
        <tr><th>Rule Set</th><th>Score</th><th>Passed/Total</th><th>Weight</th><th>AI Confidence</th></tr>
"""
        
        for rule_set, scores in report.rule_set_scores.items():
            name = rule_set.replace('_', ' ').title()
            confidence = scores.get('avg_confidence', 0) * 100
            confidence_class = 'confidence-high' if confidence > 80 else 'confidence-medium' if confidence > 50 else 'confidence-low'
            html += f"""
        <tr>
            <td>{name}</td>
            <td>{scores['score']:.1f}%</td>
            <td>{scores['passed']}/{scores['total']}</td>
            <td>{scores['weight']*100:.0f}%</td>
            <td class="{confidence_class}">{confidence:.0f}%</td>
        </tr>"""
        
        html += """
    </table>
    """
        
        # Add token usage summary
        total_input_tokens = sum(getattr(r, 'input_tokens', 0) or 0 for r in report.results)
        total_output_tokens = sum(getattr(r, 'output_tokens', 0) or 0 for r in report.results)
        
        if total_input_tokens > 0:
            html += f"""
<h2>🔢 Token Usage Summary</h2>
<table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Total Input Tokens</td><td>{total_input_tokens:,}</td></tr>
    <tr><td>Total Output Tokens</td><td>{total_output_tokens:,}</td></tr>
</table>
"""
        
        html += """
    <h2>📋 Validation Results (with AI Analysis)</h2>
    <table>
        <tr>
            <th>Rule ID</th>
            <th>Title</th>
            <th>Category</th>
            <th>Status</th>
            <th>Message</th>
            <th>Confidence</th>
            <th>Reasoning</th>
            <th>Token Usage</th>
        </tr>
"""
        
        for result in report.results:
            status_class = f"status-{result.status}"
            
            # Format reasoning and solution
            reasoning_html = result.reasoning
            
            # Format suggested files
            suggested_files_html = ', '.join(result.suggested_files) if result.suggested_files else 'N/A'
            
            # Format token usage
            token_usage = f"{getattr(result, 'input_tokens', 0) or 0} in, {getattr(result, 'output_tokens', 0) or 0} out" if hasattr(result, 'input_tokens') and result.input_tokens else 'N/A'
            
            html += f"""
    <tr>
        <td>{result.rule_id}</td>
        <td>{result.rule_title}</td>
        <td>{result.category} / {result.subcategory}</td>
        <td class="{status_class}">{result.status.upper()}</td>
        <td>{result.message}</td>
        <td class="{confidence_class}">{result.confidence*100:.0f}%</td>
        <td class="reasoning">{reasoning_html}</td>
        <td>{suggested_files_html}</td>
        <td>{token_usage}</td>
    </tr>"""

        
        html += """
    </table>
</body>
</html>"""
        return html

def main():
    """Main CLI function for smart validator."""
    import argparse
    from llm_providers.factory import LLMProviderFactory
    from llm_providers.cli_help import LLMCLIHelp
    
    parser = argparse.ArgumentParser(
        prog='lintelligence',
        description='Smart AI-Powered Nextflow Pipeline Validator'
    )
    parser.add_argument('pipeline_path', nargs='?', help='Path to Nextflow pipeline directory')
    parser.add_argument('--format', choices=['cli', 'json', 'html'], default='cli', help='Output format')
    parser.add_argument('--output', help='Output file (default: stdout)')
    parser.add_argument('--rules-dir', default='rules', help='Directory containing rule YAML files')
    
    # LLM Provider Options
    llm_group = parser.add_argument_group('LLM Provider Options')
    llm_group.add_argument('--provider', choices=['openai', 'anthropic'], default='anthropic',
                          help='LLM provider to use (default: anthropic)')
    llm_group.add_argument('--model', help='Specific model to use (e.g., gpt-4o, claude-3-5-sonnet-20241022)')
    llm_group.add_argument('--api-key', help='API key for the LLM provider (overrides environment variables)')
    llm_group.add_argument('--list-models', action='store_true', help='List available models for the provider')
    llm_group.add_argument('--show-pricing', action='store_true', help='Show detailed pricing information for models')
    llm_group.add_argument('--provider-help', action='store_true', help='Show provider-specific setup and usage help')
    
    # Cache Management Options
    cache_group = parser.add_argument_group('Cache Management Options')
    cache_group.add_argument('--no-cache', action='store_true', help='Disable caching (force fresh validation)')
    cache_group.add_argument('--reset-cache', action='store_true', help='Clear existing cache before validation')
    cache_group.add_argument('--cache-dir', default='.nextflow_cache', help='Cache directory (default: .nextflow_cache)')
    cache_group.add_argument('--cache-stats', action='store_true', help='Show cache statistics and exit')
    
    args = parser.parse_args()
    
    # Handle help options first
    if args.provider_help:
        LLMCLIHelp.print_provider_help(args.provider)
        sys.exit(0)
    
    if args.list_models or args.show_pricing:
        if args.show_pricing:
            LLMCLIHelp.print_cost_comparison()
        # Show all models if --list-models is used without explicit --provider
        provider_to_show = None if args.list_models and not any(arg.startswith('--provider') for arg in sys.argv) else args.provider
        LLMCLIHelp.print_models_table(provider_to_show)
        sys.exit(0)
    
    # Handle cache-only operations
    if args.cache_stats:
        if args.pipeline_path:
            # Show stats for specific pipeline
            cache = ValidationCache(args.pipeline_path, args.cache_dir)
            stats = cache.get_cache_stats()
            
            print(f"\n💾 Cache Statistics for {args.pipeline_path}")
            print(f"{'='*50}")
            print(f"Cache Directory: {cache.cache_dir}")
            print(f"Total Cached Rules: {stats['total_cached_rules']}")
            print(f"Cache Size: {stats['cache_size_mb']:.2f} MB")
            print(f"Last Updated: {stats['last_updated']}")
            
            if stats['total_cached_rules'] > 0:
                print(f"\n📊 Cached Rule Breakdown:")
                for rule_set, count in stats['cached_by_rule_set'].items():
                    print(f"  {rule_set}: {count} rules")
                
                # Show cost savings with dynamic pricing
                try:
                    # Initialize LLM provider for dynamic pricing
                    api_key = args.api_key
                    if not api_key:
                        if args.provider == 'openai':
                            api_key = os.getenv('OPENAI_API_KEY')
                        else:  # anthropic
                            api_key = os.getenv('ANTHROPIC_API_KEY')
                    
                    if api_key:
                        config = LLMConfig(
                            provider=args.provider,
                            model=args.model,
                            api_key=api_key
                        )
                        llm_provider = LLMProviderFactory.create_provider(config)
                        
                        # Estimate total rules (use typical count)
                        total_rules = 118  # Current total: 26 + 85 + 7
                        
                        cost_info = cache.estimate_cost_savings(
                            args.provider, args.model, total_rules, llm_provider
                        )
                        
                        print(f"\n💰 Cost Analysis (Model: {args.provider}/{args.model})")
                        print(f"{'='*50}")
                        print(f"Cost per Rule: ${cost_info['cost_per_rule']:.4f}")
                        print(f"Estimated Savings: ${cost_info['estimated_savings']:.3f}")
                        print(f"Total Cost (no cache): ${cost_info['total_cost_without_cache']:.3f}")
                        print(f"Actual Cost (with cache): ${cost_info['actual_cost']:.3f}")
                        print(f"Savings Percentage: {cost_info['savings_percentage']:.1f}%")
                    else:
                        print(f"\n💰 Cost Analysis (Estimated - {args.provider}/{args.model})")
                        print(f"{'='*50}")
                        cost_info = cache.estimate_cost_savings(args.provider, args.model, 118)
                        print(f"Cost per Rule: ${cost_info['cost_per_rule']:.4f} (estimated)")
                        print(f"Estimated Savings: ${cost_info['estimated_savings']:.3f}")
                        print(f"Savings Percentage: {cost_info['savings_percentage']:.1f}%")
                        print("💡 Provide API key for accurate pricing")
                        
                except Exception as e:
                    print(f"\n⚠️  Could not calculate cost savings: {e}")
            else:
                print("\n📭 No cached results found")
        else:
            # Show general cache information
            cache_base_dir = Path(args.cache_dir).resolve()
            print(f"\n💾 General Cache Information")
            print(f"{'='*50}")
            print(f"Default Cache Directory: {cache_base_dir}")
            
            if cache_base_dir.exists():
                cache_dirs = [d for d in cache_base_dir.iterdir() if d.is_dir()]
                if cache_dirs:
                    print(f"Found {len(cache_dirs)} cached pipeline(s):")
                    for cache_dir in cache_dirs:
                        print(f"  📁 {cache_dir.name}")
                else:
                    print("📭 No cached pipelines found")
            else:
                print("📭 Cache directory does not exist")
            
            print("\n💡 Use --cache-stats with a pipeline path for detailed statistics")
        
        sys.exit(0)
    
    # Ensure pipeline_path is provided for validation
    if not args.pipeline_path:
        parser.error("pipeline_path is required for validation (use --help for usage)")
    
    # Determine API key
    api_key = args.api_key
    if not api_key:
        if args.provider == 'openai':
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                print("❌ OpenAI API key not found")
                print("💡 Set OPENAI_API_KEY environment variable or use --api-key option")
                sys.exit(1)
        else:  # anthropic
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                print("❌ Anthropic API key not found")
                print("💡 Set ANTHROPIC_API_KEY environment variable or use --api-key option")
                sys.exit(1)
    
    # Handle cache reset if requested
    if args.reset_cache:
        cache = ValidationCache(args.pipeline_path, args.cache_dir)
        cache.clear_cache()
        print(f"🗑️  Cache cleared for {args.pipeline_path}")
    
    # Initialize smart validator with LLM provider and cache settings
    try:
        validator = SmartNextflowValidator(
            rules_dir=args.rules_dir,
            max_workers=4,  # Default value
            llm_provider=args.provider,
            llm_model=args.model,
            llm_api_key=api_key,
            use_cache=not args.no_cache,
            cache_dir=args.cache_dir
        )
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Validate pipeline using adaptive validation with caching
    try:
        report = validator.validate_pipeline_adaptive(
            args.pipeline_path,
            output_file=args.output,
            output_format=args.format
        )
        
        # Generate report using the new adaptive report format
        if hasattr(validator, '_generate_cli_output'):
            if args.format == 'cli':
                output = validator._generate_cli_output(report)
            elif args.format == 'json':
                output = validator._generate_json_output(report)
            elif args.format == 'html':
                output = validator._generate_html_output(report)
            else:
                output = validator._generate_cli_output(report)  # Default fallback
        else:
            # Fallback to legacy method if needed
            standard_report = validator._convert_to_standard_report(report)
            output = validator.generate_report(standard_report, args.format)
        
        # Auto-generate output files with meaningful names
        pipeline_name = Path(args.pipeline_path).name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if args.output:
            output_file = args.output
        else:
            # Auto-generate filename based on format
            if args.format == 'html':
                output_file = f"smart_validation_report_{pipeline_name}_{timestamp}.html"
            elif args.format == 'json':
                output_file = f"smart_validation_report_{pipeline_name}_{timestamp}.json"
            else:
                output_file = None  # CLI output to stdout
        
        # Write output
        if output_file:
            with open(output_file, 'w') as f:
                f.write(output)
            print(f"📄 Smart validation report saved to: {output_file}")
            
            # Also generate HTML report if not already HTML format
            if args.format != 'html':
                html_output = validator.generate_report(report, 'html')
                html_file = f"smart_validation_report_{pipeline_name}_{timestamp}.html"
                with open(html_file, 'w') as f:
                    f.write(html_output)
                print(f"📄 Enhanced HTML report also saved to: {html_file}")
        else:
            print(output)
            
    except Exception as e:
        print(f"❌ Smart validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
