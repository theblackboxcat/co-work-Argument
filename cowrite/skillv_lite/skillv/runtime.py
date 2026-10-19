# -*- coding: utf-8 -*-
"""Flag-gated hook. SKILLV_LITE must be exactly '1' or this module is a no-op."""

import os

from skillv.contracts import load, resolve_library_path
from skillv.decide import apply_gate, cascade
from skillv.episodes import episode_from_signals

_CACHE = {}


def enabled():
    return os.environ.get('SKILLV_LITE', '') == '1'


def mode_name():
    name = (os.environ.get('SKILLV_MODE') or 'gate').strip().lower()
    if name not in ('gate', 'cascade'):
        return 'gate'
    return name


def load_active_library():
    path = os.path.abspath(resolve_library_path())
    cached = _CACHE.get(path)
    if cached is not None:
        return cached
    lib = load(path)
    _CACHE[path] = lib
    return lib


def clear_cache():
    _CACHE.clear()


def maybe_apply(info, signals, mode=None, text_len=None, library=None):
    """Return `info` unchanged unless SKILLV_LITE=1.

    Gate mode only sets speak to False. Cascade mode writes the contract
    speak bit. Neither path edits prompt text.
    """
    if not enabled():
        return info
    if not isinstance(info, dict):
        return info
    lib = library if library is not None else load_active_library()
    episode = episode_from_signals(signals, mode=mode, text_len=text_len)
    decision = cascade(lib, episode)
    out = dict(info)
    out['skillv'] = {
        'enabled': True,
        'mode': mode_name(),
        'library_version': lib.get('library_version'),
        'abstain': decision['abstain'],
        'selected': decision['selected'],
        'version': decision['version'],
        'contract_speak': decision['speak'],
        'dropped': decision['dropped'],
        'uncertain': decision['uncertain'],
        'why': decision['why'],
    }
    chosen = mode_name()
    if decision['abstain']:
        return out
    if chosen == 'cascade':
        out['speak'] = bool(decision['speak'])
        return out
    gated = apply_gate(out.get('speak'), decision)
    if gated is False:
        out['speak'] = False
    return out
