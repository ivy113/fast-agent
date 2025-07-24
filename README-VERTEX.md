  # Terminal 1: Run your token server
  cd /path/to/fast-agent
  python examples/dynamic_api_key_server.py

  # Output:
  # Starting Dynamic API Key Server
  # Endpoints:
  #   GET /           - Original token format
  #   GET /anthropic  - Fast-agent compatible format
  #   GET /stats      - Polling statistics
  #   POST /force-poll - Force token refresh
  #   GET /health     - Health check
  # INFO: Uvicorn running on http://0.0.0.0:8000

  2. Configuration Setup

  Create/modify your fastagent.config.yaml:

  # Enable dynamic key fetching
  dynamic_key:
    enabled: true
    endpoint_url: "http://localhost:8000"  # Your token server
    cache_duration_seconds: 300  # 5 minutes (less than 30min rotation)
    timeout_seconds: 10
    # Optional authentication:
    # auth_token: "your-bearer-token"
    # headers:
    #   Custom-Header: "value"

  # Configure Anthropic with Vertex AI
  anthropic:
    vertex_ai:
      enabled: true
      project_id: "your-gcp-project-id"
      region: "us-central1"  # or your preferred region
      use_dynamic_tokens: true  # This is the key setting!

  # Your other settings remain the same
  default_model: "sonnet"
  # ... rest of config

  3. Usage in Your Code

  No changes needed! Your existing code works:

  # This now automatically uses rotating tokens
  from mcp_agent.context import initialize_context

  context = await initialize_context("fastagent.config.yaml")
  # The library handles token rotation transparently

  Files Changed Summary

  Here's exactly what was modified:

  Modified Files:

  1. src/mcp_agent/config.py (Lines 119-157)
    - Added AnthropicVertexSettings class
    - Added vertex_ai field to AnthropicSettings
  2. src/mcp_agent/llm/dynamic_key_provider.py (Lines 105-117)
    - Enhanced to parse your token format {"token": "...", "age_seconds": ...}
    - Smart expiration calculation
  3. src/mcp_agent/llm/providers/augmented_llm_anthropic.py
    - Added AnthropicVertex import (Lines 24-27)
    - Added _create_anthropic_client() method (Lines 86-138)
    - Modified _llm() method to use new client creation (Line 347)
  4. examples/dynamic_api_key_server.py (Complete rewrite)
    - Your adaptive token poller integrated
    - FastAPI endpoints compatible with fast-agent

  Unchanged Files:

  - src/mcp_agent/llm/provider_key_manager.py (already had dynamic support)
  - src/mcp_agent/context.py (already had initialization logic)
  - All other files remain untouched
