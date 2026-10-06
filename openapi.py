"""The API's operations and its OpenAPI 3.1 document at ``/api/openapi.json``
(high_level_spec.md, "API").

``OPERATIONS`` is the single source of truth: ``main.create_app`` registers one route per
operation under ``/api`` (plus the operation's legacy alias), and ``build_document`` describes
the same list. The limits and formats are passed in from the service's own constants, so the
document always states the rules the service enforces.
"""

import re
from dataclasses import dataclass

API_PREFIX = "/api"
API_VERSION = "2.0.0"


@dataclass(frozen=True)
class Operation:
    endpoint: str  # Flask endpoint name and OpenAPI operationId
    method: str
    path: str  # Under API_PREFIX, in Flask rule syntax
    summary: str
    description: str
    responses: dict  # status -> (description, content key or None)
    upload: bool = False  # multipart body with `file` and `format`
    legacy_path: str | None = None  # Pre-/api/ address kept as an alias


OPERATIONS = (
    Operation(
        endpoint="upload",
        method="POST",
        path="/upload",
        summary="Upload a resource",
        description="Store one file and get its resource ID and link. "
                    "The file may be at most {max_size}.",
        responses={
            "201": ("Stored", "resource"),
            "400": ("No file, empty filename, or unknown format", "error"),
            "413": ("File larger than {max_size}", "error"),
        },
        upload=True,
        legacy_path="/upload",
    ),
    Operation(
        endpoint="get_resource",
        method="GET",
        path="/resource/<resource_id>",
        summary="View a resource",
        description="Serve the file inline with its stored content type and original filename. "
                    "Responses are sandboxed (Content-Security-Policy: sandbox) and carry an ETag.",
        responses={
            "200": ("The file", "file"),
            "304": ("Not modified since the ETag sent in If-None-Match", None),
            "404": ("Resource not found or expired", "error"),
        },
        legacy_path="/resource/<resource_id>",
    ),
    Operation(
        endpoint="update_resource",
        method="PUT",
        path="/resource/<resource_id>",
        summary="Replace a resource",
        description="Replace the file under the same resource ID and restart its {ttl} lifetime. "
                    "Open to anyone by design. The file may be at most {max_size}.",
        responses={
            "200": ("Replaced", "resource_update"),
            "400": ("No file, empty filename, or unknown format", "error"),
            "404": ("Resource not found or expired", "error"),
            "413": ("File larger than {max_size}", "error"),
        },
        upload=True,
        legacy_path="/resource/<resource_id>",
    ),
    Operation(
        endpoint="list_resources",
        method="GET",
        path="/resources",
        summary="List all resources",
        description="All live resources. Clients that prefer text/html get a web page; "
                    "others get JSON.",
        responses={"200": ("The resource list", "resource_list")},
        legacy_path="/resources",
    ),
    Operation(
        endpoint="health",
        method="GET",
        path="/health",
        summary="Service status",
        description="Whether the service is up and how many resources it holds.",
        responses={"200": ("Service is up", "health")},
        legacy_path="/health",
    ),
    Operation(
        endpoint="openapi",
        method="GET",
        path="/openapi.json",
        summary="This OpenAPI document",
        description="Generated from the service's operation definitions.",
        responses={"200": ("OpenAPI 3.1 document", "openapi")},
    ),
)


def openapi_path(flask_path):
    """`/resource/<resource_id>` -> `/api/resource/{resource_id}`"""
    return API_PREFIX + re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", flask_path)


def _ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def _json(name):
    return {"application/json": {"schema": _ref(name)}}


CONTENT = {
    "resource": _json("Resource"),
    "resource_update": _json("ResourceUpdate"),
    "resource_list": {
        "application/json": {"schema": _ref("ResourceList")},
        "text/html": {"schema": {"type": "string"}},
    },
    "health": _json("Health"),
    "error": _json("Error"),
    "file": {"*/*": {"schema": {"type": "string", "format": "binary"}}},
    "openapi": {"application/json": {"schema": {"type": "object"}}},
}

RESOURCE_ID = {
    "name": "resource_id",
    "in": "path",
    "required": True,
    "description": "The resource ID returned by the upload",
    "schema": {"type": "string"},
}


def _size_label(num_bytes):
    mb = 1024 * 1024
    return f"{num_bytes // mb} MB" if num_bytes % mb == 0 else f"{num_bytes:,} bytes"


