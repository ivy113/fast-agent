"""
Enhanced FastAPI server for dynamic API key retrieval with Anthropic Vertex AI support.
This extends the adaptive token poller to work with the fast-agent library.

Usage:
1. Run this server: python dynamic_api_key_server.py
2. Configure fast-agent with dynamic keys pointing to this server
3. The library will automatically fetch tokens as needed

Example fast-agent configuration (fastagent.config.yaml):
```yaml
dynamic_key:
  enabled: true
  endpoint_url: "http://localhost:8000"
  cache_duration_seconds: 300  # 5 minutes (shorter than 30min rotation)

anthropic:
  vertex_ai:
    enabled: true
    project_id: "your-gcp-project"
    region: "us-central1"
    use_dynamic_tokens: true
```
"""

from fastapi import FastAPI
import subprocess
import asyncio
import time
from typing import Optional
from dataclasses import dataclass
from loguru import logger
import threading
from contextlib import asynccontextmanager

@dataclass
class TokenPattern:
    refresh_intervals: list[int]  # Observed intervals between refreshes
    last_refresh_time: float
    confidence_level: int = 0  # How confident we are in the pattern
    
class AdaptiveTokenPoller:
    def __init__(self):
        self.current_token: Optional[str] = None
        self.pattern = TokenPattern(refresh_intervals=[], last_refresh_time=0)
        self.lock = threading.Lock()
        self.polling_interval = 30  # Start with 30 seconds
        self.running = False
        
    def start_polling(self):
        """Start the background polling loop"""
        self.running = True
        logger.info("Starting adaptive token polling")
        return asyncio.create_task(self._poll_loop())
    
    async def _poll_loop(self):
        """Main polling loop with adaptive timing"""
        consecutive_same_tokens = 0
        
        while self.running:
            try:
                new_token = await self._fetch_token_from_helix()
                current_time = time.time()
                
                with self.lock:
                    if new_token != self.current_token:
                        # Token changed!
                        if self.current_token is not None:  # Not the first fetch
                            interval = current_time - self.pattern.last_refresh_time
                            self._update_pattern(interval)
                            logger.success(f"Token refreshed after {interval:.1f} seconds")
                        
                        self.current_token = new_token
                        self.pattern.last_refresh_time = current_time
                        consecutive_same_tokens = 0
                    else:
                        consecutive_same_tokens += 1
                
                # Adaptive polling interval
                next_interval = self._calculate_next_poll_interval(
                    consecutive_same_tokens, 
                    current_time
                )
                
                logger.debug(f"Next poll in {next_interval} seconds (same token count: {consecutive_same_tokens})")
                await asyncio.sleep(next_interval)
                
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(30)  # Fallback interval on error
    
    def _update_pattern(self, interval: float):
        """Update our understanding of the refresh pattern"""
        self.pattern.refresh_intervals.append(int(interval))
        
        # Keep only last 5 intervals for pattern detection
        if len(self.pattern.refresh_intervals) > 5:
            self.pattern.refresh_intervals.pop(0)
        
        # Check if we have a consistent pattern
        if len(self.pattern.refresh_intervals) >= 3:
            intervals = self.pattern.refresh_intervals
            avg_interval = sum(intervals) / len(intervals)
            variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
            
            # If intervals are consistent (low variance), increase confidence
            if variance < 100:  # Less than 10 second variance
                self.pattern.confidence_level += 1
                logger.info(f"Pattern confidence: {self.pattern.confidence_level}, avg interval: {avg_interval:.1f}s")
            else:
                self.pattern.confidence_level = max(0, self.pattern.confidence_level - 1)
                logger.debug(f"Pattern inconsistent, confidence: {self.pattern.confidence_level}")
    
    def _calculate_next_poll_interval(self, consecutive_same_tokens: int, current_time: float) -> int:
        """Calculate smart polling interval"""
        
        # If we have high confidence in pattern, poll less frequently
        if self.pattern.confidence_level >= 3 and self.pattern.refresh_intervals:
            avg_refresh_time = sum(self.pattern.refresh_intervals) / len(self.pattern.refresh_intervals)
            time_since_last_refresh = current_time - self.pattern.last_refresh_time
            time_until_next_refresh = avg_refresh_time - time_since_last_refresh
            
            if time_until_next_refresh > 300:  # More than 5 minutes away
                return 120  # Poll every 2 minutes
            elif time_until_next_refresh > 120:  # More than 2 minutes away
                return 60   # Poll every minute
            else:
                return 30   # Poll every 30 seconds when close
        
        # Default adaptive strategy based on consecutive same tokens
        if consecutive_same_tokens < 5:
            return 30  # Every 30 seconds initially
        elif consecutive_same_tokens < 20:
            return 60  # Every minute after 5 same tokens
        elif consecutive_same_tokens < 40:
            return 120  # Every 2 minutes after 20 same tokens
        else:
            return 300  # Every 5 minutes after 40 same tokens
    
    async def _fetch_token_from_helix(self) -> str:
        """Fetch token from Helix CLI"""
        logger.debug("Attempting to fetch token from Helix CLI")
        process = await asyncio.create_subprocess_shell(
            "helix auth access-token print -a",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = f"Helix CLI failed with return code {process.returncode}: {stderr.decode()}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        token = stdout.decode().strip()
        logger.debug(f"Successfully fetched token (length: {len(token)})")
        return token
    
    def get_current_token(self) -> dict:
        """Get current token with metadata"""
        with self.lock:
            if not self.current_token:
                raise Exception("No token available yet")
            
            return {
                "token": self.current_token,
                "last_refresh": self.pattern.last_refresh_time,
                "age_seconds": time.time() - self.pattern.last_refresh_time,
                "confidence_level": self.pattern.confidence_level,
                "refresh_intervals": self.pattern.refresh_intervals.copy(),
                "polling_interval": self.polling_interval
            }
    
    def stop_polling(self):
        """Stop the polling loop"""
        self.running = False

# Initialize poller
poller = AdaptiveTokenPoller()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = poller.start_polling()
    yield
    # Shutdown
    poller.stop_polling()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

# FastAPI setup
app = FastAPI(lifespan=lifespan, title="Dynamic API Key Server", version="1.0.0")

@app.get("/")
def get_token():
    """
    Original endpoint format for compatibility.
    Returns token with metadata for fast-agent consumption.
    """
    return poller.get_current_token()

@app.get("/anthropic")
def get_anthropic_token():
    """
    Provider-specific endpoint for Anthropic Vertex AI tokens.
    Fast-agent will call this when provider_name='anthropic' is requested.
    """
    token_info = poller.get_current_token()
    
    # Return in format expected by DynamicKeyProvider
    return {
        "api_key": token_info["token"],  # The actual token
        "expires_in": max(60, 1800 - token_info["age_seconds"]),  # Remaining time
        "provider": "anthropic",
        "type": "vertex_ai_token",
        "metadata": {
            "confidence_level": token_info["confidence_level"],
            "age_seconds": token_info["age_seconds"],
            "last_refresh": token_info["last_refresh"],
            "polling_strategy": "adaptive" if token_info["confidence_level"] >= 3 else "discovery"
        }
    }

@app.get("/stats")
def get_stats():
    """Get polling statistics and pattern info"""
    with poller.lock:
        return {
            "pattern_confidence": poller.pattern.confidence_level,
            "observed_intervals": poller.pattern.refresh_intervals,
            "average_interval": (
                sum(poller.pattern.refresh_intervals) / len(poller.pattern.refresh_intervals)
                if poller.pattern.refresh_intervals else None
            ),
            "last_refresh": poller.pattern.last_refresh_time,
            "current_age": time.time() - poller.pattern.last_refresh_time if poller.pattern.last_refresh_time else 0,
            "current_polling_strategy": "adaptive" if poller.pattern.confidence_level >= 3 else "discovery"
        }

@app.post("/force-poll")
async def force_poll():
    """Trigger immediate poll (useful for testing)"""
    try:
        new_token = await poller._fetch_token_from_helix()
        logger.info("Forced poll completed")
        return {"api_key": new_token, "forced": True}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        token_info = poller.get_current_token()
        return {
            "status": "healthy",
            "has_token": bool(token_info["token"]),
            "token_age": token_info["age_seconds"],
            "last_refresh": token_info["last_refresh"]
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting Dynamic API Key Server")
    logger.info("Endpoints:")
    logger.info("  GET /           - Original token format")
    logger.info("  GET /anthropic  - Fast-agent compatible format")
    logger.info("  GET /stats      - Polling statistics")
    logger.info("  POST /force-poll - Force token refresh")
    logger.info("  GET /health     - Health check")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)