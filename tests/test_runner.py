#!/usr/bin/env python3
"""
Master Test Runner for INARA.

Usage:
    python tests/test_runner.py              # Run all tests
    python tests/test_runner.py --module=kasa    # Run specific module
    python tests/test_runner.py --quick          # Quick sanity check
"""
import subprocess
import sys
import argparse
from pathlib import Path

# Test modules mapping
MODULES = {
    "kasa": "test_kasa_agent.py",
    "printer": "test_printer_agent.py",
    "cad": "test_cad_agent.py",
    "web": "test_web_agent.py",
    "auth": "test_authenticator.py",
    "tools": "test_inara_tools.py",
}

TESTS_DIR = Path(__file__).parent


def run_tests(modules: list = None, quick: bool = False, verbose: bool = True):
    """Run pytest with specified options."""
    cmd = [sys.executable, "-m", "pytest"]
    
    if modules:
        # Run specific modules
        for mod in modules:
            if mod in MODULES:
                cmd.append(str(TESTS_DIR / MODULES[mod]))
            else:
                print(f"Unknown module: {mod}")
                print(f"Available: {', '.join(MODULES.keys())}")
                return 1
    else:
        # Run all tests
        cmd.append(str(TESTS_DIR))
    
    if verbose:
        cmd.append("-v")
    
    if quick:
        cmd.extend(["-x", "--tb=short"])  # Stop on first failure
    else:
        cmd.append("--tb=short")
    
    # Add color output
    cmd.append("--color=yes")
    
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    
    return subprocess.run(cmd).returncode


def main():
    parser = argparse.ArgumentParser(description="INARA Test Runner")
    parser.add_argument(
        "--module", "-m",
        type=str,
        help=f"Run specific module: {', '.join(MODULES.keys())}"
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick mode: stop on first failure"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available test modules"
    )
    
    args = parser.parse_args()
    
    if args.list:
        print("\nAvailable test modules:")
        for key, filename in MODULES.items():
            print(f"  {key:10} -> {filename}")
        return 0
    
    modules = [args.module] if args.module else None
    return run_tests(modules=modules, quick=args.quick)


if __name__ == "__main__":
    sys.exit(main())
