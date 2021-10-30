import asyncio
import json
import os
import pickle
import random
import time
from enum import Enum
from typing import Any

import discord
import spotipy
from async_timeout import timeout
from discord.ext import commands
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as Options
from spotipy.oauth2 import SpotifyClientCredentials

from youtube_dl import YoutubeDL

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
    def __init__(self, title, duration, url, thumbnail, live=False, config_dict: dict = None, **kwargs):
        super().__init__(config_dict, **kwargs)
        self.title = title
        self.duration = duration
        self.url = url
        self.thumbnail = thumbnail
        self.live = live

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


class CommandsHandler(commands.Cog):
    def __init__(self, bot, config, servers_data):
        self._bot = bot
        self._config = config

        self._last_url = {}
        self._music_queue = {}
        self._is_playing = {}

        self._YTDL_OPTIONS = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'simulate': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        self._FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1  '
                                                  '-reconnect_delay_max 5',
                                'options': '-vn'}

        self._vc = {}
        self.is_live = {}
        self.loop = {}
        self.ytdl = YoutubeDL(self._YTDL_OPTIONS)
        self.ytdl.cache.remove()
        self.is_stopped = {}
        self.servers = servers_data
        self.curr_track = {}
        self.sp = spotipy.Spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=config.spotify_client_id,
            client_secret=config.spotify_client_secret))

    @commands.command(aliases=['sk'])
    async def skip(self, ctx):
        curr_guild = ctx.guild.id
        self.is_live[curr_guild] = False
        self._is_playing[curr_guild] = False
        self.is_stopped[curr_guild] = False
        (await self.get_voice_client(ctx)).stop()

    @commands.command()
    async def stop(self, ctx):
        curr_guild = ctx.guild.id
        self.is_stopped[curr_guild] = True
        self.is_live[curr_guild] = False

        self._music_queue[curr_guild] = []
        (await self.get_voice_client(ctx)).stop()
        self._is_playing[curr_guild] = False
        self.loop[curr_guild] = False

    @commands.command()
    async def leave(self, ctx):
        curr_guild = ctx.guild.id

        await self.stop(ctx)

        await (await self.get_voice_client(ctx)).disconnect()
        del self._vc[curr_guild]

    @commands.command()
    async def join(self, ctx):
        await self.get_voice_client(ctx)

    def request_data(self, curr_guild, data, default_value: Any = True):
        self_data = self.__getattribute__(data)

        if curr_guild not in self_data:
            self_data[curr_guild] = default_value
        return self_data[curr_guild]

    @commands.command(name="loop")
    async def _loop(self, ctx):
        curr_guild = ctx.guild.id

        self.request_data(curr_guild, "loop")
        self.loop[curr_guild] = not self.loop[curr_guild]
        if self.loop[curr_guild]:
            await ctx.send("Loop enabled")
            if self._is_playing[curr_guild]:
                self._music_queue[curr_guild].append(self.curr_track[curr_guild])
        else:
            await ctx.send("Loop disabled")

    @commands.command(aliases=['auto'])
    async def autoplay(self, ctx):
        curr_guild = ctx.guild.id
        self.servers[curr_guild].autoplay = not self.servers[curr_guild].autoplay
        if self.servers[curr_guild].autoplay:
            await ctx.send("Autoplay enabled")
        else:
            await ctx.send("Autoplay disabled")
        self.save_server()

    @commands.command()
    async def queue(self, ctx: commands.Context):
        txt = ""
        for i, q in enumerate(self._music_queue[ctx.guild.id]):
            txt += f"{i + 1}. **{q.title}**\n"

        await ctx.send(txt)

    @commands.command(aliases=['p', 'pl'])
    async def play(self, ctx, *, query: str):
        curr_guild = ctx.guild.id
        self.is_stopped[curr_guild] = False
        self.loop[curr_guild] = False
        song_type = self.identify_url(query)
        track = None
        wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время", color=0x46c077)
        wait_msg = await ctx.send(embed=wait_msg)

        if song_type == Sites.Unknown:
            track = self.search_yt(ctx, query)
        elif song_type == Sites.YouTube:
            track = self.get_ytdl(ctx, query)
        elif song_type == Sites.Spotify:
            track = self.get_spotify_track(ctx, query)

        await wait_msg.delete()
        if isinstance(track, bool):
            embed = discord.Embed(title="Не найдено", description=query, color=0xff0000)
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=5)
            return

        track.add_data(type=song_type)

        self.request_data(curr_guild, "_music_queue", default_value=[])
        self._music_queue[curr_guild].append(track)
        self.request_data(curr_guild, "_is_playing", default_value=False)

        if not self._is_playing[curr_guild]:
            asyncio.get_event_loop().create_task(self._play_queue(ctx))
        else:
            wait_msg = discord.Embed(title="Добавлено в очередь", description=track.title, url=track.url,
                                     color=0x46c077)
            await ctx.send(embed=wait_msg)

    def search_yt(self, ctx, item):
        try:
            data = self.ytdl.extract_info(f"ytsearch:{item}", download=False)['entries'][0]
            self._last_url[ctx.guild.id] = data['webpage_url']
            return Track(title=data['title'], url=data['webpage_url'], id=data["id"],
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def get_ytdl(self, ctx, url):
        try:
            data = self.ytdl.extract_info(url, download=False)
            self._last_url[ctx.guild.id] = url

            return Track(title=data['title'], url=data['webpage_url'], id=data["id"],
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def get_spotify_track(self, ctx, url: str):
        query = url.replace("https://open.spotify.com/track/", "")
        query, _ = query.split("?si=")
        strack = self.sp.track(f"spotify:track:{query}")
        return Track(title=strack['name'], duration=int(strack['duration_ms'] / 1000),
                     url=self.search_yt(ctx, f"{strack['name']} - {strack['artists'][0]['name']}").url,
                     thumbnail=strack['album']['images'][0]['url'])

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

    def update_server(self, ctx):
        if ctx.guild.id not in self.servers:
            self.servers[ctx.guild.id] = Config(autoplay=True)

    def save_server(self):
        with open("servers.dat", "wb") as f:
            pickle.dump(self.servers, f)

    async def _play_queue(self, ctx):
        curr_guild = ctx.guild.id
        while len(self._music_queue[curr_guild]) > 0:
            if not self.is_stopped[curr_guild]:
                await self._play_song(ctx)
            else:
                return

            while self._is_playing[curr_guild]:
                await asyncio.sleep(1)

            if self.is_stopped[curr_guild]:
                self.is_stopped[curr_guild] = False
                return

            if len(self._music_queue[curr_guild]) == 0 \
                    and self.servers[curr_guild].autoplay \
                    and not self.is_stopped[curr_guild]:
                wait_msg = discord.Embed(title="Идёт поиск...", description="Может занять некоторое время",
                                         color=0x46c077)
                wait_msg = await ctx.send(embed=wait_msg)
                self.__autoplay(ctx)
                await wait_msg.delete()
        self.loop[curr_guild] = False

    async def _play_song(self, ctx):
        curr_guild = ctx.guild.id
        curr_vc = await self.get_voice_client(ctx)
        self.curr_track[curr_guild] = self._music_queue[curr_guild][0]
        if self.loop[curr_guild]:
            self._music_queue[curr_guild].append(self.curr_track[curr_guild])
        self._music_queue[curr_guild].pop(0)

        if 9000 < self.curr_track[curr_guild].duration <= 14400:
            if not os.path.exists(f"./{self.curr_track[curr_guild].id}.mp3"):
                wait_msg = discord.Embed(title="Трек скачивается...", description="Может занять много времени",
                                         color=discord.Color.orange())
                wait_msg = await ctx.send(embed=wait_msg)
                with YoutubeDL({
                    'format': 'bestaudio/best',
                    'keepvideo': False,
                    'outtmpl': f"./{self.curr_track[curr_guild].id}.mp3",
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }) as ytdl:
                    ytdl.download([self.curr_track[curr_guild].url])

                await wait_msg.delete()

            embed = discord.Embed(title=self.curr_track[curr_guild].title, url=self.curr_track[curr_guild].url,
                                  description="Сейчас играет", color=0x46c077)
            embed.set_thumbnail(url=self.curr_track[curr_guild].thumbnail)
            await ctx.send(embed=embed)

            curr_vc.play(discord.FFmpegPCMAudio(source=f"./{self.curr_track[curr_guild].id}.mp3"),
                         after=lambda x: end())

        elif self.curr_track[curr_guild].duration > 14400:
            wait_msg = discord.Embed(title="Трек слишком длинный",
                                     description="Попробуйте найти более короткую версию песни",
                                     color=discord.Color.dark_red())
            await ctx.send(embed=wait_msg)

        else:
            m_url = self.curr_track[curr_guild].get_media_url(self.ytdl)
            print(self.curr_track[curr_guild].url)

            embed = discord.Embed(title=self.curr_track[curr_guild].title, url=self.curr_track[curr_guild].url,
                                  description="Сейчас играет", color=0x46c077)
            embed.set_thumbnail(url=self.curr_track[curr_guild].thumbnail)
            await ctx.send(embed=embed)

            curr_vc.stop()
            self._is_playing[curr_guild] = True

            def end():
                self._is_playing[curr_guild] = False

            def end_s():
                self.is_live[curr_guild] = False

            self.request_data(curr_guild, "is_live", default_value=False)
            self.is_live[curr_guild] = self.curr_track[curr_guild].live

            if self.is_live[curr_guild]:
                while self.is_live[curr_guild] and not self.is_stopped[curr_guild]:
                    try:
                        async with timeout(7200):
                            if curr_vc.is_playing():
                                curr_vc.stop()
                                curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS),
                                             after=lambda x: end_s())
                            else:
                                curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS),
                                             after=lambda x: end_s())
                            while self._is_playing[curr_guild]:
                                await asyncio.sleep(5)
                    except asyncio.TimeoutError:
                        m_url = self.curr_track[curr_guild].get_media_url(self.ytdl)

                return
            else:
                curr_vc.play(await discord.FFmpegOpusAudio.from_probe(m_url, **self._FFMPEG_OPTIONS),
                             after=lambda x: end())

    def __autoplay(self, ctx):
        curr_guild = ctx.guild.id
        if self.is_stopped[curr_guild]:
            return
        print("Autoplay")
        options = Options()
        options.add_argument("--headless")
        driver = webdriver.Firefox(firefox_options=options, log_path=os.devnull)
        track = None
        while True:
            driver.get(self._last_url[curr_guild])
            time.sleep(2)
            elems = driver.execute_script(
                'return document.getElementsByClassName("yt-simple-endpoint inline-block style-scope ytd-thumbnail")')
            elems = elems[1: 5 if len(elems) >= 5 else len(elems) - 1]
            track = self.get_ytdl(ctx, random.choice(elems).get_attribute('href'))
            if type(track) in (bool, NoneType) or track.duration > 14400:
                continue
            break

        self._music_queue[curr_guild].append(track)


with open('config.json') as f:
    config = Config(json.load(f))

try:
    with open("servers.dat", "rb") as f:
        servers_data = pickle.load(f)
except FileNotFoundError:
    servers_data = {}

bot = commands.Bot(config.prefix)

cog = CommandsHandler(bot, config, servers_data)
bot.add_cog(cog)


@bot.event
async def on_ready():
    print("Connected")


@bot.event
async def on_message(message):
    cog.update_server(await bot.get_context(message))
    await bot.process_commands(message)


bot.run(config.token)
