from utils import *

NoneType = type(None)


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
        if 'entries' in data:
            data = data['entries'][0]
        return data['url']

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description=f'```css\n{self.title}\n```',
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.duration)
                 .add_field(name='URL', value=f'[Click]({self.url})')
                 .set_thumbnail(url=self.thumbnail))

        return embed


class Music(commands.Cog):
    def __init__(self, bot, config):
        self._bot = bot
        self._config = config

        self._last_url = {}
        self._music_queue = {}
        self._is_playing = {}
        self._ctx = {}
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
        self.curr_track = {}
        self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=config.spotify_client_id,
            client_secret=config.spotify_client_secret))
        self.m_url = {}

    def log(self, ctx, command):
        print(f"\n[{datetime.datetime.now()}][{self._bot.user}][{ctx.author}][{ctx.guild.name}]\n\t{command}")

    @commands.command(aliases=['sk'])
    async def skip(self, ctx):
        self.log(ctx, "skip")
        curr_guild = ctx.guild.id
        self.is_live[curr_guild] = False
        self._is_playing[curr_guild] = False
        self.is_stopped[curr_guild] = False
        (await self.get_voice_client(ctx)).stop()

    @commands.command()
    async def stop(self, ctx, orig=None):
        self.log(ctx, "stop")
        curr_guild = ctx.guild.id
        self.is_stopped[curr_guild] = True
        self.is_live[curr_guild] = False

        self._music_queue[curr_guild] = []
        (await self.get_voice_client(ctx)).stop()
        self._is_playing[curr_guild] = False
        self.loop[curr_guild] = False
        if orig != self.leave:
            await ctx.send("Stopped")

    @commands.command()
    async def leave(self, ctx):
        self.log(ctx, "leave")
        curr_guild = ctx.guild.id

        await self.stop(ctx, orig=self.leave)

        await (await self.get_voice_client(ctx)).disconnect()
        del self._vc[curr_guild]

    @commands.command()
    async def join(self, ctx):
        self.log(ctx, "join")
        await self.get_voice_client(ctx)

    def request_data(self, curr_guild, data, default_value: Any = True):
        self_data = self.__getattribute__(data)

        if curr_guild not in self_data:
            self_data[curr_guild] = default_value
        return self_data[curr_guild]

    @commands.command(name="loop")
    async def _loop(self, ctx):
        self.log(ctx, "loop")
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
        self.log(ctx, "auto")
        curr_guild = ctx.guild.id
        servers = get_servers_data(curr_guild)
        servers[curr_guild].autoplay = not servers[curr_guild].autoplay
        if servers[curr_guild].autoplay:
            await ctx.send("Autoplay enabled")
        else:
            await ctx.send("Autoplay disabled")
        save_servers_data(servers)

    @commands.command(aliases=['q'])
    async def queue(self, ctx: commands.Context):
        self.log(ctx, "queue")
        txt = ""
        for i, q in enumerate(self._music_queue[ctx.guild.id]):
            txt += f"{i + 1}. [{q.title}]({q.url})\n"
        max_ln = 2000
        if len(txt) > max_ln:
            txt_lines = txt.split("\n")
            chunked_txt = ""
            for ln in txt_lines:
                if len(chunked_txt + ln) > max_ln:
                    await ctx.send(chunked_txt)
                    chunked_txt = ""
                chunked_txt += ln
                chunked_txt += "\n"
        else:
            if len(txt) == 0:
                return
            await ctx.send(txt)

    @commands.command(aliases=['sh'])
    async def shuffle(self, ctx):
        self.log(ctx, "shuffle")
        random.shuffle(self._music_queue[ctx.guild.id])

    @commands.command(aliases=['p', 'pl'])
    async def play(self, ctx, *, query: str):
        self.log(ctx, ctx.message.content)
        curr_guild = ctx.guild.id
        self.is_stopped[curr_guild] = False
        self.loop[curr_guild] = False
        song_type = identify_url(query)
        track = None
        wait_msg = discord.Embed(title="???????? ??????????...", description="?????????? ???????????? ?????????????????? ??????????", color=0x46c077)
        wait_msg = await ctx.send(embed=wait_msg)

        if song_type == Sites.Unknown:
            track = self.search_yt(ctx, query, song_type)
        elif song_type == Sites.YouTube:
            track = self.get_ytdl(ctx, query, song_type)
        elif song_type == Sites.Spotify:
            track = self.get_spotify_track(ctx, query, song_type)
        elif song_type == Sites.Spotify_User_Playlist:
            track = await self.get_spotify_user_playlist(ctx, query, Sites.Spotify_Playlist)
        elif song_type == Sites.Spotify_Playlist:
            track = await self.get_spotify_playlist(ctx, query, song_type)

        if isinstance(track, bool):
            await wait_msg.delete()
            embed = discord.Embed(title="???? ??????????????", description=query, color=0xff0000)
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=5)
            return

        self.request_data(curr_guild, "_music_queue", default_value=[])
        self.request_data(curr_guild, "_is_playing", default_value=False)

        if isinstance(track, list):
            self._music_queue[curr_guild] += track
        else:
            self._music_queue[curr_guild].append(track)

        if not self._is_playing[curr_guild]:
            asyncio.get_event_loop().create_task(self._play_queue(ctx))
        else:
            if not isinstance(track, list):
                msg = discord.Embed(title="?????????????????? ?? ??????????????", description=track.title, url=track.url,
                                    color=0x46c077)
                await ctx.send(embed=msg)
        await wait_msg.delete()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, after, before):
        try:
            d = discord.utils.find(lambda u: u.id == self._bot.user.id,
                                   after.channel.members
                                   ) is not None and member != self._bot.user
            if len(after.channel.voice_states) == 1 and d:
                await self.leave(self._ctx[member.guild.id])
        except AttributeError:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self._bot.get_context(message)
        self._ctx[ctx.guild.id] = ctx


    def search_yt(self, ctx, item, song_type):
        self.ytdl.cache.remove()
        try:
            data = self.ytdl.extract_info(f"ytsearch:{item}", download=False)['entries'][0]
            self._last_url[ctx.guild.id] = data['webpage_url']
            return Track(title=data['title'], url=data['webpage_url'], id=data["id"], song_type=song_type,
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def get_ytdl(self, ctx, url, song_type):
        self.ytdl.cache.remove()
        try:
            data = self.ytdl.extract_info(url, download=False)
            self._last_url[ctx.guild.id] = url

            return Track(title=data['title'], url=data['webpage_url'], id=data["id"], song_type=song_type,
                         thumbnail=data['thumbnail'], duration=data['duration'], live=data['is_live'])
        except:
            return False

    def get_spotify_track(self, ctx, url: str, song_type):
        query = url.replace("https://open.spotify.com/track/", "")
        query, _ = query.split("?si=")
        strack = self.sp.track(f"spotify:track:{query}")
        return Track(title=strack['name'], duration=int(strack['duration_ms'] / 1000), song_type=song_type,
                     url=self.search_yt(ctx, f"{strack['name']} - {strack['artists'][0]['name']}", song_type).url,
                     thumbnail=strack['album']['images'][0]['url'])

    async def get_spotify_user_playlist(self, ctx, url: str, song_type):
        # https://open.spotify.com/user/z94mky2mjmv9camvvney7wxo2/playlist/5nM0PENVxsDumIga1BJjqC?si=9t13s8hSSMaMV8vWe7z_5w
        curr_guild = ctx.guild.id
        query = url.replace("https://open.spotify.com/user/", "")
        user, play_id = query.split("/playlist/")
        play_id, _ = play_id.split("?si=")
        playlist = self.sp.playlist(f"spotify:user:{user}:playlist:{play_id}")
        res = playlist['tracks']
        tracks = res['items']
        while res['next']:
            res = self.sp.next(res)
            tracks.extend(res['items'])
        output = []

        for t in tracks:
            output.append(Track(title=t['track']['name'], duration=int(t['track']['duration_ms'] / 1000),
                                song_type=song_type,
                                url=f"{t['track']['name']} - {t['track']['artists'][0]['name']}",
                                thumbnail=t['track']['album']['images'][0]['url']))

        embed = discord.Embed(title=playlist['name'], url=playlist['external_urls']['spotify'],
                              description="?????????????????? ?? ??????????????", color=0x46c077)
        embed.set_thumbnail(url=playlist['images'][0]['url'])
        embed.add_field(name="????????????", value=str(len(output)), inline=True)
        await ctx.send(embed=embed)

        return output

    async def get_spotify_playlist(self, ctx, url: str, song_type):
        # https://open.spotify.com/playlist/5PP7FlIhbxm90bgY4jyF4r?si=J2uZjh6NTZeTftmcEDMrpQ&utm_source=copy-link
        query = url.replace("https://open.spotify.com/playlist/", "")
        play_id, _ = query.split("?si=")
        playlist = self.sp.playlist(f"spotify:playlist:{play_id}")
        res = playlist['tracks']
        tracks = res['items']
        while res['next']:
            res = self.sp.next(res)
            tracks.extend(res['items'])
        output = []

        for t in tracks:
            output.append(Track(title=t['track']['name'], duration=int(t['track']['duration_ms'] / 1000),
                                song_type=song_type,
                                url=f"{t['track']['name']} - {t['track']['artists'][0]['name']}",
                                thumbnail=t['track']['album']['images'][0]['url']))

        embed = discord.Embed(title=playlist['name'], url=playlist['external_urls']['spotify'],
                              description="?????????????????? ?? ??????????????", color=0x46c077)
        embed.set_thumbnail(url=playlist['images'][0]['url'])
        embed.add_field(name="????????????", value=str(len(output)), inline=True)
        await ctx.send(embed=embed)

        return output

    async def get_voice_client(self, ctx):
        if ctx.guild.id not in self._vc:
            self._vc[ctx.guild.id] = None

        state = self._vc[ctx.guild.id]
        try:
            state = await ctx.author.voice.channel.connect()
            self._vc[ctx.guild.id] = state
        except discord.errors.ClientException:
            pass

        except AttributeError:
            await state.disconnect()

        return state

    async def _play_queue(self, ctx):
        curr_guild = ctx.guild.id
        servers = get_servers_data(curr_guild)[curr_guild]
        while len(self._music_queue[curr_guild]) > 0:
            if not self.is_stopped[curr_guild]:
                await self._play_song(ctx)
            else:
                return

            try:
                while self._is_playing[curr_guild] or (await self.get_voice_client(ctx)).is_playing():
                    await asyncio.sleep(1)
            except AttributeError:
                return

            if self.is_stopped[curr_guild]:
                self.is_stopped[curr_guild] = False
                return

            if len(self._music_queue[curr_guild]) == 0 \
                    and servers.autoplay \
                    and not self.is_stopped[curr_guild]:
                wait_msg = discord.Embed(title="???????? ??????????...", description="?????????? ???????????? ?????????????????? ??????????",
                                         color=0x46c077)
                wait_msg = await ctx.send(embed=wait_msg)
                self.__autoplay(ctx)
                await wait_msg.delete()
        self.loop[curr_guild] = False

    async def _play_song(self, ctx):
        curr_guild = ctx.guild.id
        curr_vc = await self.get_voice_client(ctx)
        self.curr_track[curr_guild] = self._music_queue[curr_guild][0]
        print(f"\t[{self._bot.user}] Now playing: {self.curr_track[curr_guild].url}")
        if self.loop[curr_guild]:
            self._music_queue[curr_guild].append(self.curr_track[curr_guild])
        self._music_queue[curr_guild].pop(0)

        if self.curr_track[curr_guild].song_type == Sites.Spotify_Playlist:
            self.curr_track[curr_guild] = self.search_yt(ctx, self.curr_track[curr_guild].url, Sites.Unknown)

        if self.curr_track[curr_guild].duration > 18000:
            wait_msg = discord.Embed(title="???????? ?????????????? ??????????????",
                                     description="???????????????????? ?????????? ?????????? ???????????????? ???????????? ??????????",
                                     color=discord.Color.dark_red())
            await ctx.send(embed=wait_msg)
            return

        else:
            self.m_url[curr_guild] = self.curr_track[curr_guild].get_media_url(self.ytdl)

            embed = discord.Embed(title=self.curr_track[curr_guild].title, url=self.curr_track[curr_guild].url,
                                  description="???????????? ????????????", color=0x46c077)
            embed.set_thumbnail(url=self.curr_track[curr_guild].thumbnail)
            if self.curr_track[curr_guild].duration == 0:
                embed.add_field(name="????????????????????????", value="??????????", inline=True)
            else:
                embed.add_field(name="????????????????????????",
                                value=str(datetime.timedelta(seconds=self.curr_track[curr_guild].duration)),
                                inline=True)
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
                    asyncio.get_event_loop().create_task(self.timeout_reconnect(ctx, self.curr_track[curr_guild]))
                    if curr_vc.is_playing():
                        curr_vc.stop()
                        curr_vc.play(
                            await discord.FFmpegOpusAudio.from_probe(self.m_url[curr_guild], **self._FFMPEG_OPTIONS),
                            after=lambda x: end_s())
                    else:
                        curr_vc.play(
                            await discord.FFmpegOpusAudio.from_probe(self.m_url[curr_guild], **self._FFMPEG_OPTIONS),
                            after=lambda x: end_s())
                    while self._is_playing[curr_guild]:
                        await asyncio.sleep(5)
                return

            else:
                try:
                    curr_vc.play(
                        await discord.FFmpegOpusAudio.from_probe(self.m_url[curr_guild], **self._FFMPEG_OPTIONS),
                        after=lambda x: end())
                except discord.errors.ClientException:
                    curr_vc = await self.get_voice_client(ctx)
                    curr_vc.play(
                        await discord.FFmpegOpusAudio.from_probe(self.m_url[curr_guild], **self._FFMPEG_OPTIONS),
                        after=lambda x: end())

    def __autoplay(self, ctx):
        curr_guild = ctx.guild.id
        if self.is_stopped[curr_guild]:
            return
        print(f"\t[{self._bot.user}] Autoplay")
        options = Options()
        options.add_argument("-remote-debugging-port=9224")
        options.add_argument("-headless")
        options.add_argument("-disable-gpu")
        options.add_argument("-no-sandbox")
        FF_profile = webdriver.FirefoxProfile()
        FF_profile.update_preferences()
        driver = webdriver.Firefox(firefox_options=options, firefox_profile=FF_profile, executable_path=os.environ.get("GECKODRIVER_PATH"), firefox_binary=FirefoxBinary(os.environ.get("FIREFOX_BIN")), log_path=os.devnull)
        track = None
        while True:
            driver.get(self._last_url[curr_guild])
            time.sleep(2)
            elems = driver.execute_script(
                'return document.getElementsByClassName("yt-simple-endpoint inline-block style-scope ytd-thumbnail")')
            elems = elems[1: 5 if len(elems) >= 5 else len(elems) - 1]
            track = self.get_ytdl(ctx, random.choice(elems).get_attribute('href'), Sites.YouTube)
            if type(track) in (bool, NoneType) or track.duration > 14400:
                continue
            break
        driver.close()
        self._music_queue[curr_guild].append(track)

    async def timeout_reconnect(self, ctx, curr_track):
        await asyncio.sleep(20000)
        curr_guild = ctx.guild.id
        if curr_track == self.curr_track[curr_guild]:
            await self.get_voice_client(ctx)
            self._music_queue[curr_guild].insert(0, self.curr_track[curr_guild])
            await self.skip(ctx)
