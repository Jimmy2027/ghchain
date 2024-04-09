import subprocess
from typing import Optional

import click


def run_command(
    command, check=False, env: Optional[dict] = None
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=check,
            env=env,
        )
        return result
    except subprocess.CalledProcessError as e:
        click.echo(f"Command '{' '.join(command)}' failed with error: {str(e)}")
        click.echo(f"Stdout: {e.stdout}")
        click.echo(f"Stderr: {e.stderr}")
        raise e
