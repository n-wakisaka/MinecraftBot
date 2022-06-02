import subprocess
import asyncio

async def subprocess_run(cmd, encording='utf-8'):
    """
    subprocessのrun, callをasyncにする関数
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    # print(f'[{cmd!r} exited with {proc.returncode}]')
    return stdout, stderr
