# forcejoin.py
#
# When a game is in progress and the teams are uneven while spectators are
# present, warn the spectators that they will be kicked unless they join a
# team. After a fixed grace period, re-check the teams: if they are still
# uneven (nobody joined and autospec did not even them out) the remaining
# spectators are kicked. This prevents idle spectators from occupying slots
# that real players who want to play could use.
#
# The grace period is shared by every spectator (a single timer), giving
# everyone the same window to react before any auto-kick happens.
#
# Uses:
# - qlx_forcejoin_grace "5"   (seconds spectators get to join before a kick)


import minqlx
import time

VERSION = "v0.1"

VAR_GRACE = "qlx_forcejoin_grace"
DEFAULT_GRACE = "5"


def teams_even(red_count, blue_count):
    """Return True when both teams hold the same number of players."""
    return red_count == blue_count


def joinable_spectators(spectators):
    """Keep only connected spectators we are able to act on (valid steam_id)."""
    return [p for p in spectators if p.steam_id]


class forcejoin(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once(VAR_GRACE, DEFAULT_GRACE)

        # True while a grace period is already running, so overlapping rounds
        # do not start a second timer.
        self._pending = False

        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("unload", self.handle_unload)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._pending = False

    def handle_round_start(self, round_number):
        # Only act once an actual game is running, never during warmup.
        if not self.game or self.game.state != "in_progress":
            return

        if self._pending:
            return

        teams = self.teams()
        if teams_even(len(teams["red"]), len(teams["blue"])):
            return

        spectators = joinable_spectators(teams["spectator"])
        if not spectators:
            return

        self._pending = True
        grace = self.get_cvar(VAR_GRACE, int)
        self.warn(spectators, grace)
        self.schedule_enforcement(grace)

    def warn(self, spectators, grace):
        names = "^7, ^1".join(p.clean_name for p in spectators)
        self.msg(
            "^3Uneven teams!^7 Spectator(s) ^1{}^7 will be kicked in ^3{}s^7 "
            "unless they join a team.".format(names, grace)
        )

    @minqlx.thread
    def schedule_enforcement(self, grace):
        # The whole window is shared: one sleep for everyone, then a single
        # re-check. Always the full grace, never shortened.
        time.sleep(grace)
        self.enforce()

    @minqlx.next_frame
    def enforce(self):
        try:
            if not self.game or self.game.state != "in_progress":
                return

            teams = self.teams()
            # If the teams are even now -- someone joined, or autospec moved a
            # player to spec during the grace -- we do nothing.
            if teams_even(len(teams["red"]), len(teams["blue"])):
                self.msg(
                    "^2Teams are even now^7 -- spectators no longer need to join."
                )
                return

            spectators = joinable_spectators(teams["spectator"])
            if not spectators:
                return

            names = "^7, ^1".join(p.clean_name for p in spectators)
            self.msg(
                "^1Teams still uneven^7 -- kicking idle spectator(s): ^1{}^7.".format(names)
            )
            for p in spectators:
                p.kick(
                    "Join a team to play -- idle spectators are removed "
                    "when teams stay uneven."
                )
        finally:
            self._pending = False
