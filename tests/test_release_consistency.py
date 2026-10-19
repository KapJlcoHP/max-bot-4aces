"""Machine-check the local handoff package without network or optional parsers."""

import json
import re
from pathlib import Path

from core.db.seed import load_catalog, load_scenarios
from server.main import app


ROOT = Path(__file__).resolve().parents[1]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _data_api_checks() -> list[tuple[str, str, str]]:
    """Read the small method/path subset needed from DATA-API.yaml.

    A YAML dependency is intentionally not required by the offline test suite;
    these fields are scalar and ordered in the handoff format.
    """
    checks: list[tuple[str, str, str]] = []
    current_id = None
    current_method = None
    for line in (ROOT / "DATA-API.yaml").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*- id:\s*(\S+)\s*$", line)
        if match:
            current_id = match.group(1)
            current_method = None
            continue
        match = re.match(r"^\s*method:\s*(\S+)\s*$", line)
        if match and current_id:
            current_method = _unquote(match.group(1))
            continue
        match = re.match(r"^\s*path:\s*(.+?)\s*$", line)
        if match and current_id and current_method:
            checks.append((current_id, current_method, _unquote(match.group(1))))
            current_id = None
            current_method = None
    return checks


def _openapi_matches(template: str, concrete: str) -> bool:
    template_parts = template.strip("/").split("/")
    concrete_parts = concrete.strip("/").split("/")
    return len(template_parts) == len(concrete_parts) and all(
        left == right or (left.startswith("{") and left.endswith("}"))
        for left, right in zip(template_parts, concrete_parts)
    )


def test_exported_openapi_is_current_and_covers_data_api_checks():
    exported = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    actual = app.openapi()
    assert exported == actual

    for check_id, method, path in _data_api_checks():
        concrete = f"/api/v1{path}"
        assert any(
            method.lower() in operations and _openapi_matches(template, concrete)
            for template, operations in actual["paths"].items()
        ), f"{check_id}: {method} {path} отсутствует в OpenAPI"


def test_data_api_and_test_data_have_the_same_order_and_identity():
    checks = _data_api_checks()
    test_data = json.loads((ROOT / "TEST-DATA.json").read_text(encoding="utf-8"))
    assert [f"{method} {path}" for _, method, path in checks] == test_data["scenario_order"]

    data_api = (ROOT / "DATA-API.yaml").read_text(encoding="utf-8")
    assert re.search(r'^base_url:\s*"([^"]+)"\s*$', data_api, re.MULTILINE).group(1) == test_data["base_url"]
    assert re.search(r'^solution:\s*"([^"]+)"\s*$', data_api, re.MULTILINE).group(1) == test_data["solution"]
    assert re.search(r'^team:\s*"([^"]+)"\s*$', data_api, re.MULTILINE).group(1) == test_data["team"]


def test_documented_template_and_demo_counts_match_content_and_handlers():
    catalog = load_catalog()
    scenarios = load_scenarios()
    assert len(catalog) == 8
    assert sum(len(scenarios[item["key"]]["steps"]) for item in catalog) == 32
    assert set(item["key"] for item in catalog) == set(scenarios) - {"family"}

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    data_api = (ROOT / "DATA-API.yaml").read_text(encoding="utf-8")
    test_data = (ROOT / "TEST-DATA.json").read_text(encoding="utf-8")
    actions = (ROOT / "bot/handlers/actions.py").read_text(encoding="utf-8")
    assert "8 доступных шаблонов" in readme and "32 базовых шага" in readme
    assert "8 доступных шаблонов, 32 базовых шага" in data_api
    assert "Доступны 8 шаблонов (32 базовых шага)" in test_data
    assert '/demo' in readme and '@router.message_created(Command("demo"))' in actions


def test_readme_app_bot_commands_match_compose_services():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "docker compose --profile bot up -d --build" in readme
    assert "services:" in compose and "  app:" in compose and "  bot:" in compose
    assert 'profiles: ["bot"]' in compose
    assert "command: python run_bot.py" in compose
    assert "run_bot.py" in readme
