import asyncio
import random
import datetime
import os
import time
import json
from enum import Enum

import discord
from async_timeout import timeout
from discord.ext import commands
from youtube_dl import YoutubeDL

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as Options

config = servers_data = None

NoneType = type(None)


class Sites(Enum):
    Spotify = "Spotify"
    Spotify_Playlist = "Spotify Playlist"
    YouTube = "YouTube"
    Twitter = "Twitter"
    SoundCloud = "SoundCloud"
    Bandcamp = "Bandcamp"
    Custom = "Custom"
    Unknown = "Unknown"


class Config:
    def __init__(self, config_dict: dict = None, **kwargs):
        if config_dict is not None:
            for arg in config_dict.keys():
                self.__setattr__(arg, config_dict[arg])

        for arg in kwargs.keys():
            self.__setattr__(str(arg), kwargs[arg])

    def add_data(self, config_dict: dict = None, **kwargs):
        if config_dict is not None:
            for arg in config_dict.keys():
                self.__setattr__(arg, config_dict[arg])

        for arg in kwargs.keys():
            self.__setattr__(str(arg), kwargs[arg])

    def save(self, filename):
        with open(filename, "w") as f:
            json.dump(vars(self), f)


class Track(Config):
    def __init__(self, title, duration, url, thumbnail, config_dict: dict = None, **kwargs):
        super().__init__(config_dict, **kwargs)
        self.title = title
        self.duration = duration
        self.url = url
        self.thumbnail = thumbnail

    def get_media_url(self, ytdl: YoutubeDL):
        data = ytdl.extract_info(url=self.url, download=False)
        return data['url']

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description=f'```css\n{self.title}\n```',
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.duration)
                 .add_field(name='URL', value=f'[Click]({self.url})')
                 .set_thumbnail(url=self.thumbnail))

        return embed


with open('config.json') as f:
    globals()["config"] = Config(json.load(f))


# with open('settings.json') as f:
#     globals()['servers_data'] = Config(json.load(f))


