import minqlx
import time
import re
import requests
from datetime import datetime
import json

RELEVANT_WEAPONS = ["lightning", "grenade", "rocket", "railgun", "plasma", "machinegun", "hmg", "shotgun"]
SNIPER_MEDALS = ["accuracy", "headshot", "impressive",]
ATTACKER_MEDALS = ["excellent", "firstfrag", "midair", "revenge"]
AVAILABLE_LEADERBOARDS = ["accuracy", "best", "damage", "damage_taken", "kills", "deaths", "snipers", "attackers", "wins", "losses", "all"]
AVAILABLE_TIME_FILTERS = ["day", "week", "month", "year", "all"]
DEFAULT_LIMIT = 10
DEFAULT_TIME_FILTER = "day"
HIGHLITHED_LIST_ENTRIES_SEPARATOR = "^7, ^2"
LEADERBOARDS_ARG = "^7 | ^2".join(AVAILABLE_LEADERBOARDS)
TIME_FILTER_ARG = "^7 | ^2".join(AVAILABLE_TIME_FILTERS)
CACHE_DURATION_IN_SECONDS = 300
LEADERBOARD_CACHE_KEY = "lb:{}"

class leaderboards(minqlx.Plugin):
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost")
        self.logger.info(f"Leaderboards host: {self.leaderboards_host}")

        self.add_command("help", self.cmd_help, priority=minqlx.PRI_HIGH, usage = "!lb help")
        self.add_command("stats", self.cmd_stats, priority=minqlx.PRI_HIGH, usage = "!stats [{TIME_FILTER_ARG}]")
        self.add_command("clear_cache", self.cmd_clear_cache, permission="admin", usage = "!clear_cache")
        for lb in AVAILABLE_LEADERBOARDS:
            self.add_command(lb, self.cmd_leaderboard, priority=minqlx.PRI_HIGH, usage=f"!{lb} [{TIME_FILTER_ARG}]")
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("game_end", self.handle_game_end)

    def cmd_help(self, player, msg, channel):
        self.help_message(player)

    def help_message(self, player):
        player.tell("---------------- help ------------------------")
        player.tell("USAGE: ^2!leaderboard ^7[^2time^7]")
        player.tell("EXAMPLE: ^1!accuracy week")
        player.tell(f"LEADERBOARDS: ^2{LEADERBOARDS_ARG}")
        player.tell(f"TIMES: ^2{TIME_FILTER_ARG}")
        player.tell("^2NOTE^7: Names with ideograms won't display correctly in tables; replaced with standard characters.")
        player.tell("^2注意^7：包含表意文字的名称在表格中可能无法正确显示，已替换为标准字符。")
        player.tell("----------------------------------------------")

        player.tell("Check the console to see the help!")

    def plugin_load(self):
        self.handle_game_end(None)

    def cmd_clear_cache(self, player, msg, channel):
        self.logger.info("Clearing leaderboard cache.")

        for key in self.db.keys("lb:*"):
            self.db.delete(key)

    def handle_game_end(self, data):
        self.cmd_clear_cache(None, None, None)
        url = self.request_url("best", "day", "", "", "false", 3)
        self.fetch(url, lambda *a, **kw: None)

    def cmd_leaderboard(self, player, msg, channel):
        lb_type = msg[0].lstrip("!").lower()
        time_filter = msg[1].lower() if len(msg) > 1 else DEFAULT_TIME_FILTER

        if not self.is_valid_leaderboard(lb_type) or not self.is_valid_time_filter(time_filter):
            self.help_message(player)
            return

        weapons = ",".join(RELEVANT_WEAPONS)
        medals = ""

        if lb_type == "snipers":
            lb_type = "medals"
            medals = ",".join(SNIPER_MEDALS)
        elif lb_type == "attackers":
            lb_type = "medals"
            medals = ",".join(ATTACKER_MEDALS)

        if lb_type == "all":
            self.request_all_leaderboards(player, time_filter, weapons, medals)
        else:
            self.request_leaderboard(player, lb_type, time_filter, weapons, medals)

    @minqlx.thread
    def request_all_leaderboards(self, player, time_filter, weapons, medals):
        for lb in AVAILABLE_LEADERBOARDS:
            if lb == "all":
                continue
            lb_medals = medals
            if lb == "snipers":
                lb = "medals"
                lb_medals = ",".join(SNIPER_MEDALS)
            elif lb == "attackers":
                lb = "medals"
                lb_medals = ",".join(ATTACKER_MEDALS)
            time.sleep(0.1)
            self.request_leaderboard(player, lb, time_filter, weapons, lb_medals)

    def request_leaderboard(self, player, lb_type, time_filter, weapons, medals):
        url = self.request_url(lb_type, time_filter, weapons, medals)
        self.fetch(url, self.handle_leaderboard_request, player)

    def request_stats(self, player, time_filter, weapons):
        if time_filter == "all":
            time_filter = "all_time"
        url = f"{self.leaderboards_host}/stats?steam_id={player.steam_id}&time_filter={time_filter}&weapons={weapons}"
        self.fetch(url, self.handle_stats_request, player)

    def is_valid_leaderboard(self, lb_type):
        return lb_type in AVAILABLE_LEADERBOARDS + ["all"]

    def is_valid_time_filter(self, time_filter):
        return time_filter in AVAILABLE_TIME_FILTERS

    def handle_leaderboard_request(self, data, player):
        table_data = data.get("data", [])

        if not table_data:
            player.tell("No leaderboard data available for this period! Play more games!")
            return

        self.send_multiline_message(player, table_data)

    def cmd_stats(self, player, msg, channel):
        time_filter = msg[1].lower() if len(msg) > 1 else DEFAULT_TIME_FILTER

        if not self.is_valid_time_filter(time_filter):
            player.tell(f"Invalid time filter: ^2{time_filter}^7.")
            player.tell(f"Available time filters: ^6{HIGHLITHED_LIST_ENTRIES_SEPARATOR.join(AVAILABLE_TIME_FILTERS)}")
            return

        weapons = ",".join(RELEVANT_WEAPONS)

        self.request_stats(player, time_filter, weapons)

    def handle_stats_request(self, data, player):
        stats_data = data.get("data", [])

        if not stats_data:
            player.tell("No stats data available for this period! Play more games!")
            return

        stats = stats_data[0]

        stats_message = self.colorize_stats(stats, player)
        player.tell(f"{stats_message}")

    def colorize_stats(self, stats, player):
        def get_color(value):
            if value is None or value == "":
                return "^7-"
            try:
                value = float(value)
            except ValueError:
                return "^7-"

            if value > 35:
                return f"^2{value}"
            elif value >= 30:
                return f"^3{value}"
            else:
                return f"^1{value}"

        stat_names = ["avg", "lg", "gl", "rl", "rg", "pg", "mg", "hmg", "sg"]
        colored_stats = [f"^7{stat}: {get_color(stats.get(stat))}" for stat in stat_names]

        return ", ".join(colored_stats)

    def request_url(self, lb_type, time_filter, weapons, medals, formatted_table="true", limit=DEFAULT_LIMIT):
        if time_filter == "all":
            time_filter = "all_time"
        return f"{self.leaderboards_host}/leaderboards/{lb_type}?time_filter={time_filter}&weapons={weapons}&medals={medals}&formatted_table={formatted_table}&limit={limit}"

    def handle_team_switch(self, player, old_team, new_team):
        url = self.request_url("best", "day", "", "", "false", 3)
        self.fetch(url, self.show_best_players, player)

    def show_best_players(self, data, player):
        if not data:
            player.tell("Failed to fetch data.")
            return

        top_names = ""
        for i, player_data in enumerate(data.get("data", [])):
            player_name = player_data.get("name", "Unknown")
            player_name = self.strip_formatting(player_name)
            player_name = self.truncate(player_name, 15)
            strength = player_data.get("strength")

            top_names += f"{i + 1}. ^2{player_name}^7 (strength ^3{strength}^7)\n"

        if not top_names:
            top_names = "Play more games!"

        time.sleep(1)

        player.center_print(f"\n\nToday's ^3BEST^7 players:\n\n{top_names}")

    # Helper functions

    def strip_formatting(self, text):
        return re.sub(r"\^.", "", text)

    def truncate(self, text, length):
        return text[:length] if len(text) > length else text

    @minqlx.thread
    def fetch(self, endpoint, callback, *args, **kwargs):
        cache_key = LEADERBOARD_CACHE_KEY.format(endpoint)
        cached_raw = self.db.get(cache_key)
        if cached_raw:
            try:
                cached = json.loads(cached_raw)
                cached_date = datetime.fromisoformat(cached["date"])
                if (datetime.utcnow() - cached_date).total_seconds() <= CACHE_DURATION_IN_SECONDS:
                    self.logger.info(f"Using cached data for {endpoint}")
                    return callback(cached["data"], *args, **kwargs)
            except Exception as e:
                self.logger.warning(f"Cache parse failed for {endpoint}: {e}")

        self.logger.info(f"Fetching {endpoint}")

        try:
            response = requests.get(endpoint)
            if response.status_code != requests.codes.ok:
                self.logger.error(f"Failed to fetch {endpoint}: {response.status_code}")
                return callback(None, *args, **kwargs)

            data = response.json()
            payload = {
                "data": data,
                "date": datetime.utcnow().isoformat()
            }
            self.db.set(cache_key, json.dumps(payload))
            callback(data, *args, **kwargs)
        except Exception as e:
            self.logger.exception(f"Error fetching {endpoint}: {e}")
            callback(None, *args, **kwargs)

    @minqlx.thread
    def send_multiline_message(self, player, message):
        for line in message.splitlines():
            time.sleep(0.01)
            player.tell(line)

        if len(message.splitlines()) > 1:
            for _ in range(5):
                player.tell(" ")

            player.tell("Check the console to see the leaderboard!")
