import minqlx

class help(minqlx.Plugin):
    def __init__(self):
        self.add_command("help", self.cmd_help, priority=minqlx.PRI_HIGH, usage="Shows available commands.")

    def cmd_help(self, player, msg, channel):
        player.tell("Available commands:")
        player.tell("^6!stats^7, ^6!qlstats^7 - Shows current player accuracy from last 10 CA games from local data or QLstats.net.")
        return minqlx.RET_STOP_ALL
