import minqlx
import time
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from .utils import get_json_from_redis, table, strip_formatting

class leaderboards(minqlx.Plugin):
    def __init__(self):
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_command(
            "lb",
            self.cmd_leaderboard,
            priority=minqlx.PRI_HIGH,
            usage="!lb <type>\nAvailable types: damage, kills, deaths, snipers, attackers, winners, losers, accuracy, best, all"
        )

    def send_multiline_message(self, player, message):
        for line in message.splitlines():
            player.tell(line)

    def clean_chat(self, player, time_filter, start_time, time_now):
        start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")

        player.tell(" ")
        player.tell(" ")
        player.tell(" ")
        player.tell(" ")
        player.tell(" ")
        player.tell(f"Check the console to view the leaderboards for the {time_filter} (from {start_time_str} to now).")

    @minqlx.thread
    def cmd_leaderboard(self, player, msg, channel):
        if len(msg) < 2:
            player.tell(
                "Usage: !lb <type> [time]\nAvailable types: damage, kills, deaths, snipers, attackers, winners, losers, accuracy, best, all\n"
                "Available times: day (default), week, month."
            )
            return

        leaderboard_type = msg[1].lower()
        time_filter = msg[2].lower() if len(msg) > 2 else "day"

        shanghai_tz = ZoneInfo("Asia/Shanghai")
        time_now = datetime.now(shanghai_tz)

        start_time, end_time = None, None

        if time_filter == "day":
            # Midnight today in Shanghai time
            start_time = time_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)  # Next midnight
        elif time_filter == "week":
            # Start from Monday of the current week in Shanghai time
            start_of_week = time_now - timedelta(days=time_now.weekday())  # Monday
            start_time = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=7)  # End of the week
        elif time_filter == "month":
            # Start from the first day of the current month in Shanghai time
            start_time = time_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # End of the month
            if time_now.month == 12:  # December, next month is January
                end_time = start_time.replace(year=time_now.year + 1, month=1)
            else:
                end_time = start_time.replace(month=time_now.month + 1)
        else:
            player.tell(f"Unknown time filter: {time_filter}. Valid options are 'day', 'week', or 'month'.")
            return

        player.tell(f"{end_time}")

        keys_pattern = f"minqlx:players:*:local_stats:*"
        keys = self.db.keys(keys_pattern)
        if not keys:
            player.tell("No local stats available.")
            return

        all_local_stats = []
        for key in keys:
            stats = get_json_from_redis(self, key)
            if stats and "timestamp" in stats:
                # Convert the timestamp to Shanghai time for comparison
                stat_time = datetime.fromisoformat(stats["timestamp"]).replace(tzinfo=ZoneInfo("UTC")).astimezone(shanghai_tz)
                if start_time <= stat_time < end_time:
                    all_local_stats.append(stats)

        if not all_local_stats:
            player.tell(f"No local stats available for the selected period ({time_filter}).")
            return

        if leaderboard_type == "all":
            self.run_all_leaderboards(all_local_stats, player, channel, time_filter)
            self.clean_chat(player, time_filter, start_time, time_now)
            return

        leaderboard_mapping = {
            "accuracy": self.handle_accuracy_leaderboard,
            "damage": self.handle_damage_leaderboard,
            "kills": self.handle_kills_leaderboard,
            "deaths": self.handle_deaths_leaderboard,
            "winners": self.handle_winners_leaderboard,
            "losers": self.handle_losers_leaderboard,
            "snipers": self.handle_snipers_leaderboard,
            "attackers": self.handle_attackers_leaderboard,
            "best": self.handle_best_players_leaderboard,
        }

        if leaderboard_type in leaderboard_mapping:
            leaderboard_mapping[leaderboard_type](all_local_stats, player, channel, time_filter)
            self.clean_chat(player, time_filter, start_time, time_now)
        else:
            player.tell(
                f"Unknown leaderboard type: {leaderboard_type}. Available types: all, accuracy, damage, kills, deaths, winners, losers, snipers, attackers."
            )

        return

    # Hooks

    @minqlx.thread
    def handle_team_switch(self, player, old_team, new_team):
        time.sleep(5)

        keys_pattern = f"minqlx:players:*:local_stats:*"
        keys = self.db.keys(keys_pattern)
        if not keys:
            return

        all_local_stats = [get_json_from_redis(self, key) for key in keys]
        all_local_stats = [stat for stat in all_local_stats if stat]

        if not all_local_stats:
            return

        top_players = self.top_combined_stats(all_local_stats, "day")[:3]

        if top_players:
            top_names = "\n".join([
                f"{index + 1}. {name[:15] + '…' if len(name) > 10 else name}^7 (score: {round(score, 2)})"
                for index, (name, score) in enumerate(top_players)
            ])
            player.center_print(f"Today's ^3BEST^7 players:\n{top_names}")

    # Handlers

    def top_combined_stats(self, stats_data, time_filter="day"):
        """Combines kills, damage, and average accuracy to determine the top players, filtered by time."""
        shanghai_tz = ZoneInfo("Asia/Shanghai")
        time_now = datetime.now(shanghai_tz)

        if time_filter == "day":
            start_time = time_now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_filter == "week":
            start_time = time_now - timedelta(days=time_now.weekday())  # Start of the week (Monday)
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_filter == "month":
            start_time = time_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # Start of the month
        else:
            raise ValueError(f"Invalid time filter: {time_filter}. Choose from 'day', 'week', or 'month'.")

        combined_totals = {}

        relevant_weapons = {
            "LIGHTNING": "LG",
            "GRENADE": "GL",
            "RAILGUN": "RG",
            "PLASMA": "PG",
            "ROCKET": "RL",
            "MACHINEGUN": "MG",
            "HMG": "HMG",
            "SHOTGUN": "SG",
        }

        for stat in stats_data:
            if "DATA" in stat and "timestamp" in stat:
                stat_time = datetime.fromisoformat(stat["timestamp"])
                if stat_time.tzinfo is None:  # If stat_time is naive, make it timezone-aware
                    stat_time = stat_time.replace(tzinfo=shanghai_tz)

                if stat_time < start_time:
                    continue

                player_name = stat["DATA"].get("NAME", "Unknown")
                kills = stat["DATA"].get("KILLS", 0)
                damage_given = stat["DATA"].get("DAMAGE", {}).get("DEALT", 0)
                weapons = stat["DATA"].get("WEAPONS", {})

                if player_name not in combined_totals:
                    combined_totals[player_name] = {
                        "kills": 0,
                        "damage_given": 0,
                        "total_avg_accuracy": 0,
                        "total_weapons": 0,
                        "weapons": {abbr: {"hits": 0, "shots": 0} for abbr in relevant_weapons.values()}
                    }

                combined_totals[player_name]["kills"] += kills
                combined_totals[player_name]["damage_given"] += damage_given

                for weapon, abbr in relevant_weapons.items():
                    weapon_stats = weapons.get(weapon, {})
                    hits = weapon_stats.get("H", 0)
                    shots = weapon_stats.get("S", 0)

                    combined_totals[player_name]["weapons"][abbr]["hits"] += hits
                    combined_totals[player_name]["weapons"][abbr]["shots"] += shots

        final_scores = []
        for player_name, stats in combined_totals.items():
            total_avg_accuracy = 0
            total_weapons = 0

            for abbr, weapon_stats in stats["weapons"].items():
                hits = weapon_stats["hits"]
                shots = weapon_stats["shots"]

                if shots > 0:
                    accuracy = hits / shots * 100
                    total_avg_accuracy += accuracy
                    total_weapons += 1

            avg_accuracy = total_avg_accuracy / total_weapons if total_weapons > 0 else 0

            kills = stats["kills"]
            damage_given = stats["damage_given"]
            combined_score = round(kills * 0.5 + (damage_given / 1000) * 0.3 + avg_accuracy * 0.9)

            final_scores.append((player_name, combined_score))

        sorted_totals = sorted(final_scores, key=lambda x: -x[1])

        return sorted_totals[:10]

    @minqlx.thread
    def run_all_leaderboards(self, all_local_stats, player, channel, time_filter):
        """Runs all leaderboards in separate threads to reduce server lag."""
        leaderboard_handlers = [
            self.handle_accuracy_leaderboard,
            self.handle_damage_leaderboard,
            self.handle_kills_leaderboard,
            self.handle_deaths_leaderboard,
            self.handle_winners_leaderboard,
            self.handle_losers_leaderboard,
            self.handle_snipers_leaderboard,
            self.handle_attackers_leaderboard,
            self.handle_best_players_leaderboard,
        ]

        for handler in leaderboard_handlers:
            # Run each leaderboard in its own thread
            handler(all_local_stats, player, channel, time_filter)
            player.tell(" ")
            time.sleep(0.2)  # Add a short delay between leaderboards to reduce server strain

    def handle_best_players_leaderboard(self, stats_data, player, channel, time_filter):
        top_players = self.top_combined_stats(stats_data, time_filter)

        if top_players:
            headers = ["#", "PLAYER", "SCORE"]
            rows = [
                [str(index + 1), name[:15] + '…' if len(strip_formatting(name)) > 10 else name, f"{round(score, 2)}"]
                for index, (name, score) in enumerate(top_players)
            ]

            leaderboard_table = table(headers, rows, f"Best Players (1 {time_filter})")

            self.send_multiline_message(player, leaderboard_table)
        else:
            self.send_multiline_message(player, f"No stats available for the {time_filter}.")

    @minqlx.thread
    def handle_damage_leaderboard(self, stats_data, player, channel, time_filter):
        damage_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                damage_given = stat["DATA"].get("DAMAGE", {}).get("DEALT", 0)
                damage_taken = stat["DATA"].get("DAMAGE", {}).get("TAKEN", 0)

                if player_name not in damage_totals:
                    damage_totals[player_name] = {"DAMAGE GIVEN": 0, "DAMAGE TAKEN": 0}
                damage_totals[player_name]["DAMAGE GIVEN"] += damage_given
                damage_totals[player_name]["DAMAGE TAKEN"] += damage_taken

        sorted_totals = sorted(
            damage_totals.items(),
            key=lambda x: -x[1]["DAMAGE GIVEN"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "DAMAGE GIVEN", "DAMAGE TAKEN"]
        rows = []

        for index, (player_name, totals) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(totals["DAMAGE GIVEN"]),
                str(totals["DAMAGE TAKEN"])
            ])

        leaderboard = table(headers, rows, f"Damage Dealt (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_snipers_leaderboard(self, stats_data, player, channel, time_filter):
        sniper_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                medals = stat["DATA"].get("MEDALS", {})
                accuracy = medals.get("ACCURACY", 0)
                headshots = medals.get("HEADSHOT", 0)
                impressives = medals.get("IMPRESSIVE", 0)

                if player_name not in sniper_totals:
                    sniper_totals[player_name] = {
                        "ACCURACY": 0,
                        "HEADSHOTS": 0,
                        "IMPRESSIVES": 0,
                        "TOTAL": 0
                    }
                sniper_totals[player_name]["ACCURACY"] += accuracy
                sniper_totals[player_name]["HEADSHOTS"] += headshots
                sniper_totals[player_name]["IMPRESSIVES"] += impressives
                sniper_totals[player_name]["TOTAL"] += (accuracy + headshots + impressives)

        sorted_totals = sorted(
            sniper_totals.items(),
            key=lambda x: -x[1]["TOTAL"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "ACCURACY", "HEADSHOTS", "IMPRESSIVES", "TOT"]
        rows = []

        for index, (player_name, stats) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(stats["ACCURACY"]),
                str(stats["HEADSHOTS"]),
                str(stats["IMPRESSIVES"]),
                str(stats["TOTAL"]),
            ])

        leaderboard = table(headers, rows, f"Sniper Medals (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_attackers_leaderboard(self, stats_data, player, channel, time_filter):
        attack_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                medals = stat["DATA"].get("MEDALS", {})
                excellent = medals.get("EXCELLENT", 0)
                firstfrag = medals.get("FIRSTFRAG", 0)
                midair = medals.get("MIDAIR", 0)
                revenge = medals.get("REVENGE", 0)

                if player_name not in attack_totals:
                    attack_totals[player_name] = {
                        "EXCELLENT": 0,
                        "FIRSTFRAG": 0,
                        "MIDAIR": 0,
                        "REVENGE": 0,
                        "TOTAL": 0
                    }
                attack_totals[player_name]["EXCELLENT"] += excellent
                attack_totals[player_name]["FIRSTFRAG"] += firstfrag
                attack_totals[player_name]["MIDAIR"] += midair
                attack_totals[player_name]["REVENGE"] += revenge
                attack_totals[player_name]["TOTAL"] += (excellent + firstfrag + midair + revenge)

        sorted_totals = sorted(
            attack_totals.items(),
            key=lambda x: -x[1]["TOTAL"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "EXCELLENT", "FIRSTFRAG", "MIDAIR", "REVENGE", "TOT"]
        rows = []

        for index, (player_name, stats) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(stats["EXCELLENT"]),
                str(stats["FIRSTFRAG"]),
                str(stats["MIDAIR"]),
                str(stats["REVENGE"]),
                str(stats["TOTAL"]),
            ])

        leaderboard = table(headers, rows, f"Attack Medals (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_kills_leaderboard(self, stats_data, player, channel, time_filter):
        kills_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                kills = stat["DATA"].get("KILLS", 0)
                deaths = stat["DATA"].get("DEATHS", 0)
                kdr = round(kills / deaths, 2) if deaths > 0 else kills

                if player_name not in kills_totals:
                    kills_totals[player_name] = {"KILLS": 0, "DEATHS": 0, "K/D RATIO": 0}

                kills_totals[player_name]["KILLS"] += kills
                kills_totals[player_name]["DEATHS"] += deaths
                kills_totals[player_name]["K/D RATIO"] = (
                    round(kills_totals[player_name]["KILLS"] / kills_totals[player_name]["DEATHS"], 2)
                    if kills_totals[player_name]["DEATHS"] > 0
                    else kills_totals[player_name]["KILLS"]
                )

        sorted_totals = sorted(
            kills_totals.items(),
            key=lambda x: -x[1]["KILLS"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "KILLS", "DEATHS", "K/D RATIO"]
        rows = []

        for index, (player_name, stats) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(stats["KILLS"]),
                str(stats["DEATHS"]),
                str(stats["K/D RATIO"])
            ])

        leaderboard = table(headers, rows, f"Kills (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_deaths_leaderboard(self, stats_data, player, channel, time_filter):
        deaths_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                deaths = stat["DATA"].get("DEATHS", 0)

                if player_name not in deaths_totals:
                    deaths_totals[player_name] = {"DEATHS": 0}

                deaths_totals[player_name]["DEATHS"] += deaths

        sorted_totals = sorted(
            deaths_totals.items(),
            key=lambda x: -x[1]["DEATHS"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "DEATHS"]
        rows = []

        for index, (player_name, stats) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(stats["DEATHS"]),
            ])

        leaderboard = table(headers, rows, f"Deaths (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_winners_leaderboard(self, stats_data, player, channel, time_filter):
        game_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                wins = stat["DATA"].get("WIN", 0)
                losses = stat["DATA"].get("LOSE", 0)

                if player_name not in game_totals:
                    game_totals[player_name] = {"WINS": 0, "LOSSES": 0}
                game_totals[player_name]["WINS"] += wins
                game_totals[player_name]["LOSSES"] += losses

        sorted_totals = sorted(
            game_totals.items(),
            key=lambda x: -x[1]["WINS"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "WINS", "LOSSES"]
        rows = [
            [str(index + 1), player_name, str(stats["WINS"]), str(stats["LOSSES"])]
            for index, (player_name, stats) in enumerate(top_players)
        ]

        leaderboard = table(headers, rows, f"Wins (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_losers_leaderboard(self, stats_data, player, channel, time_filter):
        game_totals = {}

        for stat in stats_data:
            if "DATA" in stat:
                player_name = stat["DATA"].get("NAME", "Unknown")
                wins = stat["DATA"].get("WIN", 0)
                losses = stat["DATA"].get("LOSE", 0)

                if player_name not in game_totals:
                    game_totals[player_name] = {"WINS": 0, "LOSSES": 0}
                game_totals[player_name]["WINS"] += wins
                game_totals[player_name]["LOSSES"] += losses

        sorted_totals = sorted(
            game_totals.items(),
            key=lambda x: -x[1]["LOSSES"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "WINS", "LOSSES"]
        rows = [
            [str(index + 1), player_name, str(stats["WINS"]), str(stats["LOSSES"])]
            for index, (player_name, stats) in enumerate(top_players)
        ]

        leaderboard = table(headers, rows, f"Losses (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)

    @minqlx.thread
    def handle_accuracy_leaderboard(self, stats_data, player, channel, time_filter):
        relevant_weapons = {
            "LIGHTNING": "LG",
            "GRENADE": "GL",
            "RAILGUN": "RG",
            "PLASMA": "PG",
            "ROCKET": "RL",
            "MACHINEGUN": "MG",
            "HMG": "HMG",
            "SHOTGUN": "SG",
        }

        # Initialize data structure for all players
        accuracy_totals = {}

        for stat in stats_data:
            if "DATA" in stat and "WEAPONS" in stat["DATA"]:
                player_name = stat["DATA"].get("NAME", "Unknown")
                if player_name not in accuracy_totals:
                    accuracy_totals[player_name] = {
                        "total_avg_accuracy": 0,
                        "total_weapons": 0,
                        "weapons": {abbr: {"hits": 0, "shots": 0} for abbr in relevant_weapons.values()}
                    }

                for weapon, abbr in relevant_weapons.items():
                    weapon_stats = stat["DATA"]["WEAPONS"].get(weapon, {})
                    hits = weapon_stats.get("H", 0)
                    shots = weapon_stats.get("S", 0)

                    accuracy_totals[player_name]["weapons"][abbr]["hits"] += hits
                    accuracy_totals[player_name]["weapons"][abbr]["shots"] += shots

        for player_name, player_stats in accuracy_totals.items():
            total_avg_accuracy = 0
            total_weapons = 0

            for abbr, stats in player_stats["weapons"].items():
                total_hits = stats["hits"]
                total_shots = stats["shots"]

                if total_shots > 0:
                    accuracy = round(total_hits / total_shots * 100)
                    player_stats["weapons"][abbr] = accuracy
                    total_avg_accuracy += accuracy
                    total_weapons += 1
                else:
                    player_stats["weapons"][abbr] = "-"

            player_stats["total_avg_accuracy"] = (
                round(total_avg_accuracy / total_weapons) if total_weapons > 0 else 0
            )

        sorted_totals = sorted(
            accuracy_totals.items(),
            key=lambda x: -x[1]["total_avg_accuracy"]
        )

        top_players = sorted_totals[:10]

        headers = ["#", "PLAYER", "AVG"] + list(relevant_weapons.values())
        rows = []

        for index, (player_name, player_stats) in enumerate(top_players):
            rows.append([
                str(index + 1),
                player_name,
                str(player_stats["total_avg_accuracy"]),
            ] + [str(player_stats["weapons"][abbr]) for abbr in relevant_weapons.values()])

        leaderboard = table(headers, rows, f"Average Accuracy (1 {time_filter})")

        self.send_multiline_message(player, leaderboard)
