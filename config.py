import toml
from dataclasses import dataclass

@dataclass
class ConfigMinecraftServer:
    aws_instance_id: str
    timeout_minute: int
    maintenance_hour: int
    timezone: str
    ssh_username: str
    ssh_key_filepath: str
    run_command: str
    query_port: int
    rcon_port: int
    rcon_passwd: str

@dataclass
class Config:
    token: str
    minecraft_server: ConfigMinecraftServer


def load_config(path):
    config = {}
    with open(path) as f:
        config = toml.load(f)
    config = Config(**config)
    config.minecraft_server = ConfigMinecraftServer(**config.minecraft_server)
    return config
