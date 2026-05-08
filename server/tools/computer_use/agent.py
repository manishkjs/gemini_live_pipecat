from google import genai
from google.genai import types
import os
import time
from loguru import logger
import platform
import io
import subprocess
from PIL import ImageGrab
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

class ComputerUseAgent:
    def __init__(self, project_id: str = None, location: str = "us-central1"):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.location = location or os.getenv("GCP_LOCATION") or "us-central1"
        self.client = genai.Client(vertexai=True, project=self.project_id, location="global")
        self.model = "gemini-3-flash-preview"

    async def execute_task(self, task_description: str, get_screenshot_callback, execute_action_callback):
        """
        Executes a computer use task in a loop.
        """
        logger.info(f"Starting Computer Use task: {task_description}")
        
        generate_content_config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    )
                )
            ]
        )
        
        contents = [task_description]
        
        # Initial screenshot
        screenshot_bytes = await get_screenshot_callback()
        if screenshot_bytes:
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
            
        max_turns = 10
        turn = 0
        
        while turn < max_turns:
            turn += 1
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
                
                # Call the callback to execute the action
                result = await execute_action_callback(function_call.name, function_call.args)
                
                # Handle safety confirmation request
                if result.get("status") == "require_confirmation":
                    logger.info("Action requires user confirmation. Returning control to main agent.")
                    return f"Action requires user confirmation: {result.get('message')}. Please ask the user for confirmation."
                
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
            
            # Take new screenshot and append
            screenshot_bytes = await get_screenshot_callback()
            if screenshot_bytes:
                contents[-1].parts.append(
                    types.Part.from_bytes(
                        data=screenshot_bytes,
                        mime_type='image/png'
                    )
                )
                
            time.sleep(1) # Give UI time to settle
            
        return "Task exceeded maximum turns."

def execute_action_locally(name: str, args: dict) -> dict:
    """Executes UI actions locally on macOS using AppleScript."""
    logger.info(f"Executing local Mac action: {name} with {args}")
    
    # Check for safety decision requiring confirmation
    safety_decision = args.get('safety_decision')
    if safety_decision and safety_decision.get('decision') == 'require_confirmation':
        explanation = safety_decision.get('explanation')
        logger.warning(f"Action requires confirmation: {explanation}")
        return {"status": "require_confirmation", "message": explanation}
    
    # Get screen size for coordinate mapping
    try:
        img = ImageGrab.grab()
        screen_width, screen_height = img.size
    except Exception as e:
        logger.error(f"Failed to get screen size: {e}")
        return {"status": "error", "message": "Failed to get screen size"}
    
    def map_coords(x, y):
        # Model uses 1000x1000 grid
        actual_x = int((x / 1000.0) * screen_width)
        actual_y = int((y / 1000.0) * screen_height)
        return actual_x, actual_y

    try:
        # Computer Use requires returning a URL in the response for browser environment
        default_url = "https://www.google.com"
        
        if name == "open_web_browser":
            subprocess.run(["open", "-a", "Safari"])
            return {"status": "success", "url": default_url}
            
        elif name == "navigate":
            url = args.get("url") or default_url
            script = f'tell application "Safari" to set URL of current tab of window 1 to "{url}"'
            subprocess.run(["osascript", "-e", script])
            return {"status": "success", "url": url}
            
        elif name == "click_at":
            x, y = map_coords(args.get("x"), args.get("y"))
            script = f'tell application "System Events" to click at {{{x}, {y}}}'
            subprocess.run(["osascript", "-e", script])
            return {"status": "success", "url": default_url} # Stub URL as required by API
            
        elif name == "type_text_at":
            x, y = map_coords(args.get("x"), args.get("y"))
            text = args.get("text")
            script_click = f'tell application "System Events" to click at {{{x}, {y}}}'
            subprocess.run(["osascript", "-e", script_click])
            time.sleep(0.5)
            script_type = f'tell application "System Events" to keystroke "{text}"'
            subprocess.run(["osascript", "-e", script_type])
            if args.get("press_enter", True):
                subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke return'])
            return {"status": "success", "url": default_url} # Stub URL
            
        elif name == "wait_5_seconds":
            time.sleep(5)
            return {"status": "success", "url": default_url} # Stub URL
            
        elif name == "key_combination":
            keys = args.get("keys")
            if keys.lower() == "enter":
                subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke return'])
            else:
                logger.warning(f"Key combination {keys} not fully supported in stub.")
                return {"status": "warning", "message": f"Key combination {keys} not fully supported", "url": default_url}
            return {"status": "success", "url": default_url}
            
        logger.warning(f"Action {name} not supported locally yet.")
        return {"status": "unsupported", "message": f"Action {name} not supported locally", "url": default_url}
        
    except Exception as e:
        logger.error(f"Error executing local action: {e}")
        return {"status": "error", "message": str(e), "url": default_url}

async def get_screenshot():
    """Captures a screenshot if running locally on supported OS."""
    if platform.system() in ["Darwin", "Windows"]:
        try:
            logger.info("Capturing local screenshot...")
            img = ImageGrab.grab()
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            return img_byte_arr.getvalue()
        except Exception as e:
            logger.error(f"Failed to capture local screenshot: {e}")
            return None
    else:
        logger.warning("Local screenshot not supported on this OS or remote execution requested.")
        return None

async def execute_computer_task(params: FunctionCallParams, *, send_to_client_fn=None):
    """Handler for the execute_computer_task tool."""
    is_explicit = params.arguments.get('is_explicit_intent')
    if not is_explicit:
        await params.result_callback({"error": "Explicit intent validation required."})
        return

    task = params.arguments.get('task_description')
    logger.info(f"Executing computer task: {task}")
    
    agent = ComputerUseAgent()
    
    async def action_callback(name, args):
        # Decide execution path
        if platform.system() == "Darwin":
            return execute_action_locally(name, args)
        elif send_to_client_fn:
            logger.info(f"Sending action to client: {name}")
            await send_to_client_fn("computer_use_action", {"action": name, "args": args})
            # Computer Use requires returning a URL in the response.
            # We provide the target URL if it was a navigate command, or a default one.
            url = args.get("url") or "https://www.google.com"
            return {"status": "sent_to_client", "message": f"Action {name} sent to client.", "url": url}
        else:
            logger.warning("Remote execution requested but no sender function provided.")
            return {"status": "error", "message": "Remote execution bridge not configured"}
            
    try:
        result = await agent.execute_task(task, get_screenshot, action_callback)
        await params.result_callback({"status": "success", "result": result})
    except Exception as e:
        logger.error(f"Error in execute_computer_task: {e}")
        await params.result_callback({"status": "error", "message": str(e)})

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
