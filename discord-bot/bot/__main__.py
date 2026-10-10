import logging

import discord

from .config import Config
from .main import HelperBot


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    config = Config.load()
    HelperBot(config).run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
