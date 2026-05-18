"""Seed the mock state with sample fills / inventory so the dashboard
shows non-zero values immediately on a fresh start. Useful for screenshots
and recordings.

Run:
    python scripts/seed_mock_data.py [--orchestrator http://localhost:8000]
"""
import argparse
import json
import sys
import time
import urllib.request


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--orchestrator", default="http://localhost:8000")
    args = p.parse_args()

    # Drive the canonical demo flow 3 times to populate state
    for i in range(3):
        req = urllib.request.Request(
            f"{args.orchestrator}/demo/run",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                print(f"[{i + 1}/3] demo run: {len(data['steps'])} steps, "
                      f"cumulative fees ${data['cumulative_builder_fees_usdc']:.4f}")
        except Exception as e:
            print(f"FAIL on iteration {i + 1}: {e}", file=sys.stderr)
            sys.exit(1)
        time.sleep(0.5)

    print("\nSeed complete. Open the dashboard at the orchestrator URL.")


if __name__ == "__main__":
    main()
