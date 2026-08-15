# teamplay.py
#
# One plugin that owns every automatic team decision: evening out the teams,
# pushing idle spectators to play, and balancing on skill ratings.
#
# It replaces autospec.py and mybalance.py. Those two carried the *same*
# team-evening algorithm and both ran it from a background thread that slept
# until just before the round start (mybalance at countdown - 0.8s, autospec at
# countdown - 0.3s), then mutated teams from a @minqlx.next_frame callback. Each
# read self.teams() while the other's mutations were still queued, so they
# regularly acted on stale rosters and fought each other. An earlier forcejoin
# plugin tried to work around that by scheduling itself even earlier, which is a
# timing hack rather than a fix.
#
# Here this plugin is the only thing touching teams, so it does not have to race
# anybody. Each round is handled in two phases:
#
#   Phase 1, when the countdown starts:
#     - say who is about to be benched, if the teams are uneven
#     - even teams  -> clear every flag, all is forgiven
#     - uneven teams -> ONE line covering the whole round, e.g. "Klesk will be
#       specced, VOX will be kicked NOW unless they join, Bob will be kicked
#       next round unless they join". A round can hold both spectator groups at
#       once, and they are worded differently on purpose: a first sighting is a
#       warning with a round to run, an earlier flag means it happens at the end
#       of this countdown
#     - anyone still inside their connect grace is named too, so being left
#       alone reads as deliberate rather than as the plugin missing them
#     - apply any skill balancing noticed during the previous round
#
#   Phase 2, one second before the round starts:
#     - kick spectators that were warned in an EARLIER round and are still
#       watching (they are treated as AFK)
#     - even the teams by benching the player who joined last on the bigger team
#
# Nothing is ever moved earlier than one second before a round starts, match
# start included: the countdown is the window in which people join, and taking
# it away is how you end up benching somebody the roster was about to fix.
#
# Lopsided skill is spotted the moment the roster changes and announced right
# away ("unfair teams noticed"), but the switching itself waits for the next
# countdown: moving somebody mid round is the sudden change people object to.
#
# During a match the ratings alone are not enough to justify moving anyone. The
# scoreline has to agree: the game must be genuinely one sided (gap above
# qlx_teamplay_score_gap) AND the team the ratings favour must be the one
# winning. If the underdog is ahead, the ratings are wrong about this game and a
# swap would hand the stronger player to the side already winning. Match start
# is exempt -- at 0-0 there is no scoreline, and that is the cheapest moment to
# balance.
#
# Both the kick and the bench wait until the end of the countdown on purpose: a
# warned spectator has the whole countdown to save themselves. If they join, the
# teams are even by phase 2, so nobody is kicked and nobody is benched. Joining
# also clears the flag immediately -- otherwise two spectators joining together
# would make the teams uneven again and both would be kicked for doing exactly
# what was asked.
#
# A player this plugin autospec'd is off the hook for that round only -- they
# did not choose to watch. From the next round they are an ordinary spectator,
# so if the teams go uneven again they get asked like anybody else. If the teams
# only just became uneven (someone joined seconds before the round) nobody is
# warned or kicked, they are only evened out.
#
# Bots are treated exactly like players: a bot idling in spectator holds a slot
# the same way an AFK human does.
#
# round_start runs an evening-only pass, for players who joined in the last
# second. It never warns and never kicks.
#
# Uses:
# - set qlx_teamplay_min_players "2"     below this many players, do nothing
#                                        (the old autospec used 2; at 4 a 2v1 was
#                                        silently ignored)
# - set qlx_teamplay_settle "5"          imbalance younger than this: no warn/kick
# - set qlx_teamplay_connect_grace "60"  freshly connected specs are not warned
# - set qlx_teamplay_kick "1"            "0" warns but never kicks
# - set qlx_teamplay_balance "1"         skill balancing on/off
# - set qlx_teamplay_score_gap "3"       mid-match: only balance once one team
#                                        is more than this many rounds ahead

import minqlx
import time

VERSION = "v1.0"

