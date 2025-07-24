# Dynamic API Key Management

This feature allows fast-agent to fetch API keys dynamically from an external endpoint instead of storing them statically in configuration files or environment variables. This is useful when:

- Your API keys rotate frequently (e.g., every 30 minutes)
- You want centralized key management across multiple services
- You need to implement more complex authentication flows
- You want to avoid storing sensitive keys in configuration files

## Configuration

Add the following to your `fastagent.config.yaml`:

```yaml
dynamic_key:
  enabled: true
  endpoint_url: "http://localhost:8000/keys"  # Your API key server
  cache_duration_seconds: 1800  # Cache keys for 30 minutes
  timeout_seconds: 10
  auth_token: "your-secure-auth-token-here"  # Bearer token for authentication
  headers:  # Optional additional headers
    X-Custom-Header: "value"
```

## How It Works

1. When fast-agent needs an API key for a provider (e.g., "anthropic"), it first checks if dynamic key fetching is enabled
2. If enabled, it makes a GET request to `{endpoint_url}/{provider}` (e.g., `http://localhost:8000/keys/anthropic`)
3. The endpoint should return a JSON response with:
   ```json
   {
     "api_key": "your-api-key-here",
     "expires_in": 1800  // optional, in seconds
   }
   ```
4. The key is cached for the specified duration to minimize API calls
5. If the dynamic fetch fails, fast-agent falls back to static configuration (config file or environment variables)

## Example Server

See `examples/dynamic_api_key_server.py` for a complete FastAPI server implementation. To run it:

```bash
# Install dependencies
pip install fastapi uvicorn

# Run the server
python examples/dynamic_api_key_server.py
```

The example server:
- Provides API keys for different providers at `/keys/{provider}`
- Requires Bearer token authentication
- Returns keys with expiration information
- Includes health check endpoint

## Security Considerations

1. **Use HTTPS**: Always use HTTPS in production to protect API keys in transit
2. **Authentication**: Implement proper authentication on your key server (the example uses a simple bearer token)
3. **Network Security**: Ensure your key server is only accessible from authorized services
4. **Audit Logging**: Log all key requests for security auditing
5. **Key Rotation**: Implement proper key rotation in your key management service
6. **Error Handling**: The dynamic provider gracefully falls back to static keys if the endpoint is unavailable

## Integration with Key Management Services

In production, your endpoint would typically integrate with services like:
- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- Google Secret Manager

Example integration pattern:
```python
@app.get("/keys/{provider}")
async def get_api_key(provider: str):
    # Fetch from your KMS
    secret = await fetch_from_kms(f"fast-agent/{provider}/api-key")
    return {
        "api_key": secret.value,
        "expires_in": secret.ttl
    }
```

## Fallback Behavior

The dynamic key provider includes automatic fallback:
1. First tries to fetch from the dynamic endpoint
2. If that fails (network error, timeout, etc.), falls back to config file
3. If no config file key, falls back to environment variables
4. If all fail, raises an error with helpful instructions

This ensures your application remains functional even if the key server is temporarily unavailable.