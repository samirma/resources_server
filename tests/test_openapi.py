"""The OpenAPI document at /api/openapi.json, as high_level_spec.md ("API") requires."""

import io
import re

import jsonschema
import pytest
from openapi_spec_validator import validate

from main import FORMAT_CONTENT_TYPES, MAX_FILE_SIZE, RESOURCE_TTL, create_app
from openapi import API_PREFIX, OPERATIONS

HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def doc(client):
    res = client.get("/api/openapi.json", base_url="http://pi.local:3100")
    assert res.status_code == 200
    assert res.mimetype == "application/json"
    return res.get_json()


def operations(doc):
    return {(path, method): op for path, item in doc["paths"].items()
            for method, op in item.items() if method in HTTP_METHODS}


def conforms(doc, instance, name):
    """Validate a response body against one of the document's component schemas."""
    schema = {"$ref": f"#/components/schemas/{name}", "components": doc["components"]}
    jsonschema.validate(instance, schema, cls=jsonschema.Draft202012Validator)


def test_is_valid_openapi_3_1(doc):
    assert doc["openapi"] == "3.1.0"
    validate(doc)


def test_describes_exactly_the_api_routes(doc):
    rules = {
        (re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule), method.lower())
        for rule in create_app().url_map.iter_rules() if rule.rule.startswith(API_PREFIX + "/")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    assert set(operations(doc)) == rules


def test_one_documented_operation_per_definition(doc):
    assert sorted(op["operationId"] for op in operations(doc).values()) == sorted(op.endpoint for op in OPERATIONS)


def test_every_operation_has_summary_and_success(doc):
    for op in operations(doc).values():
        assert op["summary"] and op["description"]
        assert any(status.startswith("2") for status in op["responses"])


def test_uploads_document_their_errors(doc):
    ops = operations(doc)
    assert {"201", "400", "413"} <= set(ops[("/api/upload", "post")]["responses"])
    assert {"200", "400", "404", "413"} <= set(ops[("/api/resource/{resource_id}", "put")]["responses"])
    assert {"200", "304", "404"} <= set(ops[("/api/resource/{resource_id}", "get")]["responses"])


def test_format_choices_match_the_service(doc):
    for key in [("/api/upload", "post"), ("/api/resource/{resource_id}", "put")]:
        schema = operations(doc)[key]["requestBody"]["content"]["multipart/form-data"]["schema"]
        assert schema["required"] == ["file"]
        assert schema["properties"]["format"]["enum"] == list(FORMAT_CONTENT_TYPES)


def test_states_current_limits(doc):
    assert doc["info"]["x-limits"] == {"max_file_size_bytes": MAX_FILE_SIZE, "ttl_seconds": RESOURCE_TTL}
    assert "10 MB" in operations(doc)[("/api/upload", "post")]["description"]
    assert "24 hours" in doc["info"]["description"]


def test_names_the_legacy_aliases(doc):
    for alias in ("/upload", "/resource/{id}", "/resources", "/health"):
        assert alias in doc["info"]["description"]


def test_server_url_follows_the_request_host(doc):
    assert doc["servers"] == [{"url": "http://pi.local:3100"}]


def test_schemas_match_real_responses(client, doc):
    form = {"file": (io.BytesIO(b"hello"), "hello.txt"), "format": "text"}
    uploaded = client.post("/api/upload", data=form, content_type="multipart/form-data").get_json()
    conforms(doc, uploaded, "Resource")

    form = {"file": (io.BytesIO(b"bye"), "bye.txt")}
    replaced = client.put(f"/api/resource/{uploaded['id']}", data=form, content_type="multipart/form-data").get_json()
    conforms(doc, replaced, "ResourceUpdate")

    conforms(doc, client.get("/api/resources").get_json(), "ResourceList")
    conforms(doc, client.get("/api/health").get_json(), "Health")
    conforms(doc, client.get("/api/resource/doesnotx").get_json(), "Error")


def test_schemas_reject_unknown_fields(doc):
    with pytest.raises(jsonschema.ValidationError):
        conforms(doc, {"status": "healthy", "resources_count": 0, "uptime_seconds": 0, "extra": 1}, "Health")
