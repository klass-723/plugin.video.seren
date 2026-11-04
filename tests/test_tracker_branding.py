import os
import re
import sys
import unittest
from unittest import mock
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(__file__))
import kodi_stubs  # noqa: E402  must come before resources.lib imports

from resources.lib.indexers import personal_tracker as pt  # noqa: E402
from resources.lib.indexers import trakt  # noqa: E402
from resources.lib.modules import tracker_branding as tb  # noqa: E402

g = kodi_stubs.g
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "resources", "images", "icons")
SETTINGS_XML = os.path.join(ROOT, "resources", "settings.xml")
STRINGS_PO = os.path.join(ROOT, "resources", "language", "resource.language.en_gb", "strings.po")

INSTEAD = {
    "personal_tracker.enabled": "true",
    "personal_tracker.url": "https://tracker.example",
    "personal_tracker.mode": "1",
}


class TestReplacesTrakt(unittest.TestCase):
    def test_needs_enabled_address_and_instead_mode(self):
        cases = [
            ({}, False),
            (INSTEAD, True),
            ({**INSTEAD, "personal_tracker.enabled": "false"}, False),
            ({**INSTEAD, "personal_tracker.url": ""}, False),
            ({**INSTEAD, "personal_tracker.url": " / "}, False),
            ({**INSTEAD, "personal_tracker.mode": "0"}, False),
        ]
        for settings, expected in cases:
            g.reset(**settings)
            self.assertEqual(tb.replaces_trakt(g), expected, settings)
            self.assertEqual(pt.replaces_trakt(), expected, settings)


class TestDisplayName(unittest.TestCase):
    def test_default_when_blank(self):
        for value in (None, "", "   "):
            g.reset(**{"personal_tracker.name": value})
            self.assertEqual(tb.display_name(g), "Personal Tracker")

    def test_custom_name(self):
        g.reset(**{"personal_tracker.name": "  Tracker "})
        self.assertEqual(tb.display_name(g), "Tracker")

    def test_tracker_api_uses_the_name(self):
        g.reset(**{**INSTEAD, "personal_tracker.name": "Tracker"})
        self.assertEqual(pt.PersonalTrackerAPI().service_name, "Tracker")


class TestRelabel(unittest.TestCase):
    def test_trakt_word_swapped_only_when_replacing(self):
        self.assertEqual(tb.relabel("Trakt Sync Tools", "Tracker", True), "Tracker Sync Tools")
        self.assertEqual(tb.relabel("Trakt Sync Tools", "Tracker", False), "Trakt Sync Tools")

    def test_whole_word_only(self):
        self.assertEqual(
            tb.relabel("Force Seren to perform a sync with Trakt's servers", "Tracker", True),
            "Force Seren to perform a sync with Tracker's servers",
        )
        self.assertEqual(tb.relabel("TraktSync", "Tracker", True), "TraktSync")

    def test_tracker_strings_use_the_name_in_either_mode(self):
        for replacing in (True, False):
            self.assertEqual(
                tb.relabel("Successfully authenticated with Personal Tracker", "Tracker", replacing),
                "Successfully authenticated with Tracker",
            )

    def test_default_name_leaves_tracker_strings_alone(self):
        self.assertEqual(
            tb.relabel("Authorize Personal Tracker", "Personal Tracker", True), "Authorize Personal Tracker"
        )

    def test_empty_text(self):
        self.assertEqual(tb.relabel("", "Tracker", True), "")
        self.assertIsNone(tb.relabel(None, "Tracker", True))


class TestIcons(unittest.TestCase):
    def test_swapped_only_when_replacing(self):
        self.assertEqual(tb.icon_slug("trakt_sync", True), "tracker_sync")
        self.assertEqual(tb.icon_slug("trakt_sync", False), "trakt_sync")
        self.assertEqual(tb.icon_slug("movies", True), "movies")

    def test_every_icon_exists(self):
        for trakt_slug, plain_slug in tb.ICON_SLUGS.items():
            self.assertTrue(os.path.exists(os.path.join(ICONS, f"{trakt_slug}.png")), trakt_slug)
            self.assertTrue(os.path.exists(os.path.join(ICONS, f"{plain_slug}.png")), plain_slug)

    def test_every_trakt_logo_icon_has_a_plain_version(self):
        logo_icons = {f[:-4] for f in os.listdir(ICONS) if re.search(r"(^|_)trakt(_|\.)", f)}
        self.assertEqual(logo_icons, set(tb.ICON_SLUGS))


def _visible_conditions(setting):
    dependency = setting.find("dependencies/dependency[@type='visible']")
    return [] if dependency is None else list(dependency.iter("condition"))


