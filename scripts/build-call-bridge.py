"""Build the optional local helper with the existing compiler; install nothing."""

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build():
    framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
    compiler = framework / "csc.exe"
    if not compiler.is_file():
        raise RuntimeError("The existing .NET Framework compiler is required; nothing is downloaded.")
    output = ROOT / ".runtime/call-bridge/bin/CallControl.exe"
    output.parent.mkdir(parents=True, exist_ok=True)
    references = [framework / name for name in ("System.Web.Extensions.dll", "WPF/UIAutomationClient.dll", "WPF/UIAutomationTypes.dll", "WPF/WindowsBase.dll")]
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                    f"/out:{output}", *[f"/reference:{path}" for path in references],
                    str(ROOT / "native/call-bridge/CallControl.cs")], check=True)
    print("Built .runtime/call-bridge/bin/CallControl.exe. No application or audio was activated.")


if __name__ == "__main__":
    build()
