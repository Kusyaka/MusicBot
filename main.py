import asyncio
from discord import Embed
import os
import random
import discord
from discord.ext import commands
from discord import Message
import time

from selenium import webdriver
from bs4 import BeautifulSoup
import json

from youtube_dl import YoutubeDL

config = None

class Config:
    def __init__(self, config_dict: dict = None, **kwargs):
        if config_dict is not None:
            for arg in config_dict.keys():
                self.__setattr__(arg, config_dict[arg])

        for arg in kwargs.keys():
            self.__setattr__(str(arg), kwargs[arg])


class CommandsHandler:
    def __init__(self, bot, config):
        self._bot = bot
        self._config = config

        self._fr = open("autoplay", "r")

        self._autoplay = False if int(self._fr.read()) == 0 else True

        del self._fr
        self._last_url = ""
        self._is_command = False

        self._music_queue = []
        self._is_playing = False

        self._YTDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist':'True'}

        self._FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                               'options': '-vn'}
        self._vc: discord.VoiceClient = None

    async def process_commands(self, message: Message):
        if not str(message.content).startswith(config.prefix):
            return
        command = str(message.content).split(" ")
        command_name = command[0].replace(config.prefix, "")
        if command_name.startswith("_"):
            return
        # command_method = self.commands[command_name]
        command_method = getattr(self, command_name)
        command_ctx = await self._bot.get_context(message)
        command_args = [command_ctx]
        for a in command[1:]:
            command_args.append(a)
        await command_method(*tuple(command_args))

    async def play(self, ctx: commands.Context, *args):
        url = " ".join(args)

        def search_yt(item):
            with YoutubeDL(self._YTDL_OPTIONS) as ytdl:
                try:
                    info = ytdl.extract_info(f"ytsearch:{item}", download=False)['entries'][0]
                    self._last_url = f"https://www.youtube.com/watch?v={info['id']}"
                    video_format = None

                    if 'entries' in info:
                        video_format = info['entries'][0]["formats"][0]
                    elif 'formats' in info:
                        video_format = info["formats"][0]

                except Exception:
                    return False, False

            return video_format, info['title']

        def get_ytdl(url):
            with YoutubeDL(self._YTDL_OPTIONS) as ytdl:
                try:
                    video_format = None
                    info = ytdl.extract_info(url, download=False)
                    if 'entries' in info:
                        video_format = info['entries'][0]["formats"][0]["url"]
                    elif 'formats' in info:
                        video_format = info["formats"][0]["url"]

                except Exception:
                    return False, False

            return video_format, info['title']


        if (url.startswith("https://") or url.startswith("www.")):
            turl, title = get_ytdl(url)
            self._last_url = url
        else:
            turl, title = search_yt(url)
        if type(turl) == bool:
            await ctx.send(f"Can`t find {url}")
            return

        url = turl

        voice_channel = ctx.author.voice.channel
        if voice_channel is None:
            await ctx.send("You are not in the voice channel")
            return

        await ctx.send("Song added to queue")
        self._music_queue.append([url, voice_channel, title])
        if not self._is_playing:
            await self._play_music(ctx)

    async def skip(self, ctx):
        await self._play_next(ctx)

    async def stop(self, ctx):
        self._vc.stop()
        self._last_url = ""
        self._music_queue = []
        self._is_playing = False

    async def leave(self, ctx):
        await self.stop(ctx)
        await self._vc.disconnect()


    async def autoplay(self, ctx):
        await self.auto(ctx)

    async def auto(self, ctx):
        self._autoplay = not self._autoplay
        fw = open("autoplay", "w")
        fw.write("1" if self._autoplay else "0")
        await ctx.send("Autoplay enabled") if self._autoplay else await ctx.send("Autoplay disabled")

    async def __autoplay(self, ctx):

        def get_ytdl(url):
            with YoutubeDL(self._YTDL_OPTIONS) as ytdl:
                try:
                    video_format = None
                    info = ytdl.extract_info(url, download=False)
                    if 'entries' in info:
                        video_format = info['entries'][0]["formats"][0]
                    elif 'formats' in info:
                        video_format = info["formats"][0]

                except Exception:
                    return False, False

            return video_format, info['title']

        browser = webdriver.Firefox(service_log_path=os.path.devnull)
        browser.get(self._last_url)
        await asyncio.sleep(3)
        data = browser.page_source
        browser.close()

        soup = BeautifulSoup(data, 'html.parser')
        a = soup.find_all("a", {"class": "yt-simple-endpoint inline-block style-scope ytd-thumbnail"})
        links = []
        for i in a[1:]:
            links.append(f"https://www.youtube.com{i.get('href')}")
        self._last_url = links[random.randint(0, 4 if len(links)-1 > 4 else len(links)-1)]
        url, title = get_ytdl(self._last_url)
        self._music_queue.append([url, self._vc.channel, title])
        await self._play_music(ctx)

    async def _pl(self, ctx):
        await self._play_next(ctx)

    async def _play_next(self, ctx):
        self._vc.stop()
        if len(self._music_queue) > 0:
            self._is_playing = True

            m_url = self._music_queue[0][0]
            self._music_queue.pop(0)

            # self._vc.play(discord.FFmpegPCMAudio(m_url, **self._FFMPEG_OPTIONS))
            self._vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS))
            while self._vc.is_playing():
                await asyncio.sleep(1)
            await self._play_next(ctx)

        else:
            if not self._is_playing:
                return
            print(f"autoplay: {self._autoplay}")
            if self._autoplay and not self._vc.is_playing():
                await self.__autoplay(ctx)
                return
            self._is_playing = False

    async def _play_music(self, ctx):
        if len(self._music_queue) > 0:
            self._is_playing = True

            m_url = self._music_queue[0][0]

            if self._vc is None or not self._vc.is_connected():
                self._vc = await self._music_queue[0][1].connect()

            self._music_queue.pop(0)

            self._vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS))
            while self._vc.is_playing():
                await asyncio.sleep(1)
            await self._play_next(ctx)
        else:
            self._is_playing = False



class EventHandler(commands.Cog):
    def __init__(self, bot: commands.Bot, config: Config):
        self.bot = bot
        self.conf = config
        self.command_handler = CommandsHandler(bot, config)

    @commands.Cog.listener()
    async def on_connected(self):
        print("Connected")

    @commands.Cog.listener()
    async def on_message(self, message):
        # print(message)
        await self.command_handler.process_commands(message)


with open('config.json') as f:
    globals()["config"] = Config(json.load(f))

bot = commands.Bot(command_prefix=config.prefix, self_bot=True)
bot.add_cog(EventHandler(bot, config))
bot.run(config.token, bot=False)
