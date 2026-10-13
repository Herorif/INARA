
try:
    lines = []
    with open("trace.txt", "r", encoding="utf-16le") as f:
        lines = f.readlines()
except:
    try:
        with open("trace.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(e)
        exit()

for i, line in enumerate(lines):
    if "AttributeError" in line:
        start = max(0, i - 10)
        end = min(len(lines), i + 10)
        print(f"--- Match at line {i+1} ---")
        print("".join(lines[start:end]))
