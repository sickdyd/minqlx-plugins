import minqlx
import time
import re
import threading
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
CACHE_DURATION_IN_SECONDS = 60
LEADERBOARD_CACHE_KEY = "lb:{}"

class leaderboards(minqlx.Plugin):
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost")
        self.logger.info(f"Leaderboards host: {self.leaderboards_host}")

        self.add_command("help", self.cmd_help, priority=minqlx.PRI_HIGH, usage="!help")
        self.add_command("stats", self.cmd_stats, priority=minqlx.PRI_HIGH, usage=f"!stats [{TIME_FILTER_ARG}]")
        self.add_command("clear_cache", self.cmd_clear_cache, permission="admin", usage = "!clear_cache")
        for lb in AVAILABLE_LEADERBOARDS:
            self.add_command(lb, self.cmd_leaderboard, priority=minqlx.PRI_HIGH, usage=f"!{lb} [{TIME_FILTER_ARG}]")
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("game_end", self.handle_game_end)
        self._in_flight_callbacks = {}
        self._in_flight_lock = threading.Lock()

    @minqlx.thread
    def cmd_help(self, player, msg, channel):
        self.help_message(player)

    def help_message(self, player):
        player.tell("---------------- leaderboards help -----------")
        player.tell("^2COMMANDS^7:")
        player.tell("  ^2!<leaderboard> ^7[^2time^7]  ^7— show a leaderboard")
        player.tell("  ^2!stats ^7[^2time^7]          ^7— show your personal accuracy stats")
        player.tell("  ^2!all ^7[^2time^7]            ^7— show all leaderboards")
        player.tell("  ^2!help                ^7— show this message")
        player.tell(f"^2LEADERBOARDS^7: ^2accuracy ^7| ^2best ^7| ^2damage ^7| ^2damage_taken ^7| ^2kills ^7| ^2deaths")
        player.tell(f"             ^2snipers ^7| ^2attackers ^7| ^2wins ^7| ^2losses ^7| ^2all")
        player.tell(f"^2TIME FILTERS^7:  ^2{TIME_FILTER_ARG}")
        player.tell("^2EXAMPLE^7: ^1!accuracy week^7, ^1!kills day^7, ^1!snipers month")
        player.tell("^2NOTE^7: Names with ideograms won't display correctly in tables.")
        player.tell("----------------------------------------------")
        player.tell("Check the console to see the help!")

    def plugin_load(self):
        self.handle_game_end(None)

    def cmd_clear_cache(self, player, msg, channel):
        self.logger.info("Clearing leaderboard cache.")

        keys = self.db.keys("lb:*")
        if keys:
            self.db.delete(*keys)

    @minqlx.thread
    def handle_game_end(self, data):
        time.sleep(5)
        self.cmd_clear_cache(None, None, None)
        time.sleep(1)
        url = self.request_url("best", "day", "", "", "false", DEFAULT_LIMIT)
        self.fetch(url, lambda *a, **kw: None)

    def cmd_leaderboard(self, player, msg, channel):
        lb_type = msg[0].lstrip("!").lower()
        time_filter = msg[1].lower() if len(msg) > 1 else DEFAULT_TIME_FILTER

        if not self.is_valid_leaderboard(lb_type) or not self.is_valid_time_filter(time_filter):
            self.help_message(player)
            return

        weapons = "" if lb_type == "best" else ",".join(RELEVANT_WEAPONS)
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
            lb_type = lb
            lb_medals = medals
            if lb == "snipers":
                lb_type = "medals"
                lb_medals = ",".join(SNIPER_MEDALS)
            elif lb == "attackers":
                lb_type = "medals"
                lb_medals = ",".join(ATTACKER_MEDALS)
            url = self.request_url(lb_type, time_filter, weapons, lb_medals)
            data = self._fetch_sync(url)
            table_data = data.get("data", []) if data else []
            if table_data:
                self._send_multiline_sync(player, table_data)
            time.sleep(0.2)

    def request_leaderboard(self, player, lb_type, time_filter, weapons, medals):
        url = self.request_url(lb_type, time_filter, weapons, medals)
        self.fetch(url, self.handle_leaderboard_request, player)

    def request_stats(self, player, time_filter, weapons):
        if time_filter == "all":
            time_filter = "all_time"
        url = f"{self.leaderboards_host}/api/v1/stats?steam_id={player.steam_id}&time_filter={time_filter}&weapons={weapons}"
        self.fetch(url, self.handle_stats_request, player)

    def is_valid_leaderboard(self, lb_type):
        return lb_type in AVAILABLE_LEADERBOARDS + ["all"]

    def is_valid_time_filter(self, time_filter):
        return time_filter in AVAILABLE_TIME_FILTERS

    def handle_leaderboard_request(self, data, player):
        table_data = data.get("data", []) if data else []

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
        stats_data = data.get("data", {}) if data else {}

        if not stats_data:
            player.tell("No stats data available for this period! Play more games!")
            return

        stats_message = self.colorize_stats(stats_data, player)
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
        params = f"time_filter={time_filter}&formatted_table={formatted_table}&limit={limit}"
        if weapons:
            params += f"&weapons={weapons}"
        if medals:
            params += f"&medals={medals}"
        return f"{self.leaderboards_host}/api/v1/leaderboards/{lb_type}?{params}"

    def handle_team_switch(self, player, old_team, new_team):
        if new_team not in ("red", "blue", "free"):
            return
        url = self.request_url("best", "day", "", "", "false", DEFAULT_LIMIT)
        self.fetch(url, self.show_best_players, player)

    def show_best_players(self, data, player):
        if not data:
            player.tell("Failed to fetch data.")
            return

        top_names = ""
        for i, player_data in enumerate(data.get("data", [])[:3]):
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

    def _fetch_sync(self, endpoint):
        """Fetch endpoint synchronously, returning data or None. Respects cache and in-flight deduplication."""
        cache_key = LEADERBOARD_CACHE_KEY.format(endpoint)
        try:
            cached_raw = self.db.get(cache_key)
            if cached_raw:
                cached = json.loads(cached_raw)
                cached_date = datetime.fromisoformat(cached["date"])
                if (datetime.utcnow() - cached_date).total_seconds() <= CACHE_DURATION_IN_SECONDS:
                    self.logger.info(f"Using cached data for {endpoint}")
                    return cached["data"]
        except Exception as e:
            self.logger.warning(f"Cache read/parse failed for {endpoint}: {e}")

        event = threading.Event()
        result = [None]

        with self._in_flight_lock:
            if endpoint in self._in_flight_callbacks:
                def waiter(data, ev=event, res=result):
                    res[0] = data
                    ev.set()
                self._in_flight_callbacks[endpoint].append((waiter, [], {}))
                self.logger.info(f"Request already in flight for {endpoint}, waiting")
                event.wait(timeout=10)
                return result[0]
            self._in_flight_callbacks[endpoint] = []

        self.logger.info(f"Fetching {endpoint}")

        data = None
        try:
            response = requests.get(endpoint, timeout=5)
            if response.status_code != requests.codes.ok:
                self.logger.error(f"Failed to fetch {endpoint}: {response.status_code}")
            else:
                data = response.json()
                payload = {
                    "data": data,
                    "date": datetime.utcnow().isoformat()
                }
                self.db.set(cache_key, json.dumps(payload), ex=CACHE_DURATION_IN_SECONDS)
        except Exception as e:
            self.logger.exception(f"Error fetching {endpoint}: {e}")
        finally:
            with self._in_flight_lock:
                pending = self._in_flight_callbacks.pop(endpoint, [])
            for cb, a, kw in pending:
                cb(data, *a, **kw)

        return data

    @minqlx.thread
    def fetch(self, endpoint, callback, *args, **kwargs):
        data = self._fetch_sync(endpoint)
        callback(data, *args, **kwargs)

    def _send_multiline_sync(self, player, message):
        for line in message.splitlines():
            time.sleep(0.01)
            player.tell(line)

        if len(message.splitlines()) > 1:
            for _ in range(5):
                player.tell(" ")
            player.tell("Check the console to see the leaderboard!")

    @minqlx.thread
    def send_multiline_message(self, player, message):
        self._send_multiline_sync(player, message)
