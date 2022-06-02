import discord
from discord.ext import commands, tasks

import argparse
import asyncio

from config import load_config
from minecraft_cog import MinecraftCog
from help_command import EmbedHelpCommand


class Bot:
    def __init__(self, config):
        self.bot = commands.Bot(
            intents=self.getDefaultIntents(),
            command_prefix=commands.when_mentioned,
            status=discord.Status.dnd,
            activity=discord.Game('起動中...'),
            help_command=EmbedHelpCommand())
        self.config = config

    def start(self, loop):
        loop.create_task(self.bot.add_cog(MinecraftCog(self.bot, self.config)))
        loop.create_task(self.bot.start(self.config.token))

    def run(self):
        self.bot.run(self.config.token)

    def close(self, loop):
        loop.run_until_complete(self.bot.change_presence(status=discord.Status.offline, activity=None))
        loop.run_until_complete(self.bot.close())

    def getDefaultIntents(self):
        intents = discord.Intents.default()
        # intents.bans = True
        # intents.dm_messages = True
        # intents.dm_reactions = True
        intents.dm_typing = False
        # intents.emojis = True
        # intents.emojis_and_stickers = True
        # intents.guild_messages = True
        # intents.guild_reactions = True
        # intents.guild_scheduled_events = True
        intents.guild_typing = False
        # intents.guilds = True
        # intents.integrations = True
        # intents.invites = True
        # intents.members = False
        # intents.message_content = False
        # intents.messages = True
        # intents.presences = False
        # intents.reactions = True
        intents.typing = False
        # intents.value = True
        # intents.voice_states = True
        # intents.webhooks = True
        return intents


def getArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config_file', default='config.toml')
    args = parser.parse_args()
    return args

def main(args, config):
    loop = asyncio.get_event_loop()

    bot = Bot(config)
    # bot.run()
    bot.start(loop)
    try:
        loop.run_forever()
    except:
        pass
    finally:
        bot.close(loop)


if __name__ == '__main__':
    args = getArgs()
    main(args, load_config(args.config_file))