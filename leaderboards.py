import minqlx
import time
import re
import requests
from datetime import datetime, timedelta

RELEVANT_WEAPONS = ["lightning", "grenade", "rocket", "railgun", "plasma", "machinegun", "hmg", "shotgun"]
# SNIPER_MEDALS = ["accuracy", "headshot", "impressive",]
# ATTACKER_MEDALS = ["excellent", "firstfrag", "midair", "revenge"]
RELEVANT_MEDALS = ["accuracy", "impressive", "excellent", "midair",]
AVAILABLE_LEADERBOARDS = ["accuracy", "best", "damage", "damage_taken", "kills", "deaths", "medals", "wins", "losses"]
AVAILABLE_TIME_FILTERS = ["all_time", "monthly", "weekly", "daily"]
LEADERBOARS_HOST = "http://qlove_api:3000/api/v1"

class leaderboards(minqlx.Plugin):
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost") or LEADERBOARS_HOST

        self.add_command("lb", self.cmd_leaderboard, priority=minqlx.PRI_HIGH, usage = "!lb <type> <timeframe>")

    def cmd_leaderboard(self, player, msg, channel):
        lb_type = msg[1].lower()
        time_filter = msg[2].lower() if len(msg) > 2 else "day"

        if lb_type == "help":
            return player.tell(f"Usage: !lb <type> <timeframe>\nAvailable leaderboards: {', '.join(AVAILABLE_LEADERBOARDS)}\nAvailable timeframes: {', '.join(AVAILABLE_TIME_FILTERS)}")

        if not self.is_valid_time_filter(time_filter):
            return player.tell(f"Invalid time filter: {time_filter}. Available time filters: {', '.join(AVAILABLE_TIME_FILTERS)}")

        if not self.is_valid_leaderboard(lb_type):
            return player.tell(f"Invalid leaderboard type: {lb_type}. Available leaderboards: {', '.join(AVAILABLE_LEADERBOARDS)}")

        weapons = ",".join(RELEVANT_WEAPONS)
        medals = ",".join(RELEVANT_MEDALS)

        self.logger.info(f"Leaderboard type: {lb_type}, time_filter: {time_filter}")
        url = f"{self.leaderboards_host}/leaderboards/{lb_type}?time_filter={time_filter}&weapons={weapons}&medals={medals}&formatted_table=true"
        self.fetch(url, self.handle_leaderboard_request, player)

    def is_valid_leaderboard(self, lb_type):
        return lb_type in AVAILABLE_LEADERBOARDS

    def is_valid_time_filter(self, time_filter):
        return time_filter in AVAILABLE_TIME_FILTERS

    def handle_leaderboard_request(self, data, player):
        table_data = data.get("data", [])
        self.send_multiline_message(player, table_data)

    def handle_team_switch(self, player):
        url = f"{self.leaderboards_host}/leaderboards/{lb_type}?time_filter={time_filter}&weapons={weapons}&medals={medals}&formatted_table=true"
        self.fetch(url, self.show_best_players, player)

    def show_best_players(self, data, player):
        table_data = data.get("data", [])
        
        player.center_print(f"\n\nToday's ^3BEST^7 players:\n\n{top_names}")

    # Helper functions

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

    @minqlx.thread
    def send_multiline_message(self, player, message):
        for line in message.splitlines():
            time.sleep(0.01)
            player.tell(line)
