import discord
from discord.ext import commands, tasks

import toml
import argparse
import asyncio
import paramiko
import subprocess
import time
import datetime
from mcipc.rcon.je import Client as rconClient
from mcipc.query import Client as queryClient

from dataclasses import dataclass


@dataclass
class ConfigMinecraftServer:
    ssh_username: str
    ssh_key_filepath: str
    run_command: str
    query_port: int
    rcon_port: int
    rcon_passwd: str

@dataclass
class Config:
    token: str
    game_server_instance_id: str
    timeout_minute: int
    maintenance_hour: int
    minecraft_server: ConfigMinecraftServer

class MyHelpCommand(commands.MinimalHelpCommand):
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


class MinecraftCog(commands.Cog, name='Minecraft'):
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.instance_id = self.config.game_server_instance_id
        self.server_ip = None
        self.local_ip = None

        self.is_restarted = False
        self.text_channels = {}

        self.member_empty_time = None
        self.elapsed_time = datetime.timedelta()
        self.timeout_timedelta = datetime.timedelta(minutes=self.config.timeout_minute+1)

    @commands.Cog.listener()
    async def on_ready(self):
        print('on_ready')
        if not self.check_close.is_running():
            self.check_close.start()
        self.server_ip = await self.get_public_ip()
        self.local_ip = await self.get_private_ip()
        await self.set_discord_status()

    async def set_discord_status(self):
        if await self.get_server_state() == 'running':
            await self.bot.change_presence(status=discord.Status.online)
        else:
            await self.bot.change_presence(status=discord.Status.idle, activity=discord.Game('サーバ停止中...'))

    async def subprocess_run(self, cmd, encording='utf-8'):
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        stdout, stderr = await proc.communicate()
        # print(f'[{cmd!r} exited with {proc.returncode}]')
        return stdout, stderr

    # get server infomation from aws instance
    async def get_server_info(self, key):
        stdout, _ = await self.subprocess_run(f'aws ec2 describe-instances --instance-ids {self.instance_id} --query "Reservations[*].Instances[*].{key}" --output text')
        return f'{stdout.decode("utf-8")}'.strip()

    async def get_server_state(self):
        return await self.get_server_info('State.Name')

    async def get_private_ip(self):
        return await self.get_server_info('PrivateIpAddress')
    
    async def get_public_ip(self):
        return await self.get_server_info('PublicIpAddress')

    # サーバとssh接続する
    def get_ssh_client(self):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(self.local_ip, username=self.config.minecraft_server.ssh_username, key_filename=self.config.minecraft_server.key_filepath)
        return ssh_client
    
    def get_minecraft_stats(self):
        with queryClient(self.local_ip, self.config.minecraft_server.query_port) as client:
            stats = client.stats(full=True)
        return stats
    
    def get_member_empty_elapsed_time(self):
        if self.member_empty_time is not None:
            return datetime.datetime.now() - self.member_empty_time
        else:
            return datetime.timedelta()

    # commands
    @commands.group()
    async def minecraft(self, ctx):
        pass

    def start_minecraft_server(self):
        ssh_client = self.get_ssh_client()

        # SSHでminecraftサーバ起動
        _, stdout, _ = ssh_client.exec_command(self.config.minecraft_server.run_command)
        for x in stdout:
            print(x.strip())
            if 'Done' in x:
                break
        ssh_client.close()
        self.can_stop = False
    
    def stop_minecraft_server(self):
        try:
            with rconClient(self.local_ip, self.config.minecraft_server.rcon_port, passwd=self.config.minecraft_server.rcon_passwd) as client:
                log = client.stop()
                print(log)
                time.sleep(10)
        except:
            pass
        self.member_empty_time = None

    async def send_message(self, channel, text):
        if channel is not None:
            await channel.send(text)
    
    async def send_message_all(self, text):
        for guild_id, channel in self.text_channels.items():
            await channel.send(text)

    async def start_impl(self, channel=None):
        # インスタンス起動状況確認
        if await self.get_server_state() == 'running':
            await self.send_message(channel, f'サーバは起動しています。アドレスは `{self.server_ip}` です')
            return
        
        await self.send_message(channel, 'サーバ起動中...')
        # インスタンスの起動
        await self.subprocess_run(f'aws ec2 start-instances --instance-ids {self.instance_id}')

        # インスタンスが起動するまで待機
        await self.subprocess_run(f'aws ec2 wait instance-running --instance-ids {self.instance_id}')
        await self.subprocess_run(f'aws ec2 wait instance-status-ok --instance-ids {self.instance_id}')

        # start server
        self.start_minecraft_server()

        # 接続用のIPアドレスをdiscordに送信
        await self.send_message(channel, f'サーバの起動に成功しました！ アドレスは `{self.server_ip}` です')
        await self.status_impl(channel)
    
    async def stop_impl(self, channel=None):
        # インスタンス起動状況確認
        if await self.get_server_state() != 'running':
            await self.send_message(channel, f'サーバは起動していません。')
            return

        await self.send_message(channel, f'サーバ停止中...')
        self.stop_minecraft_server()

        # インスタンスの停止
        await self.subprocess_run(f'aws ec2 stop-instances --instance-ids {self.instance_id}')
        await self.subprocess_run(f'aws ec2 wait instance-stopped --instance-ids {self.instance_id}')

        await self.send_message(channel, f'サーバの停止が完了しました。')
        await self.status_impl(channel)

    async def status_impl(self, channel):
        if channel is None:
            return
        if await self.get_server_state() != 'running':
            text = f'サーバ停止中'
            color = 0xff3232
        else:
            try:
                stats = self.get_minecraft_stats()
                text = f'サーバ稼働中 `{self.server_ip}`\n現在サーバに {stats.num_players} 人参加しています\n'
                if stats.num_players == 0:
                    text += f'0人で{self.config.timeout_minute}分経過するとサーバを自動停止します(現在{self.get_member_empty_elapsed_time().seconds//60}分経過しています)\n'
                text += f'毎日 `{str(self.config.maintenance_time).zfill(2)}:00` にサーバメンテナンスを実施予定です'
                color = 0x65ff32
            except:
                text = f'サーバ接続エラー'
                color = 0xff3232
        emby = discord.Embed(title=f'Minecraft Server Status', color=color, description=text)
        await channel.send(embed=emby)


    @minecraft.command()
    async def start(self, ctx):
        """
        Mincraftサーバを起動する
        """
        await self.start_impl(ctx.channel)
        self.text_channels[ctx.guild.id] = ctx.channel

    @minecraft.command()
    async def stop(self, ctx):
        """
        Mincraftサーバを停止する
        """
        await self.stop_impl(ctx.channel)
        self.text_channels[ctx.guild.id] = ctx.channel

    @minecraft.command()
    async def status(self, ctx):
        """
        Mincraftサーバのステータスを表示する
        """
        await self.status_impl(ctx.channel)
        self.text_channels[ctx.guild.id] = ctx.channel
        

    # hidden commands for debug
    @minecraft.command(hidden=True)
    async def start_on_server(self, ctx):
        self.start_minecraft_server()
    
    @minecraft.command(hidden=True)
    async def stop_on_server(self, ctx):
        self.stop_minecraft_server()

    @minecraft.command(hidden=True)
    async def restart_on_server(self, ctx):
        self.stop_minecraft_server()
        self.start_minecraft_server()

    # loop task
    @tasks.loop(minutes=1.0)
    async def check_close(self):
        await self.set_discord_status()
        if await self.get_server_state() != 'running':
            return
        try:
            stats = self.get_minecraft_stats()
            if self.member_empty_time is None and stats.num_players == 0:
                self.member_empty_time = datetime.datetime.now()
            elif stats.num_players != 0:
                self.member_empty_time = None
        except:
            self.member_empty_time = None

        elapsed_time = self.get_member_empty_elapsed_time()
        print('elapsed_time:', elapsed_time)
        if elapsed_time >= self.timeout_timedelta:
            await self.send_message_all(f'サーバ参加人数が0人で {elapsed_time.seconds//60}分経過したためサーバを停止します...')
            await self.stop_impl()
            for channel in self.text_channels.values():
                await self.status_impl(channel)
            return

        # 朝5時くらいに1日1度サーバを再起動する(放置対策)
        now = datetime.datetime.now()
        if not self.is_restarted and now.hour == self.config.maintenance_hour:
            self.is_restarted = True
            await self.send_message_all('サーバメンテナンス中...')
            self.stop_minecraft_server()
            self.start_minecraft_server()
            await self.send_message_all('サーバメンテナンスが終了しました')
            for channel in self.text_channels.values():
                await self.status_impl(channel)

        if self.is_restarted and now.hour == (self.config.maintenance_time+1)%24:
            self.is_restarted = False


    @check_close.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


class Bot:
    def __init__(self, config):
        self.bot = commands.Bot(
            intents=self.getDefaultIntents(),
            command_prefix=commands.when_mentioned,
            status=discord.Status.dnd,
            activity=discord.Game('起動中...'),
            help_command=MyHelpCommand())
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
        intents.members = True
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
    config = {}
    with open(args.config_file) as f:
        config = toml.load(f)
    main(args, Config(**config))