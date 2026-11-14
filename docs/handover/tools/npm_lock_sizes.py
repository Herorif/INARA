"""Count a package-lock.json's packages and sum their registry tarball sizes (HEAD requests only).

Usage: python -I npm_lock_sizes.py <package-lock.json>
Reads the lockfile as data; never runs or imports anything from it.
"""
import concurrent.futures
import json
import ssl
import sys
import urllib.request

import truststore


def head_size(url, context):
    """Total size from a one-byte ranged GET ("Content-Range: bytes 0-0/<total>")."""
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        total = (response.headers.get("Content-Range") or "").rpartition("/")[2]
        if total.isdigit():
            return int(total)
        return int(response.headers.get("Content-Length") or 0)


def main(path):
    with open(path, encoding="utf-8") as handle:
        lock = json.load(handle)
    packages = {key: value for key, value in lock.get("packages", {}).items() if key}
    optional = {key for key, value in packages.items() if value.get("optional")}
    dev = {key for key, value in packages.items() if value.get("dev")}
    resolved = {key: value["resolved"] for key, value in packages.items() if value.get("resolved")}
    hosts = sorted({url.split("/")[2] for url in resolved.values()})
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    sizes, failures = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(head_size, url, context): key for key, url in resolved.items()}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                sizes[key] = future.result()
            except Exception as exc:  # noqa: BLE001 - report and continue
                failures.append((key, type(exc).__name__))
    windows_optional = [k for k in optional if "win32" in k or "windows" in k]
    other_platform = [k for k in optional if any(p in k for p in ("darwin", "linux", "android", "freebsd", "sunos", "aix", "netbsd", "openbsd"))]
    skip = set(other_platform)
    total = sum(size for key, size in sizes.items())
    likely = sum(size for key, size in sizes.items() if key not in skip)
    biggest = sorted(((size, key) for key, size in sizes.items()), reverse=True)[:8]
    print(f"packages in lockfile: {len(packages)} (dev {len(dev)}, optional {len(optional)})")
    print(f"registry hosts: {', '.join(hosts)}")
    print(f"tarballs sized: {len(sizes)}; failed: {len(failures)} {failures[:5]}")
    print(f"all tarballs: {total / 1e6:.1f} MB; skipping other-OS optional packages: {likely / 1e6:.1f} MB")
    print(f"optional for other OSes (npm skips on Windows): {len(other_platform)}; Windows optional: {len(windows_optional)}")
    print("largest:", "; ".join(f"{key.removeprefix('node_modules/')} {size / 1e6:.1f} MB" for size, key in biggest))
    scripts = [key for key, value in packages.items() if value.get("hasInstallScript")]
    print(f"packages with install scripts: {len(scripts)}: {', '.join(k.removeprefix('node_modules/') for k in scripts)}")


if __name__ == "__main__":
    main(sys.argv[1])
