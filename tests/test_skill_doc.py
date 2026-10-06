"""Checks that SKILL.md stays in step with the service, as agent_skill.md requires."""

import io
import re
import subprocess
from pathlib import Path

import pytest

import main
from main import FORMAT_CONTENT_TYPES, MAX_FILE_SIZE, RESOURCE_TTL, create_app

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text()
INIT_SH = (ROOT / "init.sh").read_text()
SPEC = (ROOT / "high_level_spec.md").read_text()
FRONT_MATTER = SKILL.split("---")[1]


def test_states_file_size_limit():
    assert main.format_size(MAX_FILE_SIZE) in SKILL


def test_states_lifetime():
    assert f"{RESOURCE_TTL // 3600} hours" in SKILL


def test_states_no_other_size_or_lifetime():
    sizes = set(re.findall(r"\b\d+(?:\.\d+)?\s*(?:[KMG]B|bytes?)\b", SKILL))
    assert sizes == {main.format_size(MAX_FILE_SIZE)}
    hours = set(re.findall(r"\b(\d+)(?:[- ]hours?|h\b)", SKILL))
    assert hours == {str(RESOURCE_TTL // 3600)}


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
    # Old addresses still work as aliases, but the skill teaches the /api ones
    assert not re.search(r"(?::3100|\$BASE)/(?!api/)\w", SKILL)


def test_locates_the_server_instead_of_assuming_it():
    resolver = SKILL.index("$RESOURCES_SERVER_URL")
    cached = SKILL.index('$CACHE/base_url"')
    known = SKILL.index("http://raspberry-server.local:3100")
    assert resolver < cached < known < SKILL.index("http://192.168.0.2:3100")
    assert 'CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/resources-server"' in SKILL
    assert "ask the user for the server's address" in SKILL
    assert "localhost" not in SKILL
    assert "cd ~/" not in SKILL


def test_needs_only_sh_and_curl():
    assert re.search(r"bins: \[curl\]", FRONT_MATTER)
    for program in ("python", "jq", "hostname", "node"):
        assert program not in SKILL


def test_parses_responses_with_sh_only():
    response = create_app().test_client().post(
        "/api/upload",
        data={"file": (io.BytesIO(b"<p>hi</p>"), "a.html"), "format": "html"},
        base_url="http://raspberry-server.local:3100",
    )
    body = response.get_json()
    for field in ("id", "link"):
        command = re.search(rf"^{field.upper()}=\$\((.*)\)$", SKILL, re.MULTILINE).group(1)
        result = subprocess.run(
            ["sh", "-c", command], env={"BODY": response.get_data(as_text=True), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == body[field]
    assert body["link"].startswith("http://raspberry-server.local:3100/")


def test_does_not_repeat_the_openapi_document():
    for field in ('"created_at"', '"expires_at"', '"resources_count"', '"uptime_seconds"', '{"error"'):
        assert field not in SKILL


def test_spec_links_agent_skill():
    assert "[agent_skill.md](agent_skill.md)" in SPEC
    assert (ROOT / "agent_skill.md").exists()


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
