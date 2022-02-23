import asyncio
import datetime
import json
import os
import pickle
import random
import time
from enum import Enum
from typing import Any
import aiohttp
import io
import discord
import spotipy
from async_timeout import timeout
from discord.ext import commands
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as Options
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
from spotipy.oauth2 import SpotifyClientCredentials

from youtube_dl import YoutubeDL

class Sites(Enum):
    Spotify = "Spotify"
    Spotify_Playlist = "Spotify Playlist"
    Spotify_User_Playlist = "Spotify User Playlist"
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


async def determine_prefix(bot, message):
    guild = message.guild
    if guild:
        return get_servers_data(guild.id)[guild.id].prefix


def get_servers_data(guild_id):
    try:
        with open("servers.dat", "rb") as f:
            servers_data = pickle.load(f)
    except FileNotFoundError:
        servers_data = {}

    if guild_id not in servers_data:
        servers_data[guild_id] = Config(autoplay=True, prefix="_")

    save_servers_data(servers_data)

    return servers_data


def save_servers_data(servers):
    with open("servers.dat", "wb") as f:
        pickle.dump(servers, f)


def identify_url(url):
    if url is None:
        return Sites.Unknown

    if "https://www.youtu" in url or "https://youtu.be" in url:
        return Sites.YouTube

    if "https://open.spotify.com/track" in url:
        return Sites.Spotify

    if 'https://open.spotify.com/playlist/' in url:
        return Sites.Spotify_Playlist

    if 'https://open.spotify.com/user/' in url and '/playlist' in url:
        return Sites.Spotify_User_Playlist

    # if "bandcamp.com/track/" in url:
    #     return Sites.Bandcamp
    #
    # if "https://twitter.com/" in url:
    #     return Sites.Twitter
    #
    # if "soundcloud.com/" in url:
    #     return Sites.SoundCloud

    # If no match
    return Sites.Unknown