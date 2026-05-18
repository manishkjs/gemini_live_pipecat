import asyncio
import os
from google.genai import Client
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

async def main():
    project_id = os.getenv("GCP_PROJECT_ID") or "deep-clock-339817"
    location = os.getenv("GCP_LOCATION") or "us-central1"
    
    print(f"Attempting connection with project={project_id}, location={location}")
    client = Client(vertexai=True, project=project_id, location=location)
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
    )
    
    try:
        async with client.aio.live.connect(
            model="gemini-live-2.5-flash-native-audio",
            config=config
        ) as session:
            print("SUCCESS: Connected to Gemini Live on Vertex AI!")
    except Exception as e:
        print(f"FAILURE: Connection failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
