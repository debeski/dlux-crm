"""Store wording written into the DjangoLux translation override layer.

Some store choices change words across the whole UI: machine instead of vehicle
(automotive), EUR instead of USD (pricing currency). Each registers a wording
*axis*: its modes, the mode stored on the settings row, and how a string reads in
a non-default mode. The overrides are the same layer an admin edits in System
Settings, so DjangoLux's own labels and breadcrumbs follow too.

All axes are generated together and written in one place, so changing one axis
never strands or clobbers another's words. A key is treated as ours when its
override is missing or equals what *some* combination of modes generates; any
other override is an admin's own and is never touched.

The wording follows the settings row on every save (``sync_wording`` on
``post_save``) and after migrate, so the setup wizard, imports and upgrades that
add strings all end up with the store's words.
"""
import importlib
import itertools
import threading
from functools import lru_cache

SOURCE_APPS = ("common", "finance", "catalog", "sales", "automotive", "public_catalog")

_AXES = {}
_saving = threading.local()


def register_wording(name, *, modes, default, stored_mode, rewrite, examples=None, skip_prefixes=()):
    """Register a wording axis.

    ``stored_mode(settings) -> mode`` reads the mode from a SystemSettings row;
    ``rewrite(text, lang, mode) -> text`` words a string for a non-default mode;
    ``examples`` is ``{mode: {lang: {key: text}}}`` for strings a word swap cannot
    fix; keys starting with ``skip_prefixes`` keep their source wording.
    """
    _AXES[name] = {
        "modes": tuple(modes),
        "default": default,
        "stored_mode": stored_mode,
        "rewrite": rewrite,
        "examples": examples or {},
        "skip": tuple(skip_prefixes),
    }
    _generate.cache_clear()


@lru_cache(maxsize=1)
def _source_strings():
    merged = {}
    for app in SOURCE_APPS:
        try:
            bundle = importlib.import_module(f"{app}.translations").DLUX_STRINGS
        except (ImportError, AttributeError):
            continue
        for lang, strings in bundle.items():
            merged.setdefault(lang, {}).update(strings)
    return merged


@lru_cache(maxsize=16)
def _generate(combo):
    """``{lang: {key: text}}`` for every string the mode combination rewords."""
    modes = dict(combo)
    generated = {}
    for lang, strings in _source_strings().items():
        for key, source in strings.items():
            if not isinstance(source, str):
                continue
            text = source
            for name in sorted(_AXES):
                axis, mode = _AXES[name], modes.get(name)
                if mode is None or mode == axis["default"] or key.startswith(axis["skip"]):
                    continue
                example = axis["examples"].get(mode, {}).get(lang, {}).get(key)
                text = example or axis["rewrite"](text, lang, mode)
            if text != source:
                generated.setdefault(lang, {})[key] = text
    return generated


def _combo(modes):
    return tuple(sorted(modes.items()))


def wording_overrides(**modes):
    """The overrides a mode combination generates (unnamed axes at their defaults)."""
    return _generate(_combo({name: modes.get(name, axis["default"]) for name, axis in _AXES.items()}))


def apply_wording(settings=None, **modes):
    """Write the wording for ``modes`` (default: the modes stored on ``settings``)."""
    if settings is None:
        from dlux.models import SystemSettings

        settings = SystemSettings.load()
    wanted = {name: modes.get(name) or axis["stored_mode"](settings) for name, axis in _AXES.items()}
    target = _generate(_combo(wanted))
    every = [
        _generate(_combo(dict(zip(_AXES, choice))))
        for choice in itertools.product(*(axis["modes"] for axis in _AXES.values()))
    ]
    current = settings.translations_override if isinstance(settings.translations_override, dict) else {}
    overrides = {lang: dict(values) for lang, values in current.items() if isinstance(values, dict)}
    changed = False
    for lang in {lang for generated in every for lang in generated}:
        bucket = overrides.setdefault(lang, {})
        for key in {key for generated in every for key in generated.get(lang, {})}:
            ours = key not in bucket or any(g.get(lang, {}).get(key) == bucket[key] for g in every)
            if not ours:
                continue
            want = target.get(lang, {}).get(key)
            if want is None and key in bucket:
                del bucket[key]
                changed = True
            elif want is not None and bucket.get(key) != want:
                bucket[key] = want
                changed = True
    if changed:
        settings.translations_override = {lang: values for lang, values in overrides.items() if values}
        # A flag on the instance would be pickled into the settings cache by
        # save() and read back as "mid-sync" by every later load.
        _saving.active = True
        try:
            settings.save(update_fields=["translations_override"])
        finally:
            _saving.active = False
    return changed


def sync_wording(sender, instance, **kwargs):
    """post_save of SystemSettings: match the wording to the modes just saved."""
    if getattr(_saving, "active", False) or not _AXES:
        return
    apply_wording(instance)


def refresh_wording(**kwargs):
    """After migrate: strings an upgrade added get the store's chosen wording."""
    from django.db import DatabaseError

    try:
        apply_wording()
    except DatabaseError:
        pass
