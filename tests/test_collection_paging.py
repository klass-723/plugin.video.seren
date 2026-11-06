import datetime
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import kodi_stubs  # noqa: E402  must come before resources.lib imports

from resources.lib.database.trakt_sync import movies  # noqa: E402
from resources.lib.database.trakt_sync import shows  # noqa: E402

g = kodi_stubs.g

PAST = "2020-01-01T00:00:00"
FUTURE = "2099-01-01T00:00:00"


def _database(cls, db, hide_unaired=True, hide_watched=False, page_limit=3):
    """
    A sync database object over an in-memory sqlite db, without the real one's setup
    """
    database = object.__new__(cls)
    database.hide_unaired = hide_unaired
    database.hide_watched = hide_watched
    database.page_limit = page_limit

    def fetchall(query):
        return [dict(row) for row in db.execute(query).fetchall()]

    database.fetchall = fetchall
    return database


class CollectionPagingTestBase(unittest.TestCase):
    def setUp(self):
        g.reset(**{"general.paginatecollection": "true", "general.sortcollection": "0"})
        g.datetime_to_string = lambda value: value.strftime("%Y-%m-%dT%H:%M:%S")
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()
        del g.datetime_to_string


class TestCollectedMoviesPaging(CollectionPagingTestBase):
    def setUp(self):
        super().setUp()
        self.db.executescript(
            """
            CREATE TABLE movies (
                trakt_id INTEGER, collected INTEGER, collected_at TEXT, air_date TEXT, watched INTEGER
            );
            CREATE TABLE movies_meta (id INTEGER, value TEXT);
            """
        )
        # newest first: 1 unaired, 2 aired, 3 unaired, 4 aired (watched), 5 aired, 6 no date yet, 7 aired
        rows = [
            (1, FUTURE, 0),
            (2, PAST, 0),
            (3, FUTURE, 0),
            (4, PAST, 1),
            (5, PAST, 0),
            (6, None, 0),
            (7, PAST, 0),
        ]
        for position, (trakt_id, air_date, watched) in enumerate(rows):
            collected_at = (datetime.datetime(2026, 1, 1) - datetime.timedelta(days=position)).isoformat()
            self.db.execute("INSERT INTO movies VALUES (?, 1, ?, ?, ?)", (trakt_id, collected_at, air_date, watched))

    def _page(self, page, **kwargs):
        database = _database(movies.TraktSyncDatabase, self.db, **kwargs)
        return [row["trakt_id"] for row in database.get_collected_movies(page)]

    def test_unaired_movies_are_skipped_before_the_page_is_cut(self):
        self.assertEqual(self._page(1), [2, 4, 5])
        self.assertEqual(self._page(2), [6, 7])

    def test_watched_movies_are_skipped_when_hidden(self):
        self.assertEqual(self._page(1, hide_watched=True), [2, 5, 6])

    def test_nothing_skipped_when_filters_are_off(self):
        self.assertEqual(self._page(1, hide_unaired=False), [1, 2, 3])

    def test_unpaged_collection_is_unfiltered(self):
        g.settings["general.paginatecollection"] = "false"
        self.assertEqual(sorted(self._page(1)), [1, 2, 3, 4, 5, 6, 7])


class TestCollectedShowsPaging(CollectionPagingTestBase):
    def setUp(self):
        super().setUp()
        self.db.executescript(
            """
            CREATE TABLE episodes (trakt_show_id INTEGER, collected INTEGER, collected_at TEXT);
            CREATE TABLE shows (trakt_id INTEGER, air_date TEXT, watched_episodes INTEGER, episode_count INTEGER);
            CREATE TABLE shows_meta (id INTEGER, type TEXT, value TEXT);
            """
        )
        # newest first: 10 unaired, 11 aired, 12 fully watched, 13 aired, 14 aired
        rows = [(10, FUTURE, 0, 8), (11, PAST, 1, 8), (12, PAST, 8, 8), (13, PAST, 0, 8), (14, PAST, 0, 8)]
        for position, (trakt_id, air_date, watched_episodes, episode_count) in enumerate(rows):
            collected_at = (datetime.datetime(2026, 1, 1) - datetime.timedelta(days=position)).isoformat()
            self.db.execute(
                "INSERT INTO shows VALUES (?, ?, ?, ?)", (trakt_id, air_date, watched_episodes, episode_count)
            )
            self.db.execute("INSERT INTO episodes VALUES (?, 1, ?)", (trakt_id, collected_at))

    def _page(self, page, **kwargs):
        database = _database(shows.TraktSyncDatabase, self.db, **kwargs)
        return [row["trakt_id"] for row in database.get_collected_shows(page)]

    def test_unaired_shows_are_skipped_before_the_page_is_cut(self):
        self.assertEqual(self._page(1), [11, 12, 13])
        self.assertEqual(self._page(2), [14])

    def test_watched_shows_are_skipped_when_hidden(self):
        self.assertEqual(self._page(1, hide_watched=True), [11, 13, 14])

    def test_force_all_is_unfiltered(self):
        database = _database(shows.TraktSyncDatabase, self.db)
        self.assertEqual(len(database.get_collected_shows(force_all=True)), 5)


if __name__ == "__main__":
    unittest.main()
