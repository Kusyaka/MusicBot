import discord

import music

from utils import *

with open('config.json') as f:
    config = Config(json.load(f))

loop = asyncio.get_event_loop()
bots = {}


class BaseCog(commands.Cog):
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} ready")
        servers = get_servers_data(self.bot.user.id)
        loop = asyncio.get_event_loop()
        try:
            p = servers[self.bot.user.id].presence
            loop.create_task(self.bot.change_presence(activity=discord.Activity(
                type=discord.ActivityType.__getattribute__(discord.ActivityType, p['type']),
                name=p['name'], url=p['url'])))

        except AttributeError:
            print(f"No activity for {self.bot.user}")

    @commands.command()
    async def status(self, ctx: commands.Context, st_type: str, n, u=None):
        if ctx.author.id not in self.config.owners:
            return
        st_type = st_type.lower()
        if st_type not in ["playing", "streaming", "listening", "watching"]:
            await ctx.send(
                "Incorrect status type, allowed only **playing**, **streaming**, **listening** or **watching**")
            return

        a_type = discord.ActivityType.__getattribute__(discord.ActivityType, st_type)

        url = None

        cmd = ctx.message.content
        cmd = cmd.split(" ")
        del cmd[0]
        del cmd[0]
        if st_type == "streaming":
            url = cmd[len(cmd) - 1]
            del cmd[len(cmd) - 1]
        name = " ".join(cmd)

        if st_type == "streaming" and url is None and name != "":
            await ctx.send("Url required")
            return
        activity = discord.Activity(type=a_type, name=name, url=url)
        await self.bot.change_presence(activity=activity)
        servers = get_servers_data(self.bot.user.id)
        servers[self.bot.user.id].presence = {"type": st_type, "name": name, "url": url}
        save_servers_data(servers)

    @commands.guild_only()
    @commands.command()
    async def prefix(self, ctx: commands.Context, prefix):
        if ctx.author.id not in self.config.owners:
            return

        servers = get_servers_data(ctx.guild.id)
        servers[ctx.guild.id].prefix = prefix
        save_servers_data(servers)


for token in config.tokens:
    bot = commands.Bot(command_prefix=determine_prefix)
    bot.add_cog(BaseCog(bot, config))
    excepts = config.tokens[token]
    if "Music" in config.tokens[token] or "All" in config.tokens[token]:
        bot.add_cog(music.Music(bot, config))
    bots[token] = bot


tasks = []

for token in bots:
    tasks.append(loop.create_task(bots[token].start(token)))

gathered = asyncio.gather(*tasks, loop=loop)
loop.run_until_complete(gathered)
