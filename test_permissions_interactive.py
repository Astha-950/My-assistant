"""
Interactive CLI tester for HP Assistant Permission Gateway (core/permissions.py).
Allows manual verification of safe, confirm, blocked, and unknown actions.
"""

import sys
import time
from core.permissions import permissions


def test_safe() -> None:
    print("\n--- 1. Testing SAFE Action: 'volume' ---")
    print("Expected: Runs immediately with NO popup.")
    start = time.time()
    result = permissions.request("volume", details="Increase master volume to 50%")
    elapsed = time.time() - start
    print(f"Result: {result} (Execution time: {elapsed:.3f}s)")
    if result:
        print("[PASS] Safe action allowed instantly without popup.")
    else:
        print("[FAIL] Safe action was not allowed.")


def test_confirm() -> None:
    print("\n--- 2. Testing CONFIRM Action: 'shutdown' ---")
    print("Expected: Small always-on-top popup with Allow / Deny buttons and 10s countdown.")
    print("Try one of these tests:")
    print("  a) Click 'Allow' -> returns True")
    print("  b) Click 'Deny'  -> returns False")
    print("  c) Do nothing for 10 seconds -> auto-denies and returns False")
    print("Showing popup now...")
    start = time.time()
    result = permissions.request("shutdown", details="Full computer shutdown requested")
    elapsed = time.time() - start
    print(f"Result: {result} (Response time: {elapsed:.2f}s)")
    if result:
        print("[OUTCOME] You clicked ALLOW.")
    elif elapsed >= 9.5:
        print("[OUTCOME] Timed out after 10 seconds -> AUTO-DENIED.")
    else:
        print("[OUTCOME] You clicked DENY (or closed window).")


def test_blocked() -> None:
    print("\n--- 3. Testing BLOCKED Action: 'format_drive' ---")
    print("Expected: Denied instantly with NO popup.")
    start = time.time()
    result = permissions.request("format_drive", details="Disk C: quick format")
    elapsed = time.time() - start
    print(f"Result: {result} (Execution time: {elapsed:.3f}s)")
    if not result:
        print("[PASS] Blocked action denied instantly without popup.")
    else:
        print("[FAIL] Blocked action was allowed!")


def test_unknown() -> None:
    print("\n--- 4. Testing UNKNOWN Action: 'launch_rocket' ---")
    print("Expected: Small always-on-top popup appears (verifies unknown actions default to confirm, never safe).")
    print("Showing popup now...")
    start = time.time()
    result = permissions.request("launch_rocket", details="Target: Mars trajectory")
    elapsed = time.time() - start
    print(f"Result: {result} (Response time: {elapsed:.2f}s)")
    print("[PASS] Unknown action correctly defaulted to CONFIRM tier.")


def main() -> None:
    print("==================================================")
    print("   HP Assistant - Permission System Live Tester   ")
    print("==================================================")
    print("1. Test Safe Action      ('volume' -> no popup)")
    print("2. Test Confirm Action   ('shutdown' -> popup with Allow/Deny/10s timeout)")
    print("3. Test Blocked Action   ('format_drive' -> denied instantly)")
    print("4. Test Unknown Action   ('launch_rocket' -> defaults to confirm popup)")
    print("5. Run all tests in sequence")
    print("q. Quit")
    print("==================================================")

    choice = input("Select an option (1-5, q): ").strip().lower()

    if choice == "1":
        test_safe()
    elif choice == "2":
        test_confirm()
    elif choice == "3":
        test_blocked()
    elif choice == "4":
        test_unknown()
    elif choice == "5":
        test_safe()
        test_blocked()
        test_unknown()
        test_confirm()
    elif choice == "q":
        sys.exit(0)
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    main()
