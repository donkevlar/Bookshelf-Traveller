import asyncio
import os
import settings
import logging
import sys
import pytz
import time

from config import current_config
from interactions import *
from interactions.api.events import *
from datetime import datetime
from dotenv import load_dotenv

# File Imports
import bookshelfAPI as c

# Pulls from bookshelf file
load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# Experimental Imports
# enables experimental features and modules


# Global Vars
MULTI_USER = eval(settings.MULTI_USER)
AUDIO_ENABLED = eval(settings.AUDIO_ENABLED)
DEBUG_MODE = settings.DEBUG_MODE

# TEMP
if DEBUG_MODE == "True":
    DEBUG_MODE = True
    logger.setLevel(logging.DEBUG)
else:
    DEBUG_MODE = False

# Controls if ALL commands are ephemeral
EPHEMERAL_OUTPUT = settings.EPHEMERAL_OUTPUT

# Timezone
TIMEZONE = settings.TIMEZONE
timeZone = pytz.timezone(TIMEZONE)

# Print Startup Time
current_time = datetime.now(timeZone)
logger.info(f'Bot is Starting Up! | Startup Time: {current_time}')

# Get Discord Token from ENV
token = os.environ.get("DISCORD_TOKEN")

logger.info(f'Starting up bookshelf traveller v.{settings.versionNumber}')
logger.warning('Please wait for this process to finish prior to use, you have been warned!')

# Print current config if value is present
logger.info("Current config to follow!")
for key, value in current_config.items():
    if value != '' and value is not None:
        logger.info(f"{key}: {value}")

# Start Server Connection Prior to Running Bot
server_status_code = c.bookshelf_test_connection()

# Quit if server does not respond
if server_status_code != 200:
    logger.warning(f'\nCurrent Server Status = {server_status_code}')
    logger.warning("\nIssue with connecting to Audiobookshelf server!")
    logger.warning("\nQuitting!")
    time.sleep(0.5)
    sys.exit(1)

else:
    logger.info(f'Current Server Status = {server_status_code}, Good to go!')


async def conn_test():
    # Will print username when successful
    auth_test, user_type, user_locked = await c.bookshelf_auth_test()
    logger.info(f"Logging user in and verifying role.")

    # Quit if user is locked
    if user_locked:
        logger.warning("User locked from logging in, please unlock via web gui.")
        sys.exit("User locked from logging in, please unlock via web gui.")

    # Check if ABS user is an admin
    ADMIN_USER = False
    if user_type == "root" or user_type == "admin":
        ADMIN_USER = True
        logger.info(f"ABS user logged in as ADMIN with type: {user_type}")
    else:
        logger.info(f"ABS user logged in as NON-ADMIN with type: {user_type}")
    return ADMIN_USER


# Bot basic setup
bot = Client(intents=Intents.DEFAULT, logger=logger)


# Event listener
@listen()
async def on_startup(event: Startup):
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
            mu.insert_data(discord_id=owner_id, user=username, token=user_token)
            logger.info(f'Registered initial user {username} successfully')
            if not DEBUG_MODE:
                await owner.send(f'Bot is ready. Logged in as {bot.user}. ABS user: {username} signed in.')
        else:
            logger.warning("No initial user registered, please use '/login' to register a user.")
            await owner.send("No initial user registered, please use '/login' to register a user.")
    else:
        if not DEBUG_MODE:
            await owner.send(f'Bot is ready. Logged in as {bot.user}.')

    logger.info('Bot has finished loading, it is now safe to use! :)')


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

    if AUDIO_ENABLED:
        # Load Audio Extension
        logger.info("Audio module loaded!")
        bot.load_extension("audio")
    else:
        logger.warning('Audio module disabled!')

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

    # Start Bot
    bot.start(settings.DISCORD_API_SECRET)
