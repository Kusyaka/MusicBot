import asyncio
import datetime
import os
import random

import discord
from discord.ext import commands
from discord import Message
import time

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as Options
import json

from youtube_dl import YoutubeDL

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

config = None


class Config:
    def __init__(self, config_dict: dict = None, **kwargs):
        if config_dict is not None:
            for arg in config_dict.keys():
                self.__setattr__(arg, config_dict[arg])

        for arg in kwargs.keys():
            self.__setattr__(str(arg), kwargs[arg])


class Track():
    def __init__(self, config_dict: dict = None, **kwargs):
        if config_dict is not None:
            for arg in config_dict.keys():
                self.__setattr__(arg, config_dict[arg])

        for arg in kwargs.keys():
            self.__setattr__(str(arg), kwargs[arg])

    def set_data(self, name: str, value):
        self.__setattr__(name, value)


class CommandsHandler:
    def __init__(self, bot, config):
        self._bot = bot
        self._config = config
        auth = SpotifyClientCredentials(client_id="3ac5c7d1174e486d94ea70af4799fd7f",
                                        client_secret="8f1047b890be4c859d5e1e36dc09300e")
        self._sp: spotipy.Spotify = spotipy.Spotify(auth_manager=auth)
        self._fr = open("autoplay", "r")

        self._autoplay = False if int(self._fr.read()) == 0 else True

        del self._fr
        self._last_url = ""
        self._is_command = False

        self._music_queue = []
        self._is_playing = False

        self._YTDL_OPTIONS = {'format': 'bestaudio/best'}

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

    async def queue(self, ctx: commands.Context):
        txt = ""
        for i, q in enumerate(self._music_queue):
            txt += f"{i+1}. **{q.title}**\n"

        await ctx.send(txt)

    async def play(self, ctx: commands.Context, *args):
        url = " ".join(args)

        def search_yt(item):
            with YoutubeDL(self._YTDL_OPTIONS) as ytdl:
                try:
                    data = ytdl.extract_info(f"ytsearch:{item}", download=False)['entries'][0]
                    self._last_url = f"https://www.youtube.com/watch?v={data['id']}"

                    if "_type" in data:
                        tracks = []
                        for e in data["entries"]:
                            tracks.append(Track(media_url=e["formats"][0]["url"], title=e['title'], url=e['webpage_url'], thumbnail=e['thumbnail'], duration=e['duration']))
                        return [data["title"], data["webpage_url"], tracks]

                    return Track(media_url=data['url'], title=data['title'], url=data['webpage_url'],
                                 thumbnail=data['thumbnail'], duration=data['duration'])
                except Exception:
                    return False



        def get_ytdl(url):
            with YoutubeDL(self._YTDL_OPTIONS) as ytdl:
                try:
                    data = ytdl.extract_info(url, download=False)
                    if "_type" in data:
                        tracks = []
                        for e in data["entries"]:
                            tracks.append(
                                Track(media_url=e["formats"][0]["url"], title=e['title'], url=e['webpage_url'],
                                      thumbnail=e['thumbnail'], duration=e['duration']))
                        return [data["title"], data["webpage_url"], tracks]

                    return Track(media_url=data['url'], title=data['title'], url=data['webpage_url'],
                                 thumbnail=data['thumbnail'], duration=data['duration'])

                except Exception:
                    return False


        wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время", color=0x46c077)
        wait_msg = await ctx.send(embed=wait_msg)



        voice_channel = ctx.author.voice.channel

        if voice_channel is None:
            embed = discord.Embed(title="Вы не в голосовом канале ", color=0xffff00)
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=5)
            return

        if url.startswith("https://www.youtube") or url.startswith("www.youtube"):
            track = get_ytdl(url)
            self._last_url = url
        else:
            track = search_yt(url)
        if type(track) == bool:
            embed = discord.Embed(title="Не найдено", description=url, color=0xff0000)
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=5)
            return

        if type(track) == list:
            for t in track[2]:
                self._music_queue.append(t)

            embed = discord.Embed(title=track[0], url=track[1],
                                  description="Добавлен в очередь", color=0x46c077)
            embed.set_thumbnail(url=track[2][0].thumbnail)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title=track.title, url=track.url,
                                  description="Добавлен в очередь", color=0x46c077)
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.send(embed=embed)
            track.set_data("voice_channel", voice_channel)
            self._music_queue.append(track)

        await wait_msg.delete()

        if not self._is_playing:
            await self._play_music(ctx)

    async def skip(self, ctx):
        self._vc.stop()

    async def stop(self, ctx):
        self._vc.stop()
        self._last_url = ""
        self._music_queue = []
        self._is_playing = False

        await ctx.send("Остановлено")

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
            with YoutubeDL({'format': 'bestaudio/best', 'noplaylist': 'True'}) as ytdl:
                try:
                    video_format = None
                    info = ytdl.extract_info(url, download=False)
                    if "_type" in info:
                        return False
                    if 'entries' in info:
                        video_format = info['entries'][0]["formats"][0]["url"]
                    elif 'formats' in info:
                        video_format = info["formats"][0]["url"]

                except Exception:
                    return False

            return Track(media_url=video_format, title=info['title'], url=info['webpage_url'], thumbnail=info['thumbnail'], duration=info['duration'])

        options = Options()
        options.add_argument("--headless")
        driver = webdriver.Firefox(firefox_options=options, log_path=os.devnull)
        track = None

        while True:
            driver.get(self._last_url)
            time.sleep(2)
            elems = driver.execute_script(
                'return document.getElementsByClassName("yt-simple-endpoint inline-block style-scope ytd-thumbnail")')
            self._last_url = random.choice(elems).get_attribute('href')
            track = get_ytdl(self._last_url)
            if type(track) == bool:
                continue
            break

        await self._wait_msg.delete()

        track.set_data("voice_channel", ctx.author.voice.channel)
        self._music_queue.append(track)

        if self._vc is None or not self._vc.is_connected():
            self._vc = await self._music_queue[0].voice_channel.connect()

        await self._play_next(ctx)

    async def _play_next(self, ctx):
        self._vc.stop()
        if len(self._music_queue) > 0:
            self._is_playing = True

            m_url = self._music_queue[0].media_url
            track = self._music_queue[0]

            embed = discord.Embed(title=track.title, url=track.url,
                                  description="Сейчас играет", color=0x46c077)
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.send(embed=embed)

            self._music_queue.pop(0)

            # self._vc.play(discord.FFmpegPCMAudio(m_url, **self._FFMPEG_OPTIONS))
            self._vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS), after=lambda x: self.__play(ctx))

        else:
            if not self._is_playing:
                return
            print(f"autoplay: {self._autoplay}")
            if self._autoplay:
                wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время",
                                         color=0x46c077)
                self._wait_msg = await ctx.send(embed=wait_msg)
                await self.__autoplay(ctx)
                return
            self._is_playing = False

    async def _play_music(self, ctx):
        if len(self._music_queue) > 0:
            self._is_playing = True

            m_url = self._music_queue[0].media_url
            track = self._music_queue[0]

            embed = discord.Embed(title=track.title, url=track.url,
                                  description="Сейчас играет", color=0x46c077)
            embed.set_thumbnail(url=track.thumbnail)
            if track.duration == 0:
                embed.add_field(name="Длительность", value="Стрим", inline=True)
            else:
                embed.add_field(name="Длительность", value=str(datetime.timedelta(seconds=track.duration)), inline=True)
            await ctx.send(embed=embed)

            if self._vc is None or not self._vc.is_connected():
                self._vc = await ctx.author.voice.channel.connect()

            self._music_queue.pop(0)

            self._vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS), after=lambda x: self.__play(ctx))
        else:
            self._is_playing = False

    def __play(self, ctx):
        if self._is_playing:
            loop: asyncio.AbstractEventLoop = self._bot.loop
            loop.create_task(self._play_next(ctx))


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