def _schemas(max_file_size, ttl_seconds):
    resource = {
        "type": "object",
        "required": ["id", "filename", "content_type", "size", "created_at", "expires_at", "url", "link"],
        "properties": {
            "id": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
            "filename": {"type": "string", "maxLength": 255},
            "content_type": {"type": "string"},
            "size": {"type": "integer", "minimum": 0, "maximum": max_file_size},
            "created_at": {"type": "string", "format": "date-time"},
            "expires_at": {"type": "string", "format": "date-time"},
            "url": {"type": "string", "description": "Path of the resource on this server"},
            "link": {"type": "string", "format": "uri", "description": "Full link, using the host the client called"},
        },
        "additionalProperties": False,
    }
    def with_extra(extra):
        return {
            **resource,
            "required": resource["required"] + list(extra),
            "properties": {**resource["properties"], **extra},
        }

    return {
        "Resource": resource,
        "ResourceUpdate": with_extra({"updated_at": {"type": "string", "format": "date-time"}}),
        "ListedResource": with_extra({
            "ttl_seconds": {"type": "integer", "const": ttl_seconds},
            "time_remaining_seconds": {"type": "integer"},
        }),
        "ResourceList": {
            "type": "object",
            "required": ["resources", "count", "ttl_hours", "max_file_size_bytes"],
            "properties": {
                "resources": {"type": "array", "items": _ref("ListedResource")},
                "count": {"type": "integer", "minimum": 0},
                "ttl_hours": {"type": "integer", "const": ttl_seconds // 3600},
                "max_file_size_bytes": {"type": "integer", "const": max_file_size},
            },
            "additionalProperties": False,
        },
        "Health": {
            "type": "object",
            "required": ["status", "resources_count", "uptime_seconds"],
            "properties": {
                "status": {"type": "string", "enum": ["healthy"]},
                "resources_count": {"type": "integer", "minimum": 0},
                "uptime_seconds": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
        "Error": {
            "type": "object",
            "required": ["error"],
            "properties": {"error": {"type": "string"}},
            "additionalProperties": False,
        },
    }


def _upload_body(max_size, formats):
    return {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": f"The file, at most {max_size}",
                        },
                        "format": {
                            "type": "string",
                            "enum": list(formats),
                            "description": "Optional, case-insensitive. Sets the content type: "
                                           + ", ".join(f"{k} = {v}" for k, v in formats.items())
                                           + ". Without it, the type the client sent is used.",
                        },
                    },
                }
            }
        },
    }


def build_document(server_url, *, max_file_size, ttl_seconds, formats):
    """The OpenAPI 3.1 document for OPERATIONS, served from `server_url`."""
    max_size = _size_label(max_file_size)
    ttl = f"{ttl_seconds // 3600}-hour" if ttl_seconds % 3600 == 0 else f"{ttl_seconds}-second"

    def fill(text):
        return text.format(max_size=max_size, ttl=ttl)

    paths = {}
    for op in OPERATIONS:
        item = {
            "operationId": op.endpoint,
            "summary": op.summary,
            "description": fill(op.description),
            "responses": {
                status: {"description": fill(text), **({"content": CONTENT[kind]} if kind else {})}
                for status, (text, kind) in op.responses.items()
            },
        }
        if "<resource_id>" in op.path:
            item["parameters"] = [RESOURCE_ID]
        if op.upload:
            item["requestBody"] = _upload_body(max_size, formats)
        paths.setdefault(openapi_path(op.path), {})[op.method.lower()] = item

    aliases = sorted({op.legacy_path.replace("<resource_id>", "{id}") for op in OPERATIONS if op.legacy_path})
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Resource Server",
            "version": API_VERSION,
            "description": (
                "Temporary file sharing on a trusted network. Files are kept in memory for "
                f"{ttl_seconds // 3600} hours after upload or last replacement and are lost on restart. "
                f"Each file may be at most {max_size}. There is no authentication, and anyone can "
                "replace any resource. The original addresses without the /api prefix ("
                + ", ".join(aliases) + ") remain as aliases for links and clients made before it."
            ),
            "x-limits": {"max_file_size_bytes": max_file_size, "ttl_seconds": ttl_seconds},
        },
        "servers": [{"url": server_url}],
        "paths": paths,
        "components": {"schemas": _schemas(max_file_size, ttl_seconds)},
    }
