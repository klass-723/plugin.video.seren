"""
Personal Tracker: a user supplied server that speaks the Trakt API v2.

Alongside Trakt: successful Trakt writes (history, collection, watchlist, ratings and scrobbles) are
copied to the tracker in the background, with ids the tracker can resolve added from the local sync database.

Instead of Trakt: TraktAPI() hands back a PersonalTrackerAPI, so reads, syncing and writes all go to the tracker.
"""
import copy
import re
import threading
import time
from functools import cached_property

from resources.lib.indexers.trakt import TraktAPI
from resources.lib.modules.globals import g

MODE_ALONGSIDE = 0
MODE_INSTEAD = 1

# Mirrored writes must never hold anything up for long
MIRROR_TIMEOUT = 8
# Tracker requests when it replaces Trakt
REQUEST_TIMEOUT = 30

# Marks the sync database as holding tracker data rather than Trakt data
SYNC_IDENTITY_PREFIX = "personal-tracker:"

_MIRRORED_PATHS = re.compile(
    r"^(?:sync/(?:history|collection|watchlist|ratings)(?:/remove)?|scrobble/(?:start|pause|stop))$"
)

_SETTINGS = {
    "enabled": "personal_tracker.enabled",
    "url": "personal_tracker.url",
    "clientid": "personal_tracker.clientid",
    "secret": "personal_tracker.secret",
    "mode": "personal_tracker.mode",
    "manual_token": "personal_tracker.manual_token",
    "username": "personal_tracker.username",
    "auth": "personal_tracker.auth",
    "refresh": "personal_tracker.refresh",
    "expires": "personal_tracker.expires",
}


# region Settings
def _setting(key):
    return (g.get_setting(_SETTINGS[key]) or "").strip()


def server_url():
    return _setting("url").rstrip("/")


def is_enabled():
    return bool(g.get_bool_setting(_SETTINGS["enabled"])) and bool(server_url())


def mode():
    return g.get_int_setting(_SETTINGS["mode"]) or MODE_ALONGSIDE


def access_token():
    return _setting("manual_token") or _setting("auth")


def replaces_trakt():
    return is_enabled() and mode() == MODE_INSTEAD


def mirrors_trakt():
    return is_enabled() and mode() == MODE_ALONGSIDE and bool(access_token())


def active_auth_token():
    """
    The auth token of whichever service TraktAPI is talking to
    """
    if replaces_trakt():
        return access_token() or None
    return g.get_setting("trakt.auth")


def trakt_auth_present():
    return bool(active_auth_token())


def sync_identity():
    """
    Who the local sync database should belong to for the current settings
    """
    if replaces_trakt():
        return f"{SYNC_IDENTITY_PREFIX}{_setting('username')}@{server_url()}"
    return g.get_setting("trakt.username")


def sync_identity_mismatch(stored_identity):
    """
    Returns the identity the sync database should be switched to, or None when it is already correct.
    With the tracker off this only fires for a database still holding tracker data, so Trakt-only setups are untouched
    """
    if replaces_trakt():
        identity = sync_identity()
        return identity if stored_identity != identity else None
    if stored_identity and str(stored_identity).startswith(SYNC_IDENTITY_PREFIX):
        return g.get_setting("trakt.username") or ""
    return None


def settings_controls_before_premiumize():
    """
    Number of settings dialog controls the Personal Tracker group adds ahead of the Premiumize group, so
    g.open_addon_settings offsets for later accounts still land on the right control
    """
    controls = 3  # separator, group title, enable toggle
    if g.get_bool_setting(_SETTINGS["enabled"]):
        controls += 4  # server address, client id, client secret, mode
        controls += 2 if _setting("username") else 1  # username + revoke, or authorize
    return controls


def settings_controls_before_personal_tracker():
    """
    Number of settings dialog controls in the Accounts category ahead of the Personal Tracker group
    """
    controls = 5  # General title + notifications, separator + Trakt title, separator
    if g.get_setting("trakt.username"):
        controls += 3  # username, scrobbling, revoke
        if g.get_bool_setting("trakt.scrobbling"):
            controls += 2  # ignore seconds at start, play count minimum percent
    else:
        controls += 2  # username, authorize
    return controls


# endregion


# region Mirroring
def normalize_path(url):
    return url.split("?", 1)[0].strip("/")


def is_mirrored_path(url):
    return bool(_MIRRORED_PATHS.match(normalize_path(url)))


def should_mirror(url, response):
    return response is not None and 200 <= response.status_code < 300 and is_mirrored_path(url)


