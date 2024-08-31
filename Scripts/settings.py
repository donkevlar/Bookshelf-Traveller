import os
from logging.config import dictConfig
from dotenv import load_dotenv


load_dotenv(override=True)

# Version Info
versionNumber = 'V1.2.7'

COMMAND_COUNT = 0

# Debug Mode
DEBUG_MODE = os.environ.get('DEBUG_MODE', True)

# Server URL
SERVER_URL = os.environ.get("bookshelfURL")

OPT_IMAGE_URL = os.getenv('OPT_IMAGE_URL', '')

# Time Zone
TIMEZONE = os.getenv("TIMEZONE", "America/Toronto")

# Audio Enabled
AUDIO_ENABLED = os.getenv('AUDIO_ENABLED', True)

# Multi-user functionality, will remove token from admin and all admin functions
MULTI_USER = os.environ.get('MULTI_USER', True)

# Discord token
DISCORD_API_SECRET = os.getenv("DISCORD_TOKEN")

# Default search provider
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", '')

# Controls if ALL commands are ephemeral
EPHEMERAL_OUTPUT = os.getenv('EPHEMERAL_OUTPUT', True)

# Enables Experimental Commands
EXPERIMENTAL = os.getenv('EXPERIMENTAL', False)

# Task frequency
TASK_FREQUENCY = int(os.getenv('TASK_FREQUENCY', 5))

# Update Frequency for internal tasks, default 5 seconds
UPDATES = os.getenv('UPDATES', 5)

# TEST ENV1
TEST_ENV1 = os.getenv('TEST_ENV1')

# Playback Role
PLAYBACK_ROLE = os.getenv('PLAYBACK_ROLE', 0)

# Ownership check
OWNER_ONLY = os.getenv('OWNER_ONLY', True)

# Used for embed footers
bookshelf_traveller_footer = f'Powered by Bookshelf Traveller 🕮 | {versionNumber}'

LOGGING_CONFIG = {
    "version": 1,
    "disabled_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)-5s - %(asctime)s - %(module)-5s : %(message)s"
        },
        "standard": {"format": "%(levelname)-5s - %(asctime)s : %(message)s"},
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "console2": {
            "level": "WARNING",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "bot": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "discord": {
            "handlers": ["console2"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

dictConfig(LOGGING_CONFIG)