class CommandsHandler(commands.Cog):
    def __init__(self, bot, config):
        self._bot = bot
        self._config = config
        self._autoplay = {}

        self._last_url = {}

        self._music_queue = {}
        self._is_playing = {}

        self._YTDL_OPTIONS = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'simulate': True
        }

        self._FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 '
                                                  '-reconnect_delay_max 5',
                                'options': '-vn'}

        self._vc = {}
        self.is_live = {}

        self.ytdl = YoutubeDL(self._YTDL_OPTIONS)
        self.ytdl.cache.remove()

    @commands.command(aliases=['sk'])
    async def skip(self, ctx):
        curr_guild = ctx.guild.id
        try:
            self.is_live[curr_guild] = False
        except:
            pass
        self._is_playing[curr_guild] = False
        (await self.get_voice_client(ctx)).stop()

    @commands.command(aliases=['leave'])
    async def stop(self, ctx):
        curr_guild = ctx.guild.id

        try:
            self.is_live[curr_guild] = False
        except:
            pass
        self._music_queue[curr_guild] = []
        (await self.get_voice_client(ctx)).stop()
        self._is_playing[curr_guild] = False
        await (await self.get_voice_client(ctx)).disconnect()
        del self._vc[curr_guild]

    @commands.command()
    async def join(self, ctx):
        await ctx.author.voice.channel.connect()

    @commands.command(aliases=['auto'])
    async def autoplay(self, ctx):
        curr_guild = ctx.guild.id
        if curr_guild not in self._autoplay:
            self._autoplay[curr_guild] = True
        self._autoplay[curr_guild] = not self._autoplay[curr_guild]
        if self._autoplay[curr_guild]:
            await ctx.send("Autoplay enabled")
        else:
            await ctx.send("Autoplay disabled")

    @commands.command()
    async def queue(self, ctx: commands.Context):
        txt = ""
        for i, q in enumerate(self._music_queue[ctx.guild.id]):
            txt += f"{i + 1}. **{q.title}**\n"

        await ctx.send(txt)

    @commands.command(aliases=['p', 'pl'])
    async def play(self, ctx, *, query: str):
        curr_guild = ctx.guild.id
        if curr_guild not in self._autoplay:
            self._autoplay[curr_guild] = False
        song_type = self.identify_url(query)
        track = None
        wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время", color=0x46c077)
        wait_msg = await ctx.send(embed=wait_msg)
        if song_type == Sites.Unknown:
            track = self.search_yt(ctx, query)
        elif song_type == Sites.YouTube:
            track = self.get_ytdl(ctx, query)

        await wait_msg.delete()
        if isinstance(track, bool):
            embed = discord.Embed(title="Не найдено", description=query, color=0xff0000)
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=5)
            return

        track.add_data(type=song_type)

        if curr_guild not in self._music_queue:
            self._music_queue[curr_guild] = []
        self._music_queue[curr_guild].append(track)
        if curr_guild not in self._is_playing:
            self._is_playing[curr_guild] = False

        if not self._is_playing[curr_guild]:
            asyncio.get_event_loop().create_task(self._play_queue(ctx))

    def search_yt(self, ctx, item):
        try:
            data = self.ytdl.extract_info(f"ytsearch:{item}", download=False)['entries'][0]
            self._last_url[ctx.guild.id] = data['webpage_url']
            return Track(title=data['title'], url=data['webpage_url'],
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def get_ytdl(self, ctx, url):
        try:
            data = self.ytdl.extract_info(url, download=False)
            self._last_url[ctx.guild.id] = url

            return Track(title=data['title'], url=data['webpage_url'],
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def identify_url(self, url):
        if url is None:
            return Sites.Unknown

        if "https://www.youtu" in url or "https://youtu.be" in url:
            return Sites.YouTube

        if "https://open.spotify.com/track" in url:
            return Sites.Spotify

        if "https://open.spotify.com/playlist" in url or "https://open.spotify.com/album" in url:
            return Sites.Spotify_Playlist

        if "bandcamp.com/track/" in url:
            return Sites.Bandcamp

        if "https://twitter.com/" in url:
            return Sites.Twitter

        if "soundcloud.com/" in url:
            return Sites.SoundCloud

        # If no match
        return Sites.Unknown

    async def get_voice_client(self, ctx):
        if ctx.guild.id not in self._vc:
            self._vc[ctx.guild.id] = None

        state = self._vc[ctx.guild.id]
        if not state:
            state = await ctx.author.voice.channel.connect()
            self._vc[ctx.guild.id] = state

        return state

    async def _play_queue(self, ctx):
        curr_guild = ctx.guild.id
        while len(self._music_queue[curr_guild]) > 0:

            await self._play_song(ctx)

            while self._is_playing[curr_guild]:
                await asyncio.sleep(5)

            if self._autoplay[curr_guild]:
                wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время",
                                         color=0x46c077)
                wait_msg = await ctx.send(embed=wait_msg)
                self.__autoplay(ctx)
                await wait_msg.delete()

    async def _play_song(self, ctx):
        curr_guild = ctx.guild.id
        curr_vc = await self.get_voice_client(ctx)
        curr_track = self._music_queue[curr_guild][0]
        m_url = self._music_queue[curr_guild][0].get_media_url(self.ytdl)
        print(self._music_queue[curr_guild][0].url)

        embed = discord.Embed(title=curr_track.title, url=curr_track.url,
                              description="Сейчас играет", color=0x46c077)
        embed.set_thumbnail(url=curr_track.thumbnail)
        await ctx.send(embed=embed)

        curr_vc.stop()
        self._is_playing[curr_guild] = True

        def end():
            self._is_playing[curr_guild] = False

        def end_s():
            self.is_live[curr_guild] = False

        if curr_guild not in self.is_live:
            self.is_live[curr_guild] = False
        self.is_live[curr_guild] = self._music_queue[curr_guild][0].live

        self._music_queue[curr_guild].pop(0)
        if self.is_live[curr_guild]:
            while self.is_live[curr_guild]:
                try:
                    async with timeout(7200):
                        if curr_vc.is_playing():
                            curr_vc.stop()
                            curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS), after=lambda x: end_s())
                        else:
                            curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS), after=lambda x: end_s())
                        while self._is_playing[curr_guild]:
                            await asyncio.sleep(5)
                except asyncio.TimeoutError:
                    m_url = curr_track.get_media_url(self.ytdl)

            return
        else:
            curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS), after=lambda x: end())

    def __autoplay(self, ctx):
        curr_guild = ctx.guild.id
        print(self._autoplay[curr_guild])
        options = Options()
        options.add_argument("--headless")
        driver = webdriver.Firefox(firefox_options=options, log_path=os.devnull)
        track = None
        while True:
            driver.get(self._last_url[curr_guild])
            time.sleep(2)
            elems = driver.execute_script('return document.getElementsByClassName("yt-simple-endpoint inline-block style-scope ytd-thumbnail")')
            elems = elems[1: 5 if len(elems) >= 5 else len(elems)-1]
            track = self.get_ytdl(ctx, random.choice(elems).get_attribute('href'))
            if type(track) in (bool, NoneType):
                continue
            break

        self._music_queue[curr_guild].append(track)


bot = commands.Bot(config.prefix)
bot.add_cog(CommandsHandler(bot, config))


@bot.event
async def on_ready():
    print("Connected")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

# @bot.event
# async def on_message(message):
#     await bot.process_commands(message)

bot.run(config.token)




