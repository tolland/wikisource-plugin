# src-py/scripts/export_openapi.py
import json
from pathlib import Path

from wtbot.main import app  # adjust this import


def main() -> None:
    schema = app.openapi()
    output = Path("src-py/wtbot/api/openapi.json")
    output.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
