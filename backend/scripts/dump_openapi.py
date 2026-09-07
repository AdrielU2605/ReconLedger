"""Writes the FastAPI app's OpenAPI schema to disk without booting a server.

Used to regenerate the frontend's TypeScript types (openapi-typescript) and
to detect drift in CI (PRD 10.1: "A contract check regenerates the
TypeScript client from the OpenAPI schema and fails when the committed
client has drifted"). Importing app.main only builds the route table and
introspects it - the lifespan (DB engine, worker loop) never runs unless
the app is actually served, so this is safe to run standalone.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
