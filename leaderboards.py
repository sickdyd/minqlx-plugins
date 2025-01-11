import minqlx
import time
import re
import requests
from datetime import datetime, timedelta

RELEVANT_WEAPONS = ["lightning", "grenade", "rocket", "railgun", "plasma", "machinegun", "hmg", "shotgun"]
SNIPER_MEDALS = ["accuracy", "headshot", "impressive",]
ATTACKER_MEDALS = ["excellent", "firstfrag", "midair", "revenge"]
LEADERBOARS_HOST = "http://localhost:3000/api/v1"

class leaderboards(minqlx.Plugin):
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost") or LEADERBOARS_HOST
        self.logger.info(f"Leaderboards host: {self.leaderboards_host}")

        self.add_command("lb", self.cmd_leaderboard, priority=minqlx.PRI_HIGH, usage = "!lb <type> <timeframe>")

    def cmd_leaderboard(self, player, msg, channel):
        lb_type = msg[1].lower()
        time_filter = "month"
        self.logger.info(f"Leaderboard type: {lb_type}, time_filter: {time_filter}")

        if lb_type == "accuracy":
            weapons = ",".join(RELEVANT_WEAPONS)
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?time_filter={time_filter}&weapons={weapons}&formatted_table=true"
            self.fetch(url, self.handle_accuracy_leaderboard, player, lb_type, time_filter)

    def handle_accuracy_leaderboard(self, data, player, lb_type, time_filter):
        table_data = data.get("data", [])
        self.send_multiline_message(player, table_data)

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
