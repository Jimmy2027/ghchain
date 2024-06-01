import subprocess
from typing import Optional

import click

from ghchain.config import logger


@logger.catch
def run_command(
    command, check=False, env: Optional[dict] = None, shell=False
) -> subprocess.CompletedProcess:
    try:
        logger.debug(f"Running command: {' '.join(command)}")
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=shell,
            check=check,
            env=env,
        )
        return result
    except subprocess.CalledProcessError as e:
        click.echo(f"Command '{' '.join(command)}' failed with error: {str(e)}")
        click.echo(f"Stdout: {e.stdout}")
        click.echo(f"Stderr: {e.stderr}")
        raise e
