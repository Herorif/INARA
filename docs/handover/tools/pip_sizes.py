r"""Sum the download sizes of a pip dry-run report, from PyPI's JSON metadata only.

Make the report first (nothing is installed):
  <venv>\Scripts\python -m pip install --use-feature=truststore --dry-run
      --ignore-installed --quiet --report report.json <packages>
Then: python -I pip_sizes.py report.json
"""
import json
import ssl
import sys
import urllib.request

import truststore


def main(path):
    with open(path, encoding="utf-8") as handle:
        items = json.load(handle).get("install", [])
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    total, rows, unknown = 0, [], []
    for item in items:
        name, version = item["metadata"]["name"], item["metadata"]["version"]
        url = item.get("download_info", {}).get("url", "")
        filename = url.rsplit("/", 1)[-1].split("#")[0]
        size = None
        try:
            api = f"https://pypi.org/pypi/{name}/{version}/json"
            with urllib.request.urlopen(api, timeout=30, context=context) as response:
                for entry in json.load(response).get("urls", []):
                    if entry.get("filename") == filename:
                        size = int(entry["size"])
        except Exception as exc:  # noqa: BLE001 - report and continue
            unknown.append((name, type(exc).__name__))
        if size is None:
            unknown.append((name, "size not listed"))
            continue
        total += size
        rows.append((size, f"{name} {version}", url.split("/")[2] if "//" in url else "?"))
    rows.sort(reverse=True)
    print(f"packages: {len(items)}; sized: {len(rows)}; unknown: {unknown}")
    print(f"total: {total / 1e6:.1f} MB; hosts: {sorted({row[2] for row in rows})}")
    for size, label, _ in rows[:10]:
        print(f"  {size / 1e6:8.1f} MB  {label}")


if __name__ == "__main__":
    main(sys.argv[1])
