import json
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import time

# ValidationResult will be imported from smart_validator when needed
# or we'll use duck typing for compatibility


class ValidationCache:
    """Manages caching and resume functionality for pipeline validation."""
    
    def __init__(self, pipeline_path: str, cache_dir: str = None):
        """Initialize validation cache.
        
        Args:
            pipeline_path: Path to the pipeline being validated
            cache_dir: Optional custom cache directory (defaults to .nextflow_cache in pipeline root)
        """
        self.pipeline_path = Path(pipeline_path)
        
        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = self.pipeline_path / '.nextflow_cache'
        
        self.cache_dir.mkdir(exist_ok=True)
        
        # Cache file paths
        self.results_cache_file = self.cache_dir / 'validation_results.json'
        self.metadata_cache_file = self.cache_dir / 'validation_metadata.json'
        self.file_hashes_file = self.cache_dir / 'file_hashes.json'
        
        # Load existing cache
        self.cached_results = self._load_cached_results()
        self.cached_metadata = self._load_cached_metadata()
        self.file_hashes = self._load_file_hashes()
        
    def _load_cached_results(self) -> Dict[str, Dict]:
        """Load cached validation results."""
        if self.results_cache_file.exists():
            try:
                with open(self.results_cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _load_cached_metadata(self) -> Dict[str, Any]:
        """Load cached validation metadata."""
        if self.metadata_cache_file.exists():
            try:
                with open(self.metadata_cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _load_file_hashes(self) -> Dict[str, str]:
        """Load cached file hashes for change detection."""
        if self.file_hashes_file.exists():
            try:
                with open(self.file_hashes_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_cached_results(self):
        """Save validation results to cache."""
        try:
            with open(self.results_cache_file, 'w') as f:
                json.dump(self.cached_results, f, indent=2)
        except IOError as e:
            print(f"⚠️  Warning: Could not save results cache: {e}")
    
    def _save_cached_metadata(self):
        """Save validation metadata to cache."""
        try:
            with open(self.metadata_cache_file, 'w') as f:
                json.dump(self.cached_metadata, f, indent=2)
        except IOError as e:
            print(f"⚠️  Warning: Could not save metadata cache: {e}")
    
    def _save_file_hashes(self):
        """Save file hashes to cache."""
        try:
            with open(self.file_hashes_file, 'w') as f:
                json.dump(self.file_hashes, f, indent=2)
        except IOError as e:
            print(f"⚠️  Warning: Could not save file hashes: {e}")
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        if not file_path.exists():
            return ""
        
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except IOError:
            return ""
    
    def _get_pipeline_files(self) -> List[Path]:
        """Get list of relevant pipeline files to monitor for changes."""
        pipeline_files = []
        
        # Core pipeline files
        core_files = ['main.nf', 'nextflow.config', 'README.md', 'README.rst']
        for file_name in core_files:
            file_path = self.pipeline_path / file_name
            if file_path.exists():
                pipeline_files.append(file_path)
        
        # Module files
        modules_dir = self.pipeline_path / 'modules'
        if modules_dir.exists():
            for module_file in modules_dir.rglob('*.nf'):
                pipeline_files.append(module_file)
        
        # Workflow files
        workflows_dir = self.pipeline_path / 'workflows'
        if workflows_dir.exists():
            for workflow_file in workflows_dir.rglob('*.nf'):
                pipeline_files.append(workflow_file)
        
        # Subworkflow files
        subworkflows_dir = self.pipeline_path / 'subworkflows'
        if subworkflows_dir.exists():
            for subworkflow_file in subworkflows_dir.rglob('*.nf'):
                pipeline_files.append(subworkflow_file)
        
        # Configuration files
        conf_dir = self.pipeline_path / 'conf'
        if conf_dir.exists():
            for conf_file in conf_dir.rglob('*.config'):
                pipeline_files.append(conf_file)
        
        return pipeline_files
    
    def _update_file_hashes(self):
        """Update file hashes for change detection."""
        pipeline_files = self._get_pipeline_files()
        
        for file_path in pipeline_files:
            relative_path = str(file_path.relative_to(self.pipeline_path))
            self.file_hashes[relative_path] = self._calculate_file_hash(file_path)
        
        self._save_file_hashes()
    
    def _has_pipeline_changed(self) -> bool:
        """Check if pipeline files have changed since last validation."""
        pipeline_files = self._get_pipeline_files()
        
        for file_path in pipeline_files:
            relative_path = str(file_path.relative_to(self.pipeline_path))
            current_hash = self._calculate_file_hash(file_path)
            cached_hash = self.file_hashes.get(relative_path, "")
            
            if current_hash != cached_hash:
                return True
        
        return False
    
    def is_cache_valid(self, max_age_hours: int = 24) -> bool:
        """Check if cache is valid and not too old."""
        if not self.cached_metadata:
            return False
        
        # Check cache age
        cache_timestamp = self.cached_metadata.get('timestamp')
        if cache_timestamp:
            cache_time = datetime.fromisoformat(cache_timestamp)
            if datetime.now() - cache_time > timedelta(hours=max_age_hours):
                return False
        
        # Check if pipeline files have changed
        if self._has_pipeline_changed():
            return False
        
        return True
    
    def get_cached_result(self, rule_id: str, rule_set_name: str = None) -> Optional[Any]:
        """Get cached validation result for a specific rule.
        
        Returns a dictionary-like object that can be used to create
        SmartValidationResult or ValidationResult objects.
        """
        cache_key = f"{rule_id}_{rule_set_name}" if rule_set_name else rule_id
        
        if cache_key not in self.cached_results:
            return None
        
        cached_data = self.cached_results[cache_key]
        
        # Return a simple object with the cached data that can be used
        # by the calling code to create the appropriate result type
        class CachedResult:
            def __init__(self, data):
                for key, value in data.items():
                    setattr(self, key, value)
        
        try:
            return CachedResult(cached_data)
        except (KeyError, TypeError):
            return None
    
    def cache_result(self, rule_id: str, rule_set_name: str, result: Any):
        """Cache a validation result.
        
        Args:
            rule_id: The rule ID
            rule_set_name: The rule set name
            result: ValidationResult or SmartValidationResult object
        """
        cache_key = f"{rule_id}_{rule_set_name}" if rule_set_name else rule_id
        
        cached_data = {
            'rule_id': getattr(result, 'rule_id', rule_id),
            'rule_title': getattr(result, 'rule_title', ''),
            'category': getattr(result, 'category', ''),
            'subcategory': getattr(result, 'subcategory', ''),
            'status': getattr(result, 'status', ''),
            'message': getattr(result, 'message', ''),
            'confidence': getattr(result, 'confidence', 0.0),
            'reasoning': getattr(result, 'reasoning', ''),
            'line_number': getattr(result, 'line_number', None),
            'file_path': getattr(result, 'file_path', None),
            'rule_set_name': rule_set_name,
            'cached_at': datetime.now().isoformat()
        }
        
        self.cached_results[cache_key] = cached_data
        self._save_cached_results()
    
    def get_cached_rules(self) -> List[str]:
        """Get list of rule IDs that have cached results."""
        return list(self.cached_results.keys())
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics including token usage and cost information."""
        total_rules = len(self.cached_results)
        cache_age = None
        last_updated = "Never"
        
        if self.cached_metadata.get('timestamp'):
            cache_time = datetime.fromisoformat(self.cached_metadata['timestamp'])
            cache_age = datetime.now() - cache_time
            last_updated = cache_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Count cached rules by rule set and calculate token usage
        cached_by_rule_set = {}
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        rules_with_cost_data = 0
        
        for rule_id, result in self.cached_results.items():
            rule_set = getattr(result, 'rule_set_name', 'unknown')
            cached_by_rule_set[rule_set] = cached_by_rule_set.get(rule_set, 0) + 1
            
            # Aggregate token usage and cost information
            if hasattr(result, 'input_tokens') and result.input_tokens:
                total_input_tokens += result.input_tokens
                rules_with_cost_data += 1
            if hasattr(result, 'output_tokens') and result.output_tokens:
                total_output_tokens += result.output_tokens
            if hasattr(result, 'cost') and result.cost:
                total_cost += result.cost
        
        return {
            'total_cached_rules': total_rules,
            'cache_age': cache_age,
            'last_updated': last_updated,
            'cache_valid': self.is_cache_valid(),
            'pipeline_changed': self._has_pipeline_changed(),
            'cache_size_mb': self._get_cache_size_mb(),
            'cached_by_rule_set': cached_by_rule_set,
            # Token usage and cost statistics
            'total_input_tokens': total_input_tokens,
            'total_output_tokens': total_output_tokens,
            'total_cost': total_cost,
            'rules_with_cost_data': rules_with_cost_data,
            'estimated_cost_saved': total_cost  # Cost saved by using cache
        }
    
    def _get_cache_size_mb(self) -> float:
        """Get total cache size in MB."""
        total_size = 0
        for cache_file in [self.results_cache_file, self.metadata_cache_file, self.file_hashes_file]:
            if cache_file.exists():
                total_size += cache_file.stat().st_size
        return total_size / (1024 * 1024)
    
    def update_metadata(self, metadata: Dict[str, Any]):
        """Update validation metadata."""
        self.cached_metadata.update(metadata)
        self.cached_metadata['timestamp'] = datetime.now().isoformat()
        self._save_cached_metadata()
        
        # Update file hashes
        self._update_file_hashes()
    
    def clear_cache(self):
        """Clear all cached data."""
        self.cached_results = {}
        self.cached_metadata = {}
        self.file_hashes = {}
        
        # Remove cache files
        for cache_file in [self.results_cache_file, self.metadata_cache_file, self.file_hashes_file]:
            if cache_file.exists():
                cache_file.unlink()
        
        print("🗑️  Cache cleared successfully")
    
    def estimate_cost_savings(self, provider: str, model: str, total_rules: int, llm_provider=None) -> Dict[str, Any]:
        """Estimate cost savings from using cache using dynamic pricing from LLM provider.
        
        Args:
            provider: Provider name (e.g., 'openai', 'anthropic')
            model: Model name (e.g., 'gpt-4-turbo', 'claude-3-haiku-20240307')
            total_rules: Total number of rules to validate
            llm_provider: LLM provider instance to get actual pricing from
            
        Returns:
            Dictionary with cost savings information
        """
        cached_count = len(self.cached_results)
        
        # Try to get actual pricing from LLM provider
        cost_per_rule = self._get_dynamic_cost_per_rule(provider, model, llm_provider)
        
        saved_cost = cached_count * cost_per_rule
        total_cost_without_cache = total_rules * cost_per_rule
        actual_cost = (total_rules - cached_count) * cost_per_rule
        
        return {
            'cached_rules': cached_count,
            'total_rules': total_rules,
            'cost_per_rule': cost_per_rule,
            'estimated_savings': saved_cost,
            'total_cost_without_cache': total_cost_without_cache,
            'actual_cost': actual_cost,
            'savings_percentage': (cached_count / total_rules * 100) if total_rules > 0 else 0,
            'provider': provider,
            'model': model
        }
    
    def _get_dynamic_cost_per_rule(self, provider: str, model: str, llm_provider=None) -> float:
        """Get dynamic cost per rule from LLM provider or fallback to estimates.
        
        Args:
            provider: Provider name (e.g., 'openai', 'anthropic')
            model: Model name (e.g., 'gpt-4-turbo', 'claude-3-haiku-20240307')
            llm_provider: LLM provider instance to get actual pricing from
            
        Returns:
            Cost per rule in USD
        """
        # Try to get actual pricing from LLM provider
        if llm_provider and hasattr(llm_provider, 'get_model_info'):
            try:
                model_info = llm_provider.get_model_info(model)
                if model_info:
                    # Estimate cost per rule based on typical token usage
                    # Assume ~1000 input tokens and ~200 output tokens per rule validation
                    input_tokens = 1000
                    output_tokens = 200
                    
                    input_cost = (input_tokens / 1000) * model_info.cost_per_1k_input
                    output_cost = (output_tokens / 1000) * model_info.cost_per_1k_output
                    
                    return input_cost + output_cost
            except Exception as e:
                print(f"⚠️  Could not get dynamic pricing: {e}")
        
        # Fallback to hardcoded estimates if dynamic pricing fails
        cost_estimates = {
            'openai': {
                'gpt-4o-mini': 0.001,
                'gpt-4o': 0.005,
                'gpt-4': 0.02,
                'gpt-4-turbo': 0.005,
                'gpt-4-turbo-2024-04-09': 0.005,
                'gpt-4-0125-preview': 0.005,
                'gpt-4-1106-preview': 0.005,
                'gpt-4.1': 0.015,
                'gpt-3.5-turbo': 0.0005,
                'gpt-3.5-turbo-16k': 0.001
            },
            'anthropic': {
                'claude-3-haiku-20240307': 0.002,
                'claude-3-sonnet-20240229': 0.01,
                'claude-3-5-sonnet-20241022': 0.012,
                'claude-3-opus-20240229': 0.05
            }
        }
        
        provider_costs = cost_estimates.get(provider.lower(), {})
        return provider_costs.get(model.lower(), 0.005)  # Default estimate
