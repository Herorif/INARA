import asyncio
import aiohttp
import sys

# Usage: python3 debug_printer_connection.py <IP>
# Example: python3 debug_printer_connection.py 10.0.0.34

async def probe(ip):
    print(f"--- Probing {ip} ---")
    
    ports = [80, 7125, 4408, 9999]
    paths = ["/", "/printer/info", "/api/version", "/init_print"]
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        for port in ports:
            print(f"\nChecking Port {port}...")
            try:
                # Check root first
                url = f"http://{ip}:{port}/"
                try:
                    async with session.get(url) as resp:
                        print(f"  [ROOT] {url} -> {resp.status}")
                        print(f"  Headers: {resp.headers}")
                        if resp.status == 200:
                            text = await resp.text()
                            if "<title>" in text:
                                title = text.split("<title>")[1].split("</title>")[0]
                                print(f"  Title: {title}")
                            else:
                                print("  No title found in body")
                except Exception as e:
                     print(f"  [ROOT] Failed: {e}")

                # Check endpoints if port seems open (optimization: only if root worked? no, API might be separate)
                for path in paths:
                    if path == "/": continue
                    url = f"http://{ip}:{port}{path}"
                    try:
                        async with session.get(url) as resp:
                            print(f"  [API]  {url} -> {resp.status}")
                    except:
                        pass
                        
            except Exception as e:
                 print(f"  Port Error: {e}")

if __name__ == "__main__":
    target_ip = "10.0.0.34" # Default
    if len(sys.argv) > 1:
        target_ip = sys.argv[1]
    
    asyncio.run(probe(target_ip))
