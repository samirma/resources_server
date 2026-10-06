"""Checks that SKILL.md stays in step with the service, as high_level_spec.md requires."""

import re
from pathlib import Path

import pytest

import main
from main import FORMAT_CONTENT_TYPES, MAX_FILE_SIZE, RESOURCE_TTL, create_app

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text()
INIT_SH = (ROOT / "init.sh").read_text()


def test_states_file_size_limit():
    assert main.format_size(MAX_FILE_SIZE) in SKILL


def test_states_lifetime():
    assert f"{RESOURCE_TTL // 3600} hours" in SKILL


def test_states_temporary_storage_and_open_access():
    assert "lost when the server restarts" in SKILL
    assert "anyone can overwrite any resource" in SKILL


@pytest.mark.parametrize("fmt", FORMAT_CONTENT_TYPES)
def test_documents_every_format(fmt):
    assert f"`{fmt}`" in SKILL


def test_documents_every_supported_action():
    assert "-X POST" in SKILL and "/api/upload" in SKILL
    assert "-X PUT" in SKILL and "/api/resource/{id}" in SKILL
    assert "/api/resources" in SKILL
    assert "/api/health" in SKILL


def test_points_to_the_openapi_document():
    assert "/api/openapi.json" in SKILL


def test_uses_api_addresses_only():
    # Old addresses still work as aliases, but the guide teaches the /api ones
    assert not re.search(r":(?:3100|\$PORT)/(?!api/)\w", SKILL)


def test_documented_routes_exist():
    rules = {(rule.rule, method) for rule in create_app().url_map.iter_rules() for method in rule.methods}
    assert ("/api/upload", "POST") in rules
    assert ("/api/resource/<resource_id>", "PUT") in rules
    assert ("/api/resource/<resource_id>", "GET") in rules
    assert ("/api/resources", "GET") in rules
    assert ("/api/health", "GET") in rules
    assert ("/api/openapi.json", "GET") in rules
    assert ("/", "GET") in rules


def test_offers_no_unsupported_actions():
    assert "DELETE" not in SKILL
    assert not re.search(r"^#+ .*delete", SKILL, re.IGNORECASE | re.MULTILINE)
    rules = {method for rule in create_app().url_map.iter_rules() for method in rule.methods}
    assert "DELETE" not in rules


def test_documented_management_commands_exist():
    documented = set(re.findall(r"\./init\.sh (\w+)", SKILL))
    usage = re.search(r"\{([\w|]+)\}", INIT_SH).group(1).split("|")
    assert documented
    assert documented <= set(usage)
    assert set(usage) <= documented


def test_documents_error_statuses():
    for status in ("400", "404", "413"):
        assert f"`{status}`" in SKILL