def mirror_write(url, data, response):
    """
    Copies a successful Trakt write to the Personal Tracker on a background thread.
    Never raises and never waits on the tracker
    :return: the started thread, or None when nothing was mirrored
    """
    try:
        if not should_mirror(url, response) or not mirrors_trakt():
            return None
        thread = threading.Thread(
            target=_send_mirror,
            args=(normalize_path(url), copy.deepcopy(data)),
            name="PersonalTrackerMirror",
        )
        thread.start()
        return thread
    except Exception as e:
        g.log(f"Personal Tracker: unable to mirror {url}: {e}", "warning")
        return None


def _send_mirror(path, data, timeout=None):
    timeout = timeout or MIRROR_TIMEOUT
    try:
        api = PersonalTrackerAPI(timeout=timeout, retries=False)
        body = IdEnricher(api.trakt_db.fetchone).enrich(data)
        response = api.mirror_post(path, body, timeout)
        if not 200 <= response.status_code < 300:
            g.log(f"Personal Tracker returned {response.status_code} mirroring {path}", "warning")
    except Exception as e:
        g.log(f"Personal Tracker: failed to mirror {path}: {e}", "warning")


class IdEnricher:
    """
    Adds the ids a Personal Tracker can resolve (tmdb, tvdb, imdb, season/episode numbers and show ids)
    to a Trakt request body, using the local Trakt sync database. Works on a copy, the given body is never changed
    """

    def __init__(self, fetchone):
        """
        :param fetchone: callable(query, params) returning a dict row or None
        """
        self._fetchone = fetchone
        self._show_ids = {}

    def enrich(self, data):
        body = copy.deepcopy(data)
        if not isinstance(body, dict):
            return body

        for key, enrich_item in (
            ("movies", self._movie),
            ("shows", self._show),
            ("seasons", self._season),
            ("episodes", self._episode),
        ):
            for item in body.get(key) or []:
                if isinstance(item, dict):
                    enrich_item(item)

        # Scrobble bodies carry a single item
        if isinstance(body.get("movie"), dict):
            self._movie(body["movie"])
        if isinstance(body.get("show"), dict):
            self._show(body["show"])
        if isinstance(body.get("episode"), dict):
            self._episode(body["episode"])
            show = body["episode"].get("show")
            if isinstance(show, dict) and "show" not in body:
                body["show"] = {"ids": dict(show.get("ids", {}))}
        return body

    @staticmethod
    def _trakt_id(item):
        ids = item.get("ids")
        return ids.get("trakt") if isinstance(ids, dict) else None

    @staticmethod
    def _add_ids(ids, row, columns):
        for key, column in columns:
            if row.get(column) is not None and ids.get(key) is None:
                ids[key] = row[column]

    def _get_show_ids(self, trakt_show_id):
        if trakt_show_id not in self._show_ids:
            ids = {"trakt": trakt_show_id}
            if row := self._fetchone(
                "SELECT tvdb_id, tmdb_id, imdb_id FROM shows WHERE trakt_id=?", (trakt_show_id,)
            ):
                self._add_ids(ids, row, (("tvdb", "tvdb_id"), ("tmdb", "tmdb_id"), ("imdb", "imdb_id")))
            self._show_ids[trakt_show_id] = ids
        return dict(self._show_ids[trakt_show_id])

    def _movie(self, item):
        if (trakt_id := self._trakt_id(item)) is None:
            return
        if row := self._fetchone("SELECT tmdb_id, imdb_id FROM movies WHERE trakt_id=?", (trakt_id,)):
            self._add_ids(item["ids"], row, (("tmdb", "tmdb_id"), ("imdb", "imdb_id")))

    def _show(self, item):
        if (trakt_id := self._trakt_id(item)) is None:
            return
        for key, value in self._get_show_ids(trakt_id).items():
            if item["ids"].get(key) is None:
                item["ids"][key] = value

    def _season(self, item):
        if (trakt_id := self._trakt_id(item)) is None:
            return
        if row := self._fetchone("SELECT trakt_show_id, season FROM seasons WHERE trakt_id=?", (trakt_id,)):
            item.setdefault("number", row["season"])
            item.setdefault("show", {"ids": self._get_show_ids(row["trakt_show_id"])})

    def _episode(self, item):
        if (trakt_id := self._trakt_id(item)) is None:
            return
        if row := self._fetchone(
            "SELECT trakt_show_id, season, number, tvdb_id, tmdb_id FROM episodes WHERE trakt_id=?",
            (trakt_id,),
        ):
            self._add_ids(item["ids"], row, (("tvdb", "tvdb_id"), ("tmdb", "tmdb_id")))
            item.setdefault("season", row["season"])
            item.setdefault("number", row["number"])
            item.setdefault("show", {"ids": self._get_show_ids(row["trakt_show_id"])})


