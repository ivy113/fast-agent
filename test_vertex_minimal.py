#!/usr/bin/env python3
"""
Minimal test to debug Vertex AI client issue
"""
import asyncio
import httpx
from anthropic import AsyncAnthropicVertex
from google.oauth2.credentials import Credentials

async def test_minimal():
    # Your token (replace with actual)
    token = "dummy-token-for-vertex"
    
    # Create credentials
    credentials = Credentials(token=token)
    
    print("Creating AsyncAnthropicVertex client...")
    
    # Try without httpx client first
    try:
        client = AsyncAnthropicVertex(
            region="us-central1",
            project_id="your-project-id",  # Replace with actual
            credentials=credentials
        )
        print(f"Client created: {client}")
        print(f"Client type: {type(client)}")
        print(f"Has _client attr: {hasattr(client, '_client')}")
        if hasattr(client, '_client'):
            print(f"_client is: {client._client}")
        
        # Try creating a message without streaming first
        print("\nTrying non-streaming create...")
        response = await client.messages.create(
            model="claude-3-sonnet@20240229",  # Use Vertex format
            max_tokens=100,
            messages=[{"role": "user", "content": "Hello"}],
            extra_headers={"x-r2d2-user": "test"}
        )
        print(f"Response: {response}")
        
    except Exception as e:
        print(f"Error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Now try with httpx client
    print("\n\nTrying with custom httpx client...")
    try:
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers={"x-r2d2-user": "test"}
        )
        
        client2 = AsyncAnthropicVertex(
            region="us-central1",
            project_id="your-project-id",
            credentials=credentials,
            http_client=http_client
        )
        
        print(f"Client2 created: {client2}")
        print(f"Has _client attr: {hasattr(client2, '_client')}")
        if hasattr(client2, '_client'):
            print(f"_client is: {client2._client}")
            
    except Exception as e:
        print(f"Error with httpx: {type(e).__name__}: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_minimal())