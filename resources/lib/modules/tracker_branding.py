"""
What Seren calls the service behind its Trakt features.

While a Personal Tracker replaces Trakt, labels say the tracker's name instead of "Trakt" and the Trakt-logo icons
are swapped for plain ones. With Trakt in use nothing changes.
Kept free of Kodi and Seren imports so globals can use it without an import cycle.
"""
import re

DEFAULT_NAME = "Personal Tracker"
MODE_INSTEAD = 1

ENABLED_SETTING = "personal_tracker.enabled"
URL_SETTING = "personal_tracker.url"
MODE_SETTING = "personal_tracker.mode"
NAME_SETTING = "personal_tracker.name"

# Trakt-logo icons and their plain equivalents
ICON_SLUGS = {
    "trakt": "tracker",
    "trakt_sync": "tracker_sync",
    "trakt_reset": "tracker_reset",
    "trakt_rebuild": "tracker_rebuild",
    "list_trakt": "list_tracker",
    "movies_trakt": "movies_tracker",
    "shows_trakt": "shows_tracker",
}

_TRAKT_WORD = re.compile(r"\bTrakt\b")


def replaces_trakt(settings):
    """
    :param settings: anything with Seren's get_setting / get_bool_setting / get_int_setting, normally g
    """
    return (
        bool(settings.get_bool_setting(ENABLED_SETTING))
        and bool((settings.get_setting(URL_SETTING) or "").strip().rstrip("/"))
        and settings.get_int_setting(MODE_SETTING) == MODE_INSTEAD
    )


def display_name(settings):
    return (settings.get_setting(NAME_SETTING) or "").strip() or DEFAULT_NAME


def relabel(text, name, replacing_trakt):
    """
    Puts the user's tracker name into a localized string
    :param name: the tracker's display name
    :param replacing_trakt: True to also swap the word "Trakt" for the name
    """
    if not text:
        return text
    if name != DEFAULT_NAME:
        text = text.replace(DEFAULT_NAME, name)
    if replacing_trakt:
        text = _TRAKT_WORD.sub(name, text)
    return text


def icon_slug(slug, replacing_trakt):
    return ICON_SLUGS.get(slug, slug) if replacing_trakt else slug
