
import asyncio
from google import genai
import inspect

async def main():
    print("Checking google.genai SDK...")
    # Try to find LiveSession or similar
    # client = genai.Client()
    # It seems we can't easily instantiate a session without connecting, which requires credentials.
    # But we can check the available types and methods via inspection if we can find the class.
    
    # live is likely a module or property on client
    client = genai.Client(api_key="dummy") # dummy key
    print(f"Client.aio.live type: {type(client.aio.live)}")
    
    # Check connect signature
    print(f"Connect signature: {inspect.signature(client.aio.live.connect)}")
    
    # We can't easily retrieve the return type class 'LiveSession' without running it?
    # Maybe we can find it in types?
    
    # Let's check google.genai.types
    from google.genai import types
    print("Types available:", [t for t in dir(types) if "Live" in t])
    
    # content with system role?
    print("Content signature:", inspect.signature(types.Content))

if __name__ == "__main__":
    asyncio.run(main())
