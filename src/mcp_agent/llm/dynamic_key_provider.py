"""
Dynamic API key provider that fetches keys from a FastAPI endpoint.
Supports caching with expiration to minimize API calls.
"""

import asyncio
import time
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel, Field
from mcp_agent.core.exceptions import ProviderKeyError
from mcp_agent.logging.logger import get_logger

logger = get_logger(__name__)


class DynamicKeyConfig(BaseModel):
    """Configuration for dynamic API key retrieval."""
    endpoint_url: str = Field(description="FastAPI endpoint URL to fetch API keys")
    cache_duration_seconds: int = Field(default=1800, description="How long to cache keys (default 30 minutes)")
    timeout_seconds: int = Field(default=10, description="Request timeout")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Additional headers for the request")
    auth_token: Optional[str] = Field(default=None, description="Authentication token for the endpoint")


class CachedApiKey(BaseModel):
    """Cached API key with expiration."""
    key: str
    expires_at: float
    
    @property
    def is_expired(self) -> bool:
        """Check if the cached key has expired."""
        return time.time() > self.expires_at


class DynamicKeyProvider:
    """
    Fetches API keys dynamically from a FastAPI endpoint with caching.
    
    Expected endpoint response format:
    {
        "api_key": "your-api-key-here",
        "expires_in": 1800  # optional, in seconds
    }
    """
    
    def __init__(self, config: DynamicKeyConfig):
        self.config = config
        self._cache: Dict[str, CachedApiKey] = {}
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            headers = self.config.headers or {}
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"
            self._client = httpx.AsyncClient(headers=headers)
        return self._client
    
    async def fetch_api_key(self, provider_name: str) -> str:
        """
        Fetch API key for the given provider from the FastAPI endpoint.
        
        Args:
            provider_name: Name of the provider (e.g., "anthropic", "openai")
            
        Returns:
            The API key as a string
            
        Raises:
            ProviderKeyError: If unable to fetch the key
        """
        async with self._lock:
            # Check cache first
            cached_key = self._cache.get(provider_name)
            if cached_key and not cached_key.is_expired:
                logger.debug(f"Using cached API key for {provider_name}")
                return cached_key.key
            
            # Fetch new key
            try:
                client = await self._get_client()
                
                # Support both provider-specific endpoints and root endpoint
                # First try root endpoint (for your adaptive token poller)
                url = self.config.endpoint_url.rstrip('/')
                
                logger.info(f"Fetching API key for {provider_name} from {url}")
                response = await client.get(
                    url,
                    timeout=self.config.timeout_seconds
                )
                response.raise_for_status()
                
                data = response.json()
                
                # Handle different response formats
                api_key = None
                expires_in = self.config.cache_duration_seconds
                
                # Check for your adaptive token poller format
                if "token" in data:
                    api_key = data["token"]
                    # Use age information if available
                    if "age_seconds" in data:
                        # Estimate remaining time based on typical 30min refresh
                        age_seconds = data["age_seconds"]
                        typical_refresh_interval = 1800  # 30 minutes
                        expires_in = max(60, typical_refresh_interval - age_seconds)  # At least 1 minute
                elif "api_key" in data:
                    # Standard format
                    api_key = data["api_key"]
                    expires_in = data.get("expires_in", self.config.cache_duration_seconds)
                
                if not api_key:
                    raise ProviderKeyError(
                        f"Invalid response from key endpoint",
                        f"Endpoint did not return a token or api_key field for {provider_name}. Response: {data}"
                    )
                
                # Calculate expiration
                expires_at = time.time() + expires_in
                
                # Cache the key
                self._cache[provider_name] = CachedApiKey(
                    key=api_key,
                    expires_at=expires_at
                )
                
                logger.info(f"Successfully fetched and cached API key for {provider_name} (expires in {expires_in}s)")
                return api_key
                
            except httpx.HTTPStatusError as e:
                raise ProviderKeyError(
                    f"Failed to fetch API key for {provider_name}",
                    f"HTTP {e.response.status_code}: {e.response.text}"
                )
            except httpx.RequestError as e:
                raise ProviderKeyError(
                    f"Failed to connect to key endpoint",
                    f"Could not reach {self.config.endpoint_url}: {str(e)}"
                )
            except Exception as e:
                raise ProviderKeyError(
                    f"Unexpected error fetching API key",
                    f"Error: {str(e)}"
                )
    
    def get_api_key_sync(self, provider_name: str) -> str:
        """
        Synchronous wrapper for fetch_api_key.
        Creates a new event loop if needed.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, we need to handle this differently
                # This is a complex scenario that might require refactoring
                raise ProviderKeyError(
                    "Cannot fetch dynamic key in sync context",
                    "Dynamic key fetching requires async context"
                )
        except RuntimeError:
            # No event loop exists, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self.fetch_api_key(provider_name))
        finally:
            if not loop.is_running():
                loop.close()
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def clear_cache(self, provider_name: Optional[str] = None):
        """Clear cached keys."""
        if provider_name:
            self._cache.pop(provider_name, None)
        else:
            self._cache.clear()