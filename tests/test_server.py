"""Tests for the Resource Server, organized by the sections of high_level_spec.md."""

import io
import threading
import time

import pytest

import main
from main import MAX_FILE_SIZE, RESOURCE_TTL, ResourceStore, create_app


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return ResourceStore(clock=clock)


@pytest.fixture
def client(store):
    app = create_app(store)
    app.config["TESTING"] = True
    return app.test_client()


def upload(client, data=b"hello", filename="hello.txt", fmt=None, content_type=None):
    form = {"file": (io.BytesIO(data), filename, content_type) if content_type else (io.BytesIO(data), filename)}
    if fmt is not None:
        form["format"] = fmt
    return client.post("/upload", data=form, content_type="multipart/form-data")


def replace(client, resource_id, data=b"updated", filename="updated.txt", fmt=None):
    form = {"file": (io.BytesIO(data), filename)}
    if fmt is not None:
        form["format"] = fmt
    return client.put(f"/resource/{resource_id}", data=form, content_type="multipart/form-data")


def list_json(client):
    return client.get("/resources", headers={"Accept": "application/json"}).get_json()


def list_html(client):
    return client.get("/resources", headers={"Accept": "text/html,application/xhtml+xml"}).get_data(as_text=True)


# --- 1. Upload a resource ---------------------------------------------------

