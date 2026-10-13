import asyncio
import os
import sys

# Add current directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from cad_agent import CadAgent

async def main():
    agent = CadAgent()
    prompt = "A simple 10x10x10 cube with a 5mm hole in the center."
    
    print(f"Testing CadAgent with prompt: '{prompt}'")
    data = await agent.generate_prototype(prompt)
    
    if data and data.get('format') == 'stl' and data.get('data'):
        print("\n✅ Verification Successful!")
        print(f"Format: {data['format']}")
        print(f"Data Length: {len(data['data'])} bytes")
    else:
        print("\n❌ Verification Failed!")
        if data:
            print(f"Received data: {data.keys()}")

if __name__ == "__main__":
    asyncio.run(main())
