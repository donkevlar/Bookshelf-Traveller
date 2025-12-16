import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import pytz
from dotenv import load_dotenv
from interactions import *

# File Imports
import bookshelfAPI as c
import db_additions
import settings
from subscription_task import conn_test, initialize_task_database, close_task_database
from wishlist import initialize_database as initialize_wishlist_database, close_database as close_wishlist_database
from interactions.api.events import *
from settings_watcher import SettingsWatcher, reload_bot_components

# Pulls from bookshelf file
load_dotenv()

# Logger Config
logger = logging.getLogger("bot")
handler = logging.StreamHandler()
console_handler = logger.handlers[0]
original_formatter = console_handler.formatter

# Global Vars
MULTI_USER = settings.MULTI_USER
# AUDIO_ENABLED = settings.AUDIO_ENABLED
DEBUG_MODE = settings.DEBUG_MODE
INITIALIZED_MSG = settings.INITIALIZED_MSG
EPHEMERAL_OUTPUT = settings.EPHEMERAL_OUTPUT

# Timezone
TIMEZONE = settings.TIMEZONE
timeZone = pytz.timezone(TIMEZONE)

# Print Startup Time
current_time = datetime.now(timeZone)

# Remove the formatter temporarily to log without any format
console_handler.setFormatter(None)
logger.info(f'Bot is Starting Up! | Startup Time: {current_time}')

if settings.CLIENT_ID:
    CLIENT_ID = settings.CLIENT_ID
    invite_url = f"Bot Invite Link: https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=277062405120&integration_type=0&scope=bot"
    logger.info(invite_url)

logger.info(settings.bookshelf_startup_msg)

# Get Discord Token from ENV
token = os.environ.get("DISCORD_TOKEN")

# Restore original Formatting
console_handler.setFormatter(original_formatter)
logger.info(f'Starting up bookshelf traveller {settings.versionNumber}')
logger.warning('Please wait for this process to finish prior to use, you have been warned!')

# Print current config if value is present
logger.info("Current config to follow!")
# Should initial msg be sent
logger.info(f"Initialization MSGs Enabled: {INITIALIZED_MSG}")
for key, value in settings.current_config.items():
    if value != '' and value is not None:
        logger.info(f"{key}: {value}")

# Start Server Connection Prior to Running Bot
server_status_code = c.bookshelf_test_connection()

# Quit if server does not respond
if server_status_code != 200:
    logger.warning(f'Current Server Status = {server_status_code}')
    logger.warning("Issue with connecting to Audiobookshelf server!")
    logger.warning("Quitting!")
    time.sleep(0.5)
    sys.exit(1)

else:
    logger.info(f'Current Server Status = {server_status_code}, Good to go!')

# Bot basic setup
bot = Client(intents=Intents.DEFAULT, logger=logger)

# Settings watcher for auto-reload
settings_watcher = None


# Event listener
@listen()
async def on_startup(event: Startup):
    # Initialize databases in the bot's event loop
    logger.info("Initializing async databases...")
    try:
        await initialize_wishlist_database()
        logger.info("Wishlist database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize wishlist database: {e}")
        raise

    try:
        await initialize_task_database()
        logger.info("Task database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize task database: {e}")
        raise

    # Start settings watcher for auto-reload
    global settings_watcher
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_file):
        env_file = ".env"
    settings_watcher = SettingsWatcher(env_file, reload_bot_components)
    settings_watcher.start()

    # Startup Sequence
    print(f'Bot is ready. Logged in as {bot.user}')

    owner = event.client.owner
    owner_id = owner.id

    if settings.EXPERIMENTAL:
        logger.warning(f'EXPERIMENTAL FEATURES ENABLED!')

    if MULTI_USER:
        import multi_user as mu
        user_token = os.getenv('bookshelfToken')
        user_info = c.bookshelf_user_login(token=user_token)
        username = user_info['username']
        if username != '':
            # Check if multi_user also needs async conversion
            try:
                mu.insert_data(discord_id=owner_id, user=username, token=user_token)
            except Exception as e:
                # If multi_user is also async
                await mu.insert_data(discord_id=owner_id, user=username, token=user_token)
            logger.info(f'Registered initial user {username} successfully')
            if not DEBUG_MODE and INITIALIZED_MSG:
                await owner.send(f'Bot is ready. Logged in as {bot.user}. ABS user: {username} signed in.')
                # Set env to true
                os.putenv('INITIALIZED_MSG', "False")
        else:
            logger.warning("No initial user registered, please use '/login' to register a user.")
            await owner.send("No initial user registered, please use '/login' to register a user.")
    else:
        if not DEBUG_MODE and INITIALIZED_MSG:
            await owner.send(f'Bot is ready. Logged in as {bot.user}.')
            os.putenv('INITIALIZED_MSG', "False")

    logger.info('Bot has finished loading, it is now safe to use! :)')


@listen()
async def on_disconnect(event):
    """Handle bot shutdown and cleanup"""
    logger.info("Bot is shutting down, closing database connections...")
    try:
        await close_wishlist_database()
        logger.info("Wishlist database closed successfully")
    except Exception as e:
        logger.error(f"Error closing wishlist database: {e}")

    try:
        await close_task_database()
        logger.info("Task database closed successfully")
    except Exception as e:
        logger.error(f"Error closing task database: {e}")

    # Stop settings watcher
    global settings_watcher
    if settings_watcher:
        settings_watcher.stop()


# Main Loop
if __name__ == '__main__':
    ADMIN = asyncio.run(conn_test())

    # Load default commands
    logger.info("Default Commands loaded!")
    bot.load_extension('default_commands')

    # Load context menu module
    logger.info('Context Menus module loaded!')
    bot.load_extension("context-menus")

    # Load subscription module
    logger.info('Subscribable Task module loaded!')
    bot.load_extension("subscription_task")

    # Load wishlist module
    logger.info('Wishlist module loaded!')
    bot.load_extension("wishlist")

    # Must load audio module
    logger.info("Audio module loaded!")
    bot.load_extension("audio")

    # Load Admin related extensions
    if ADMIN and not MULTI_USER:
        logger.info("Admin module loaded!")
        bot.load_extension("administration")

    # Load multi user extension
    if MULTI_USER:
        logger.info("MULTI_USER module loaded!")
        bot.load_extension("multi_user")
    else:
        logger.warning("MULTI_USER module disabled!")

    logger.info("Extensions loaded. Database will initialize when bot starts.")

    # Start Bot
    bot.start(settings.DISCORD_API_SECRET)