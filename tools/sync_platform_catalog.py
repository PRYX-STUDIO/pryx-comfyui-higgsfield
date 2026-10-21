"""CLI entry point for the public, credential-free catalog synchronizer."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pryx_comfyui_higgsfield.catalog.discovery import main


if __name__ == "__main__":
    main()