class TestUpload:
    def test_returns_id_details_and_link(self, client):
        res = upload(client, b"hello", "hello.txt", fmt="text")
        assert res.status_code == 201
        body = res.get_json()
        assert len(body["id"]) == 8
        assert body["filename"] == "hello.txt"
        assert body["content_type"] == "text/plain"
        assert body["size"] == 5
        assert body["created_at"].endswith("+00:00")
        assert body["expires_at"].endswith("+00:00")
        assert body["url"] == f"/resource/{body['id']}"
        assert body["link"] == f"http://localhost/resource/{body['id']}"

    @pytest.mark.parametrize("fmt,expected", [
        ("html", "text/html"),
        ("json", "application/json"),
        ("text", "text/plain"),
        ("pdf", "application/pdf"),
        ("HTML", "text/html"),
    ])
    def test_format_hint_sets_content_type(self, client, fmt, expected):
        body = upload(client, fmt=fmt).get_json()
        assert body["content_type"] == expected

    def test_format_hint_overrides_client_type(self, client):
        body = upload(client, filename="page.txt", content_type="text/plain", fmt="html").get_json()
        assert body["content_type"] == "text/html"

    def test_client_type_kept_without_hint(self, client):
        body = upload(client, filename="pic.png", content_type="image/png").get_json()
        assert body["content_type"] == "image/png"

    def test_generic_type_without_hint(self, client):
        body = upload(client, filename="blob.bin", content_type="application/octet-stream").get_json()
        assert body["content_type"] == "application/octet-stream"

    def test_unknown_format_rejected(self, client, store):
        res = upload(client, fmt="png")
        assert res.status_code == 400
        assert "Unknown format" in res.get_json()["error"]
        assert store.count() == 0

    def test_missing_file_rejected(self, client):
        res = client.post("/upload", data={"format": "text"}, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json()["error"] == "No file provided"

    def test_empty_filename_rejected(self, client):
        res = upload(client, filename="")
        assert res.status_code == 400
        assert res.get_json()["error"] == "Empty filename"

    def test_ids_are_unique(self, client):
        ids = {upload(client).get_json()["id"] for _ in range(50)}
        assert len(ids) == 50

    def test_id_collision_is_avoided(self, client, monkeypatch):
        first = upload(client).get_json()["id"]
        tokens = iter([first, "abcdef12"])
        real_token_hex = main.secrets.token_hex
        monkeypatch.setattr(main.secrets, "token_hex", lambda n: next(tokens) if n == 4 else real_token_hex(n))
        second = upload(client).get_json()["id"]
        assert second == "abcdef12"
        assert client.get(f"/resource/{first}").data == b"hello"


# --- 2. View a resource -----------------------------------------------------

class TestView:
    def test_returns_content_and_type(self, client):
        rid = upload(client, b"<h1>Hi</h1>", "page.html", fmt="html").get_json()["id"]
        res = client.get(f"/resource/{rid}")
        assert res.status_code == 200
        assert res.data == b"<h1>Hi</h1>"
        assert res.mimetype == "text/html"
        assert res.headers["X-Resource-ID"] == rid
        assert "X-Created-At" in res.headers
        assert "X-Expires-At" in res.headers

    def test_binary_content_round_trips(self, client):
        data = bytes(range(256)) * 10
        rid = upload(client, data, "blob.bin").get_json()["id"]
        assert client.get(f"/resource/{rid}").data == data

    def test_offers_original_filename_inline(self, client):
        rid = upload(client, filename="report.pdf", fmt="pdf").get_json()["id"]
        disposition = client.get(f"/resource/{rid}").headers["Content-Disposition"]
        assert disposition.startswith("inline")
        assert "report.pdf" in disposition

    @pytest.mark.parametrize("filename,expected", [
        ('quo"te;x.txt', 'filename="quo\\"te;x.txt"'),
        ("naïve résumé.txt", "filename*=UTF-8''na%C3%AFve%20r%C3%A9sum%C3%A9.txt"),
    ])
    def test_unusual_filenames_are_safely_encoded(self, client, store, filename, expected):
        # Stored directly: the test client cannot send a quote in a multipart filename
        rid = store.add(b"x", filename, "text/plain")["id"]
        res = client.get(f"/resource/{rid}")
        assert res.status_code == 200
        assert expected in res.headers["Content-Disposition"]

    @pytest.mark.parametrize("sent,stored", [
        ("dir/sub/file.txt", "file.txt"),
        ("tab\there.txt", "tabhere.txt"),
        ("  padded.txt  ", "padded.txt"),
    ])
    def test_filenames_are_cleaned_on_upload(self, client, sent, stored):
        body = upload(client, filename=sent).get_json()
        assert body["filename"] == stored
        assert client.get(f"/resource/{body['id']}").status_code == 200

    def test_filename_with_only_control_characters_rejected(self, client):
        assert upload(client, filename="\t\x7f").status_code == 400

    def test_clean_filename_drops_newlines(self):
        assert main.clean_filename("evil\r\nX-Injected: 1.txt") == "evilX-Injected: 1.txt"

    def test_long_filename_capped_keeping_extension(self, client):
        body = upload(client, filename="n" * 5000 + ".pdf").get_json()
        assert len(body["filename"]) == main.MAX_FILENAME_LENGTH
        assert body["filename"].endswith(".pdf")
        disposition = client.get(f"/resource/{body['id']}").headers["Content-Disposition"]
        assert len(disposition) < 300

    def test_long_filename_with_long_extension_capped(self):
        name = main.clean_filename("a" * 300 + "." + "b" * 40)
        assert len(name) == main.MAX_FILENAME_LENGTH

    def test_filename_at_cap_unchanged(self):
        name = "n" * main.MAX_FILENAME_LENGTH
        assert main.clean_filename(name) == name

    def test_clean_filename_drops_windows_paths(self):
        assert main.clean_filename("C:\\Users\\me\\file.txt") == "file.txt"

    def test_served_with_safety_headers(self, client):
        rid = upload(client, fmt="html").get_json()["id"]
        res = client.get(f"/resource/{rid}")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["Content-Security-Policy"].startswith("sandbox")
        assert "allow-scripts" in res.headers["Content-Security-Policy"]
        assert "allow-same-origin" not in res.headers["Content-Security-Policy"]

    def test_cached_copy_revalidates(self, client):
        rid = upload(client).get_json()["id"]
        etag = client.get(f"/resource/{rid}").headers["ETag"]
        res = client.get(f"/resource/{rid}", headers={"If-None-Match": etag})
        assert res.status_code == 304

    def test_replacement_is_never_served_as_cached(self, client):
        # The fake clock does not move, so this is a replacement within the same instant
        rid = upload(client, b"v1").get_json()["id"]
        first = client.get(f"/resource/{rid}")
        replace(client, rid, b"v2")
        res = client.get(f"/resource/{rid}", headers={"If-None-Match": first.headers["ETag"]})
        assert res.status_code == 200
        assert res.data == b"v2"
        assert res.headers["ETag"] != first.headers["ETag"]

    def test_no_date_based_caching(self, client):
        rid = upload(client).get_json()["id"]
        res = client.get(f"/resource/{rid}")
        assert "Last-Modified" not in res.headers
        assert "no-cache" in res.headers["Cache-Control"] or "max-age=0" in res.headers["Cache-Control"]

    def test_unknown_resource_not_found(self, client):
        res = client.get("/resource/doesnotx")
        assert res.status_code == 404
        assert res.get_json()["error"] == "Resource not found"


# --- 3. Replace a resource --------------------------------------------------

class TestReplace:
    def test_replaces_content_under_same_link(self, client):
        rid = upload(client, b"v1", "v1.txt").get_json()["id"]
        res = replace(client, rid, b"version two", "v2.html", fmt="html")
        assert res.status_code == 200
        body = res.get_json()
        assert body["id"] == rid
        assert body["filename"] == "v2.html"
        assert body["content_type"] == "text/html"
        assert body["size"] == 11
        assert "updated_at" in body
        assert body["url"] == f"/resource/{rid}"
        assert client.get(f"/resource/{rid}").data == b"version two"
        assert list_json(client)["count"] == 1

    def test_all_format_hints_apply(self, client):
        rid = upload(client).get_json()["id"]
        assert replace(client, rid, fmt="pdf").get_json()["content_type"] == "application/pdf"

    def test_restarts_lifetime(self, client, clock):
        rid = upload(client).get_json()["id"]
        clock.advance(RESOURCE_TTL - 60)
        replace(client, rid)
        clock.advance(RESOURCE_TTL - 60)
        assert client.get(f"/resource/{rid}").status_code == 200
        clock.advance(60)
        assert client.get(f"/resource/{rid}").status_code == 404

    def test_unknown_resource_rejected(self, client, store):
        res = replace(client, "doesnotx")
        assert res.status_code == 404
        assert store.count() == 0

    def test_expired_resource_cannot_be_revived(self, client, clock, store):
        rid = upload(client).get_json()["id"]
        clock.advance(RESOURCE_TTL)
        assert replace(client, rid).status_code == 404
        assert store.count() == 0

    def test_missing_file_rejected(self, client):
        rid = upload(client).get_json()["id"]
        res = client.put(f"/resource/{rid}", data={}, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json()["error"] == "No file provided"

    def test_empty_filename_rejected(self, client):
        rid = upload(client).get_json()["id"]
        assert replace(client, rid, filename="").status_code == 400

    def test_unknown_format_rejected(self, client):
        rid = upload(client, b"original").get_json()["id"]
        assert replace(client, rid, fmt="exe").status_code == 400
        assert client.get(f"/resource/{rid}").data == b"original"


# --- 4. Browse all resources ------------------------------------------------

class TestBrowse:
    def test_root_redirects_to_list(self, client):
        res = client.get("/")
        assert res.status_code == 302
        assert res.headers["Location"].endswith("/resources")

    def test_json_lists_live_resources(self, client, clock):
        first = upload(client, b"abc", "a.txt", fmt="text").get_json()["id"]
        clock.advance(10)
        second = upload(client, b"{}", "b.json", fmt="json").get_json()["id"]
        body = list_json(client)
        assert body["count"] == 2
        assert body["ttl_hours"] == 24
        assert body["max_file_size_bytes"] == MAX_FILE_SIZE
        assert [r["id"] for r in body["resources"]] == [first, second]
        item = body["resources"][0]
        assert item["filename"] == "a.txt"
        assert item["content_type"] == "text/plain"
        assert item["size"] == 3
        assert item["ttl_seconds"] == RESOURCE_TTL
        assert item["time_remaining_seconds"] == RESOURCE_TTL - 10
        assert item["url"] == f"/resource/{first}"
        assert "created_at" in item and "expires_at" in item

    def test_default_accept_gets_json(self, client):
        res = client.get("/resources", headers={"Accept": "*/*"})
        assert res.mimetype == "application/json"

    def test_json_empty(self, client):
        assert list_json(client) == {
            "resources": [], "count": 0, "ttl_hours": 24, "max_file_size_bytes": MAX_FILE_SIZE,
        }

    def test_html_lists_resources(self, client):
        rid = upload(client, filename="notes.txt", fmt="text").get_json()["id"]
        res = client.get("/resources", headers={"Accept": "text/html"})
        assert res.mimetype == "text/html"
        html = res.get_data(as_text=True)
        assert rid in html
        assert "notes.txt" in html
        assert f'href="/resource/{rid}"' in html
        assert "badge-text" in html
        assert "24h" in html
        assert "10 MB" in html

    def test_html_empty_state_explains_how_to_add(self, client):
        html = list_html(client)
        assert "No resources available" in html
        assert "POST /upload" in html

    def test_html_escapes_filenames(self, client):
        upload(client, filename='<img src=x onerror="alert(1)">.txt')
        html = list_html(client)
        assert "<img src=x" not in html
        assert "&lt;img src=x" in html

    def test_html_escapes_content_type_badge(self, client):
        upload(client, filename="x.bin", content_type="application/<script>")
        assert "<script>" not in list_html(client)

    def test_html_highlights_expiring_soon(self, client, clock):
        upload(client)
        assert 'class="expires-soon"' not in list_html(client)
        clock.advance(RESOURCE_TTL - 30 * 60)
        assert 'class="expires-soon"' in list_html(client)

    @pytest.mark.parametrize("content_type,badge", [
        ("text/html", "badge-html"),
        ("application/json", "badge-json"),
        ("application/pdf", "badge-pdf"),
        ("text/plain", "badge-text"),
        ("image/png", "badge-other"),
    ])
    def test_html_badges(self, client, content_type, badge):
        upload(client, filename="f", content_type=content_type)
        assert badge in list_html(client)


# --- 5. Service status ------------------------------------------------------

class TestHealth:
    def test_reports_status_and_count(self, client, clock):
        upload(client)
        upload(client)
        body = client.get("/health").get_json()
        assert body["status"] == "healthy"
        assert body["resources_count"] == 2
        assert body["uptime_seconds"] >= 0

    def test_count_excludes_expired(self, client, clock):
        upload(client)
        clock.advance(RESOURCE_TTL)
        assert client.get("/health").get_json()["resources_count"] == 0


# --- Rules: file size -------------------------------------------------------

class TestFileSizeLimit:
    def test_limit_is_10_mb(self):
        assert MAX_FILE_SIZE == 10 * 1024 * 1024

    @pytest.mark.parametrize("size", [MAX_FILE_SIZE - 1, MAX_FILE_SIZE])
    def test_upload_at_or_under_limit_accepted(self, client, size):
        res = upload(client, b"x" * size, "big.bin")
        assert res.status_code == 201
        assert res.get_json()["size"] == size

    def test_upload_over_limit_rejected(self, client, store):
        res = upload(client, b"x" * (MAX_FILE_SIZE + 1), "big.bin")
        assert res.status_code == 413
        assert res.get_json()["error"] == "File too large: maximum size is 10 MB"
        assert store.count() == 0

    def test_upload_far_over_limit_rejected(self, client, store):
        res = upload(client, b"x" * (MAX_FILE_SIZE * 2), "huge.bin")
        assert res.status_code == 413
        assert "10 MB" in res.get_json()["error"]
        assert store.count() == 0

    def test_replace_at_limit_accepted(self, client):
        rid = upload(client).get_json()["id"]
        assert replace(client, rid, b"x" * MAX_FILE_SIZE).status_code == 200

    def test_replace_over_limit_rejected_and_original_kept(self, client):
        rid = upload(client, b"original").get_json()["id"]
        res = replace(client, rid, b"x" * (MAX_FILE_SIZE + 1))
        assert res.status_code == 413
        assert client.get(f"/resource/{rid}").data == b"original"


# --- Rules: lifetime and expiry ---------------------------------------------

class TestExpiry:
    def test_lifetime_is_24_hours(self):
        assert RESOURCE_TTL == 24 * 3600

    def test_available_until_24_hours(self, client, clock):
        rid = upload(client).get_json()["id"]
        clock.advance(RESOURCE_TTL - 1)
        assert client.get(f"/resource/{rid}").status_code == 200
        assert list_json(client)["count"] == 1

    def test_expired_resource_not_viewable(self, client, clock):
        rid = upload(client).get_json()["id"]
        clock.advance(RESOURCE_TTL)
        assert client.get(f"/resource/{rid}").status_code == 404

    def test_expired_resource_not_listed(self, client, clock):
        upload(client)
        clock.advance(RESOURCE_TTL)
        assert list_json(client)["count"] == 0
        assert "No resources available" in list_html(client)

    def test_purge_removes_only_expired(self, store, clock):
        old = store.add(b"old", "old.txt", "text/plain")
        clock.advance(RESOURCE_TTL - 10)
        fresh = store.add(b"new", "new.txt", "text/plain")
        clock.advance(10)
        assert store.purge_expired() == [old["id"]]
        assert store.get(fresh["id"]) is not None
        assert store.get(old["id"]) is None

    def test_cleanup_thread_purges(self, monkeypatch):
        store = ResourceStore()
        purged = threading.Event()
        monkeypatch.setattr(store, "purge_expired", lambda: purged.set() or ["deadbeef"])
        stop = main.start_cleanup_thread(store, interval=0.01)
        try:
            assert purged.wait(timeout=2)
        finally:
            stop.set()

    def test_cleanup_thread_stops(self, monkeypatch):
        store = ResourceStore()
        calls = []
        monkeypatch.setattr(store, "purge_expired", lambda: calls.append(1) or [])
        stop = main.start_cleanup_thread(store, interval=0.01)
        stop.set()
        time.sleep(0.1)
        settled = len(calls)
        time.sleep(0.1)
        assert len(calls) == settled


# --- Rules: open access (intentional) ---------------------------------------

class TestOpenAccess:
    def test_all_actions_work_without_credentials(self, client):
        rid = upload(client).get_json()["id"]
        assert client.get(f"/resource/{rid}").status_code == 200
        assert client.get("/resources").status_code == 200
        assert replace(client, rid).status_code == 200
        assert client.get("/health").status_code == 200

    def test_anyone_can_overwrite_anyone_elses_resource(self, store):
        app = create_app(store)
        alice, bob = app.test_client(), app.test_client()
        rid = upload(alice, b"alice's content").get_json()["id"]
        assert replace(bob, rid, b"bob's content").status_code == 200
        assert alice.get(f"/resource/{rid}").data == b"bob's content"


# --- Concurrency ------------------------------------------------------------

class TestConcurrency:
    def test_parallel_uploads_get_distinct_ids(self, store):
        app = create_app(store)
        ids, lock = [], threading.Lock()

        def worker():
            c = app.test_client()
            for _ in range(20):
                rid = upload(c).get_json()["id"]
                with lock:
                    ids.append(rid)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == len(set(ids)) == 160
        assert store.count() == 160


# --- Helpers and entry point ------------------------------------------------

class TestHelpers:
    @pytest.mark.parametrize("seconds,label", [(86400, "24h"), (1800, "30m"), (45, "45s")])
    def test_format_duration(self, seconds, label):
        assert main.format_duration(seconds) == label

    @pytest.mark.parametrize("size,label", [(10 * 1024 * 1024, "10 MB"), (1500, "1,500 bytes")])
    def test_format_size(self, size, label):
        assert main.format_size(size) == label


class TestEntryPoint:
    def test_main_serves_with_env_config(self, monkeypatch):
        calls = {}

        class FakeServer:
            def run(self):
                calls["ran"] = True

        def fake_make_server(app, host, port):
            calls.update(app=app, host=host, port=port)
            return FakeServer()

        monkeypatch.setenv("RESOURCE_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("RESOURCE_SERVER_PORT", "4321")
        monkeypatch.setenv("RESOURCE_CLEANUP_INTERVAL", "60")
        monkeypatch.setattr(main, "start_cleanup_thread", lambda store, interval: calls.update(interval=interval))
        monkeypatch.setattr(main, "make_server", fake_make_server)
        main.main()
        assert calls["interval"] == 60
        assert calls["host"] == "127.0.0.1"
        assert calls["port"] == 4321
        assert calls["ran"]
        assert calls["app"].config["MAX_CONTENT_LENGTH"] > MAX_FILE_SIZE

    def test_server_body_cap_leaves_room_for_json_errors(self):
        assert main.SERVER_MAX_BODY > main.MAX_FILE_SIZE + main.MULTIPART_OVERHEAD
