import minqlx
import re
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
        self.add_command("qlstats", self.cmd_ql_stats, priority=minqlx.PRI_HIGH, usage="Shows current player accuracy with datas from QLstats.net.")
        self.add_command("stats", self.cmd_local_stats, priority=minqlx.PRI_HIGH, usage="Shows current player accuracy with local data.")

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
        if stats.get("TYPE") == "PLAYER_STATS":
            self.logger.info(f"Received player stats: {stats}")
            data = stats.get("DATA", {})
            steam_id = data.get("STEAM_ID")
            if not steam_id:
                return

            self.append_game_stats(steam_id, stats)

    def append_game_stats(self, steam_id, game_stats):
        try:
            stats_array = get_json_from_redis(self, _local_stats_key.format(steam_id)) or []
            stats_array.append(game_stats)

            if len(stats_array) > WEAPON_STATS_LAST_GAMES:
                stats_array = stats_array[-WEAPON_STATS_LAST_GAMES:]

            store_in_redis(self, _local_stats_key.format(steam_id), stats_array)
        except Exception as e:
            self.logger.exception(f"Error appending game stats for {steam_id}: {e}")

    # Commands

    def cmd_local_stats(self, player, msg, channel):
        local_stats = get_json_from_redis(self, _local_stats_key.format(player.steam_id))
        if local_stats:
            self.handle_local_stats(local_stats, player, channel)
            return

        channel.reply(f"No local stats available for {player.name}.")

    def cmd_ql_stats(self, player, msg, channel):
        player_ql_stats_id = get_from_redis(self, _ql_stats_player_id.format(player.steam_id))
        accuracy = get_json_from_redis(self, _ql_stats_key.format(player.steam_id))

        if player_ql_stats_id and accuracy:
            self.handle_get_ql_stats({"averages": accuracy}, player, channel)
            return

        url = f"http://qlstats.net/player/{player.steam_id}.json"
        fetch(self, url, self.handle_get_player_id, player, channel)

    # Handlers

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

        # Initialize accumulators for total hits and shots
        weapon_totals = {short_name: {"hits": 0, "shots": 0} for short_name in relevant_weapons.values()}

        # Process local stats and accumulate totals
        for game in local_stats:
            if "DATA" in game and "WEAPONS" in game["DATA"]:
                for weapon, weapon_data in game["DATA"]["WEAPONS"].items():
                    if weapon in relevant_weapons:
                        short_name = relevant_weapons[weapon]
                        hits = weapon_data.get("H", 0)
                        shots = weapon_data.get("S", 0)
                        weapon_totals[short_name]["hits"] += hits
                        weapon_totals[short_name]["shots"] += shots

        # Calculate average accuracy for each weapon
        weapons = {}
        for short_name, totals in weapon_totals.items():
            total_hits = totals["hits"]
            total_shots = totals["shots"]

            if total_shots > 0:
                accuracy = round(total_hits / total_shots * 100)
                if accuracy > MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                    color = "^2"  # Green
                elif LOW_ACCURACY_PERCENTAGE_THRESHOLD <= accuracy <= MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD:
                    color = "^3"  # Yellow
                else:
                    color = "^1"  # Red
                weapons[short_name] = f"{color}{accuracy}^7"
            else:
                weapons[short_name] = "-"  # No shots fired

        # Generate the local stats summary
        local_stats_summary = ", ".join(f"{abbreviation}: {weapons.get(abbreviation, '-')}" for abbreviation in relevant_weapons.values())

        # Send the summary to the player
        channel.reply(f"{player.name}'s last {len(local_stats)} games stats from local data:")
        channel.reply(f"{local_stats_summary}")

    def handle_get_player_id(self, response, player, channel):
        if not response or not isinstance(response, list):
            channel.reply(f"Could not retrieve data for {player.name}.")
            return

        try:
            player_ql_stats_id = response[0]["player"]["player_id"]
            store_in_redis(self, _ql_stats_player_id.format(player.steam_id), player_ql_stats_id)

            player_ql_stats_id = 42756

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
            channel.reply(f"No stats available for {player.name}.")
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
