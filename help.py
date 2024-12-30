import minqlx

class help(minqlx.Plugin):
    def __init__(self):
        self.add_command("help", self.cmd_help, priority=minqlx.PRI_HIGH, usage="Shows available commands.")

    def cmd_help(self, player, msg, channel):
        contents = "All commands are related to the last 10 games:\n^6!stats^7: view your local stats^7\n^6!qlstats^7: view your stats on QLstats.net\n^6!lb accuracy^7: view accuracy leaderboard\n^6!lb damage^7: view damage leaderboard\n^6!lb kills^7: view kills leaderboard\n^6!lb deaths^7: view deaths leaderboard\n^6!lb winners^7: view winners leaderboard\n^6!lb losers^7: view losers leaderboard\n^6!lb snipers^7: view snipers leaderboard\n^6!lb attackers^7: view attackers leaderboard\n^6!lb all^7: view all leaderboards.\nCheck the console to see a list of commands!"
        for line in contents.split("\n"):
            player.tell(line)
        return minqlx.RET_STOP_ALL
