import os
import platform
from logging.config import dictConfig
from dotenv import load_dotenv

load_dotenv(override=True)

# Version Info
versionNumber = 'V1.3.2 '

COMMAND_COUNT = 0

# Determine Platform
current_platform = platform.system()

# Debug Mode
DEBUG_MODE = os.environ.get('DEBUG_MODE', True)

# Server URL
# Mandatory
SERVER_URL = os.environ.get("bookshelfURL")

OPT_IMAGE_URL = os.getenv('OPT_IMAGE_URL', '')

# Client ID
CLIENT_ID = os.getenv('CLIENT_ID', '')

# Time Zone
TIMEZONE = os.getenv("TIMEZONE", "America/Toronto")

# Audio Enabled
AUDIO_ENABLED = os.getenv('AUDIO_ENABLED', True)

# Multi-user functionality, will remove token from admin and all admin functions
MULTI_USER = os.environ.get('MULTI_USER', True)

# Discord token
# Mandatory
DISCORD_API_SECRET = os.getenv("DISCORD_TOKEN")

# Default search provider
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", 'audible')

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

# Initial MSG when not in debug mode
INITIALIZED_MSG = os.getenv('INITIALIZED_MSG', True)

# Used for embed footers
bookshelf_traveller_footer = f'Powered by Bookshelf Traveller 🕮 | {versionNumber}'

bookshelf_startup_msg = f'''
    =============================================================
    |                                                           |
    |        WELCOME TO BOOKSHELF-TRAVELLER                     |
    |-----------------------------------------------------------|
    |        Discover your next literary adventure!             |
    |                                                           |
    |        Version: {versionNumber}                                   |
    |        Author: DonKevlar                                  |
    |-----------------------------------------------------------|
    =============================================================
    
    '''

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # Fixed typo: disabled_existing_loggers should be disable_existing_loggers
    "formatters": {
        "verbose": {
            "format": "%(levelname)-5s - %(asctime)s - %(module)-5s : %(message)s",
            "datefmt": "%H:%M:%S",  # Apply datefmt here for verbose formatter
        },
        "standard": {
            "format": "%(levelname)-5s - %(asctime)s : %(message)s",
            "datefmt": "%H:%M:%S",  # Apply datefmt here for standard formatter
        },
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