# endregion


class PersonalTrackerAPI(TraktAPI):
    """
    TraktAPI pointed at the user's Personal Tracker server, with its own credentials and tokens
    """

    service_name = "Personal Tracker"
    lock_name = "personal_tracker"

    username_setting_key = _SETTINGS["username"]
    auth_setting_keys = {"auth": _SETTINGS["auth"], "refresh": _SETTINGS["refresh"], "expires": _SETTINGS["expires"]}

    auth_title_string = 30676
    auth_success_string = 30677
    auth_revoked_string = 30678
    auth_problem_string = 30679
    auth_reset_string = 30679

    mirrors_writes = False

    def __init__(self, timeout=None, retries=True, **kwargs):
        self.request_timeout = timeout or REQUEST_TIMEOUT
        self.retries = retries
        self.manual_token = ""
        super().__init__()

    @cached_property
    def session(self):
        if not self.retries:
            import requests

            return requests.Session()
        session = TraktAPI.session.func(self)
        # Self hosted servers may well be plain http
        session.mount("http://", session.get_adapter("https://"))
        return session

    def _get_headers(self):
        headers = super()._get_headers()
        if not self.client_id:
            headers.pop("trakt-api-key", None)
        return headers

    # region settings
    def _load_settings(self):
        self.ApiUrl = server_url()
        self.client_id = _setting("clientid")
        self.client_secret = _setting("secret")
        self.manual_token = _setting("manual_token")
        self.access_token = self.manual_token or _setting("auth")
        # A pasted token is used as is, there is nothing to refresh it with
        self.refresh_token = None if self.manual_token else _setting("refresh") or None
        self.token_expires = g.get_float_setting(_SETTINGS["expires"]) or 0
        self.default_limit = g.get_int_setting("item.limit")
        self.username = _setting("username") or None

    def _save_settings(self, response):
        if "expires_in" in response and "created_at" not in response:
            response = dict(response, created_at=int(time.time()))
        super()._save_settings(response)

    def _reset_auth(self, notify=True):
        for key in ("auth", "refresh", "expires", "username", "manual_token"):
            g.clear_setting(_SETTINGS[key])
        if notify:
            import xbmcgui

            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(self.auth_reset_string))

    # endregion

    # region Auth
    def auth(self):
        """
        Signs in to the Personal Tracker with the Trakt device code flow, or with a pasted access token
        """
        import xbmcgui

        if not self.ApiUrl:
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30680))
            return
        if self.manual_token:
            self._token_sign_in()
            return
        super().auth()

    def _token_sign_in(self):
        import xbmcgui

        try:
            username = self.get_username()
        except Exception as e:
            g.log(f"Personal Tracker: unable to sign in with access token: {e}", "warning")
            username = None
        if not username:
            xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(30681))
            return
        self.username = username
        g.set_setting(self.username_setting_key, username)
        xbmcgui.Dialog().ok(g.ADDON_NAME, g.get_language_string(self.auth_success_string))
        self._sync_trakt_user_data_if_required()

    def try_refresh_token(self, force=False):
        # Without a known expiry wait for a 401 to force the refresh, rather than refreshing on every call
        if not force and not self.token_expires:
            return
        super().try_refresh_token(force)

    def revoke_auth(self):
        if self.manual_token:
            # Not issued to us, so nothing to revoke on the server
            self.access_token = None
        super().revoke_auth()

    def _verification_url(self, device_code_response):
        return (
            device_code_response.get("verification_url")
            or device_code_response.get("verification_uri")
            or self.ApiUrl
        )

    def _auth_completed(self):
        return self.username is not None

    def _sync_trakt_user_data_if_required(self):
        # The sync database only follows the tracker when it replaces Trakt. The sync itself notices the
        # change of identity and rebuilds the database, as the tracker's ids are not Trakt's
        if replaces_trakt():
            import xbmc

            xbmc.executebuiltin(f'RunPlugin("{g.BASE_URL}?action=syncTraktActivities")')

    def get_username(self):
        """
        Fetch the signed in tracker user's username
        :return: string username
        """
        response = self.get("users/settings")
        if response is None or not response.ok:
            return None
        return response.json()["user"]["username"]

    # endregion

    def mirror_post(self, path, data, timeout=MIRROR_TIMEOUT):
        """
        Single, short POST for mirroring: no retries and no auth dialogs
        """
        import requests

        return requests.post(self._url(path), json=data, headers=self._get_headers(), timeout=timeout)