def _hidden_while_replacing(setting):
    """
    True when the setting's visibility requires one of: tracker off, mode not Instead, or no server address
    """
    dependency = setting.find("dependencies/dependency[@type='visible']")
    if dependency is None:
        return False
    for group in dependency.iter("or"):
        conditions = {(c.get("operator"), c.get("setting"), (c.text or "").strip()) for c in group.findall("condition")}
        if conditions == {
            ("is", "personal_tracker.enabled", "false"),
            ("!is", "personal_tracker.mode", "1"),
            ("is", "personal_tracker.url", ""),
        }:
            return True
    return False


class TestSettingsXml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = {s.get("id"): s for s in ElementTree.parse(SETTINGS_XML).iter("setting")}

    def test_trakt_account_settings_hidden_while_replacing(self):
        trakt_ids = [
            "trakt.username", "trakt.authTrakt", "trakt.scrobbling", "trakt.ignoreSecondsAtStart",
            "trakt.playCountMinimumPercent", "trakt.revokeTrakt", "trakt.clientid", "trakt.secret", "traktdb.force",
        ]
        for setting_id in trakt_ids:
            self.assertTrue(_hidden_while_replacing(self.settings[setting_id]), setting_id)

    def test_trakt_users_keep_their_existing_conditions(self):
        revoke = self.settings["trakt.revokeTrakt"]
        conditions = {(c.get("operator"), c.get("setting")) for c in _visible_conditions(revoke)}
        self.assertIn(("!is", "trakt.username"), conditions)

    def test_neutral_force_sync_only_while_replacing(self):
        conditions = {
            (c.get("operator"), c.get("setting"), (c.text or "").strip())
            for c in _visible_conditions(self.settings["traktdb.forceTracker"])
        }
        self.assertEqual(
            conditions,
            {
                ("is", "personal_tracker.enabled", "true"),
                ("is", "personal_tracker.mode", "1"),
                ("!is", "personal_tracker.url", ""),
            },
        )
        self.assertEqual(
            self.settings["traktdb.forceTracker"].findtext("data"), self.settings["traktdb.force"].findtext("data")
        )

    def test_tracker_name_setting(self):
        setting = self.settings["personal_tracker.name"]
        self.assertEqual(setting.findtext("default"), tb.DEFAULT_NAME)
        self.assertEqual(setting.get("id"), tb.NAME_SETTING)


class TestSettingsOffsets(unittest.TestCase):
    def test_trakt_settings_counted_when_trakt_in_use(self):
        g.reset(**{"trakt.username": "someone", "trakt.scrobbling": "false"})
        self.assertEqual(pt.settings_controls_before_personal_tracker(), 8)
        g.reset()
        self.assertEqual(pt.settings_controls_before_personal_tracker(), 7)

    def test_trakt_groups_gone_while_replacing(self):
        # checked on a Shield: with every Trakt account setting hidden, Kodi drops its title and separators too
        g.reset(**{**INSTEAD, "trakt.username": "someone", "trakt.scrobbling": "true"})
        self.assertEqual(pt.settings_controls_before_personal_tracker(), 2)

    def test_tracker_name_counted_before_premiumize(self):
        g.reset(**{**INSTEAD, "personal_tracker.username": "Klass7"})
        # separator, title, toggle, address, name, client id, secret, mode, username, revoke
        self.assertEqual(pt.settings_controls_before_premiumize(), 10)


class _LockedSession:
    def post(self, url, json=None, headers=None, timeout=None):
        response = mock.Mock(status_code=423, url=url, ok=False, headers={})
        return response


class TestLockedAccountMessage(unittest.TestCase):
    def setUp(self):
        kodi_stubs.dialog.reset_mock()

    def _locked_post(self, api):
        api.__dict__["session"] = _LockedSession()
        api._post("sync/history", {})
        return kodi_stubs.dialog.notification.call_args[0][1]

    def test_names_trakt_for_trakt(self):
        g.reset()
        self.assertEqual(self._locked_post(trakt.TraktAPI()), "Locked User Account - Contact Trakt support")

    def test_names_the_tracker(self):
        g.reset(**{**INSTEAD, "personal_tracker.name": "Tracker", "personal_tracker.auth": "token"})
        self.assertEqual(self._locked_post(pt.PersonalTrackerAPI()), "Locked User Account - Contact Tracker support")


class TestStrings(unittest.TestCase):
    def test_new_strings_present(self):
        with open(STRINGS_PO, encoding="utf-8") as f:
            text = f.read()
        for string_id, msgid in ((30684, "Tracker name"), (30685, "Sync Tools"), (30686, "Force a sync now")):
            self.assertIn(f'msgctxt "#{string_id}"\nmsgid "{msgid}"', text)


if __name__ == "__main__":
    unittest.main()
