"""Make phonemizer load the real espeak-ng library instead of a temp copy.

phonemizer copies libespeak-ng into a temporary folder and loads the copy.
On macOS the copy is refused ("library load disallowed by system policy") and
a "Not Opened" warning pops up. Linking the original instead avoids that.

With one shared library, every EspeakFallback shares espeak's global voice, so
each call re-selects its own voice (American vs British) under a lock.
"""

import os
import shutil
import threading
import types


def _link_instead_of_copy(src, dst, *args, **kwargs):
    os.symlink(os.path.realpath(src), dst)
    return dst


def use_original_espeak_library(espeak_module=None) -> None:
    try:
        from phonemizer.backend.espeak import api
    except Exception:
        return
    if getattr(api, "_mlxa_patched", False):
        return
    shim = types.SimpleNamespace(
        copy=_link_instead_of_copy, rmtree=shutil.rmtree
    )
    api.shutil = shim
    api._mlxa_patched = True
    if espeak_module is not None:
        _per_call_voice(espeak_module)


_lock = threading.Lock()


def _per_call_voice(espeak_module) -> None:
    fallback_cls = espeak_module.EspeakFallback
    if getattr(fallback_cls, "_mlxa_patched", False):
        return
    original = fallback_cls.__call__

    def call(self, token):
        with _lock:
            self.backend._espeak.set_voice(
                "en-gb" if self.british else "en-us"
            )
            return original(self, token)

    fallback_cls.__call__ = call
    fallback_cls._mlxa_patched = True
