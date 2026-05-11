from google import genai
from google.genai import types
import os
import time
from loguru import logger
import platform
import io
from playwright.async_api import async_playwright, Playwright, Page
from typing import Optional
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

class ComputerUseAgent:
    def __init__(self, project_id: str = None, location: str = "us-central1"):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.location = location or os.getenv("GCP_LOCATION") or "us-central1"
        self.client = genai.Client(vertexai=True, project=self.project_id, location="global")
        self.model = "gemini-3-flash-preview"
        self.playwright: Optional[Playwright] = None
        self.browser = None
        self.page: Optional[Page] = None

    async def ensure_browser(self):
        """Ensures the Playwright browser is launched and a page is available."""
        if not self.browser:
            logger.info("Starting Playwright...")
            self.playwright = await async_playwright().start()
            logger.info("Launching Playwright browser using system Chrome...")
            # Launch headed browser using system Chrome to avoid Santa blocks
            self.browser = await self.playwright.chromium.launch(headless=False, channel="chrome")
            self.page = await self.browser.new_page()
            
            # Set viewport size to 1000x1000 to match Gemini's grid
            await self.page.set_viewport_size({"width": 1000, "height": 1000})
            
            # Initial navigation to avoid blank page
            await self.page.goto("https://www.google.com")

            # Handle new pages/tabs by redirecting to the main page
            async def handle_popup(popup_page):
                url = popup_page.url
                logger.info(f"Popup/New tab detected: {url}. Redirecting main page.")
                await popup_page.close()
                if self.page:
                    await self.page.goto(url)

            self.page.on("popup", handle_popup)

    async def close(self):
        """Closes the browser and stops Playwright."""
        if self.browser:
            logger.info("Closing Playwright browser...")
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright stopped.")

    async def execute_task(self, task_description: str):
        """
        Executes a computer use task in a loop using Playwright.
        """
        await self.ensure_browser()
        
        logger.info(f"Starting Computer Use task: {task_description}")
        
        generate_content_config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    )
                )
            ],
            max_output_tokens=300
        )
        
        contents = [task_description]
        
        max_turns = 10
        turn = 0
        MAX_RECENT_SCREENSHOTS = 3
        
        while turn < max_turns:
            turn += 1
            
            # Take screenshot
            logger.info("Capturing Playwright screenshot...")
            screenshot_bytes = await self.page.screenshot(type="png")
            
            # Prune old screenshots to save context space
            image_count = 0
            for content in reversed(contents):
                if not isinstance(content, types.Content):
                    continue
                for part in content.parts:
                    if part.inline_data and part.inline_data.mime_type == 'image/png':
                        image_count += 1
                        if image_count > MAX_RECENT_SCREENSHOTS:
                            # Replace image part with text placeholder
                            content.parts[content.parts.index(part)] = types.Part.from_text(text="[Screenshot removed to save space]")
            
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            data=screenshot_bytes,
                            mime_type='image/png'
                        )
                    ]
                )
            )
            
            logger.debug(f"Sending request to Gemini 3 Flash Preview (Turn {turn})...")
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            )
            
            if not response.function_calls:
                logger.info("Task completed or no function calls returned.")
                return response.text
                
            # Append model response to history
            contents.append(response.candidates[0].content)
            
            function_responses = []
            for function_call in response.function_calls:
                logger.info(f"Model requested action: {function_call.name} with args {function_call.args}")
                
                result = await self.execute_action(function_call.name, function_call.args)
                
                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=function_call.name,
                            response=result
                        )
                    )
                )
                
            # Append function responses to history
            contents.append(
                types.Content(
                    role="user",
                    parts=function_responses
                )
            )
            
            time.sleep(1) # Give UI time to settle
            
        return "Task exceeded maximum turns."

    async def execute_action(self, name: str, args: dict) -> dict:
        """Executes UI actions using Playwright."""
        logger.info(f"Executing Playwright action: {name} with {args}")
        
        try:
            if name == "open_web_browser":
                return {"status": "success", "url": self.page.url}
                
            elif name == "navigate":
                url = args.get("url")
                await self.page.goto(url)
                return {"status": "success", "url": self.page.url}
                
            elif name == "click_at":
                x = args.get("x")
                y = args.get("y")
                await self.page.mouse.click(x, y)
                return {"status": "success", "url": self.page.url}
                
            elif name == "type_text_at":
                x = args.get("x")
                y = args.get("y")
                text = args.get("text")
                await self.page.mouse.click(x, y)
                await self.page.keyboard.type(text)
                if args.get("press_enter", True):
                    await self.page.keyboard.press("Enter")
                return {"status": "success", "url": self.page.url}
                
            elif name == "wait_5_seconds":
                await self.page.wait_for_timeout(5000)
                return {"status": "success", "url": self.page.url}
                
            logger.warning(f"Action {name} not supported yet.")
            return {"status": "unsupported", "message": f"Action {name} not supported", "url": self.page.url}
            
        except Exception as e:
            logger.error(f"Error executing action {name}: {e}")
            return {"status": "error", "message": str(e), "url": self.page.url}

def get_tool_schema() -> FunctionSchema:
    """Returns the FunctionSchema for the execute_computer_task tool."""
    return FunctionSchema(
        name="execute_computer_task",
        description="Executes a task on the computer screen (browser or desktop).",
        properties={
            "task_description": {"type": "string", "description": "The specific task to perform (e.g., 'Open Google and search for weather')."},
            "is_explicit_intent": {
                "type": "boolean",
                "description": (
                    "Return `true` ONLY if the user explicitly requests to perform an action on the computer.\n"
                    "Return `false` for casual mentions or theoretical discussions."
                )
            }
        },
        required=["task_description", "is_explicit_intent"]
    )
