import subprocess

import click


def run_command(command, check=False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=check)
        return result
    except subprocess.CalledProcessError as e:
        click.echo(f"Command '{' '.join(command)}' failed with error: {str(e)}")
        return None
