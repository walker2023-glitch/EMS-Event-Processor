"""Export the frontend contract without loading local credentials."""

import json
from pathlib import Path

from ems_backend.app import create_app
from ems_backend.config import Settings


def main():
    destination = Path(__file__).resolve().parents[1] / "docs/backend/openapi.json"
    destination.write_text(json.dumps(create_app(Settings()).openapi(), indent=2) + "\n")
    print("Exported docs/backend/openapi.json without loading credentials.")


if __name__ == "__main__":
    main()
