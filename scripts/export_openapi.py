"""Экспорт OpenAPI-схемы API в openapi.json — для пакета сдачи (DATA-API).

Запуск из корня zabota:  .venv/Scripts/python.exe scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.main import app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = len(schema.get("paths", {}))
    print(f"openapi.json записан: {OUT} ({paths} путей)")


if __name__ == "__main__":
    main()
