#!/usr/bin/env python3
"""Install dependencies and run probability model tests."""
import subprocess
import sys

def run_command(cmd, description):
    """Run a command and print results."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"Error: {e}")
        return False

# Check current dependencies
print("Checking current dependencies...")
run_command("python3 check_dependencies.py", "Current dependency status")

# Install dependencies
print("\n\nInstalling dependencies...")
packages = [
    "psycopg[binary]",
    "fastapi",
    "redis",
    "prometheus-client",
    "httpx",
]

for package in packages:
    success = run_command(f"pip3 install {package} --quiet", f"Installing {package}")
    if success:
        print(f"✓ {package} installed")
    else:
        print(f"✗ {package} installation failed")

# Check dependencies again
print("\n\nRechecking dependencies...")
run_command("python3 check_dependencies.py", "Updated dependency status")

# Try to run tests
print("\n\nRunning probability model tests...")
run_command(
    "python3 -m pytest tests/services/gateway/test_probability_model.py -v --tb=short",
    "Test results"
)

