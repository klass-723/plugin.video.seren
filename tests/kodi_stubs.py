"""
Minimal stand-ins for the Kodi modules and Seren's globals, so indexer code can be imported and run outside Kodi.
Import this before anything from resources.lib.
"""
import sys
import types
from unittest import mock


class FakeGlobals:
    ADDON_NAME = "Seren"
    ADDON_ID = "plugin.video.seren"
    BASE_URL = "plugin://plugin.video.seren/"
    USER_AGENT = "Seren/test"
    VERSION = "0.0.0"

    def __init__(self):
        self.settings = {}
        self.runtime_settings = {}
        self.logs = []

    def reset(self, **settings):
        self.settings = dict(settings)
        self.runtime_settings = {}
        self.logs = []

    # settings
    def get_setting(self, setting_id, default_value=None):
        return self.settings.get(setting_id, default_value)

    def get_bool_setting(self, setting_id, default_value=None):
        value = self.settings.get(setting_id, default_value)
        return value is True or str(value).lower() == "true"

    def get_int_setting(self, setting_id, default_value=None):
        try:
            return int(self.settings.get(setting_id, default_value) or 0)
        except ValueError:
            return 0

    def get_float_setting(self, setting_id, default_value=None):
        try:
            return float(self.settings.get(setting_id, default_value) or 0)
        except ValueError:
            return 0.0

    def set_setting(self, setting_id, value):
        self.settings[setting_id] = value

    def clear_setting(self, setting_id):
        self.settings[setting_id] = ""

    # runtime settings, used by GlobalLock
    def get_runtime_setting(self, setting_id, default_value=None):
        return self.runtime_settings.get(setting_id, default_value)

    def get_bool_runtime_setting(self, setting_id, default_value=None):
        return bool(self.runtime_settings.get(setting_id, default_value))

    def set_runtime_setting(self, setting_id, value):
        self.runtime_settings[setting_id] = value

    def clear_runtime_setting(self, setting_id):
        self.runtime_settings.pop(setting_id, None)

    def abort_requested(self):
        return False

    def wait_for_abort(self, timeout=0):
        return False

    # misc
    def log(self, msg, level="info"):
        self.logs.append((level, str(msg)))

    def logs_at(self, level):
        return [msg for lvl, msg in self.logs if lvl == level]

    def get_language_string(self, string_id):
        return f"#{string_id} {{}}"

    def get_language_code(self, region=False):
        return "en-US" if region else "en"

    def color_string(self, text):
        return text

    def validate_date(self, value):
        return value

    def cancel_directory(self):
        pass

    def log_stacktrace(self):
        pass


g = FakeGlobals()


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class FakeDialogProgress:
    def create(self, *args):
        self.message = args

    def update(self, *args):
        pass

    def iscanceled(self):
        return False

    def close(self):
        pass


dialog = mock.MagicMock(name="xbmcgui.Dialog()")

_module(
    "xbmc",
    LOGDEBUG=0,
    LOGINFO=1,
    LOGWARNING=2,
    LOGERROR=3,
    sleep=lambda ms: None,
    executebuiltin=mock.MagicMock(name="executebuiltin"),
    Player=mock.MagicMock(name="Player"),
    getCondVisibility=lambda *a: False,
    getInfoLabel=lambda *a: "",
    log=lambda *a, **k: None,
)
_module(
    "xbmcgui",
    Dialog=lambda: dialog,
    DialogProgress=FakeDialogProgress,
    DialogProgressBG=mock.MagicMock,
    Window=mock.MagicMock,
)
_module("xbmcvfs", translatePath=lambda p: p, exists=lambda p: False, mkdirs=lambda p: True)
_module("xbmcaddon", Addon=mock.MagicMock)
_module("xbmcplugin")

# Seren's globals and on-disk cache need a running Kodi; replace them
_module("resources.lib.modules.globals", g=g)


def _use_cache(cache_hours=12):
    def decorator(func):
        return func

    return decorator


_module("resources.lib.database.cache", use_cache=_use_cache)
