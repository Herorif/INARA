from services.capability_profiles import model_id, provider_key
from services.tls import genai_http_options
import os
from datetime import datetime
from google import genai
from google.genai import types
from typing import Optional
from services.legacy_cad import LegacyScriptRunner
from services.tools import ServiceError


class CadAgent:
    def __init__(self, on_thought=None, on_status=None, client=None, runner=None):
        self.client = client or genai.Client(
            http_options=genai_http_options(api_version="v1beta"), api_key=provider_key()
        )
        # Generated code only ever runs in an owned, hard-deadline child process.
        self.runner = runner or LegacyScriptRunner()
        # Using Gemini 2.5 Pro for thinking/streaming support
        self.model = model_id("legacy_cad")
        self.on_thought = on_thought  # Callback for streaming thoughts 
        self.on_status = on_status  # Callback for retry status info
        
        self.system_instruction = """
You are a Python-based 3D CAD Engineer using the `build123d` library.
Your goal is to write a Python script that generates a 3D model based on the user's request.

Requirements:
1. Start with `from build123d import *`.
2. Include `import numpy as np` if you use any numpy functions (like `np.sign`, `np.pi`).
3. You MUST assign the final object to a variable named `result_part`.
4. If you create a sketch or line, extrude it to make it a solid `Part`.
5. The model should be centered at (0,0,0) and have reasonable dimensions (mm).
6. **IMPORTANT**: Do NOT use old or PascalCase function names for core operations.
   - Use `make_face()` instead of `MakeFace()`.
   - Use `extrude()` instead of `Extrude()`.
   - Use `fillet()` instead of `Fillet()`.
   - Use `chamfer()` instead of `Chamfer()`.
   - Use `revolve()` instead of `Revolve()`.
   - Use `loft()` instead of `Loft()`.
   - Use `sweep()` instead of `Sweep()`.
   - Use `offset()` instead of `Offset()`.
   - generally prefer lowercase builder methods inside contexts.

7. **Vector Access**: Do NOT access vector components like `v.X`, `v.Y`, `v.Z` unless you are sure they exist (use `v.X` etc on Vector objects, but ensure they are Vectors).
8. **Final Output**: The script MUST end by exporting the final part to an STL file named 'output.stl'.
   - `export_stl(result_part, 'output.stl')`

9. **Robustness**: Operations like `fillet()` and `chamfer()` will crash if the radius is too large for the geometry.
   - Use conservative values (e.g., 0.5mm to 2mm) unless you are certain of the dimensions.
   - If a fillet is purely aesthetic, keep it small to ensure success.

Example Script:
```python
from build123d import *

with BuildPart() as p:
    Box(10, 10, 10)
    Fillet(p.edges(), radius=1)

result_part = p.part
export_stl(result_part, 'output.stl')
```
"""

    async def request_code(self, current_prompt: str) -> str:
        """Stream one model answer; thoughts go to on_thought, answer text is returned."""
        raw_content = ""
        stream = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=current_prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(include_thoughts=True)
            )
        )
        async for chunk in stream:
            if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                for part in chunk.candidates[0].content.parts:
                    if not part.text:
                        continue
                    elif part.thought:
                        # Stream thought to callback
                        if self.on_thought:
                            self.on_thought(part.text)
                    else:
                        # Accumulate answer text
                        raw_content += part.text
        return raw_content

    @staticmethod
    def project_work_dir(output_dir: Optional[str]) -> str:
        """Generated code runs only in the project's CAD output folder, never %TEMP%."""
        if not output_dir:
            raise ServiceError(
                "cad_output_required", "Legacy CAD needs the project's CAD output folder."
            )
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    async def generate_prototype(self, prompt: str, output_dir: Optional[str] = None):
        """
        Generates 3D geometry by asking Gemini for a script, then running it in an
        owned child process (hard deadline, whole-tree kill, no API keys).
        Args:
            prompt: User's description of the model to generate.
            output_dir: Project CAD folder for the script and STL (required; also the cwd).
        """
        print(f"[CadAgent DEBUG] [START] Generation started for: '{prompt}'")
        
        try:
            work_dir = self.project_work_dir(output_dir)
            
            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
            script_path = os.path.join(work_dir, "current_design.py")

            max_retries = 3
            current_prompt = f"You are a build123d expert. Write a generic python script to create a 3D model of: {prompt}. Ensure you export to 'output.stl'. Unscaled."
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = await self.request_code(current_prompt)
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Save to Local File in cad_outputs folder
                # Fix for Windows paths in python strings: escape backslashes
                safe_output_path = output_stl.replace("\\", "\\\\")
                
                with open(script_path, "w") as f:
                    # Inject output path into the script
                    code_with_path = code.replace("output.stl", safe_output_path)
                    f.write(code_with_path)
                    
                print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")
                
                # 4. Execute in an owned child (hard deadline, tree kill, no API keys)
                returncode, stderr = await self.runner.run(script_path, work_dir)

                if returncode != 0:
                    error_msg = stderr
                    # Extract a concise error message for display
                    error_lines = error_msg.strip().split('\n')
                    short_error = error_lines[-1][:100] if error_lines else "Unknown error"
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Emit retry status with error
                    if self.on_status:
                        self.on_status({
                            "status": "retrying",
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "error": short_error
                        })
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
Original request: {prompt}
"""
                    continue # Retry loop
                
                print("[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     # If script ran but no output, treat as failure and retry?
                     # Ideally yes.
                     current_prompt = "The script executed successfully but 'output.stl' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success
            print("[CadAgent DEBUG] [ERR] All attempts failed.")
            if self.on_status:
                self.on_status({
                    "status": "failed",
                    "attempt": max_retries,
                    "max_attempts": max_retries,
                    "error": "All generation attempts failed"
                })
            return None

        except ServiceError:
            # Timeouts, mode cancellation and cleanup faults must reach the caller.
            raise
        except Exception as e:
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def iterate_prototype(self, prompt: str, output_dir: Optional[str] = None):
        """
        Iterates on the existing design by reading 'current_design.py' and applying changes.
        Args:
            prompt: User's description of the changes to make.
            output_dir: Project CAD folder holding the script; new STL is saved there (required).
        """
        print(f"[CadAgent DEBUG] [START] Iteration started for: '{prompt}'")
        
        work_dir = self.project_work_dir(output_dir)
        
        # Generate timestamped filename for the output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_path = os.path.join(work_dir, "current_design.py")
        output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
        
        existing_code = ""
        
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                existing_code = f.read()
            
            # Sanitize existing code: replace any absolute paths with 'output.stl'
            # This prevents the LLM from seeing/reproducing Windows paths that cause Unicode escape errors
            import re
            # Match both escaped (\\) and unescaped (\) Windows paths to output.stl
            existing_code = re.sub(
                r"['\"]C:\\\\?Users\\\\?[^'\"]+\\\\?output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
            # Also handle forward-slash variants
            existing_code = re.sub(
                r"['\"]C:/Users/[^'\"]+/output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
        else:
             print("[CadAgent DEBUG] [WARN] No existing script found. Falling back to fresh generation.")
             return await self.generate_prototype(prompt, output_dir=work_dir)

        try:

            max_retries = 3
            current_prompt = f"""
