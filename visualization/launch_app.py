import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch IKI Panel dashboards")
    parser.add_argument(
        "app",
        choices=["viewer", "sensitivity"],
        help="Which app to launch",
    )
    parser.add_argument(
        "--autoreload",
        action="store_true",
        help="Enable Panel autoreload while editing",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if args.app == "viewer":
        app_path = root / "visualization" / "risk_viewer_app.py"
    else:
        app_path = root / "sensitivity_analysis" / "app.py"

    command = [sys.executable, "-m", "panel", "serve", str(app_path), "--show"]
    if args.autoreload:
        command.append("--autoreload")

    return subprocess.call(command, cwd=str(root))


if __name__ == "__main__":
    raise SystemExit(main())
