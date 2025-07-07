"""
Rate limiting manager for API calls to prevent 429 errors.
"""
import time
import re
import threading
import random
from typing import Optional, Dict, Any

class RateLimitManager:
    """
    Manages rate limiting for API calls to prevent 429 errors.
    Uses adaptive backoff and request throttling based on error patterns.
    """
    
    def __init__(self):
        """Initialize the rate limit manager."""
        self._backoff_time = 0  # Current backoff time in seconds
        self._last_error_time = 0  # Last time a rate limit error occurred
        self._consecutive_errors = 0  # Count of consecutive rate limit errors
        self._lock = threading.Lock()  # Lock for updating rate limit variables
        self._provider_backoffs = {}  # Provider-specific backoff times
    
    def should_throttle(self, provider: str = "default") -> tuple[bool, float]:
        """
        Check if a request should be throttled based on recent rate limit errors.
        
        Args:
            provider: The API provider name (e.g., "openai", "anthropic")
            
        Returns:
            Tuple of (should_throttle, wait_time)
        """
        with self._lock:
            current_time = time.time()
            provider_backoff = self._provider_backoffs.get(provider, 0)
            global_backoff = self._backoff_time
            
            # Use the larger of provider-specific or global backoff
            effective_backoff = max(provider_backoff, global_backoff)
            
            if effective_backoff > 0:
                time_since_error = current_time - self._last_error_time
                if time_since_error < effective_backoff:
                    wait_time = effective_backoff - time_since_error
                    return True, wait_time
            
            return False, 0
    
    def handle_rate_limit_error(self, error: Exception, provider: str = "default") -> float:
        """
        Handle a rate limit error and calculate appropriate backoff time.
        
        Args:
            error: The exception that occurred
            provider: The API provider name
            
        Returns:
            The calculated backoff time in seconds
        """
        error_str = str(error)
        
        with self._lock:
            self._consecutive_errors += 1
            self._last_error_time = time.time()
            
            # Extract wait time from error message if available
            wait_time = None
            
            # OpenAI-style error message
            openai_wait_match = re.search(r'Please try again in ([0-9.]+)s', error_str)
            if openai_wait_match:
                wait_time = float(openai_wait_match.group(1))
            
            # Anthropic-style error message
            anthropic_wait_match = re.search(r'retry after ([0-9.]+) seconds', error_str)
            if anthropic_wait_match:
                wait_time = float(anthropic_wait_match.group(1))
            
            # Calculate backoff time
            if wait_time:
                # Use provider's suggested wait time with buffer
                backoff = wait_time * 1.5
            else:
                # Exponential backoff with increasing base for consecutive errors
                base = 2 + min(self._consecutive_errors, 5)  # Cap at base 7
                backoff = (base ** min(self._consecutive_errors, 3)) + random.uniform(1, 3)
            
            # Update provider-specific backoff
            self._provider_backoffs[provider] = backoff
            
            # Update global backoff if this is worse
            self._backoff_time = max(self._backoff_time, backoff)
            
            return backoff
    
    def reset_after_success(self, provider: str = "default"):
        """
        Reset rate limiting after a successful request.
        
        Args:
            provider: The API provider name
        """
        with self._lock:
            if self._consecutive_errors > 0:
                self._consecutive_errors = 0
                
                # Only reset the specific provider's backoff
                if provider in self._provider_backoffs:
                    self._provider_backoffs[provider] = 0
                
                # Only reset global backoff if all providers are reset
                if all(v == 0 for v in self._provider_backoffs.values()):
                    self._backoff_time = 0
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of rate limiting.
        
        Returns:
            Dictionary with rate limiting status
        """
        with self._lock:
            return {
                "global_backoff": self._backoff_time,
                "consecutive_errors": self._consecutive_errors,
                "provider_backoffs": self._provider_backoffs.copy(),
                "last_error_time": self._last_error_time
            }
