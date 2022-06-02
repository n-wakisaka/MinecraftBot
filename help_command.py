import discord
from discord.ext import commands, tasks

import asyncio

class EmbedHelpCommand(commands.MinimalHelpCommand):
    def __init__(self):
        super().__init__()
        # self.commands_heading = "コマンド:"
        self.no_category = 'その他'
        # self.sort_commands = False
    
    def get_command_signature(self, command, /):
        return f'`{self.context.clean_prefix}{command.qualified_name} {command.signature}`'

    def get_opening_note(self):
        return
    
    def get_ending_note(self):
        command_name = self.invoked_with
        return (
            f'`{self.context.clean_prefix}{command_name} [command]` でcommandのより詳しい情報が得られます\n'
        )

    def add_subcommand_formatting(self, command, /):
        fmt = '`{0}{1}` \N{EN DASH} {2}' if command.short_doc else '`{0}{1}`'
        self.paginator.add_line(fmt.format(self.context.clean_prefix, command.qualified_name, command.short_doc))

    async def send_pages(self):
        destination = self.get_destination()
        for page in self.paginator.pages:
            emby = discord.Embed(title=f'{self.context.me.name}', color=0x3399cc, description=page)
            await destination.send(embed=emby)