SUPPORTED_GAMETYPES = ("ca", "ft", "tdm", "ctf", "dom", "ad")

# Benching happens this many seconds before the round starts, so anyone who
# joins during the countdown evens the teams themselves and nobody sits out.
BENCH_LEAD_SECONDS = 1.0


class teamplay(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_teamplay_min_players", "2")
        self.set_cvar_once("qlx_teamplay_settle", "5")
        self.set_cvar_once("qlx_teamplay_connect_grace", "60")
        self.set_cvar_once("qlx_teamplay_kick", "1")
        self.set_cvar_once("qlx_teamplay_balance", "1")
        self.set_cvar_once("qlx_teamplay_score_gap", "3")

        # steam_id -> the round they were first asked to join in. Kicking
        # compares it against the current round, so nobody is kicked in the same
        # round they were warned.
        self.warned = {}
        # steam_id -> the round this plugin moved them to spectator. They stay
        # exempt from warnings and kicks for as long as they sit there, and the
        # record is dropped the moment they rejoin, disconnect, or are found on
        # a team again.
        self.benched = {}
        # steam_id -> when they last entered red or blue
        self.team_join_times = {}
        # steam_id -> when they connected
        self.connect_times = {}
        # when the teams became uneven, or None while they are even
        self.uneven_since = None
        # True between round_start and round_end, used to drop late rating
        # callbacks instead of switching players mid round
        self.round_live = False
        # bumped every round so a stale rating callback can identify itself
        self.balance_token = 0
        # bumped every round so a delayed bench from a previous round is dropped
        self.round_token = 0
        # set when lopsided teams are spotted mid round; acted on at the next
        # countdown so the switch is never sudden
        self.balance_pending = False
        # True when this round's countdown named somebody to be moved, so the
        # server can say if the teams sorted themselves out instead
        self.announced_move = False
        # last balance verdict announced, so the same line is not repeated every
        # round: "fair", "unfair", "uneven" or "balancing"
        self.balance_state = None

        self.adopt_connected_players()

        self.add_hook("game_countdown", self.handle_game_countdown)
        self.add_hook("round_countdown", self.handle_round_countdown)
        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("round_end", self.handle_round_end)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("map", self.handle_map)

    def adopt_connected_players(self):
        """Treat everyone already here as having just arrived.

        On a reload mid-match this dict starts empty, and an empty connect time
        reads as "connected long ago", so every spectator would be warnable in
        the very next round with none of the grace they are promised. Giving
        them the benefit of the doubt costs one minute and cannot punish
        anybody for our restart.
        """
        now = time.time()
        try:
            players = self.players()
        except Exception:
            return
        for player in players or []:
            sid = getattr(player, "steam_id", 0)
            if not sid:
                continue
            self.connect_times[sid] = now
            if getattr(player, "team", "spectator") in ("red", "blue", "free"):
                self.team_join_times[sid] = now

    # ------------------------------------------------------------------ hooks

    def handle_player_connect(self, player):
        if player is None:
            return
        self.connect_times[player.steam_id] = time.time()

    def handle_player_disconnect(self, player, reason):
        if player is None:
            return
        sid = player.steam_id
        self.warned.pop(sid, None)
        self.benched.pop(sid, None)
        self.team_join_times.pop(sid, None)
        self.connect_times.pop(sid, None)
        self.refresh_uneven_state()

    def handle_team_switch(self, player, old, new):
        # The dispatcher hands us None for clients it cannot resolve yet, which
        # happens while bots are being spawned.
        if player is None:
            return
        sid = player.steam_id
        if new in ("red", "blue", "free"):
            # They acted on the warning, or came back after being benched.
            self.team_join_times[sid] = time.time()
            self.warned.pop(sid, None)
            self.benched.pop(sid, None)
        self.refresh_uneven_state()
        self.notice_unfair_teams()

    def handle_game_countdown(self):
        # A match is about to start. Skill balancing happens now, but nobody is
        # moved to spectator yet: this fires a good twenty seconds before the
        # first round, and benching here would burn the whole window in which
        # people are still joining. An uneven roster is dealt with by the round
        # countdown like any other round, one second before it starts.
        self.reset_state()
        self.review_balance_next_frame()

    def handle_round_countdown(self, round_number):
        self.round_live = False
        self.round_token += 1
        # Cleared here rather than only where it is consumed: phase 1 can return
        # early (level teams, too few players) and phase 2 can be skipped
        # entirely, and a leftover True announces "teams evened out" in a later
        # round where nothing was ever announced.
        self.announced_move = False

        # Warn straight away, so the spectators have the whole countdown to act,
        # and do any pending balancing now rather than at the last second.
        self.review_spectators_next_frame()
        self.review_balance_next_frame()

        # Kick and bench only at the very end of the countdown. Anyone who joins
        # in the meantime saves themselves and evens the teams, so neither
        # happens at all.
        self.enforce_at_end_of_countdown(self.round_token)

    def handle_round_start(self, round_number):
        # Safety net for anyone who joined in the last second. Evening only:
        # they had no chance to read a warning, so nobody is flagged or kicked.
        self.even_and_balance_next_frame(False)
        self.round_live = True

    def handle_round_end(self, data):
        self.round_live = False

    def handle_game_end(self, data):
        self.reset_state()

    def handle_map(self, mapname, factory):
        self.reset_state()

    # ------------------------------------------------------------------ state

    def reset_state(self):
        self.warned.clear()
        self.benched.clear()
        self.uneven_since = None
        self.round_live = False
        self.balance_pending = False
        self.balance_state = None

    @minqlx.next_frame
    def refresh_uneven_state(self):
        """Track when the teams became uneven.

        Runs a frame later because team_switch fires while the switch is still
        settling, so self.teams() would otherwise report the old roster.
        """
        self.update_uneven_since()

    def update_uneven_since(self):
        teams = self.teams()
        if len(teams["red"]) == len(teams["blue"]):
            self.uneven_since = None
        elif self.uneven_since is None:
            self.uneven_since = time.time()

    def is_benched_this_round(self, steam_id):
        """True only for the round we sat this player down in.

        They are not warned or kicked for that round -- they did not choose to
        watch. From the next round they are an ordinary spectator again, and if
        the teams go uneven they get asked like everybody else.
        """
        return self.benched.get(steam_id, -1) >= self.round_token

    def prune_benched(self, spectators):
        """Forget anyone we benched who is not sitting in spectator any more.

        Leaving them recorded would keep somebody exempt from warnings long
        after they had rejoined a team.
        """
        watching = set()
        for player in spectators:
            sid = getattr(player, "steam_id", 0)
            if sid:
                watching.add(sid)
        for sid in list(self.benched):
            if sid not in watching:
                del self.benched[sid]

    def is_fresh_imbalance(self):
        """True when the situation changed too recently for anyone to react."""
        if self.uneven_since is None:
            # The teams are level. Whatever the shortfall is, it is not a fresh
            # imbalance somebody needs a moment to react to.
            return False
        return (time.time() - self.uneven_since) < self.get_cvar("qlx_teamplay_settle", int)

    # ------------------------------------------------------------- enforcement

    def is_actionable(self):
        # "countdown" covers the pre-match countdown, where teams still need
        # evening but no round has been played yet.
        if not self.game or self.game.state not in ("in_progress", "countdown"):
            return False
        return self.game.type_short in SUPPORTED_GAMETYPES

    def countdown_seconds(self):
        # Read from a worker thread, where the game can have ended in between
        # and an AttributeError would vanish into the log.
        if not self.game:
            return 10.0
        cvar = "g_freezeRoundDelay" if self.game.type_short == "ft" else "g_roundWarmupDelay"
        try:
            return int(self.get_cvar(cvar)) / 1000.0
        except (TypeError, ValueError):
            return 10.0

    # Phase one, at the start of the countdown: kick whoever ignored last
    # round's warning, and warn whoever is watching now.

    @minqlx.next_frame
    def review_spectators_next_frame(self):
        self.review_spectators()

    def review_spectators(self):
        if not self.is_actionable():
            return

        teams = self.teams()
        red, blue = teams["red"], teams["blue"]
        spectators = list(teams["spectator"])

        self.prune_benched(spectators)

        if len(red) + len(blue) < self.get_cvar("qlx_teamplay_min_players", int):
            return

        if len(red) == len(blue):
            # A round starting with level teams forgives everyone, autospec or
            # no autospec. Nothing is being asked of anyone, so nothing is owed.
            self.warned.clear()
            return

        plan = self.plan_even_teams(red, blue)
        self.announced_move = bool(plan)

        if self.is_fresh_imbalance():
            # Too recent for anyone to have reacted. Somebody is still being
            # moved, so say that much, but ask nothing of anyone.
            self.announce_round_actions(plan, [])
            return

        eligible = self.actionable_spectators(spectators)

        # Two different groups, and a round can hold both at once: people
        # flagged in an earlier round are out of road and get kicked at the end
        # of this countdown, while people seen for the first time are only being
        # warned and have a whole round in hand.
        due = [p for p in eligible if self.kick_is_due(p.steam_id)]
        newly = [p for p in eligible if p.steam_id not in self.warned]

        for player in due:
            player.center_print("^1Last chance!^7\nJoin now or be kicked")

        for player in newly:
            self.warned[player.steam_id] = self.round_token
            player.tell("^3The teams need players and you are spectating.^7 Join for the "
                        "next round, or you will be kicked to free the slot.")
            player.center_print("^3Teams need you!^7\nJoin the next round or be kicked")

        # One line for the whole round: who sits down, who is about to go, and
        # who is merely on notice.
        self.announce_round_actions(plan, newly, due)

        self.announce_connect_grace(spectators)

    # Phase two, one second before the round starts: kick whoever ignored an
    # earlier round's warning, then even the teams out. Anyone who joined during
    # the countdown has already fixed the imbalance and is safe, which is why
    # this is deliberately the last thing that happens.

    @minqlx.thread
    def enforce_at_end_of_countdown(self, token):
        delay = max(self.countdown_seconds() - BENCH_LEAD_SECONDS, 0)
        time.sleep(delay)
        self.even_and_balance_next_frame(False, token, kick=True)

    @minqlx.next_frame
    def even_and_balance_next_frame(self, balance, token=None, kick=False):
        # Applied in a frame of its own so the countdown text and sound are not
        # interrupted, and so every decision lands together.
        if token is not None and token != self.round_token:
            return  # a new round already started; this pass is stale
        self.even_and_balance(balance, kick)

    def even_and_balance(self, balance, kick=False):
        if not self.is_actionable():
            return

        teams = self.teams()
        red = list(teams["red"])
        blue = list(teams["blue"])
        spectators = list(teams["spectator"])

        self.prune_benched(spectators)

        if len(red) + len(blue) < self.get_cvar("qlx_teamplay_min_players", int):
            return

        # Kick only while the teams are still short: if somebody joined during
        # the countdown the server no longer needs anyone, so nobody is kicked.
        if kick and len(red) != len(blue) and not self.is_fresh_imbalance():
            self.kick_warned(spectators)
            teams = self.teams()
            red = list(teams["red"])
            blue = list(teams["blue"])

        # Worked out here, immediately before acting, never carried over from
        # the announcement at the start of the countdown. Anyone could have
        # joined or left in between, and the roster we move on has to be the
        # one in front of us.
        plan = self.plan_even_teams(red, blue)

        if not plan and self.announced_move:
            # We named somebody at the start of the countdown and the teams
            # sorted themselves out since. Say so, or the announcement just
            # hangs there unexplained.
            self.msg("^3Teams evened out^7: nobody has to sit out after all.")

        self.announced_move = False

        # The player who joined last on the bigger team is the one who made the
        # teams uneven, so they are the one who sits out.
        self.even_teams(plan)

        if balance:
            self.balance_by_rating()

    def plan_even_teams(self, red, blue):
        """Work out who has to move, without moving anybody yet.

        Returns [(player, destination, origin), ...]. Computed from local copies
        of the rosters rather than re-reading self.teams() in a loop, which is
        what made the old plugins act on stale state. Announcing and applying
        both go through this, so the server can never say one name and then move
        a different player.
        """
        red = list(red)
        blue = list(blue)
        plan = []

        # Can never need more passes than there are players.
        for _ in range(len(red) + len(blue) + 1):
            diff = len(red) - len(blue)
            if diff == 0:
                break

            bigger, smaller = (red, blue) if diff > 0 else (blue, red)
            smaller_name = "blue" if diff > 0 else "red"
            bigger_name = "red" if diff > 0 else "blue"

            player = self.last_joiner(bigger)
            if not player:
                break

            bigger.remove(player)

            if abs(diff) % 2 == 0:
                # An even gap can be closed by moving somebody across, so
                # nobody has to sit out.
                smaller.append(player)
                plan.append((player, smaller_name, bigger_name))
            else:
                # An odd gap means somebody has to sit out. That is the player
                # who joined last, and we owe them no warning for it.
                plan.append((player, "spectator", bigger_name))

        return plan

    def names(self, players):
        return "^7, ^3".join(p.clean_name for p in players)

    def kick_is_due(self, steam_id):
        """True for someone flagged in an EARLIER round than this one.

        Being warned and kicked inside the same countdown would give them ten
        seconds, not the round the warning promises.
        """
        warned_in = self.warned.get(steam_id)
        return warned_in is not None and warned_in < self.round_token

    def announce_round_actions(self, plan, warned, due=()):
        """One line covering everything this round is about to do.

        e.g. "Klesk will be specced, VOX AC10 will be kicked NOW unless they
        join, Bob will be kicked next round unless they join". Separate lines
        read like unrelated events; together they read as one decision, which is
        what it is. The two spectator groups are worded differently on purpose:
        one is a warning with a round to run, the other is about to happen.
        """
        parts = []
        for player, destination, _origin in plan:
            if destination == "spectator":
                parts.append("^3{}^7 will be specced".format(player.clean_name))
            else:
                parts.append("^3{}^7 will be moved to {}".format(player.clean_name, destination))

        if due:
            parts.append("^1{}^7 will be kicked NOW unless they join".format(self.names(due)))

        if warned:
            parts.append("^3{}^7 will be kicked next round unless they join"
                         .format(self.names(warned)))

        if parts:
            self.msg(", ".join(parts))

    def announce_connect_grace(self, spectators):
        """Say when somebody is being left alone because they just arrived.

        Otherwise a spectator sitting through an uneven round with no warning
        looks like the plugin missing them, rather than deliberately giving
        them a moment to load in and pick a team.
        """
        grace = self.get_cvar("qlx_teamplay_connect_grace", int)
        now = time.time()

        waiting = []
        for player in spectators:
            sid = getattr(player, "steam_id", 0)
            if not sid or self.is_benched_this_round(sid):
                continue
            connected_for = now - self.connect_times.get(sid, 0)
            if connected_for < grace:
                waiting.append((player, int(grace - connected_for)))

        if not waiting:
            return

        listed = "^7, ^3".join("{} ({}s)".format(p.clean_name, left) for p, left in waiting)
        self.msg("^3{}^7 just connected, they get a moment before being asked to join"
                 .format(listed))

    def even_teams(self, plan):
        """Apply a plan produced by plan_even_teams, saying what it did."""
        for player, destination, origin in plan:
            if destination == "spectator":
                self.benched[player.steam_id] = self.round_token
                self.warned.pop(player.steam_id, None)
                player.put("spectator")
                self.msg("^6Uneven teams^7: {} joined last and was moved to spectator"
                         .format(player.name))
            else:
                player.put(destination)
                self.msg("^6Uneven teams^7: moved {} from {} to {}"
                         .format(player.name, origin, destination))

    def last_joiner(self, team):
        """The player on this team who most recently joined it."""
        if not team:
            return None
        return max(team, key=lambda p: self.team_join_times.get(
            p.steam_id, self.connect_times.get(p.steam_id, 0)))

    def kick_warned(self, spectators):
        for player in spectators:
            sid = getattr(player, "steam_id", 0)
            if not sid or self.is_benched_this_round(sid):
                continue

            if not self.kick_is_due(sid):
                continue

            if not self.get_cvar("qlx_teamplay_kick", bool):
                # Dry run: keep the flag, otherwise they would be re-warned and
                # re-announced every couple of rounds forever.
                self.msg("^3{}^7 would be kicked: spectating AFK while the teams needed "
                         "players (kicking is off).".format(player.clean_name))
                continue

            self.warned.pop(sid, None)
            self.msg("^3{}^7 has been kicked: spectating AFK while the teams needed players."
                     .format(player.clean_name))
            self.kick(player, "Spectating AFK while the teams needed players. Rejoin and play!")

    def actionable_spectators(self, spectators):
        """Spectators we are willing to warn.

        Someone we benched this very round is not at fault, and someone who just
        connected gets a round to settle in first. Bots are fair game: a bot
        idling in spec holds a slot exactly the way an AFK player does.
        """
        now = time.time()
        grace = self.get_cvar("qlx_teamplay_connect_grace", int)

        targets = []
        for player in spectators:
            sid = getattr(player, "steam_id", 0)
            if not sid or self.is_benched_this_round(sid):
                continue
            if now - self.connect_times.get(sid, 0) < grace:
                continue
            targets.append(player)
        return targets

    # --------------------------------------------------------------- balancing

    def balance_plugin(self):
        if not self.get_cvar("qlx_teamplay_balance", bool):
            return None
        return minqlx.Plugin._loaded_plugins.get("balance")

    def rating_request(self, balance, callback):
        """Ask the balance plugin for the ratings of everyone playing.

        We never call balance.callback_balance: it evens team sizes itself
        (which is our job) and announces "Teams are good!" on every no-op. We
        only borrow its ratings cache and its switch suggestion. Ratings are
        cached after the first lookup, so this normally calls back immediately.
        """
        teams = self.teams()
        players = teams["red"] + teams["blue"]
        if len(players) < self.get_cvar("qlx_teamplay_min_players", int):
            return False

        request = dict((p.steam_id, self.game.type_short) for p in players)
        balance.add_request(request, callback, minqlx.CONSOLE_CHANNEL)
        return True

    @minqlx.next_frame
    def notice_unfair_teams(self):
        """Spot lopsided teams as soon as the roster changes, and say so.

        The balancing itself waits for the next countdown -- switching someone
        mid round is exactly the kind of sudden change people complain about --
        but the announcement goes out immediately so nobody is left wondering.
        """
        if self.balance_pending or not self.is_actionable():
            return

        balance = self.balance_plugin()
        if not balance:
            return
        self.rating_request(balance, lambda _players, _channel: self.flag_unfair_teams())

    def flag_unfair_teams(self):
        if self.balance_pending or not self.is_actionable():
            return

        if not self.rating_gap_worth_fixing():
            return
        if not self.scoreline_agrees():
            # Predicted lopsided, but the game itself is still close.
            return

        self.balance_pending = True
        self.say_balance_state(
            "unfair",
            "^3Unfair teams noticed^7: we will autobalance at the start of the next round.")

    def rating_gap_verdict(self):
        """Whether a swap is worth making: "fixable", "fair" or "unknown".

        The three have to stay distinct. Collapsing them into a bool made the
        server announce "Teams are fair" when it had simply been unable to
        look -- once with a 320 point gap on screen, which reads as the plugin
        being broken or lying.

        "unknown" covers uneven teams, which cannot be compared across a swap,
        and players whose ratings are not cached yet. Both are temporary, and
        neither is a statement about the teams.
        """
        balance = self.balance_plugin()
        if not balance:
            return "unknown"

        teams = self.teams()
        if len(teams["red"]) != len(teams["blue"]):
            # The roster can change between asking for ratings and being
            # answered, so this is checked here and not only by the caller.
            return "unknown"

        # Owned by balance.py, so it can be absent if that plugin has not
        # initialised yet. get_cvar would raise on None rather than return it,
        # and this runs inside a ratings callback where a raise is invisible.
        try:
            threshold = self.get_cvar("qlx_balanceMinimumSuggestionDiff", int)
        except (TypeError, ValueError):
            threshold = 0
        if threshold is None:
            threshold = 0
        try:
            switch = balance.suggest_switch(teams, self.game.type_short)
        except KeyError:
            return "unknown"  # somebody has no rating cached yet

        if switch and switch[1] >= threshold:
            return "fixable"
        return "fair"

    def rating_gap_worth_fixing(self):
        return self.rating_gap_verdict() == "fixable"

    def scoreline_verdict(self):
        """(should we balance, why not) based on what the game itself shows.

        Ratings are a guess about a game; the score is what actually happened.
        Two things have to hold before we disturb a match in progress:

          - the game has to be genuinely one sided (score gap above
            qlx_teamplay_score_gap), not merely predicted to be
          - the team the ratings favour has to be the one winning. If the
            underdog is ahead, the ratings are wrong about this game, and
            "fixing" the teams would hand the stronger player to the side
            already winning.

        Match start bypasses this entirely: at 0-0 there is no scoreline to
        agree with, and that is the cheapest moment to balance anyway.
        """
        gap_needed = self.get_cvar("qlx_teamplay_score_gap", int)
        red_score = self.game.red_score
        blue_score = self.game.blue_score
        score = "{}-{}".format(red_score, blue_score)

        if abs(red_score - blue_score) <= gap_needed:
            return False, "the game is close ({})".format(score)

        ratings = self.team_ratings()
        if not ratings:
            return False, None  # cannot tell who is favoured; say nothing
        red_rating, blue_rating = ratings
        if red_rating == blue_rating:
            return False, None

        if (red_rating > blue_rating) == (red_score > blue_score):
            return True, None

        return False, ("the underdog is ahead ({}), so the ratings are wrong "
                       "about this game".format(score))

    def scoreline_agrees(self):
        return self.scoreline_verdict()[0]

    @minqlx.next_frame
    def review_balance_next_frame(self):
        self.review_balance()

    def review_balance(self):
        """Say, every round, what is happening about skill balance.

        Three outcomes, all of them spoken out loud so nobody has to guess why
        the teams did or did not change:

          - teams uneven      -> cannot balance, skipped (the shortfall is
                                 dealt with separately; swapping people around
                                 an uneven roster just moves the problem)
          - balance pending   -> do it now, at the start of the countdown, so
                                 it is never a sudden mid-round switch
          - nothing pending   -> check, and either promise a balance for next
                                 round or state that the teams are fair

        Repeats of the same verdict are suppressed: it is reported when it
        changes, not every thirty seconds.
        """
        if not self.is_actionable():
            return
        balance = self.balance_plugin()
        if not balance:
            return

        teams = self.teams()
        red, blue = teams["red"], teams["blue"]

        if len(red) + len(blue) < self.get_cvar("qlx_teamplay_min_players", int):
            return

        if len(red) != len(blue):
            # Uneven teams cannot be balanced -- somebody is about to be moved,
            # which would invalidate any swap we picked now.
            self.say_balance_state("uneven", "^3Skill balance skipped^7: teams are uneven.")
            return

        if self.balance_pending:
            self.balance_pending = False
            self.balance_state = "balancing"
            self.balance_by_rating()
            return

        # Nothing promised yet: look now, and say what we found either way.
        self.rating_request(balance, lambda _players, _channel: self.report_fairness())

    def report_fairness(self):
        if not self.is_actionable():
            return

        verdict = self.rating_gap_verdict()
        if verdict == "unknown":
            # Could not evaluate -- uneven teams, or ratings not cached yet.
            # Say nothing rather than reassure people about something we did
            # not actually check.
            return

        detail = self.rating_text()
        if verdict == "fixable":
            agrees, why_not = self.scoreline_verdict()
            if not agrees:
                # Ratings say lopsided, the game itself does not back it up.
                if why_not:
                    self.say_balance_state("held", self.with_detail(
                        "^3Teams look uneven on paper^7", detail,
                        "but {}, leaving it alone.".format(why_not)))
                return
            self.balance_pending = True
            self.say_balance_state("unfair", self.with_detail(
                "^3Unfair teams noticed^7", detail,
                "we will autobalance at the start of the next round."))
        else:
            self.say_balance_state("fair", self.with_detail(
                "^3Teams are fair^7", detail, "no balance needed."))

    def with_detail(self, headline, detail, tail):
        if detail:
            return "{}: {}, {}".format(headline, detail, tail)
        return "{}: {}".format(headline, tail)

    def team_ratings(self):
        """(red average, blue average) rounded, or None if ratings are missing."""
        balance = self.balance_plugin()
        if not balance:
            return None
        teams = self.teams()
        try:
            red = balance.team_average(teams["red"], self.game.type_short)
            blue = balance.team_average(teams["blue"], self.game.type_short)
        except KeyError:
            return None  # somebody has no rating cached yet
        return int(round(red)), int(round(blue))

    def rating_text(self):
        """e.g. "1583 vs 1550 (diff 33)", or "" when ratings are unavailable."""
        ratings = self.team_ratings()
        if not ratings:
            return ""
        red, blue = ratings
        return "^1{} ^7vs ^4{}^7 (diff {})".format(red, blue, abs(red - blue))

    def say_balance_state(self, state, message):
        """Announce a verdict, but only when it is not the one already standing."""
        if self.balance_state == state:
            return
        self.balance_state = state
        self.msg(message)

    def balance_by_rating(self):
        balance = self.balance_plugin()
        if not balance:
            return

        self.balance_token += 1
        token = self.balance_token
        self.rating_request(balance, lambda _players, _channel: self.apply_rating_switches(token))

    def apply_rating_switches(self, token):
        """Swap players between teams until the rating gap stops shrinking."""
        if token != self.balance_token:
            return  # a newer round already asked for this
        if not self.is_actionable():
            # The ratings lookup is asynchronous, so it can land after the match
            # has ended. Never move anyone around during warmup.
            return
        if self.round_live:
            # The ratings lookup outlived the countdown. Switching now would
            # move players mid round, which is exactly what got the previous
            # attempt at per-round balancing reverted.
            return

        balance = minqlx.Plugin._loaded_plugins.get("balance")
        if not balance:
            return

        teams = self.teams()
        if len(teams["red"]) != len(teams["blue"]):
            # Somebody joined or left between the promise and the swap.
            self.balance_pending = True
            self.say_balance_state(
                "uneven", "^3Skill balance skipped^7: teams went uneven, will retry.")
            return

        before = self.rating_text()
        swapped = []
        try:
            switch = balance.suggest_switch(teams, self.game.type_short)
            while switch:
                red_player, blue_player = switch[0]
                balance.switch(red_player, blue_player)
                swapped.append((red_player, blue_player))
                teams["red"].remove(red_player)
                teams["blue"].remove(blue_player)
                teams["red"].append(blue_player)
                teams["blue"].append(red_player)
                switch = balance.suggest_switch(teams, self.game.type_short)
        except KeyError:
            # A player has no rating cached yet; try again next round.
            self.balance_pending = True
            return

        if not swapped:
            self.say_balance_state("fair", self.with_detail(
                "^3Teams are fair^7", self.rating_text(), "no balance needed."))
            return

        for red_player, blue_player in swapped:
            self.msg("^3Swapped^7 {} ^7and {}".format(red_player.clean_name,
                                                      blue_player.clean_name))

        after = self.rating_text()
        if after:
            self.msg("^3Teams balanced^7: {}{}".format(
                after, " (was {})".format(before) if before else ""))
