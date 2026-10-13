
try:
    with open("trace.txt", "r", encoding="utf-16le") as f:
        print(f.read())
except Exception:
    try:
        with open("trace.txt", "r", encoding="utf-8") as f:
            print(f.read())
    except Exception as e:
        print(e)
