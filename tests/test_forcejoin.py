"""Unit tests for the pure decision logic of the forcejoin plugin.

minqlx is only available inside the Quake Live server, so we inject a tiny
stub before importing the plugin. These tests cover the pure helpers; the
live behaviour (timing, actual kicks, autospec interaction) is verified on
the server via the manual test plan.

Run with pytest, or standalone:  python3 tests/test_forcejoin.py
"""

import os
import sys
import types

# --- Inject a minimal minqlx stub so `import forcejoin` succeeds ----------
_minqlx = types.ModuleType("minqlx")


class _Plugin:
    def __init__(self, *args, **kwargs):
        pass


def _identity_decorator(func):
    return func


_minqlx.Plugin = _Plugin
_minqlx.thread = _identity_decorator
_minqlx.next_frame = _identity_decorator
sys.modules.setdefault("minqlx", _minqlx)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forcejoin  # noqa: E402


class _FakeSpec:
    def __init__(self, steam_id, clean_name="player"):
        self.steam_id = steam_id
        self.clean_name = clean_name


def test_teams_even_true_when_equal():
    assert forcejoin.teams_even(3, 3) is True
    assert forcejoin.teams_even(0, 0) is True


def test_teams_even_false_when_unequal():
    assert forcejoin.teams_even(2, 1) is False
    assert forcejoin.teams_even(1, 0) is False
    assert forcejoin.teams_even(4, 2) is False


def test_joinable_spectators_keeps_valid_steam_ids():
    specs = [_FakeSpec(76561190000000001), _FakeSpec(76561190000000002)]
    assert forcejoin.joinable_spectators(specs) == specs


def test_joinable_spectators_drops_missing_steam_ids():
    valid = _FakeSpec(76561190000000001)
    specs = [valid, _FakeSpec(None), _FakeSpec(0)]
    assert forcejoin.joinable_spectators(specs) == [valid]


def test_joinable_spectators_empty():
    assert forcejoin.joinable_spectators([]) == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS {}".format(name))
            except AssertionError as exc:
                failures += 1
                print("FAIL {}: {}".format(name, exc))
    print("\n{} test(s) run, {} failure(s)".format(
        sum(1 for n in globals() if n.startswith("test_")), failures))
    sys.exit(1 if failures else 0)
