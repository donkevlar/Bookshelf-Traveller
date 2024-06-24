import os
from logging.config import dictConfig
from dotenv import load_dotenv


load_dotenv()

# Version Info
versionNumber = 'Beta_Audio_1.0.1'

COMMAND_COUNT = 0

# Enables monitor to send alerts to the owner
MONITOR_ALERTS = os.getenv("MONITOR_ALERTS", False)

# Time Zone
TIMEZONE = os.getenv("TIMEZONE", "America/Toronto")

# Discord token
DISCORD_API_SECRET = os.getenv("DISCORD_TOKEN")

# Controls if ALL commands are ephemeral
EPHEMERAL_OUTPUT = os.getenv('EPHEMERAL_OUTPUT', True)

# Enables Experimental Commands
EXPERIMENTAL = os.getenv('EXPERIMENTAL', False)

# Update Frequency for internal tasks, default 5 seconds
UPDATES = os.getenv('UPDATES', 5)

# TEST ENV1
TEST_ENV1 = os.getenv('TEST_ENV1')

LOGGING_CONFIG = {
    "version": 1,
    "disabled_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)-10s - %(asctime)s - %(module)-15s : %(message)s"
        },
        "standard": {"format": "%(levelname)-10s - %(name)-15s : %(message)s"},
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