import discord
from discord.ext import commands, tasks

import asyncio
import paramiko
import time
import datetime
from mcipc.rcon.je import Client as rconClient
from mcipc.query import Client as queryClient

from util import subprocess_run


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

    async def set_discord_status(self):
        """
        サーバ用AWSインスタンス起動状況をDiscord Statusに反映させる
        """
        if await self.get_server_state() == 'running':
            await self.bot.change_presence(status=discord.Status.online)
        else:
            await self.bot.change_presence(status=discord.Status.idle, activity=discord.Game('サーバ停止中...'))

    async def get_aws_server_info(self, keyword):
        """
        AWSインスタンスの情報を取得する
        """
        stdout, _ = await subprocess_run(f'aws ec2 describe-instances --instance-ids {self.instance_id} --query "Reservations[*].Instances[*].{keyword}" --output text')
        return f'{stdout.decode("utf-8")}'.strip()

    async def get_server_state(self):
        return await self.get_aws_server_info('State.Name')

    async def get_private_ip(self):
        return await self.get_aws_server_info('PrivateIpAddress')
    
    async def get_public_ip(self):
        return await self.get_aws_server_info('PublicIpAddress')

    def get_ssh_client(self):
        """
        サーバとSSH接続するparmiko clientを取得する
        """
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(self.local_ip, username=self.config.minecraft_server.ssh_username, key_filename=self.config.minecraft_server.ssh_key_filepath)
        return ssh_client
    
    def get_minecraft_stats(self):
        """
        Minecraftサーバに接続しstatsを取得する
        """
        with queryClient(self.local_ip, self.config.minecraft_server.query_port) as client:
            stats = client.stats(full=True)
        return stats
    
    def get_member_empty_elapsed_time(self):
        """
        サーバ人数が0人状態の経過時間を取得する
        """
        if self.member_empty_time is not None:
            return datetime.datetime.now() - self.member_empty_time
        else:
            return datetime.timedelta()

    @commands.Cog.listener()
    async def on_ready(self):
        print('on_ready')
        if not self.check_close.is_running():
            self.check_close.start()
        self.server_ip = await self.get_public_ip()
        self.local_ip = await self.get_private_ip()
        await self.set_discord_status()
    
    def start_minecraft_server(self):
        ssh_client = self.get_ssh_client()
        _, stdout, _ = ssh_client.exec_command(self.config.minecraft_server.run_command)
        for x in stdout:
            print(x.strip())
            if 'Done' in x:
                break
        ssh_client.close()
    
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
        await subprocess_run(f'aws ec2 start-instances --instance-ids {self.instance_id}')

        # インスタンスが起動するまで待機
        await subprocess_run(f'aws ec2 wait instance-running --instance-ids {self.instance_id}')
        await subprocess_run(f'aws ec2 wait instance-status-ok --instance-ids {self.instance_id}')

        # start server
        self.start_minecraft_server()

        # 接続用のIPアドレスをdiscordに送信
        await self.send_message_all(f'サーバが起動しました！ アドレスは `{self.server_ip}` です')
        await self.send_server_status_all()
    
    async def stop_impl(self, channel=None):
        # インスタンス起動状況確認
        if await self.get_server_state() != 'running':
            await self.send_message(channel, f'サーバは起動していません')
            return

        await self.send_message(channel, f'サーバ停止中...')
        self.stop_minecraft_server()

        # インスタンスの停止
        await subprocess_run(f'aws ec2 stop-instances --instance-ids {self.instance_id}')
        await subprocess_run(f'aws ec2 wait instance-stopped --instance-ids {self.instance_id}')

        await self.send_message_all(f'サーバが停止しました')
        await self.send_server_status_all()

    async def send_server_status(self, channel):
        if channel is None:
            return
        if await self.get_server_state() != 'running':
            text = f'サーバ停止中'
            color = 0xff9932
        else:
            try:
                stats = self.get_minecraft_stats()
                text = f'サーバ稼働中 `{self.server_ip}`\n現在サーバに {stats.num_players} 人参加しています\n'
                if stats.num_players == 0:
                    text += f'0人で{self.config.timeout_minute}分経過するとサーバを自動停止します(現在{self.get_member_empty_elapsed_time().seconds//60}分経過しています)\n'
                text += f'毎日 `{str(self.config.maintenance_hour).zfill(2)}:00` にサーバメンテナンスを実施予定です'
                color = 0x65ff32
            except:
                text = f'サーバ接続エラー'
                color = 0xff3232
        emby = discord.Embed(title=f'Minecraft Server Status', color=color, description=text)
        await channel.send(embed=emby)

    async def send_server_status_all(self):
        for guild_id, channel in self.text_channels.items():
            await self.send_server_status(channel)

    # commands
    @commands.group()
    async def minecraft(self, ctx):
        pass

    @minecraft.command()
    async def start(self, ctx):
        """
        Mincraftサーバを起動する
        """
        self.text_channels[ctx.guild.id] = ctx.channel
        await self.start_impl(ctx.channel)

    @minecraft.command()
    async def stop(self, ctx):
        """
        Mincraftサーバを停止する
        """
        self.text_channels[ctx.guild.id] = ctx.channel
        await self.stop_impl(ctx.channel)

    @minecraft.command()
    async def status(self, ctx):
        """
        Mincraftサーバのステータスを表示する
        """
        self.text_channels[ctx.guild.id] = ctx.channel
        await self.send_server_status(ctx.channel)
        

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

        # 接続人数が0人の継続時間を計算
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
            return

        # 指定時間に1日1度サーバを再起動する(放置対策)
        now = datetime.datetime.now()
        if not self.is_restarted and now.hour == self.config.maintenance_hour:
            self.is_restarted = True
            await self.send_message_all('サーバメンテナンス中...')
            self.stop_minecraft_server()
            self.start_minecraft_server()
            await self.send_message_all('サーバメンテナンスが終了しました')
            await self.send_server_status_all()

        if self.is_restarted and now.hour == (self.config.maintenance_time+1)%24:
            self.is_restarted = False


    @check_close.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
