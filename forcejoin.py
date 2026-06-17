# forcejoin.py
#
# When a game is in progress and the teams are uneven while spectators are
# present, warn the spectators that they will be kicked unless they join a
# team. After a grace period, re-check the teams: if they are still uneven
# (nobody joined) the remaining spectators are kicked. This prevents idle
# spectators from occupying slots that real players who want to play could use.
#
# The check runs on round_countdown and enforces shortly BEFORE the team-size
# eveners act (mybalance benches a player at countdown - 0.8s, autospec at
# countdown - 0.3s). Enforcing earlier means our re-check sees the real team
# state instead of one those plugins already "fixed" by benching an active
# player -- which is exactly the situation we want to avoid.
#
# The grace period is shared by every spectator (a single timer), giving
# everyone the same window to react before any kick happens.
#
# Uses:
# - qlx_forcejoin_grace "5"   (seconds spectators get to join before a kick)


import minqlx
import time

VERSION = "v0.2"

VAR_GRACE = "qlx_forcejoin_grace"
DEFAULT_GRACE = "5"

# Fire at least this many seconds before the round starts, so we act ahead of
# the team-size eveners (mybalance -0.8s, autospec -0.3s).
LEAD_SECONDS = 1.5


def teams_even(red_count, blue_count):
    """Return True when both teams hold the same number of players."""
    return red_count == blue_count


def joinable_spectators(spectators):
    """Keep only connected spectators we are able to act on (valid steam_id)."""
    return [p for p in spectators if p.steam_id]


def enforcement_delay(grace, countdown_seconds, lead=LEAD_SECONDS):
    """How long to wait before enforcing.

    Keep the full grace, but never later than `lead` seconds before the round
    starts, so we run before the team-size eveners bench an active player.
    """
    return min(grace, max(countdown_seconds - lead, 0))


class forcejoin(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once(VAR_GRACE, DEFAULT_GRACE)

        # True while a grace period is already running, so overlapping rounds
        # do not start a second timer.
        self._pending = False

        self.add_hook("round_countdown", self.handle_round_countdown)
        self.add_hook("unload", self.handle_unload)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._pending = False

    def round_countdown_seconds(self):
        countdown = int(self.get_cvar("g_roundWarmupDelay"))
        if self.game and self.game.type_short == "ft":
            countdown = int(self.get_cvar("g_freezeRoundDelay"))
        return countdown / 1000.0

    def handle_round_countdown(self, round_number):
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
        delay = enforcement_delay(grace, self.round_countdown_seconds())
        self.warn(spectators, delay)
        self.schedule_enforcement(delay)

    def warn(self, spectators, delay):
        names = "^7, ^1".join(p.clean_name for p in spectators)
        self.msg(
            "^3Uneven teams!^7 Spectator(s) ^1{}^7 will be kicked in ^3{}s^7 "
            "unless they join a team.".format(names, int(round(delay)))
        )

    @minqlx.thread
    def schedule_enforcement(self, delay):
        # The whole window is shared: one sleep for everyone, then a single
        # re-check, run before the team-size eveners bench anyone.
        time.sleep(delay)
        self.enforce()

    @minqlx.next_frame
    def enforce(self):
        try:
            if not self.game or self.game.state != "in_progress":
                return

            teams = self.teams()
            # If the teams are even now -- someone joined during the grace --
            # we do nothing.
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
