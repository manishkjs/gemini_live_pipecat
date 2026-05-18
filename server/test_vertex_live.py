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
    
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.adapters.services.gemini_adapter import GeminiLLMAdapter

    standard_tools = [
        FunctionSchema(
            name="get_current_time",
            description="Get the current time.",
            properties={
                "is_explicit_request": {
                    "type": "boolean",
                    "description": "Return `true` ONLY if the user explicitly asks for the current time."
                }
            },
            required=["is_explicit_request"]
        ),
        FunctionSchema(
            name="project_search",
            description="Search Noida/Greater Noida projects by query keywords (e.g. Noida, budget, 4 BHK).",
            properties={
                "query": {
                    "type": "string",
                    "description": "Search keywords (e.g. location, budget, configuration)"
                }
            },
            required=["query"]
        ),
        FunctionSchema(
            name="handle_other_client_queries",
            description="Handle miscellaneous user queries outside of project pitches.",
            properties={
                "query": {
                    "type": "string",
                    "description": "The user's query"
                }
            },
            required=["query"]
        )
    ]
    tools_schema = ToolsSchema(standard_tools=standard_tools)
    adapter = GeminiLLMAdapter()
    provider_tools = adapter.to_provider_tools_format(tools_schema)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=provider_tools
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
