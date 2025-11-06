#!/usr/bin/env python3
"""Check if all required dependencies for probability model tests are installed."""
import sys

missing = []
installed = []

dependencies = {
    "psycopg": "psycopg[binary]",
    "fastapi": "fastapi",
    "redis": "redis",
    "prometheus_client": "prometheus-client",
    "httpx": "httpx",
}

print("Checking dependencies for probability model tests...\n")

for module_name, package_name in dependencies.items():
    try:
        __import__(module_name)
        print(f"✓ {package_name} installed")
        installed.append(package_name)
    except ImportError:
        print(f"✗ {package_name} NOT installed")
        missing.append(package_name)

print("\n" + "="*50)
if missing:
    print(f"Missing dependencies: {', '.join(missing)}")
    print("\nTo install missing dependencies, run:")
    print(f"  pip install {' '.join(missing)}")
else:
    print("All dependencies are installed!")

# Try importing the function
print("\n" + "="*50)
print("Testing import of calculate_win_probability...")
try:
    sys.path.insert(0, '.')
    from services.gateway.main import calculate_win_probability  # noqa: F401
    print("✓ calculate_win_probability imported successfully")
    print("✓ Probability model tests should be able to run")
except ImportError as e:
    print("✗ Failed to import calculate_win_probability")
    print(f"  Error: {e}")
    print("\nThis is why the probability model tests are being skipped.")
    print("Install the missing dependencies to run the tests.")

