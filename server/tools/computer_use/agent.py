from google import genai
from google.genai import types
import os
import time
import asyncio
from loguru import logger
import platform
import io
from playwright.async_api import async_playwright, Playwright, Page
from typing import Optional
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

PLAYWRIGHT_KEY_MAP = {
    "backspace": "Backspace",
    "tab": "Tab",
    "return": "Enter",
    "enter": "Enter",
    "shift": "Shift",
    "control": "ControlOrMeta",
    "alt": "Alt",
    "escape": "Escape",
    "space": "Space",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "end": "End",
    "home": "Home",
    "left": "ArrowLeft",
    "up": "ArrowUp",
    "right": "ArrowRight",
    "down": "ArrowDown",
    "insert": "Insert",
    "delete": "Delete",
    "command": "Meta",
}

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
            
            cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
            
            try:
                logger.info(f"Connecting to existing Chrome via CDP: {cdp_url}")
                self.browser = await asyncio.wait_for(
                    self.playwright.chromium.connect_over_cdp(cdp_url),
                    timeout=5.0
                )
                
                # Use existing context (has all cookies, sessions, extensions)
                contexts = self.browser.contexts
                if contexts:
                    context = contexts[0]
                    pages = context.pages
                    self.page = pages[0] if pages else await context.new_page()
                else:
                    context = await self.browser.new_context()
                    self.page = await context.new_page()
            except Exception as e:
                logger.warning(f"CDP connection failed ({e}), falling back to launch_persistent_context")
                import pathlib
                chrome_profile = os.getenv("CHROME_USER_DATA_DIR", os.path.expanduser("~/.config/google-chrome"))
                logger.info(f"Launching Chrome with existing profile: {chrome_profile}")
                try:
                    context = await self.playwright.chromium.launch_persistent_context(
                        chrome_profile,
                        headless=False,
                        channel="chrome",
                        viewport={"width": 1000, "height": 1000}
                    )
                    self.page = context.pages[0] if context.pages else await context.new_page()
                    self.browser = context # Store context as browser
                except Exception as e2:
                    logger.warning(f"Fallback to persistent context failed ({e2}), trying clean launch")
                    self.browser = await self.playwright.chromium.launch(headless=False, channel="chrome")
                    self.page = await self.browser.new_page()
                    await self.page.goto("https://www.google.com")
                
            await self.page.set_viewport_size({"width": 1000, "height": 1000})

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
            # Don't close if connected via CDP — it would kill the user's browser
            if not os.getenv("CHROME_CDP_URL"):
                logger.info("Closing Playwright browser...")
                await self.browser.close()
            else:
                logger.info("Disconnecting from CDP (browser stays open)")
                await self.browser.close() # disconnect only, doesn't kill Chrome via CDP
        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright stopped.")

    async def denormalize_coords(self, x: int, y: int) -> tuple[int, int]:
        size = self.page.viewport_size
        return int(x / 1000 * size['width']), int(y / 1000 * size['height'])

    async def execute_task(self, task_description: str, speak_callback=None):
        """
        Executes a computer use task in a loop using Playwright.
        """
        await self.ensure_browser()
        
        logger.info(f"Starting Computer Use task: {task_description}")
        
        generate_content_config = types.GenerateContentConfig(
            temperature=1.0,
            top_p=0.95,
            top_k=40,
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    )
                )
            ],
            max_output_tokens=8192
        )
        
        contents = [task_description]
        
        max_turns = 10
        turn = 0
        MAX_RECENT_SCREENSHOTS = 3
        
        while turn < max_turns:
            turn += 1
            
            # Optimization 5: Only take screenshot on the first turn at the top of the loop
            if turn == 1:
                logger.info("Capturing initial Playwright screenshot...")
                screenshot_bytes = await self.page.screenshot(type="png")
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
            
            # Optimization 4: Prune old screenshots without mutating list during iteration
            image_count = 0
            for content in reversed(contents):
                if not isinstance(content, types.Content):
                    continue
                new_parts = []
                for part in content.parts:
                    if part.inline_data and part.inline_data.mime_type == 'image/png':
                        image_count += 1
                        if image_count > MAX_RECENT_SCREENSHOTS:
                            new_parts.append(types.Part.from_text(text="[Screenshot removed to save space]"))
                        else:
                            new_parts.append(part)
                    else:
                        new_parts.append(part)
                content.parts = new_parts
            
            logger.debug(f"Sending request to Gemini 3 Flash Preview (Turn {turn})...")
            
            # Optimization 2: Retry logic with backoff, executor, AND timeout
            max_retries = 5
            base_delay_s = 1
            response = None
            
            for attempt in range(max_retries):
                try:
                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self.client.models.generate_content(
                                model=self.model,
                                contents=contents,
                                config=generate_content_config,
                            )
                        ),
                        timeout=60.0
                    )
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"API call failed after {max_retries} attempts: {e}")
                        raise e
                    delay = base_delay_s * (2**attempt)
                    logger.warning(f"API call failed or timed out: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
            
            if response.text and speak_callback:
                await speak_callback(response.text)
            
            # Handle malformed function calls
            if response.candidates and response.candidates[0].finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL:
                logger.warning("Malformed function call detected. Retrying turn...")
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Your last function call was malformed. Please try again.")]
                    )
                )
                continue
                
            if not response.function_calls:
                logger.info("Task completed or no function calls returned.")
                return response.text
                
            contents.append(response.candidates[0].content)
            
            function_responses = []
            for function_call in response.function_calls:
                logger.info(f"Model requested action: {function_call.name} with args {function_call.args}")
                result = await self.execute_action(function_call.name, function_call.args)
                
                if result.get("status") == "error" and "closed" in result.get("message", "").lower():
                    logger.error("Browser was closed. Aborting task.")
                    return "Browser was closed."
                
                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=function_call.name,
                            response=result
                        )
                    )
                )
                
            # Optimization 3: Take fresh screenshot after actions and append with responses
            logger.info("Capturing fresh screenshot after actions...")
            fresh_screenshot_bytes = await self.page.screenshot(type="png")
            
            parts = function_responses + [
                types.Part.from_bytes(
                    data=fresh_screenshot_bytes,
                    mime_type='image/png'
                )
            ]
            
            contents.append(
                types.Content(
                    role="user",
                    parts=parts
                )
            )
            
            await asyncio.sleep(1) # Give UI time to settle
            
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
                x, y = await self.denormalize_coords(args.get("x"), args.get("y"))
                await self.page.mouse.click(x, y)
                return {"status": "success", "url": self.page.url}
                
            elif name == "type_text_at":
                x, y = await self.denormalize_coords(args.get("x"), args.get("y"))
                text = args.get("text")
                await self.page.mouse.click(x, y)
                
                if args.get("clear_before_typing", False):
                    modifier = "Meta" if platform.system() == "Darwin" else "Control"
                    await self.page.keyboard.down(modifier)
                    await self.page.keyboard.press("a")
                    await self.page.keyboard.up(modifier)
                    await self.page.keyboard.press("Backspace")
                    
                await self.page.keyboard.type(text)
                if args.get("press_enter", True):
                    await self.page.keyboard.press("Enter")
                return {"status": "success", "url": self.page.url}
                
            elif name == "wait_5_seconds":
                await self.page.wait_for_timeout(5000)
                return {"status": "success", "url": self.page.url}
                
            elif name == "hover_at":
                x, y = await self.denormalize_coords(args.get("x"), args.get("y"))
                await self.page.mouse.move(x, y)
                return {"status": "success", "url": self.page.url}
                
            elif name == "scroll_document":
                direction = args.get("direction", "down")
                if direction == "down":
                    await self.page.evaluate("window.scrollBy(0, 500)")
                elif direction == "up":
                    await self.page.evaluate("window.scrollBy(0, -500)")
                elif direction == "left":
                    await self.page.evaluate("window.scrollBy(-500, 0)")
                elif direction == "right":
                    await self.page.evaluate("window.scrollBy(500, 0)")
                return {"status": "success", "url": self.page.url}
                
            elif name == "scroll_at":
                x, y = await self.denormalize_coords(args.get("x"), args.get("y"))
                direction = args.get("direction", "down")
                await self.page.mouse.move(x, y)
                if direction == "down":
                    await self.page.mouse.wheel(0, 500)
                elif direction == "up":
                    await self.page.mouse.wheel(0, -500)
                elif direction == "left":
                    await self.page.mouse.wheel(-500, 0)
                elif direction == "right":
                    await self.page.mouse.wheel(500, 0)
                return {"status": "success", "url": self.page.url}
                
            elif name == "go_back":
                await self.page.go_back()
                return {"status": "success", "url": self.page.url}
                
            elif name == "go_forward":
                await self.page.go_forward()
                return {"status": "success", "url": self.page.url}
                
            elif name == "search":
                await self.page.goto("https://www.google.com")
                return {"status": "success", "url": self.page.url}
                
            elif name == "key_combination":
                keys = args.get("keys", "")
                parts = keys.split("+")
                modifiers = []
                key_to_press = None
                
                for p in parts:
                    p_clean = p.strip().lower()
                    if p_clean in ["control", "ctrl", "alt", "shift", "command", "cmd", "meta"]:
                        if p_clean in ["control", "ctrl"]:
                            modifiers.append("ControlOrMeta")
                        elif p_clean in ["command", "cmd", "meta"]:
                            modifiers.append("Meta")
                        elif p_clean == "alt":
                            modifiers.append("Alt")
                        elif p_clean == "shift":
                            modifiers.append("Shift")
                    else:
                        key_to_press = PLAYWRIGHT_KEY_MAP.get(p_clean, p_clean)
                        
                for mod in modifiers:
                    await self.page.keyboard.down(mod)
                    
                if key_to_press:
                    await self.page.keyboard.press(key_to_press)
                    
                for mod in reversed(modifiers):
                    await self.page.keyboard.up(mod)
                    
                return {"status": "success", "url": self.page.url}
                
            elif name == "drag_and_drop":
                source_x, source_y = await self.denormalize_coords(args.get("x"), args.get("y"))
                target_x, target_y = await self.denormalize_coords(args.get("destination_x"), args.get("destination_y"))
                await self.page.mouse.move(source_x, source_y)
                await self.page.mouse.down()
                await self.page.mouse.move(target_x, target_y)
                await self.page.mouse.up()
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