You are iterating on an existing 3D model script.

Current Python Code:
```python
{existing_code}
```

User Request: {prompt}

Task: Rewrite the code to satisfy the user's request while maintaining the rest of the model structure.
Ensure you still export to 'output.stl'.
"""
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Iteration Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = await self.request_code(current_prompt)
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Save to Local File in cad_outputs folder
                # Overwrite the script so the next iteration builds on this one
                
                # Fix for Windows paths in python strings: escape backslashes
                safe_output_path = output_stl.replace("\\", "\\\\")
                
                with open(script_path, "w") as f:
                    # Inject output path into the script
                    code_with_path = code.replace("output.stl", safe_output_path)
                    f.write(code_with_path)
                    
                print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")
                
                # 4. Execute in an owned child (hard deadline, tree kill, no API keys)
                returncode, stderr = await self.runner.run(script_path, work_dir)

                if returncode != 0:
                    error_msg = stderr
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The updated Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
"""
                    continue # Retry loop
                
                print("[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     current_prompt = f"The script executed successfully but '{output_stl}' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success
            print("[CadAgent DEBUG] [ERR] All attempts failed.")
            if self.on_status:
                self.on_status({
                    "status": "failed",
                    "attempt": max_retries,
                    "max_attempts": max_retries,
                    "error": "All iteration attempts failed"
                })
            return None

        except ServiceError:
            # Timeouts, mode cancellation and cleanup faults must reach the caller.
            raise
        except Exception as e:
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            return None

