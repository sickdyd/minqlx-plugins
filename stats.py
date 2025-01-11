import minqlx
import re
import requests
from datetime import datetime, timedelta
from .leaderboards import RELEVANT_WEAPONS, VALID_TIMEFRAMES, LEADERBOARS_HOST

WEAPON_STATS_LAST_GAMES = 10
LOW_ACCURACY_PERCENTAGE_THRESHOLD = 20
MEDIUM_ACCURACY_PERCENTAGE_THRESHOLD = 35
QL_STATS_KEY_PATTERN = "minqlx:players:*:ql_stats"

STATS_USAGE_TEXT = (
    f"Usage: ^2!stats <timeframe>^7\n\n"
    f"Timeframes: {', '.join(f'^6{tf}^7' for tf in VALID_TIMEFRAMES)}\n"
    "Example: ^2!stats week^7\n"
    "Check the console to see how to use the command."
)

_ql_stats_key = "minqlx:players:{}:ql_stats"
_local_stats_key = "minqlx:players:{}:local_stats"
_ql_stats_player_id = "minqlx:players:{}:ql_stats_player_id"


class stats(minqlx.Plugin):
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost") or LEADERBOARS_HOST

        self.add_hook("game_end", self.handle_game_end)
        self.add_command("qlstats", self.cmd_ql_stats, priority=minqlx.PRI_HIGH, usage="!qlstats")
        self.add_command("stats", self.cmd_stats, priority=minqlx.PRI_HIGH, usage="!stats day, !stats week, !stats month")

    @minqlx.thread
    def fetch(self, endpoint, callback, *args, **kwargs):
        self.logger.info(f"Fetching {endpoint}")

        try:
            response = requests.get(endpoint)
            if response.status_code != requests.codes.ok:
                self.logger.error(f"Failed to fetch {endpoint}: {response.status_code}")
                return callback(None, *args, **kwargs)

            data = response.json()
            callback(data, *args, **kwargs)
        except Exception as e:
            self.logger.exception(f"Error fetching {endpoint}: {e}")
            callback(None, *args, **kwargs)

    def store_in_redis(self, key, data):
        try:
            serialized_data = json.dumps(data)
            self.db.set(key, serialized_data)
        except Exception as e:
            self.logger.exception(f"Error storing data in Redis: {e}")

    def get_from_redis(self, key):
        try:
            return self.db.get(key)
        except Exception as e:
            self.logger.exception(f"Error retrieving data from Redis: {e}")
            return None

    def get_json_from_redis(self, key):
        try:
            data = self.db.get(key)
            if data:
                # Need to double load because the data is stored as a string
                return json.loads(data)
        except Exception as e:
            self.logger.exception(f"Error loading data from Redis: {e}")
        return None

    def send_multiline_message(self, player, message):
        for line in message.splitlines():
            player.tell(line)

    # Hooks

    def handle_game_end(self, data):
        try:
            keys = self.db.keys(QL_STATS_KEY_PATTERN)

            for key in keys:
                self.db.delete(key)

            self.logger.info(f"Cleared {len(keys)} game stat entries.")
        except Exception as e:
            self.logger.exception(f"Error clearing game stats: {e}")

    # Commands

    def cmd_stats(self, player, msg, channel):
        self.logger.info(f"Received stats command from {player.name}: {msg}")

        timeframe = msg[1].lower() if len(msg) > 1 else "day"

        if timeframe not in VALID_TIMEFRAMES:
            player.tell(
                f"Invalid timeframe. Available timeframes: {', '.join(f'^2{tf}^7' for tf in VALID_TIMEFRAMES)}"
            )
            self.send_multiline_message(player, STATS_USAGE_TEXT)
            return minqlx.RET_STOP_ALL

        url = f"{self.leaderboards_host}/leaderboards/stats?timeframe={timeframe}&steam_id={player.steam_id}&weapons={','.join(RELEVANT_WEAPONS.keys())}"

        self.logger.info(f"Fetching stats for {player.name} ({timeframe})...{url}")

        self.fetch(url, self.handle_stats, player, timeframe)

    def handle_stats(self, data, player, timeframe):
        self.logger.info(f"Received stats for {player.name} ({timeframe})")

        if not data:
            player.tell("Failed to fetch data.")
            return

        if data["data"] == []:
            player.tell(f"No stats available for {player.name} ({timeframe}).")
            return

        player_data = data["data"][0]
        average_accuracy = player_data.get("average_accuracy", 0)
        weapons = player_data.get("weapons", {})

        self.logger.info(f"Stats for {player.name} ({timeframe}): {weapons}")

        def colorize_accuracy(value):
            if value == "-":
                return "-"

            try:
                value = int(value)
            except ValueError:
                return "-"

            if value < 30:
                return f"^1{value}%^7"
            elif value < 40:
                return f"^3{value}%^7"
            else:
                return f"^2{value}%^7"

        self.logger.info(f"Stats for {player.name} ({timeframe}): {weapons}")

        weapon_stats = [
            f"{RELEVANT_WEAPONS[weapon].upper()}: {colorize_accuracy(accuracy)}"
            for weapon, accuracy in weapons.items()
            if weapon in RELEVANT_WEAPONS
        ]

        self.logger.info(f"Stats for {player.name} ({timeframe}): {weapon_stats}")

        weapon_stats.append(f"AVG: {colorize_accuracy(average_accuracy)}")
        stats_line = ", ".join(weapon_stats)
        player.tell(stats_line)

    def cmd_ql_stats(self, player, msg, channel):
        player_ql_stats_id = self.get_from_redis(_ql_stats_player_id.format(player.steam_id))
        accuracy = self.get_json_from_redis(_ql_stats_key.format(player.steam_id))

        if player_ql_stats_id and accuracy:
            self.handle_get_ql_stats({"averages": accuracy}, player, channel)
            return

        url = f"http://qlstats.net/player/{player.steam_id}.json"
        self.fetch(url, self.handle_get_player_id, player, channel)

    def handle_get_player_id(self, response, player, channel):
        if not response or not isinstance(response, list):
            channel.reply(f"Could not retrieve data for {player.name}.")
            return

        try:
            player_ql_stats_id = response[0]["player"]["player_id"]
            self.store_in_redis(self, _ql_stats_player_id.format(player.steam_id), player_ql_stats_id)

            url = f"https://qlstats.net/player/{player_ql_stats_id}/weaponstats.json?limit={WEAPON_STATS_LAST_GAMES}&game_type=ca"
            self.fetch(url, self.handle_get_ql_stats, player, channel)
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

        self.store_in_redis(self, _ql_stats_key.format(player.steam_id), response["averages"])

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
