import minqlx
import time
import re
import requests
from datetime import datetime, timedelta

RELEVANT_WEAPONS = {
    "lightning": "LG",
    "grenade": "GL",
    "railgun": "RG",
    "plasma": "PG",
    "rocket": "RL",
    "machinegun": "MG",
    "hmg": "HMG",
    "shotgun": "SG",
}

SNIPER_MEDALS = ["accuracy", "headshot", "impressive",]
ATTACKER_MEDALS = ["excellent", "firstfrag", "midair", "revenge"]
VALID_LEADERBOARDS = ["damage_dealt", "damage_taken", "kills", "deaths", "snipers", "attackers", "winners", "losers", "accuracy", "best", "all"]
VALID_TIMEFRAMES = ["day", "week", "month"]

LEADERBOARS_HOST = "https://02d46fb10495.ngrok.app"

class leaderboards(minqlx.Plugin): 
    def __init__(self):
        self.leaderboards_host = self.get_cvar("qlx_qloveLeaderboardsHost") or LEADERBOARS_HOST
        self.logger.info(f"Leaderboard host set to: {self.leaderboards_host}")
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_command(
            "lb",
            self.cmd_leaderboard,
            priority=minqlx.PRI_HIGH,
            usage = (
                "!lb <type> <timeframe>\n"
                f"Available types: {', '.join(f'^6{lb}^7' for lb in VALID_LEADERBOARDS)}\n"
                f"Timeframes: {', '.join(f'^6{tf}^7' for tf in VALID_TIMEFRAMES)}\n"
                "Example: ^6!lb kills day^7"
            )
        )
        self.add_command(("leaderboard", "leaderboards"), self.cmd_leaderboard, priority=minqlx.PRI_HIGH)

    def cmd_leaderboard(self, player, msg, channel):
        self.usage(player)

    def usage(self, player):
        self.send_multiline_message(
            player,
            f"Usage: ^2!lb <type> <timeframe>^7\n\n"
            f"Available types: {', '.join(f'^6{lb}^7' for lb in VALID_LEADERBOARDS)}\n"
            f"Timeframes: {', '.join(f'^6{tf}^7' for tf in VALID_TIMEFRAMES)}\n"
            "Example: ^2!lb kills week^7\n"
            "Check the console to see how to use the command."
        )

    def cmd_leaderboard(self, player, msg, channel):
        if len(msg) < 2:
            self.usage(player)
            return minqlx.RET_STOP_ALL

        if not self.leaderboards_host:
            player.tell("ERROR: Please set the ^6qlx_qloveLeaderboardsHost^7 cvar to point to the stats server.")
            return minqlx.RET_STOP_ALL

        lb_type = msg[1].lower()
        timeframe = msg[2].lower() if len(msg) > 2 else "day"

        if lb_type not in VALID_LEADERBOARDS:
            player.tell(
                f"Invalid leaderboard type. Available types: {', '.join(f'^2{lb}^7' for lb in VALID_LEADERBOARDS)}"
            )
            self.usage(player)
            return minqlx.RET_STOP_ALL

        if timeframe not in VALID_TIMEFRAMES:
            player.tell(
                f"Invalid timeframe. Available timeframes: {', '.join(f'^2{tf}^7' for tf in VALID_TIMEFRAMES)}"
            )
            self.usage(player)
            return minqlx.RET_STOP_ALL

        if lb_type == "accuracy":
            weapons = ",".join(RELEVANT_WEAPONS.keys())
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}&weapons={weapons}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "damage_dealt":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "damage_taken":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "kills":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "deaths":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "snipers":
            url = f"{self.leaderboards_host}/leaderboards/medals?timeframe={timeframe}&medals={','.join(SNIPER_MEDALS)}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "attackers":
            url = f"{self.leaderboards_host}/leaderboards/medals?timeframe={timeframe}&medals={','.join(ATTACKER_MEDALS)}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "winners":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "losers":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

        if lb_type == "best":
            url = f"{self.leaderboards_host}/leaderboards/{lb_type}?timeframe={timeframe}"
            self.fetch(url, self.handle_leaderboard, player, lb_type, timeframe)

    def handle_leaderboard(self, data, player, lb_type, timeframe):
        if not data:
            player.tell("Failed to fetch data.")
            return

        if lb_type == "accuracy":
            self.handle_accuracy_leaderboard(data, player, timeframe)

        if lb_type == "damage_dealt":
            self.handle_damage_dealt_leaderboard(data, player, timeframe)

        if lb_type == "damage_taken":
            self.handle_damage_taken_leaderboard(data, player, timeframe)

        if lb_type == "kills":
            self.handle_kills_leaderboard(data, player, timeframe)

        if lb_type == "deaths":
            self.handle_death_leaderboard(data, player, timeframe)

        if lb_type == "snipers":
            self.handle_medals_leaderboard(data, player, timeframe, "snipers")

        if lb_type == "attackers":
            self.handle_medals_leaderboard(data, player, timeframe, "attackers")

        if lb_type == "winners":
            self.handle_winners_leaderboard(data, player, timeframe)

        if lb_type == "losers":
            self.handle_losers_leaderboard(data, player, timeframe)

        if lb_type == "best":
            self.handle_best_leaderboard(data, player, timeframe)

        player.tell("Open the console to check the results!")
        return minqlx.RET_STOP_ALL

    def handle_accuracy_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "AVG"] + list(RELEVANT_WEAPONS.values())
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            average_accuracy = player_data.get("average_accuracy", "-")
            weapons = player_data.get("weapons", {})

            row = [i + 1, player_name, average_accuracy]
            for weapon in RELEVANT_WEAPONS:
                row.append(weapons.get(weapon, "-"))

            rows.append(row)

        title = f"Accuracy {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_damage_dealt_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Damage Dealt", "Damage Taken"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            damage_dealt = player_data.get("total_damage_dealt", "-")
            damage_taken = player_data.get("total_damage_taken", "-")

            row = [i + 1, player_name, damage_dealt, damage_taken]
            rows.append(row)

        title = f"Damage dealt {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_damage_taken_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Damage Dealt", "Damage Taken"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            damage_dealt = player_data.get("total_damage_dealt", "-")
            damage_taken = player_data.get("total_damage_taken", "-")

            row = [i + 1, player_name, damage_dealt, damage_taken]
            rows.append(row)

        title = f"Damage taken {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_kills_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Kills", "Deaths", "K/D"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            kills = player_data.get("total_kills", "-")
            deaths = player_data.get("total_deaths", "-")
            kdr = player_data.get("kill_death_ratio", "-")

            row = [i + 1, player_name, kills, deaths, kdr]
            rows.append(row)

        title = f"Kills {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_death_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Kills", "Deaths", "K/D"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            kills = player_data.get("total_kills", "-")
            deaths = player_data.get("total_deaths", "-")
            kdr = player_data.get("kill_death_ratio", "-")

            row = [i + 1, player_name, kills, deaths, kdr]
            rows.append(row)

        title = f"Deaths {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_medals_leaderboard(self, data, player, timeframe, medal_type):
        data = data.get("data", [])

        if medal_type == "snipers":
            medals = SNIPER_MEDALS
        else:
            medals = ATTACKER_MEDALS

        headers = ["#", "Player"] + medals
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]

            row = [i + 1, player_name]
            for medal in medals:
                row.append(player_data.get("medals", {}).get(medal, "-"))

            rows.append(row)

        title = f"{medal_type} medals {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_winners_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Wins", "Losses", "W/L"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            wins = player_data.get("total_wins", "-")
            losses = player_data.get("total_losses", "-")
            wlr = player_data.get("win_loss_ratio", "-")

            row = [i + 1, player_name, wins, losses, wlr]
            rows.append(row)

        title = f"Top players by wins {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_losers_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Wins", "Losses", "W/L"]
        rows = []
        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]
            wins = player_data.get("total_wins", "-")
            losses = player_data.get("total_losses", "-")
            wlr = player_data.get("win_loss_ratio", "-")

            row = [i + 1, player_name, wins, losses, wlr]
            rows.append(row)

        title = f"Top players by losses {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    def handle_best_leaderboard(self, data, player, timeframe):
        data = data.get("data", [])

        headers = ["#", "Player", "Accuracy", "Damage", "Kills", "Games", "Final Score"]
        rows = []

        for i, player_data in enumerate(data):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]

            average_accuracy = player_data.get("average_accuracy", "-")
            damage_given = player_data.get("total_damage_given", "-")
            kills = player_data.get("total_kills", "-")
            games = player_data.get("total_games", "-")
            final_score = player_data.get("final_score", "-")

            row = [i + 1, player_name, average_accuracy, damage_given, kills, games, final_score]
            rows.append(row)

        title = f"Best players {self.format_timeframe(timeframe)}"

        self.send_multiline_message(player, self.table(headers, rows, title))

    #
    # HOOKS
    #

    def handle_team_switch(self, player, old_team, new_team):
        url = f"{self.leaderboards_host}/leaderboards/best?timeframe=day&limit=3"
        self.fetch(url, self.show_top_players, player, "best", "day")

    def show_top_players(self, data, player, lb_type, timeframe):
        if not data:
            player.tell("Failed to fetch data.")
            return

        top_names = ""
        for i, player_data in enumerate(data.get("data", [])):
            player_name = player_data.get("player_name", "Unknown")
            player_name = self.strip_formatting(player_name)
            if len(player_name) > 15:
                player_name = player_name[:15]

            final_score = player_data.get("final_score", "-")

            top_names += f"{i + 1}. {player_name} (score {final_score})\n"

        time.sleep(4)

        player.center_print(f"\n\nToday's ^3BEST^7 players:\n\n{top_names}")

    #
    # UTILS
    #

    def format_timeframe(self, timeframe):
        if timeframe == "day":
            return "today"
        if timeframe == "week":
            return "this week"
        if timeframe == "month":
            return "this month"
        return timeframe

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

    def strip_formatting(self, text):
        return re.sub(r"\^\d", "", str(text))

    def send_multiline_message(self, player, message):
        for line in message.splitlines():
            player.tell(line)

    def table(self, headers, rows, title=None):
        """
        Given a list of headers and a list of rows, return a formatted table with a title, separators for each row, and a closing separator line.
        """
        if not headers or not rows:
            return "No data to display."

        MIN_COLUMN_WIDTH = 3

        max_lengths = [max(len(header), MIN_COLUMN_WIDTH) for header in headers]
        for row in rows:
            for i, cell in enumerate(row):
                max_lengths[i] = max(max_lengths[i], len(self.strip_formatting(cell)))

        header_line = "| " + " | ".join(header.ljust(max_lengths[i]) for i, header in enumerate(headers)) + " |"
        separator_line = "+-" + "-+-".join("-" * length for length in max_lengths) + "-+"

        row_lines = []
        for row in rows:
            formatted_row = "| " + " | ".join(
                f"{self.strip_formatting(cell)}{' ' * (max_lengths[i] - len(self.strip_formatting(cell)))}"
                for i, cell in enumerate(row)
            ) + " |"
            row_lines.append(formatted_row)

        if title:
            total_table_width = len(separator_line)
            centered_title = f"{title}".center(total_table_width - 2)
            title_line = f"+{'-' * (total_table_width - 2)}+\n|{centered_title}|\n{separator_line}\n"
        else:
            title_line = ""

        return title_line + "\n".join([header_line, separator_line] + row_lines + [separator_line])
