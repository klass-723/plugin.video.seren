import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import kodi_stubs  # noqa: E402  must come before resources.lib imports

for name in ("resources.lib.modules.smartPlay", "resources.lib.database.trakt_sync.bookmark"):
    sys.modules.setdefault(name, mock.MagicMock(name=name))

from resources.lib.modules import player  # noqa: E402

g = kodi_stubs.g

ITEM = {"info": {"mediatype": "movie", "trakt_id": 372518, "duration": 7200}}
STREAM = "https://real-debrid.example/d/greenland.mkv"


class FakeWindow:
    def __init__(self):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, "")

    def setProperty(self, key, value):
        self.properties[key] = value


class FakePlayer:
    def __init__(self, playing=True, playing_file=STREAM):
        self.playing = playing
        self.playing_file = playing_file
        self.resumed_with = None

    def __call__(self):
        return self

    def isPlayingVideo(self):
        return self.playing

    def getPlayingFile(self):
        return self.playing_file

    def resume_tracking(self, item_information, playing_file):
        self.resumed_with = (item_information, playing_file)


class TestResumeTrackingAfterWake(unittest.TestCase):
    def setUp(self):
        g.reset()
        g.HOME_WINDOW = FakeWindow()

    def tearDown(self):
        del g.HOME_WINDOW

    def _remember(self, item=ITEM, stream=STREAM):
        g.HOME_WINDOW.setProperty(player.WAKE_RESUME_PROPERTY, json.dumps({"file": stream, "item_information": item}))

    def test_tracks_the_item_kodi_resumed(self):
        self._remember()
        fake = FakePlayer()
        player.resume_tracking_after_wake(fake)
        self.assertEqual(fake.resumed_with, (ITEM, STREAM))

    def test_ignores_headers_kodi_appends(self):
        self._remember()
        fake = FakePlayer(playing_file=STREAM + "|User-Agent=Seren")
        player.resume_tracking_after_wake(fake)
        self.assertIsNotNone(fake.resumed_with)

    def test_leaves_other_playback_alone(self):
        self._remember()
        fake = FakePlayer(playing_file="https://elsewhere.example/other.mkv")
        player.resume_tracking_after_wake(fake)
        self.assertIsNone(fake.resumed_with)

    def test_nothing_remembered(self):
        fake = FakePlayer()
        player.resume_tracking_after_wake(fake)
        self.assertIsNone(fake.resumed_with)

    def test_nothing_playing_after_wake(self):
        self._remember()
        fake = FakePlayer(playing=False)
        with mock.patch.object(player, "WAKE_RESUME_WAIT_SECONDS", 1):
            player.resume_tracking_after_wake(fake)
        self.assertIsNone(fake.resumed_with)

    def test_bad_record_is_ignored(self):
        g.HOME_WINDOW.setProperty(player.WAKE_RESUME_PROPERTY, "not json")
        fake = FakePlayer()
        player.resume_tracking_after_wake(fake)
        self.assertIsNone(fake.resumed_with)


if __name__ == "__main__":
    unittest.main()
