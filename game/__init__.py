"""Papermoon rules and runtime, independent of terminal and editor windows.

Public classes are loaded on demand so importing a leaf rule module does not
initialize the entire engine or introduce cycles between rule packages.
"""

from importlib import import_module

_EXPORTS = {
    "GameManager": ("game.game_manager", "GameManager"),
    "GameLoop": ("game.game_loop", "GameLoop"),
    "GameSession": ("game.game_session", "GameSession"),
    "QueuedDecisionProvider": ("game.queued_decision", "QueuedDecisionProvider"),
    "HolyGrail": ("game.holy_grail", "HolyGrail"),
    "create_basic_game_scenario": ("game.basic_game_scenario", "create_basic_game_scenario"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value
