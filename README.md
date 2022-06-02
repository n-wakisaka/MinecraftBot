# MinecraftBot
AWSEC2インスタンス上に立てたMinecraftサーバの起動を制御するDiscordBot

# 使い方
```
python3 server.py --config_file config.toml
```
`config.toml`をよしなに変更してください。

# 機能
* Discordボットへのメンションでサーバの起動・停止、サーバ参加人数確認ができます。 `@bot-name help`でコマンドがみれます。
* Minecraftサーバの人数が0人の場合、設定した時間経過するとMinecraftサーバ側のEC2インスタンスを停止します
* 放置防止のため、毎日定刻にMinecraftサーバを再起動します。EC2インスタンスは停止しません

# 準備
* DiscordBotを動かすAWSEC2インスタンスからMinecraftサーバの設定がされているインスタンスへssh接続ができる必要があります
* Minecraftサーバ側でQuery, RCON接続できる設定にしておく必要があります
* Minecraftサーバを動かすEC2インスタンスはQuery, RCON接続用のポートを通す必要があります
