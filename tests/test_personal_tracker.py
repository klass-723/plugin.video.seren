import copy
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import kodi_stubs  # noqa: E402  must come before resources.lib imports

from resources.lib.indexers import personal_tracker as pt  # noqa: E402
from resources.lib.indexers import trakt  # noqa: E402

g = kodi_stubs.g


def tracker_settings(**extra):
    settings = {
        "personal_tracker.enabled": "true",
        "personal_tracker.url": "http://127.0.0.1:1/tracker/",
        "personal_tracker.clientid": "tracker-client",
        "personal_tracker.secret": "tracker-secret",
        "personal_tracker.mode": "0",
        "personal_tracker.auth": "tracker-token",
        "trakt.auth": "trakt-token",
        "trakt.username": "trakt-user",
        "item.limit": "20",
    }
    settings.update(extra)
    return settings


# region sample traktSync.db
def build_sample_sync_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE shows (trakt_id INTEGER PRIMARY KEY, tvdb_id INTEGER, tmdb_id INTEGER, imdb_id INTEGER);
        CREATE TABLE seasons (trakt_id INTEGER, trakt_show_id INTEGER, tvdb_id INTEGER, tmdb_id INTEGER,
                              season INTEGER);
        CREATE TABLE episodes (trakt_id INTEGER, trakt_show_id INTEGER, trakt_season_id INTEGER, season INTEGER,
                               tvdb_id INTEGER, tmdb_id INTEGER, imdb_id INTEGER, number INTEGER);
        CREATE TABLE movies (trakt_id INTEGER PRIMARY KEY, tmdb_id INTEGER, imdb_id INTEGER);
        INSERT INTO shows VALUES (1390, 121361, 1399, 'tt0944947');
        INSERT INTO seasons VALUES (3962, 1390, 364731, 3624, 1);
        INSERT INTO episodes VALUES (73640, 1390, 3962, 1, 3254641, 63056, 'tt1480055', 1);
        INSERT INTO movies VALUES (28, 603, 'tt0133093');
        INSERT INTO movies VALUES (29, NULL, 'tt0000029');
        """
    )
    connection.commit()
    connection.close()


class SampleSyncDb:
    def __init__(self, path):
        self.path = path
        self.queries = []

    def fetchone(self, query, data=None):
        self.queries.append(query)
        connection = sqlite3.connect(self.path)
        connection.row_factory = lambda c, r: {col[0]: r[idx] for idx, col in enumerate(c.description)}
        try:
            return connection.execute(query, data or ()).fetchone()
        finally:
            connection.close()


# endregion


# region fake tracker server
class TrackerServer:
    """
    Small Trakt-like server on localhost. Records every request; behaviour is set per test
    """

    def __init__(self, prefix="/tracker"):
        self.prefix = prefix
        self.requests = []
        self.delay = 0
        self.device_token_pending = 1
        self.token_response = {"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600}
        self.username = "alice"
        self.valid_tokens = {"tracker-token", "new-token", "pasted-token"}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, body=None):
                payload = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                server.requests.append(
                    {"method": method, "path": self.path, "headers": dict(self.headers), "body": body}
                )
                if server.delay:
                    time.sleep(server.delay)
                path = self.path.split("?", 1)[0]
                if not path.startswith(server.prefix + "/"):
                    return self._reply(404, {})
                endpoint = path[len(server.prefix) + 1 :]
                token = (self.headers.get("Authorization") or "").replace("Bearer ", "")

                if endpoint == "oauth/device/code":
                    return self._reply(
                        200,
                        {
                            "device_code": "device-123",
                            "user_code": "ABCD1234",
                            "verification_url": f"http://127.0.0.1:{server.port}{server.prefix}/activate",
                            "expires_in": 30,
                            "interval": 1,
                        },
                    )
                if endpoint == "oauth/device/token":
                    if server.device_token_pending > 0:
                        server.device_token_pending -= 1
                        return self._reply(400, {})
                    return self._reply(200, server.token_response)
                if endpoint == "oauth/token":
                    if (body or {}).get("grant_type") != "refresh_token":
                        return self._reply(400, {})
                    return self._reply(200, server.token_response)
                if endpoint == "users/settings":
                    if token not in server.valid_tokens:
                        return self._reply(401, {})
                    return self._reply(200, {"user": {"username": server.username}, "account": {}})
                if token not in server.valid_tokens:
                    return self._reply(401, {})
                return self._reply(201, {"added": {}})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}{prefix}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def find(self, endpoint):
        return [r for r in self.requests if r["path"].split("?")[0] == f"{self.prefix}/{endpoint}"]


def closed_port_url():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/tracker"


# endregion


class FakeResponse:
    def __init__(self, status_code, url="https://api.trakt.tv/sync/history", body=None):
        self.status_code = status_code
        self.url = url
        self.ok = 200 <= status_code < 400
        self._body = body or {}
        self.headers = {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, status_code=201):
        self.status_code = status_code
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers, timeout))
        return FakeResponse(self.status_code, url)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers, timeout))
        return FakeResponse(200, url)

    def delete(self, url, headers=None, timeout=None):
        self.calls.append(("DELETE", url, None, headers, timeout))
        return FakeResponse(204, url)


def trakt_api_with_session(status_code=201):
    api = trakt.TraktAPI()
    api.__dict__["session"] = FakeSession(status_code)
    return api


class TestUrls(unittest.TestCase):
    def test_join_keeps_base_path_and_uses_one_slash(self):
        self.assertEqual(trakt._join_url("https://example.com/tracker/", "/sync/history"),
                         "https://example.com/tracker/sync/history")
        self.assertEqual(trakt._join_url("https://example.com/tracker", "sync/history"),
                         "https://example.com/tracker/sync/history")
        self.assertEqual(trakt._join_url("https://api.trakt.tv/", "/oauth/token"), "https://api.trakt.tv/oauth/token")

    def test_server_url_strips_trailing_slash_and_whitespace(self):
        g.reset(**tracker_settings(**{"personal_tracker.url": " https://example.com/tracker/ "}))
        self.assertEqual(pt.server_url(), "https://example.com/tracker")


class TestEnrichment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp.name, "traktSync.db")
        build_sample_sync_db(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.enricher = pt.IdEnricher(SampleSyncDb(self.db_path).fetchone)

    def assert_enriched_copy(self, body):
        original = copy.deepcopy(body)
        enriched = self.enricher.enrich(body)
        self.assertEqual(body, original, "caller's body must not be modified")
        self.assertIsNot(enriched, body)
        return enriched

    def test_movies(self):
        enriched = self.assert_enriched_copy({"movies": [{"ids": {"trakt": 28}}, {"ids": {"trakt": 29}}]})
        self.assertEqual(enriched["movies"][0]["ids"], {"trakt": 28, "tmdb": 603, "imdb": "tt0133093"})
        # NULL columns are left out rather than sent as null
        self.assertEqual(enriched["movies"][1]["ids"], {"trakt": 29, "imdb": "tt0000029"})

    def test_shows(self):
        enriched = self.assert_enriched_copy({"shows": [{"ids": {"trakt": 1390}}]})
        self.assertEqual(enriched["shows"][0]["ids"], {"trakt": 1390, "tvdb": 121361, "tmdb": 1399, "imdb": "tt0944947"})

    def test_seasons(self):
        enriched = self.assert_enriched_copy({"seasons": [{"ids": {"trakt": 3962}}]})
        season = enriched["seasons"][0]
        self.assertEqual(season["number"], 1)
        self.assertEqual(season["show"]["ids"], {"trakt": 1390, "tvdb": 121361, "tmdb": 1399, "imdb": "tt0944947"})

    def test_episodes(self):
        enriched = self.assert_enriched_copy({"episodes": [{"ids": {"trakt": 73640}, "watched_at": "2026-11-01"}]})
        episode = enriched["episodes"][0]
        self.assertEqual(episode["ids"], {"trakt": 73640, "tvdb": 3254641, "tmdb": 63056})
        self.assertEqual((episode["season"], episode["number"]), (1, 1))
        self.assertEqual(episode["show"]["ids"], {"trakt": 1390, "tvdb": 121361, "tmdb": 1399, "imdb": "tt0944947"})
        self.assertEqual(episode["watched_at"], "2026-11-01")

    def test_episode_scrobble_gets_top_level_show(self):
        body = {"episode": {"ids": {"trakt": 73640}}, "progress": 42.0, "app_version": "3.0.77"}
        enriched = self.assert_enriched_copy(body)
        self.assertEqual(enriched["show"], {"ids": {"trakt": 1390, "tvdb": 121361, "tmdb": 1399, "imdb": "tt0944947"}})
        self.assertEqual(enriched["episode"]["season"], 1)
        self.assertEqual(enriched["progress"], 42.0)

    def test_movie_scrobble(self):
        enriched = self.assert_enriched_copy({"movie": {"ids": {"trakt": 28}}, "progress": 90})
        self.assertEqual(enriched["movie"]["ids"]["tmdb"], 603)
        self.assertNotIn("show", enriched)

    def test_caller_ids_win_and_unknown_items_pass_through(self):
        body = {
            "movies": [{"ids": {"trakt": 28, "tmdb": 1}}, {"ids": {"trakt": 999999}}, {"title": "no ids"}],
            "episodes": [{"ids": {"trakt": 73640}, "season": 5}],
        }
        enriched = self.assert_enriched_copy(body)
        self.assertEqual(enriched["movies"][0]["ids"]["tmdb"], 1)
        self.assertEqual(enriched["movies"][1], {"ids": {"trakt": 999999}})
        self.assertEqual(enriched["movies"][2], {"title": "no ids"})
        self.assertEqual(enriched["episodes"][0]["season"], 5)

    def test_show_ids_looked_up_once(self):
        db = SampleSyncDb(self.db_path)
        pt.IdEnricher(db.fetchone).enrich({"episodes": [{"ids": {"trakt": 73640}}] * 3})
        self.assertEqual(sum("FROM shows" in q for q in db.queries), 1)


class TestMirrorRules(unittest.TestCase):
    MIRRORED = [
        "sync/history", "sync/history/remove", "sync/collection", "sync/collection/remove",
        "sync/watchlist", "sync/watchlist/remove", "sync/ratings", "sync/ratings/remove",
        "scrobble/start", "scrobble/pause", "scrobble/stop", "/sync/history", "sync/history?extended=full",
    ]
    NOT_MIRRORED = [
        "sync/playback/123", "oauth/token", "/oauth/token", "oauth/device/code", "oauth/revoke",
        "users/hidden/calendar", "users/me/lists/1/items", "sync/history/extra", "sync/historyx", "scrobble/rewind",
        "sync/history/remove/x",
    ]

    def test_paths(self):
        for path in self.MIRRORED:
            self.assertTrue(pt.should_mirror(path, FakeResponse(201)), path)
        for path in self.NOT_MIRRORED:
            self.assertFalse(pt.should_mirror(path, FakeResponse(201)), path)

    def test_only_2xx_trakt_responses(self):
        for status in (200, 201, 204):
            self.assertTrue(pt.should_mirror("sync/history", FakeResponse(status)), status)
        for status in (301, 400, 401, 404, 409, 429, 500, 502):
            self.assertFalse(pt.should_mirror("sync/history", FakeResponse(status)), status)
        self.assertFalse(pt.should_mirror("sync/history", None))


class MirrorTestBase(unittest.TestCase):
    def setUp(self):
        self.server = TrackerServer()
        self.tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmp.name, "traktSync.db")
        build_sample_sync_db(db_path)
        self.db = SampleSyncDb(db_path)
        self.db_patch = mock.patch.object(pt.PersonalTrackerAPI, "trakt_db", new=property(lambda s: self.db))
        self.db_patch.start()
        g.reset(**tracker_settings(**{"personal_tracker.url": self.server.url + "/"}))

    def tearDown(self):
        self.db_patch.stop()
        self.server.close()
        self.tmp.cleanup()


class TestMirroring(MirrorTestBase):
    def test_successful_trakt_write_is_mirrored_enriched(self):
        api = trakt_api_with_session(201)
        body = {"episodes": [{"ids": {"trakt": 73640}}]}
        original = copy.deepcopy(body)
        response = api.post("sync/history", body)
        thread = next(t for t in threading.enumerate() if t.name == "PersonalTrackerMirror")
        thread.join(5)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(body, original)

        (request,) = self.server.find("sync/history")
        self.assertEqual(request["headers"]["trakt-api-key"], "tracker-client")
        self.assertEqual(request["headers"]["Authorization"], "Bearer tracker-token")
        self.assertEqual(request["headers"]["trakt-api-version"], "2")
        sent = request["body"]["episodes"][0]
        self.assertEqual(sent["ids"]["tmdb"], 63056)
        self.assertEqual(sent["show"]["ids"]["tvdb"], 121361)
        # Trakt itself got the untouched body
        self.assertEqual(api.session.calls[0][2], original)

    def test_failed_trakt_write_is_not_mirrored(self):
        for status in (401, 404, 409, 500):
            api = trakt_api_with_session(status)
            with mock.patch.object(pt.threading, "Thread") as thread_cls:
                api.post("sync/history", {"movies": [{"ids": {"trakt": 28}}]})
            thread_cls.assert_not_called()

    def test_unlisted_paths_are_not_mirrored(self):
        api = trakt_api_with_session(201)
        with mock.patch.object(pt.threading, "Thread") as thread_cls:
            api.post("users/hidden/calendar", {"shows": [{"ids": {"trakt": 1390}}]})
            api.post("oauth/revoke", {"token": "x"})
            api.delete_request("sync/playback/123")
        thread_cls.assert_not_called()

    def test_tracker_mode_does_not_mirror_to_itself(self):
        g.settings["personal_tracker.mode"] = "1"
        api = trakt.TraktAPI()
        self.assertIsInstance(api, pt.PersonalTrackerAPI)
        api.__dict__["session"] = FakeSession(201)
        with mock.patch.object(pt.threading, "Thread") as thread_cls:
            api.post("sync/history", {"movies": [{"ids": {"trakt": 28}}]})
        thread_cls.assert_not_called()

    def test_no_tracker_token_means_no_mirror(self):
        g.settings["personal_tracker.auth"] = ""
        api = trakt_api_with_session(201)
        with mock.patch.object(pt.threading, "Thread") as thread_cls:
            api.post("sync/history", {"movies": [{"ids": {"trakt": 28}}]})
        thread_cls.assert_not_called()


class TestTrackerFailuresDoNotBlock(MirrorTestBase):
    def _post_and_time(self):
        api = trakt_api_with_session(201)
        threads = []
        real_thread = threading.Thread

        def capture(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread

        with mock.patch.object(pt.threading, "Thread", side_effect=capture):
            start = time.monotonic()
            response = api.post("scrobble/stop", {"episode": {"ids": {"trakt": 73640}}, "progress": 95})
            elapsed = time.monotonic() - start
        return response, elapsed, threads

    def test_tracker_down(self):
        g.settings["personal_tracker.url"] = closed_port_url()
        response, elapsed, threads = self._post_and_time()
        self.assertEqual(response.status_code, 201)
        self.assertLess(elapsed, 0.5)
        threads[0].join(10)
        self.assertFalse(threads[0].is_alive())
        self.assertTrue(any("failed to mirror scrobble/stop" in m for m in g.logs_at("warning")), g.logs)
        self.assertFalse(g.logs_at("error"), "tracker failures must not be logged as Trakt errors")

    def test_tracker_timeout(self):
        self.server.delay = 3
        with mock.patch.object(pt, "MIRROR_TIMEOUT", 0.5):
            response, elapsed, threads = self._post_and_time()
            self.assertEqual(response.status_code, 201)
            self.assertLess(elapsed, 0.5)
            start = time.monotonic()
            threads[0].join(10)
            self.assertLess(time.monotonic() - start, 2.5, "mirror must give up at the timeout")
        self.assertTrue(any("failed to mirror" in m for m in g.logs_at("warning")), g.logs)

    def test_tracker_error_status_is_a_warning(self):
        g.settings["personal_tracker.auth"] = "rejected-token"
        response, _, threads = self._post_and_time()
        threads[0].join(10)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(any("returned 401" in m for m in g.logs_at("warning")), g.logs)

    def test_unexpected_errors_never_reach_the_caller(self):
        api = trakt_api_with_session(201)
        with mock.patch.object(pt.threading, "Thread", side_effect=RuntimeError("boom")):
            response = api.post("sync/history", {"movies": []})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(any("unable to mirror" in m for m in g.logs_at("warning")))


class TestTrackerOff(unittest.TestCase):
    def setUp(self):
        g.reset(**{"trakt.auth": "trakt-token", "trakt.username": "trakt-user", "item.limit": "20"})

    def test_trakt_api_unchanged(self):
        api = trakt.TraktAPI()
        self.assertIs(type(api), trakt.TraktAPI)
        self.assertEqual(api.ApiUrl, "https://api.trakt.tv/")
        api.__dict__["session"] = FakeSession(201)
        with mock.patch.object(pt.threading, "Thread") as thread_cls:
            api.post("sync/history", {"movies": [{"ids": {"trakt": 28}}]})
            api.get("users/me")
            api.delete_request("sync/playback/1")
        thread_cls.assert_not_called()
        urls = [call[1] for call in api.session.calls]
        self.assertEqual(urls, ["https://api.trakt.tv/sync/history", "https://api.trakt.tv/users/me",
                                "https://api.trakt.tv/sync/playback/1"])
        post_headers, post_timeout = api.session.calls[0][3], api.session.calls[0][4]
        self.assertEqual(post_headers["Authorization"], "Bearer trakt-token")
        self.assertEqual(post_headers["trakt-api-key"], api.client_id)
        self.assertIsNone(post_timeout)

    def test_disabled_tracker_with_settings_is_ignored(self):
        g.settings.update({"personal_tracker.enabled": "false", "personal_tracker.url": "https://example.com",
                           "personal_tracker.mode": "1", "personal_tracker.auth": "x"})
        self.assertIs(type(trakt.TraktAPI()), trakt.TraktAPI)
        self.assertFalse(pt.mirrors_trakt())
        self.assertEqual(pt.active_auth_token(), "trakt-token")

    def test_enabled_without_address_is_off(self):
        g.settings.update({"personal_tracker.enabled": "true", "personal_tracker.mode": "1"})
        self.assertIs(type(trakt.TraktAPI()), trakt.TraktAPI)

    def test_auth_check_and_sync_identity(self):
        self.assertTrue(pt.trakt_auth_present())
        g.settings["trakt.auth"] = ""
        self.assertFalse(pt.trakt_auth_present())
        self.assertIsNone(pt.sync_identity_mismatch("trakt-user"))
        self.assertIsNone(pt.sync_identity_mismatch("someone-else"), "Trakt-only setups are never rebuilt")
        self.assertIsNone(pt.sync_identity_mismatch(None))

    def test_settings_offsets_shift_by_new_group_only(self):
        self.assertEqual(pt.settings_controls_before_premiumize(), 3)


class TestTrackerInsteadOfTrakt(unittest.TestCase):
    def setUp(self):
        g.reset(**tracker_settings(**{"personal_tracker.mode": "1", "personal_tracker.username": "alice",
                                      "personal_tracker.url": "https://example.com/tracker/"}))

    def test_everything_goes_to_tracker(self):
        api = trakt.TraktAPI()
        self.assertIsInstance(api, pt.PersonalTrackerAPI)
        api.__dict__["session"] = FakeSession(201)
        api.get("sync/watched/shows")
        api.post("scrobble/start", {"movie": {"ids": {"trakt": 1}}})
        get_call, post_call = api.session.calls
        self.assertEqual(get_call[1], "https://example.com/tracker/sync/watched/shows")
        self.assertEqual(post_call[1], "https://example.com/tracker/scrobble/start")
        self.assertEqual(post_call[3]["trakt-api-key"], "tracker-client")
        self.assertEqual(post_call[3]["Authorization"], "Bearer tracker-token")
        self.assertEqual(post_call[4], pt.REQUEST_TIMEOUT)

    def test_no_client_id_sends_no_api_key(self):
        g.settings["personal_tracker.clientid"] = ""
        self.assertNotIn("trakt-api-key", trakt.TraktAPI()._get_headers())

    def test_trakt_tokens_left_alone(self):
        api = trakt.TraktAPI()
        api.__dict__["session"] = FakeSession(200)
        api._save_settings({"access_token": "a", "refresh_token": "r", "expires_in": 10, "created_at": 5})
        self.assertEqual(g.settings["trakt.auth"], "trakt-token")
        self.assertEqual(g.settings["personal_tracker.auth"], "a")
        self.assertEqual(g.settings["personal_tracker.expires"], "15")

    def test_auth_and_identity(self):
        self.assertEqual(pt.active_auth_token(), "tracker-token")
        g.settings["trakt.auth"] = ""
        self.assertTrue(pt.trakt_auth_present())
        identity = "personal-tracker:alice@https://example.com/tracker"
        self.assertEqual(pt.sync_identity_mismatch("trakt-user"), identity)
        self.assertIsNone(pt.sync_identity_mismatch(identity))
        # back to Trakt: a database holding tracker data is rebuilt for the Trakt user
        g.settings["personal_tracker.mode"] = "0"
        self.assertEqual(pt.sync_identity_mismatch(identity), "trakt-user")

    def test_trakt_only_still_reaches_trakt(self):
        self.assertIs(type(trakt.TraktAPI(trakt_only=True)), trakt.TraktAPI)


class TestSyncDatabaseSwitch(unittest.TestCase):
    """
    The sync database is rebuilt when moving between Trakt and a tracker that replaces it, and only then
    """

    def run_switch(self, stored_identity):
        from resources.lib.database.trakt_sync import activities

        database = mock.MagicMock(activities={"trakt_username": stored_identity})
        activities.TraktSyncDatabase._switch_sync_identity_if_required(database)
        return database

    def test_trakt_only_never_rebuilds(self):
        g.reset(**{"trakt.auth": "t", "trakt.username": "trakt-user"})
        for stored in ("trakt-user", "old-trakt-user", "", None):
            self.run_switch(stored).rebuild_database.assert_not_called()

    def test_switch_to_tracker_and_back(self):
        g.reset(**tracker_settings(**{"personal_tracker.mode": "1", "personal_tracker.username": "alice",
                                      "personal_tracker.url": "https://example.com"}))
        identity = "personal-tracker:alice@https://example.com"
        database = self.run_switch("trakt-user")
        database.rebuild_database.assert_called_once()
        database.set_trakt_user.assert_called_once_with(identity)
        self.run_switch(identity).rebuild_database.assert_not_called()

        g.settings["personal_tracker.mode"] = "0"
        database = self.run_switch(identity)
        database.rebuild_database.assert_called_once()
        database.set_trakt_user.assert_called_once_with("trakt-user")


class TestSignIn(unittest.TestCase):
    def setUp(self):
        self.server = TrackerServer()
        g.reset(**tracker_settings(**{"personal_tracker.url": self.server.url + "/", "personal_tracker.auth": ""}))
        kodi_stubs.dialog.reset_mock()
        self.progress = []
        real_progress = kodi_stubs.FakeDialogProgress

        def make_progress():
            progress = real_progress()
            self.progress.append(progress)
            return progress

        self.patches = [
            mock.patch("xbmcgui.DialogProgress", side_effect=make_progress),
            mock.patch.object(trakt.tools, "copy2clip"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.server.close()

    def dialog_messages(self):
        return [call.args[1] for call in kodi_stubs.dialog.ok.call_args_list]

    def test_device_flow(self):
        before = time.time()
        pt.PersonalTrackerAPI().auth()

        (code_request,) = self.server.find("oauth/device/code")
        self.assertEqual(code_request["body"], {"client_id": "tracker-client"})
        polls = self.server.find("oauth/device/token")
        self.assertEqual(len(polls), 2, "one pending poll, then success")
        self.assertEqual(polls[-1]["body"], {"code": "device-123", "client_id": "tracker-client",
                                             "client_secret": "tracker-secret"})
        (settings_request,) = self.server.find("users/settings")
        self.assertEqual(settings_request["headers"]["Authorization"], "Bearer new-token")

        self.assertEqual(g.settings["personal_tracker.auth"], "new-token")
        self.assertEqual(g.settings["personal_tracker.refresh"], "new-refresh")
        self.assertGreaterEqual(float(g.settings["personal_tracker.expires"]), before + 3600 - 1)
        self.assertEqual(g.settings["personal_tracker.username"], "alice")
        self.assertEqual(g.settings["trakt.auth"], "trakt-token", "Trakt sign-in untouched")

        dialog_text = str(self.progress[0].message)
        self.assertIn(f"{self.server.url}/activate", dialog_text)
        self.assertIn("ABCD1234", dialog_text)
        self.assertIn("#30677", self.dialog_messages()[-1])

    def test_pending_polls_are_quiet_whatever_the_address_case(self):
        # requests reports a normalised URL back (lower case scheme and host), the pending 400 must still match
        g.settings["personal_tracker.url"] = self.server.url.replace("http://", "HTTP://") + "/"
        self.server.device_token_pending = 3
        pt.PersonalTrackerAPI().auth()
        self.assertEqual(len(self.server.find("oauth/device/token")), 4)
        self.assertEqual(g.logs_at("error"), [])
        self.assertEqual(len(self.dialog_messages()), 1, "only the success dialog")
        self.assertIn("#30677", self.dialog_messages()[0])
        self.assertEqual(g.settings["personal_tracker.username"], "alice")

    def test_trakt_endpoint_matching_unchanged(self):
        api = trakt.TraktAPI(trakt_only=True)
        self.assertTrue(api._is_endpoint("https://api.trakt.tv/oauth/device/token", "oauth/device/token"))
        self.assertTrue(api._is_endpoint("https://api.trakt.tv/oauth/token", "/oauth/token"))
        self.assertFalse(api._is_endpoint("https://api.trakt.tv/oauth/device/token", "oauth/token"))

    def test_device_flow_then_refresh(self):
        pt.PersonalTrackerAPI().auth()
        self.server.token_response = {"access_token": "pasted-token", "refresh_token": "r2", "expires_in": 60}
        api = pt.PersonalTrackerAPI()
        api.try_refresh_token(force=True)
        (refresh,) = self.server.find("oauth/token")
        self.assertEqual(refresh["body"]["grant_type"], "refresh_token")
        self.assertEqual(refresh["body"]["refresh_token"], "new-refresh")
        self.assertEqual(g.settings["personal_tracker.auth"], "pasted-token")

    def test_pasted_token_skips_authorization(self):
        g.settings["personal_tracker.manual_token"] = "pasted-token"
        api = pt.PersonalTrackerAPI()
        self.assertEqual(api._get_headers()["Authorization"], "Bearer pasted-token")
        self.assertIsNone(api.refresh_token)
        api.auth()
        self.assertFalse(self.server.find("oauth/device/code"))
        (settings_request,) = self.server.find("users/settings")
        self.assertEqual(settings_request["headers"]["Authorization"], "Bearer pasted-token")
        self.assertEqual(g.settings["personal_tracker.username"], "alice")
        self.assertIn("#30677", self.dialog_messages()[-1])
        self.assertTrue(pt.mirrors_trakt())

    def test_bad_pasted_token(self):
        g.settings["personal_tracker.manual_token"] = "wrong"
        pt.PersonalTrackerAPI().auth()
        self.assertFalse(g.settings.get("personal_tracker.username"))
        self.assertIn("#30681", self.dialog_messages()[-1])

    def test_no_server_address(self):
        g.settings["personal_tracker.url"] = ""
        pt.PersonalTrackerAPI().auth()
        self.assertFalse(self.server.requests)
        self.assertIn("#30680", self.dialog_messages()[-1])


if __name__ == "__main__":
    unittest.main()
