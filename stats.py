import minqlx
import re
from datetime import datetime, timedelta
from .utils import fetch, store_in_redis, get_from_redis, get_json_from_redis, table

WEAPON_STATS_LAST_GAMES = 10
LOW_ACCURACY_PERCENTAGE_THRESHOLD = 20
MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD = 35
QL_STATS_KEY_PATTERN = "minqlx:players:*:ql_stats"
_ql_stats_key = "minqlx:players:{}:ql_stats"
_local_stats_key = "minqlx:players:{}:local_stats"
_ql_stats_player_id = "minqlx:players:{}:ql_stats_player_id"


class stats(minqlx.Plugin):
    def __init__(self):
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("stats", self.handle_stats)
        self.add_command("qlstats", self.cmd_ql_stats, priority=minqlx.PRI_HIGH, usage="!qlstats")
        self.add_command("stats", self.cmd_local_stats, priority=minqlx.PRI_HIGH, usage="!stats day, !stats week, !stats month")

    # Hooks

    def handle_game_end(self, data):
        try:
            keys = self.db.keys(QL_STATS_KEY_PATTERN)

            for key in keys:
                self.db.delete(key)

            self.logger.info(f"Cleared {len(keys)} game stat entries.")
        except Exception as e:
            self.logger.exception(f"Error clearing game stats: {e}")

    def handle_stats(self, stats):
        if stats["DATA"].get("WARMUP", False):
            return
        if stats["DATA"].get("ABORTED", False):
            return

        if stats.get("TYPE") == "PLAYER_STATS":
            self.logger.info(f"Received player stats: {stats}")
            data = stats.get("DATA", {})
            steam_id = data.get("STEAM_ID")

            if not steam_id or steam_id == "0":
                player_name = data.get("NAME", "Unknown")

                sanitized_name = re.sub(r"[^\w\d]", "_", player_name)
                if not sanitized_name:
                    sanitized_name = "UnknownPlayer"
                key = f"bot:{sanitized_name}"
            else:
                key = f"player:{steam_id}"

            self.append_game_stats(key, stats)

    def append_game_stats(self, steam_id, game_stats):
        try:
            game_id = game_stats.get("DATA", {}).get("MATCH_GUID")
            if not game_id:
                self.logger.warning(f"No MATCH_GUID found in game stats for Steam ID {steam_id}.")
                return

            timestamp = datetime.utcnow().isoformat()
            game_stats["timestamp"] = timestamp

            key = _local_stats_key.format(steam_id) + f":{game_id}"
            store_in_redis(self, key, game_stats)

            self.logger.info(f"Stored game stats for Steam ID {steam_id}, Game ID {game_id}, Timestamp {timestamp}.")
        except Exception as e:
            self.logger.exception(f"Error appending game stats for {steam_id}: {e}")

    # Commands

    def cmd_local_stats(self, player, msg, channel):
        time_filter = msg[1].lower() if len(msg) > 1 else "day"
        time_now = datetime.utcnow()

        if time_filter == "day":
            start_time = time_now - timedelta(days=1)
        elif time_filter == "week":
            start_time = time_now - timedelta(weeks=1)
        elif time_filter == "month":
            start_time = time_now - timedelta(days=30)
        else:
            channel.reply(f"Unknown time filter: {time_filter}. Valid options are 'day', 'week', or 'month'.")
            return

        try:
            keys_pattern = f"minqlx:players:{player.steam_id}:local_stats:*"
            keys = self.db.keys(keys_pattern)

            if not keys:
                channel.reply(f"No local stats available for {player.name}.")
                return

            local_stats = []
            for key in keys:
                stats = get_json_from_redis(self, key)
                if stats and "timestamp" in stats:
                    stat_time = datetime.fromisoformat(stats["timestamp"])
                    if stat_time >= start_time:
                        local_stats.append(stats)

            if local_stats:
                self.handle_local_stats(local_stats, player, channel)
            else:
                channel.reply(f"No stats available for the selected period for {player.name}.")
        except Exception as e:
            self.logger.exception(f"Error retrieving local stats for {player.steam_id}: {e}")
            channel.reply(f"An error occurred while retrieving stats for {player.name}.")

    def cmd_ql_stats(self, player, msg, channel):
        player_ql_stats_id = get_from_redis(self, _ql_stats_player_id.format(player.steam_id))
        accuracy = get_json_from_redis(self, _ql_stats_key.format(player.steam_id))

        if player_ql_stats_id and accuracy:
            self.handle_get_ql_stats({"averages": accuracy}, player, channel)
            return

        url = f"http://qlstats.net/player/{player.steam_id}.json"
        fetch(self, url, self.handle_get_player_id, player, channel)

    @minqlx.thread
    def handle_local_stats(self, local_stats, player, channel):
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

        weapon_totals = {short_name: {"hits": 0, "shots": 0, "games": 0} for short_name in relevant_weapons.values()}

        for game in local_stats:
            if "DATA" in game and "WEAPONS" in game["DATA"]:
                for weapon, weapon_data in game["DATA"]["WEAPONS"].items():
                    if weapon in relevant_weapons:
                        short_name = relevant_weapons[weapon]
                        hits = weapon_data.get("H", 0)
                        shots = weapon_data.get("S", 0)

                        weapon_totals[short_name]["hits"] += hits
                        weapon_totals[short_name]["shots"] += shots

                        if shots > 0:
                            weapon_totals[short_name]["games"] += 1

        weapons = {}
        for short_name, totals in weapon_totals.items():
            total_hits = totals["hits"]
            total_shots = totals["shots"]
            games_used = totals["games"]

            if games_used > 0 and total_shots > 0:
                accuracy = round(total_hits / total_shots * 100)
                if accuracy > MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                    color = "^2"
                elif LOW_ACCURACY_PERCENTAGE_THRESHOLD <= accuracy <= MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                    color = "^3"
                else:
                    color = "^1"
                weapons[short_name] = f"{color}{accuracy}^7"
            else:
                weapons[short_name] = "-"

        local_stats_summary = ", ".join(f"{abbreviation}: {weapons.get(abbreviation, '-')}" for abbreviation in relevant_weapons.values())

        channel.reply(f"{player.name}'s last {len(local_stats)} games stats from local data:")
        channel.reply(f"{local_stats_summary}")

    def handle_get_player_id(self, response, player, channel):
        if not response or not isinstance(response, list):
            channel.reply(f"Could not retrieve data for {player.name}.")
            return

        try:
            player_ql_stats_id = response[0]["player"]["player_id"]
            store_in_redis(self, _ql_stats_player_id.format(player.steam_id), player_ql_stats_id)

            url = f"https://qlstats.net/player/{player_ql_stats_id}/weaponstats.json?limit={WEAPON_STATS_LAST_GAMES}&game_type=ca"
            fetch(self, url, self.handle_get_ql_stats, player, channel)
        except KeyError:
            channel.reply(f"Invalid data received for {player.name}.")
            self.logger.error(f"Unexpected response format: {response}")

    def handle_get_ql_stats(self, response, player, channel):
        if not response or "averages" not in response:
            channel.reply(f"Could not retrieve stats for {player.name}.")
            return

        if not response["averages"]:
            channel.reply(f"No QLstats available for {player.name}.")
            return

        store_in_redis(self, _ql_stats_key.format(player.steam_id), response["averages"])

        ql_stats = []
        for weapon, accuracy in response["averages"].items():
            rounded_accuracy = round(accuracy)
            if rounded_accuracy > MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                color = "^2"
            elif LOW_ACCURACY_PERCENTAGE_THRESHOLD <= rounded_accuracy <= MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                color = "^3"
            else:
                color = "^1"

            ql_stats.append(f"{weapon.upper()}: {color}{rounded_accuracy}^7")

        channel.reply(f"{player.name}'s last {WEAPON_STATS_LAST_GAMES} games stats from QLstats:")
        channel.reply(f"{', '.join(ql_stats)}")
