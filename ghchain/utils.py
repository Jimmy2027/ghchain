import os
import subprocess
from typing import Optional

from ghchain.config import logger


def run_command(
    command: list[str],
    check=False,
    env: Optional[dict] = None,
    shell=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
) -> subprocess.CompletedProcess:
    try:
        cwd = os.getcwd()
        logger.debug(f"Running command: \"{' '.join(command)}\" in cwd: {cwd}")
        result = subprocess.run(
            command,
            stdout=stdout,
            stderr=stderr,
            text=True,
            check=check,
            env=env,
        )
        logger.debug(f"Command completed with return code: {result.returncode}")
        logger.trace(f"Command stdout: {result.stdout}")
        logger.trace(f"Command stderr: {result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Command '{' '.join(command)}' failed with error: {str(e)} in cwd: {cwd}"
        )
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        raise e
