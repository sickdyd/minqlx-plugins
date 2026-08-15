from minqlx_plugin_test import (setup_plugin, setup_cvars, setup_game_in_progress,
                                connected_players, fake_player, unstub, setup_game_in_warmup,
                                assert_player_was_put_on, assert_plugin_sent_to_console,
                                assert_plugin_center_printed)

import unittest

from mockito import verify, any_
from mockito.matchers import any as any_matcher, arg_that
from minqlx import Plugin

from teamplay import teamplay

from time import time

# Steam64 ids of real accounts start here; anything below is not a person.
HUMAN = 76561197960265728


class TestTeamplay(unittest.TestCase):

    def setUp(self):
        setup_plugin()
        setup_cvars({
            "qlx_teamplay_min_players": "4",
            "qlx_teamplay_settle": "5",
            "qlx_teamplay_connect_grace": "60",
            "qlx_teamplay_kick": "1",
            "qlx_teamplay_balance": "0",
            "qlx_teamplay_score_gap": "3",
            "qlx_balanceMinimumSuggestionDiff": "25",
        })
        setup_game_in_progress()
        connected_players()
        self.plugin = teamplay()

    def tearDown(self):
        unstub()

    # ------------------------------------------------------------- helpers

    def setup_roster(self, red, blue, spectators=()):
        """Put players on teams and give everyone a settled join/connect time."""
        players = list(red) + list(blue) + list(spectators)
        connected_players(*players)

        old = time() - 3600
        for player in players:
            self.plugin.connect_times[player.steam_id] = old
        for player in list(red) + list(blue):
            self.plugin.team_join_times[player.steam_id] = old
        # The imbalance is old news unless a test says otherwise.
        self.plugin.uneven_since = old
        return players

    def warn_in_earlier_round(self, player):
        """Flag a player as warned in a previous round, so a kick is due."""
        self.plugin.warned[player.steam_id] = self.plugin.round_token
        self.plugin.round_token += 1

    def assert_kicked(self, player, times=1):
        verify(Plugin, times=times).kick(player, any_matcher(str))

    # --------------------------------------------------------------- tests

    def test_even_teams_are_left_alone(self):
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        for player in red + blue:
            verify(player, times=0).put(any_matcher(str))

    def test_even_teams_clear_the_warning_flags(self):
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster(red, blue, [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        self.assertNotIn(spectator.steam_id, self.plugin.warned)
        self.assert_kicked(spectator, times=0)

    def test_uneven_teams_bench_the_last_player_to_join(self):
        early = fake_player(HUMAN + 1, "early", "red")
        latest = fake_player(HUMAN + 2, "latest", "red")
        red = [early, fake_player(HUMAN + 6, "r3", "red"), latest]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue)
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        assert_player_was_put_on(latest, "spectator")
        verify(early, times=0).put(any_matcher(str))

    def test_benched_player_is_not_warned_or_kicked(self):
        latest = fake_player(HUMAN + 2, "latest", "red")
        self.setup_roster([fake_player(HUMAN + 1, "early", "red"), fake_player(HUMAN + 6, "r3", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        self.assertIn(latest.steam_id, self.plugin.benched)
        self.assertNotIn(latest.steam_id, self.plugin.warned)
        self.assert_kicked(latest, times=0)

    def test_uneven_teams_warn_spectators_without_kicking_them(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        self.assertIn(spectator.steam_id, self.plugin.warned)
        self.assert_kicked(spectator, times=0)

    def test_warned_spectator_is_kicked_when_teams_are_uneven_again(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(spectator)

    def test_pending_bench_is_announced_to_everyone_before_it_happens(self):
        latest = fake_player(HUMAN + 2, "latest", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 6, "r3", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.review_spectators()

        # Chat only: it is information, not something to act on, so it does not
        # go in the middle of the screen.
        assert_plugin_sent_to_console("^3latest^7 will be specced")
        # Announced only; the move itself is still a countdown away.
        verify(latest, times=0).put(any_matcher(str))

    def test_a_bot_about_to_be_benched_is_announced_too(self):
        # Everyone should be told who is about to sit out, bot or not --
        # otherwise a bench looks arbitrary.
        bot = fake_player(90071996842377216, "Sarge", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 6, "r3", "red"), bot],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.team_join_times[bot.steam_id] = time()

        self.plugin.review_spectators()

        assert_plugin_sent_to_console("^3Sarge^7 will be specced")

    def test_a_move_applied_without_a_prior_announcement_is_reported(self):
        # The round_start safety net moves people who joined in the last
        # second, with no announcement beforehand, so it has to say what it did.
        latest = fake_player(HUMAN + 2, "latest", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 6, "r3", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.even_and_balance(balance=False)

        assert_player_was_put_on(latest, "spectator")
        assert_plugin_sent_to_console(
            "^6Uneven teams^7: latest joined last and was moved to spectator")

    def test_spectator_warned_this_round_is_not_kicked_at_the_end_of_it(self):
        # Warned in phase 1, phase 2 comes ~10s later in the SAME round. They
        # must get a whole round to act, not just the countdown.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.plugin.round_token = 7

        self.plugin.review_spectators()
        self.assertEqual(7, self.plugin.warned[spectator.steam_id])
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(spectator, times=0)
        self.assertIn(spectator.steam_id, self.plugin.warned)

        # Next round, still watching: now the kick is due.
        self.plugin.round_token = 8
        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(spectator)

    def test_rewarning_does_not_push_the_kick_out_of_reach(self):
        # Phase 1 re-warns every uneven round; the stamp must stay at the FIRST
        # round or the kick would never come due.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.plugin.round_token = 3
        self.plugin.review_spectators()

        self.plugin.round_token = 4
        self.plugin.review_spectators()

        self.assertEqual(3, self.plugin.warned[spectator.steam_id])

    def test_spectator_joining_during_the_countdown_prevents_the_bench(self):
        # The whole point of benching only at the end of the countdown: the
        # warned spectator joins, the teams even themselves, nobody sits out.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
               fake_player(HUMAN + 6, "r3", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue, [spectator])

        # Phase 1: 3v2, the spectator is asked to join.
        self.plugin.review_spectators()
        self.assertIn(spectator.steam_id, self.plugin.warned)

        # They join during the countdown, which clears the flag on the spot.
        self.plugin.handle_team_switch(spectator, "spectator", "blue")
        self.assertNotIn(spectator.steam_id, self.plugin.warned)
        spectator.team = "blue"
        self.setup_roster(red, blue + [spectator])

        # Phase 2: teams are even now, so nobody is benched.
        self.plugin.even_and_balance(balance=False)

        for player in red + blue + [spectator]:
            verify(player, times=0).put(any_matcher(str))

    def test_two_spectators_joining_together_are_both_cleared(self):
        # Both join, teams end up uneven again, but neither may be kicked for
        # it: they did exactly what they were asked.
        first = fake_player(HUMAN + 5, "first", "spectator")
        second = fake_player(HUMAN + 8, "second", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [first, second])
        self.warn_in_earlier_round(first)
        self.warn_in_earlier_round(second)

        self.plugin.handle_team_switch(first, "spectator", "blue")
        self.plugin.handle_team_switch(second, "spectator", "red")

        self.assertEqual({}, self.plugin.warned)

    def test_freshly_uneven_teams_only_even_out(self):
        latest = fake_player(HUMAN + 2, "latest", "red")
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 6, "r3", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)
        # Somebody joined a moment ago: too recent for anyone to have reacted.
        self.plugin.team_join_times[latest.steam_id] = time()
        self.plugin.uneven_since = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        assert_player_was_put_on(latest, "spectator")
        self.assert_kicked(spectator, times=0)
        self.assertIn(spectator.steam_id, self.plugin.warned)

    def test_round_start_pass_never_warns_or_kicks(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.even_and_balance(balance=False)

        self.assert_kicked(spectator, times=0)

    def test_recently_connected_spectator_is_not_warned(self):
        spectator = fake_player(HUMAN + 5, "newcomer", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.plugin.connect_times[spectator.steam_id] = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        self.assertNotIn(spectator.steam_id, self.plugin.warned)

    def test_bots_are_warned_and_kicked_like_anyone_else(self):
        # A bot idling in spec holds a slot exactly the way an AFK player does.
        bot = fake_player(90071996842377216, "Sarge", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [bot])
        self.warn_in_earlier_round(bot)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(bot)

    def test_game_countdown_does_not_move_anyone_yet(self):
        # Match start fires ~20s before the first round. Moving anyone here
        # burns the window in which people are still joining; the round
        # countdown handles it one second before the round starts.
        latest = fake_player(HUMAN + 5, "latest", "red")
        spectator = fake_player(HUMAN + 8, "watcher", "spectator")
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
               fake_player(HUMAN + 3, "r3", "red"), fake_player(HUMAN + 4, "r4", "red"), latest]
        blue = [fake_player(HUMAN + 6, "b1", "blue"), fake_player(HUMAN + 7, "b2", "blue")]
        self.setup_roster(red, blue, [spectator])
        self.plugin.team_join_times[latest.steam_id] = time()
        self.warn_in_earlier_round(spectator)

        self.plugin.handle_game_countdown()

        # Nothing moves, nobody is warned or kicked.
        for player in red + blue + [spectator]:
            verify(player, times=0).put(any_matcher(str))
        self.assert_kicked(spectator, times=0)
        self.assertEqual({}, self.plugin.warned)

        # The lopsided roster is still fixed, just at the usual moment.
        self.plugin.even_and_balance(balance=False, kick=True)
        assert_player_was_put_on(latest, "spectator")

    def test_a_spectator_is_warned_once_then_given_one_last_call(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        latest = fake_player(HUMAN + 6, "r3", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.plugin.team_join_times[latest.steam_id] = time()

        # Round 1: one fused line, autospec and warning together.
        self.plugin.round_token = 1
        self.plugin.review_spectators()
        assert_plugin_sent_to_console(
            "^3r3^7 will be specced, ^3watcher^7 will be kicked next round unless they join")

        # Round 2: already flagged, so it is now imminent, not a warning, and it
        # rides on the same line as the autospec.
        self.plugin.round_token = 2
        self.plugin.review_spectators()
        assert_plugin_sent_to_console(
            "^3r3^7 will be specced, ^1watcher^7 will be kicked NOW unless they join")

        # The stamp stays at the first round, so the kick still comes due.
        self.assertEqual(1, self.plugin.warned[spectator.steam_id])

    def test_the_move_is_decided_at_action_time_not_from_the_announcement(self):
        # Announced at the start of the countdown, then somebody else joins and
        # becomes the newest player on the bigger team. The bench must follow
        # the roster in front of us, not the name we said ten seconds ago.
        announced = fake_player(HUMAN + 6, "announced", "red")
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), announced]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue)
        self.plugin.team_join_times[announced.steam_id] = time()

        self.plugin.review_spectators()
        assert_plugin_sent_to_console("^3announced^7 will be specced")

        # A later joiner arrives during the countdown.
        latecomer = fake_player(HUMAN + 7, "latecomer", "red")
        self.setup_roster(red + [latecomer], blue)
        self.plugin.team_join_times[announced.steam_id] = time() - 5
        self.plugin.team_join_times[latecomer.steam_id] = time()

        self.plugin.even_and_balance(balance=False, kick=True)

        # The latecomer is the one acted on, not the announced player. With a
        # gap of two the fix is a move across rather than a bench, which is
        # itself the point: both the who and the what come from the roster at
        # action time.
        assert_player_was_put_on(latecomer, "blue")
        verify(announced, times=0).put(any_matcher(str))

    def test_a_spectator_leaving_can_make_the_announced_bench_unnecessary(self):
        # Your case: somebody is flagged to be specced, then another player
        # goes to spec on their own and the teams are level again. Nobody
        # should be moved on the strength of the earlier decision.
        announced = fake_player(HUMAN + 6, "announced", "red")
        other = fake_player(HUMAN + 5, "other", "red")
        red = [fake_player(HUMAN + 1, "r1", "red"), other, announced]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue)
        self.plugin.team_join_times[announced.steam_id] = time()

        self.plugin.review_spectators()
        assert_plugin_sent_to_console("^3announced^7 will be specced")

        # `other` takes themselves to spec during the countdown: 3v2 -> 2v2.
        other.team = "spectator"
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), announced], blue, [other])

        self.plugin.even_and_balance(balance=False, kick=True)

        verify(announced, times=0).put(any_matcher(str))
        assert_plugin_sent_to_console("^3Teams evened out^7: nobody has to sit out after all.")

    def test_evened_out_is_not_announced_for_a_round_that_announced_nothing(self):
        # The flag survived rounds where phase 1 returned early and phase 2 was
        # skipped, so a later quiet round claimed the teams had evened out when
        # nothing was ever named.
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue)
        self.plugin.announced_move = True  # left over from an earlier round

        self.plugin.handle_round_countdown(7)
        self.plugin.even_and_balance(balance=False)

        verify(Plugin, times=0).msg(
            "^3Teams evened out^7: nobody has to sit out after all.")

    def test_several_spectators_are_warned_in_one_line(self):
        first = fake_player(HUMAN + 5, "first", "spectator")
        second = fake_player(HUMAN + 7, "second", "spectator")
        third = fake_player(HUMAN + 8, "third", "spectator")
        latest = fake_player(HUMAN + 6, "r3", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [first, second, third])
        self.plugin.team_join_times[latest.steam_id] = time()
        self.plugin.round_token = 1

        self.plugin.review_spectators()

        assert_plugin_sent_to_console(
            "^3r3^7 will be specced, ^3first^7, ^3second^7, ^3third^7 "
            "will be kicked next round unless they join")
        for player in (first, second, third):
            self.assertEqual(1, self.plugin.warned[player.steam_id])

    def test_several_spectators_are_all_kicked_together(self):
        first = fake_player(HUMAN + 5, "first", "spectator")
        second = fake_player(HUMAN + 7, "second", "spectator")
        third = fake_player(HUMAN + 8, "third", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [first, second, third])
        self.plugin.round_token = 5
        for player in (first, second, third):
            self.plugin.warned[player.steam_id] = 4  # all flagged last round

        self.plugin.even_and_balance(balance=False, kick=True)

        for player in (first, second, third):
            self.assert_kicked(player)
        self.assertEqual({}, self.plugin.warned)

    def test_one_line_covers_an_autospec_a_kick_and_a_warning_together(self):
        # A round can hold both spectator groups: one already flagged and about
        # to go, one seen for the first time and merely on notice.
        going = fake_player(HUMAN + 5, "going", "spectator")
        noticed = fake_player(HUMAN + 7, "noticed", "spectator")
        latest = fake_player(HUMAN + 6, "r3", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [going, noticed])
        self.plugin.team_join_times[latest.steam_id] = time()
        self.plugin.round_token = 4
        self.plugin.warned[going.steam_id] = 3  # flagged last round

        self.plugin.review_spectators()

        assert_plugin_sent_to_console(
            "^3r3^7 will be specced, ^1going^7 will be kicked NOW unless they join, "
            "^3noticed^7 will be kicked next round unless they join")
        # The newcomer is flagged from this round, so their kick is not due yet.
        self.assertEqual(4, self.plugin.warned[noticed.steam_id])
        self.assertTrue(self.plugin.kick_is_due(going.steam_id))
        self.assertFalse(self.plugin.kick_is_due(noticed.steam_id))

    def test_a_freshly_connected_spectator_is_announced_not_silently_skipped(self):
        newcomer = fake_player(HUMAN + 5, "newcomer", "spectator")
        latest = fake_player(HUMAN + 6, "r3", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [newcomer])
        self.plugin.team_join_times[latest.steam_id] = time()
        self.plugin.connect_times[newcomer.steam_id] = time() - 20  # 40s of grace left

        self.plugin.review_spectators()

        self.assertNotIn(newcomer.steam_id, self.plugin.warned)
        # The countdown of remaining grace is wall-clock, so match on content.
        verify(Plugin).msg(arg_that(
            lambda m: isinstance(m, str) and "newcomer" in m and "just connected" in m))

    def test_dry_run_keeps_the_flag_so_it_does_not_loop(self):
        # With kicking off the player stays. Dropping the flag would re-warn and
        # re-announce them every couple of rounds for as long as they watch.
        setup_cvars({"qlx_teamplay_kick": "0"})
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(spectator, times=0)
        self.assertIn(spectator.steam_id, self.plugin.warned)

    def test_a_real_kick_clears_the_flag(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.even_and_balance(balance=False, kick=True)

        self.assert_kicked(spectator)
        self.assertEqual({}, self.plugin.warned)

    def test_even_teams_forgive_everyone_even_after_an_autospec(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        autospecced = fake_player(HUMAN + 6, "benched", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator, autospecced])
        self.plugin.round_token = 2
        self.warn_in_earlier_round(spectator)
        self.plugin.benched[autospecced.steam_id] = 1

        self.plugin.review_spectators()

        self.assertEqual({}, self.plugin.warned)

    def test_bench_records_are_dropped_once_the_player_stops_watching(self):
        # A record left behind for somebody who has rejoined would keep the
        # server looking short forever, warning and kicking every spectator on
        # even teams with nothing to bench.
        watching = fake_player(HUMAN + 5, "watching", "spectator")
        self.plugin.benched[HUMAN + 5] = 1
        self.plugin.benched[HUMAN + 99] = 1  # rejoined a while ago

        self.plugin.prune_benched([watching])

        self.assertEqual({HUMAN + 5: 1}, self.plugin.benched)

    def test_player_we_benched_is_not_warned_when_they_cannot_help(self):
        # 4v5 with two joiners becomes 4v4 plus the benched player. Rejoining
        # would only make it 5v4 again, so they must not be asked, let alone
        # kicked: they did exactly what the server told them to do.
        benched = fake_player(HUMAN + 5, "benched", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red"), fake_player(HUMAN + 7, "r4", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue"),
                           fake_player(HUMAN + 8, "b3", "blue"), fake_player(HUMAN + 9, "b4", "blue")],
                          [benched])
        self.plugin.round_token = 4
        self.plugin.benched[benched.steam_id] = 4  # benched this round
        self.plugin.warned[benched.steam_id] = 4  # left over from before we sat them down

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        # The flag may still be on file -- an autospec is in force, so flags are
        # not cleared -- but it can never be acted on against the person we
        # benched. They did what the server told them to do.
        self.assert_kicked(benched, times=0)
        self.assertTrue(self.plugin.is_benched_this_round(benched.steam_id))

    def test_a_stale_bench_entry_cannot_trigger_warnings_on_even_teams(self):
        # Regression: `or bool(self.benched)` meant one leftover bench entry
        # warned and then kicked every spectator, round after round, with the
        # teams perfectly even and nothing to bench.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red"), fake_player(HUMAN + 7, "r4", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue"),
                           fake_player(HUMAN + 8, "b3", "blue"), fake_player(HUMAN + 9, "b4", "blue")],
                          [spectator])
        self.plugin.benched[HUMAN + 99] = 0  # left over from an earlier round

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assertEqual({}, self.plugin.warned)
        self.assert_kicked(spectator, times=0)

    def test_warning_matures_into_a_kick_when_the_teams_go_short_again(self):
        # Warned in one round, still watching when the teams are short again:
        # that is the whole point of the flag.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        benched = fake_player(HUMAN + 6, "benched", "spectator")
        self.setup_roster(red, blue, [spectator, benched])

        # Round 1 warned them; we benched somebody, so the teams read as even.
        self.plugin.round_token = 1
        self.plugin.warned[spectator.steam_id] = 1
        self.plugin.benched[benched.steam_id] = 1
        self.plugin.uneven_since = None

        # Round 2: the autospec'd player rejoins, so the teams are short again
        # and the flag from round 1 is finally acted on.
        self.plugin.round_token = 2
        benched.team = "red"
        self.setup_roster(red + [benched], blue, [spectator])
        self.plugin.benched.clear()

        self.plugin.review_spectators()
        self.assertIn(spectator.steam_id, self.plugin.warned)

        self.plugin.even_and_balance(balance=False, kick=True)
        self.assert_kicked(spectator)

    def test_everyone_playing_clears_the_flags(self):
        # The opposite case: teams even and nobody benched, so a spectator is
        # not costing anyone a game and is forgiven.
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False, kick=True)

        self.assertEqual({}, self.plugin.warned)
        self.assert_kicked(spectator, times=0)

    def test_benched_player_is_exempt_for_that_round_then_asked_like_anyone(self):
        # Forgiven for the round we sat them down in. After that they are an
        # ordinary spectator, and uneven teams put them back on the hook.
        sarge = fake_player(90071996842377216, "Sarge", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [sarge])
        self.plugin.round_token = 4
        self.plugin.benched[sarge.steam_id] = 4

        # Round he was benched in.
        self.plugin.review_spectators()
        self.assertNotIn(sarge.steam_id, self.plugin.warned)

        # Next round, teams uneven again: he is asked like everybody else.
        self.plugin.round_token = 5
        self.plugin.review_spectators()
        self.assertIn(sarge.steam_id, self.plugin.warned)

    def test_unfair_teams_are_announced_but_not_switched_until_the_countdown(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fixable"
        self.plugin.scoreline_agrees = lambda: True

        self.plugin.flag_unfair_teams()

        self.assertTrue(self.plugin.balance_pending)
        assert_plugin_sent_to_console(
            "^3Unfair teams noticed^7: we will autobalance at the start of the next round.")
        verify(Plugin, times=0).switch(any_, any_)

    def test_unfair_teams_are_announced_only_once(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fixable"
        self.plugin.scoreline_agrees = lambda: True

        self.plugin.flag_unfair_teams()
        self.plugin.flag_unfair_teams()

        verify(Plugin, times=1).msg(
            "^3Unfair teams noticed^7: we will autobalance at the start of the next round.")

    def test_pending_balance_is_consumed_once(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        applied = []
        self.plugin.balance_by_rating = lambda: applied.append(True)
        self.plugin.balance_plugin = lambda: object()
        self.plugin.rating_request = lambda balance, callback: True
        self.plugin.balance_pending = True

        self.plugin.review_balance()
        self.plugin.review_balance()

        self.assertEqual(1, len(applied))
        self.assertFalse(self.plugin.balance_pending)

    def test_uneven_teams_skip_the_balance_and_say_so(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.balance_plugin = lambda: object()
        self.plugin.balance_pending = True

        self.plugin.review_balance()

        assert_plugin_sent_to_console("^3Skill balance skipped^7: teams are uneven.")
        # The promise survives, so it is honoured once the teams are level.
        self.assertTrue(self.plugin.balance_pending)

    def test_nothing_happens_during_warmup(self):
        # Warmup is when people pick teams and mess about. Nobody is benched,
        # warned, kicked or swapped until a match is actually under way.
        setup_game_in_warmup()
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        latest = fake_player(HUMAN + 6, "r3", "red")
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest]
        blue = [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")]
        self.setup_roster(red, blue, [spectator])
        self.warn_in_earlier_round(spectator)
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=True, kick=True)
        self.plugin.review_balance()
        self.plugin.report_fairness()
        self.plugin.apply_rating_switches(self.plugin.balance_token)

        for player in red + blue + [spectator]:
            verify(player, times=0).put(any_matcher(str))
        self.assert_kicked(spectator, times=0)
        verify(Plugin, times=0).switch(any_, any_)

    def score_setup(self, red_score, blue_score, red_rating, blue_rating, gap="3"):
        setup_cvars({"qlx_teamplay_score_gap": gap})
        setup_game_in_progress(red_score=red_score, blue_score=blue_score)
        self.plugin.team_ratings = lambda: (red_rating, blue_rating)

    def test_a_close_game_is_left_alone_however_lopsided_the_ratings(self):
        self.score_setup(red_score=5, blue_score=3, red_rating=1800, blue_rating=1300)
        self.assertFalse(self.plugin.scoreline_agrees())

    def test_a_one_sided_game_going_the_way_the_ratings_predict_is_balanced(self):
        self.score_setup(red_score=6, blue_score=1, red_rating=1800, blue_rating=1300)
        self.assertTrue(self.plugin.scoreline_agrees())

    def test_the_underdog_winning_means_the_ratings_are_wrong_so_leave_it(self):
        # Swapping here would hand the strong player to the side already ahead.
        self.score_setup(red_score=1, blue_score=6, red_rating=1800, blue_rating=1300)
        self.assertFalse(self.plugin.scoreline_agrees())

    def test_a_close_game_says_it_is_close(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fixable"
        self.plugin.rating_text = lambda: ""
        self.score_setup(red_score=5, blue_score=3, red_rating=1800, blue_rating=1300)

        self.plugin.report_fairness()

        self.assertFalse(self.plugin.balance_pending)
        assert_plugin_sent_to_console(
            "^3Teams look uneven on paper^7: but the game is close (5-3), leaving it alone.")

    def test_a_blowout_the_wrong_way_is_not_called_close(self):
        # 1-6 is not a close game. It is the direction check refusing to hand
        # the strong player to the team already winning.
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fixable"
        self.plugin.rating_text = lambda: ""
        self.score_setup(red_score=1, blue_score=6, red_rating=1800, blue_rating=1300)

        self.plugin.report_fairness()

        self.assertFalse(self.plugin.balance_pending)
        assert_plugin_sent_to_console(
            "^3Teams look uneven on paper^7: but the underdog is ahead (1-6), "
            "so the ratings are wrong about this game, leaving it alone.")

    def test_uneven_teams_are_never_reported_as_fair(self):
        # Regression: the rating request is asynchronous, so the teams can go
        # uneven between asking and answering. That returned False from the old
        # boolean check and was announced as "Teams are fair" -- once with a 320
        # point gap on screen.
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])

        self.assertEqual("unknown", self.plugin.rating_gap_verdict())

        self.plugin.report_fairness()

        verify(Plugin, times=0).msg(arg_that(lambda m: isinstance(m, str) and "Teams are fair" in m))
        self.assertFalse(self.plugin.balance_pending)

    def test_missing_ratings_are_not_reported_as_fair_either(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])

        class Uncached:
            def suggest_switch(self, teams, gametype):
                raise KeyError("no rating cached")

        self.plugin.balance_plugin = lambda: Uncached()

        self.assertEqual("unknown", self.plugin.rating_gap_verdict())

        self.plugin.report_fairness()

        verify(Plugin, times=0).msg(arg_that(lambda m: isinstance(m, str) and "Teams are fair" in m))

    def test_balance_messages_carry_the_team_ratings(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fair"
        self.plugin.rating_text = lambda: "^11583 ^7vs ^41550^7 (diff 33)"

        self.plugin.report_fairness()

        assert_plugin_sent_to_console(
            "^3Teams are fair^7: ^11583 ^7vs ^41550^7 (diff 33), no balance needed.")

    def test_balance_messages_read_fine_without_ratings(self):
        # Ratings are not always cached; the line must still make sense.
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fair"
        self.plugin.rating_text = lambda: ""

        self.plugin.report_fairness()

        assert_plugin_sent_to_console("^3Teams are fair^7: no balance needed.")

    def test_fair_teams_are_reported_once_not_every_round(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.rating_gap_verdict = lambda: "fair"

        self.plugin.report_fairness()
        self.plugin.report_fairness()

        verify(Plugin, times=1).msg("^3Teams are fair^7: no balance needed.")

    def test_handlers_survive_a_missing_player(self):
        # minqlx hands the dispatcher None for clients it cannot resolve yet,
        # which happens while bots are spawning.
        self.plugin.handle_team_switch(None, "spectator", "red")
        self.plugin.handle_player_connect(None)
        self.plugin.handle_player_disconnect(None, "disconnected")

    def test_kicking_can_be_turned_off(self):
        setup_cvars({"qlx_teamplay_kick": "0"})
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"),
                           fake_player(HUMAN + 6, "r3", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        self.assert_kicked(spectator, times=0)

    def test_gap_of_two_moves_a_player_across_instead_of_benching(self):
        latest = fake_player(HUMAN + 3, "latest", "red")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red"), latest],
                          [fake_player(HUMAN + 4, "b1", "blue")])
        self.plugin.team_join_times[latest.steam_id] = time()

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        assert_player_was_put_on(latest, "blue")

    def test_too_few_players_is_left_alone(self):
        red = [fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")]
        blue = [fake_player(HUMAN + 3, "b1", "blue")]
        self.setup_roster(red, blue)

        self.plugin.review_spectators()
        self.plugin.even_and_balance(balance=False)

        for player in red + blue:
            verify(player, times=0).put(any_matcher(str))

    def test_warning_flag_clears_when_the_spectator_joins(self):
        spectator = fake_player(HUMAN + 5, "watcher", "spectator")
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red")], [fake_player(HUMAN + 3, "b1", "blue")],
                          [spectator])
        self.warn_in_earlier_round(spectator)

        self.plugin.handle_team_switch(spectator, "spectator", "red")

        self.assertNotIn(spectator.steam_id, self.plugin.warned)

    def test_late_rating_callback_does_not_switch_mid_round(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        self.plugin.round_live = True

        self.plugin.apply_rating_switches(self.plugin.balance_token)

        verify(Plugin, times=0).switch(any_, any_)

    def test_superseded_rating_callback_is_dropped(self):
        self.setup_roster([fake_player(HUMAN + 1, "r1", "red"), fake_player(HUMAN + 2, "r2", "red")],
                          [fake_player(HUMAN + 3, "b1", "blue"), fake_player(HUMAN + 4, "b2", "blue")])
        stale_token = self.plugin.balance_token
        self.plugin.balance_token += 1

        self.plugin.apply_rating_switches(stale_token)

        verify(Plugin, times=0).switch(any_, any_)


if __name__ == '__main__':
    unittest.main()
