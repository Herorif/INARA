
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Add current directory to path to import cad_agent
sys.path.append(os.getcwd())

# Mock dependencies that might be missing or require API keys
mock_genai = MagicMock()
mock_types = MagicMock()
mock_client_cls = MagicMock()

# Configure the mock client instance
mock_client_instance = MagicMock()
mock_client_instance.aio.models.generate_content = AsyncMock()

# When Client(...) is called, return our mock instance
mock_client_cls.return_value = mock_client_instance

# Setup sys.modules patching
modules_to_patch = {
    'google': MagicMock(),
    'google.genai': mock_genai,
    'google.genai.types': mock_types,
}

# Patch modules context
with patch.dict('sys.modules', modules_to_patch):
    # Setup the class mock
    mock_genai.Client = mock_client_cls
    
    # Try importing internal modules
    # If pydantic is missing, mock it too (optional)
    try:
        from cad_agent import CadAgent
    except ImportError:
        print("Could not import cad_agent directly. Trying to mock pydantic/dotenv if needed.")
        modules_to_patch['pydantic'] = MagicMock()
        modules_to_patch['dotenv'] = MagicMock()
        with patch.dict('sys.modules', modules_to_patch):
            from cad_agent import CadAgent

async def verify():
    print("Verifying CAD Iteration Logic...")
    
    # 1. Setup Dummy Agent
    agent = CadAgent()
    # Force client mock (in case it wasn't set by __init__ due to patch timing, though it should be)
    agent.client = mock_client_instance
    agent.model = "gemini-test" # Dummy model name
    
    # Define the "NEW" code that the LLM would return
    # We use a simple cylinder script
    new_code = """
from build123d import *
import numpy as np

# Ensure we overwrite the result
with BuildPart() as p:
    Cylinder(radius=5, height=20)

result_part = p.part
export_stl(result_part, 'output.stl')
"""
    # Mock response
    mock_response = MagicMock()
    mock_response.text = f"```python\n{new_code}\n```"
    agent.client.aio.models.generate_content.return_value = mock_response
    
    # 2. Create Initial Script (Old version)
    initial_code = """
from build123d import *
import numpy as np

with BuildPart() as p:
    Box(10, 10, 10)

result_part = p.part
export_stl(result_part, 'output.stl')
"""
    with open("temp_cad_gen.py", "w") as f:
        f.write(initial_code)
        
    print("[1] Initial script written (Box).")
    
    # 3. Clean previous output
    if os.path.exists("output.stl"):
        os.remove("output.stl")

    # 4. Run Iteration
    print("[2] Running iterate_prototype('make it a cylinder')...")
    # This will:
    # 1. Read temp_cad_gen.py
    # 2. Call agent.client.aio.models.generate_content (which returns our new_code)
    # 3. Extract code and overwrite temp_cad_gen.py
    # 4. Execute temp_cad_gen.py using subprocess (REAL execution in ada_cad_env)
    # 5. Return STL
    
    result = await agent.iterate_prototype("make it a cylinder")
    
    # 5. Verify Results
    print(f"[3] Result Keys: {result.keys() if result else 'None'}")
    
    if result and result.get('format') == 'stl':
        print("[PASS] Result returned with STL data.")
    else:
        print("[FAIL] No result returned.")
        return

    # Check file content
    with open("temp_cad_gen.py", "r") as f:
        content = f.read()
        if "Cylinder" in content:
            print("[PASS] temp_cad_gen.py updated to Cylinder.")
        else:
            print("[FAIL] temp_cad_gen.py NOT updated.")
            print(f"Content Preview: {content[:100]}...")

    # Check Output
    if os.path.exists("output.stl"):
        print("[PASS] output.stl generated.")
        file_size = os.path.getsize("output.stl")
        print(f"      Size: {file_size} bytes")
    else:
        print("[FAIL] output.stl missing.")

if __name__ == "__main__":
    # Ensure backend directory is current working directory for imports
    if os.path.basename(os.getcwd()) != "backend":
        if os.path.exists("backend"):
            os.chdir("backend")
            print(f"Changed working directory to {os.getcwd()}")
        else:
            print("Warning: Could not find backend directory.")

    try:
        asyncio.run(verify())
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
