import asyncio
import traceback
import os
import settings
from config import current_config
import logging
from interactions import *
from interactions.ext.paginators import Paginator
from interactions.api.events import *
from datetime import datetime
import sys
import pytz
import time
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


# Function which holds the library options for related autocomplete
def option_library_name():
    def wrapper(func):
        return slash_option(
            name="library_name",
            opt_type=OptionType.STRING,
            description="Select a library",
            required=True,
            autocomplete=True
        )(func)

    return wrapper


# Custom check for ownership
async def ownership_check(ctx: BaseContext):
    # Default only owner can use this bot
    ownership = os.getenv('OWNER_ONLY', True)
    if ownership:
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.username == ctx.user.username:
            logger.info(f"{ctx.user.username}, you are the owner and ownership is enabled!")
            return True

        else:
            logger.warning(f"{ctx.user.username}, is not the owner and ownership is enabled!")
            return False
    else:
        return True


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


# Listening Stats, currently pulls the total time listened and converts it to hours
@slash_command(name="listening-stats", description="Pulls your total listening time and other useful stats")
async def totalTime(ctx: SlashContext):
    try:
        formatted_sessions_string, data = await c.bookshelf_listening_stats()
        total_time = round(data.get('totalTime') / 60)  # Convert to Minutes
        if total_time >= 60:
            total_time = round(total_time / 60)  # Convert to hours
            message = f'Total Listening Time : {total_time} Hours'
        else:
            message = f'Total Listening Time : {total_time} Minutes'
        await ctx.send(message, ephemeral=EPHEMERAL_OUTPUT)
        logger.info(f' Successfully sent command: listening-stats')

    except Exception as e:
        await ctx.send("Could not get complete this at the moment, please try again later.")
        print("Error: ", e)
        logger.warning(
            f'User:{bot.user} (ID: {bot.user.id}) | Error occurred: {e} | Command Name: listening-stats')


# Pings the server, can ping other servers, why? IDK, cause why not.
@slash_command(name="ping", description="Latency of the discord bot server to the discord central shard.")
async def ping(ctx: SlashContext):
    latency = round(bot.latency * 1000)
    message = f'Discord BOT Server Latency: {latency} ms'
    await ctx.send(message, ephemeral=EPHEMERAL_OUTPUT)
    logger.info(f' Successfully sent command: ping')


# Display a formatted list (embedded) of current libraries
@slash_command(name="all-libraries",
               description="Display all current libraries with their ID and a boolean ")
@check(ownership_check)
async def show_all_libraries(ctx: SlashContext):
    try:
        # Get Library Data from API
        library_data = await c.bookshelf_libraries()
        formatted_data = ""

        # Create Embed Message
        embed_message = Embed(
            title="All Libraries",
            description="This will display all of the current libraries in your audiobookshelf server.",
            color=ctx.author.accent_color
        )

        # Iterate over each key-value pair in the dictionary
        for name, (library_id, audiobooks_only) in library_data.items():
            formatted_data += f'\nName: {name} \nLibraryID: {library_id} \nAudiobooks Only: {audiobooks_only}\n\n'

        embed_message.add_field(name=f"Libraries", value=formatted_data, inline=False)

        await ctx.send(embed=embed_message, ephemeral=EPHEMERAL_OUTPUT)
        logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(f'User:{bot.user} (ID: {bot.user.id}) | Error occured: {e} | Command Name: all-libraries')
        print("Error: ", e)


# List the recent sessions, limited to 10 with API. Will merge if books are the same.
@slash_command(name="recent-sessions",
               description="Display up to 10 recent sessions")
async def show_recent_sessions(ctx: SlashContext):
    try:
        await ctx.defer(ephemeral=EPHEMERAL_OUTPUT)
        formatted_sessions_string, data = await c.bookshelf_listening_stats()

        # Split formatted_sessions_string by newline character to separate individual sessions
        sessions_list = formatted_sessions_string.split('\n\n')
        count = 0
        embeds = []
        # Add each session as a separate field in the embed
        for session_info in sessions_list:
            count = count + 1
            # Create Embed Message
            embed_message = Embed(
                title=f"Session {count}",
                description=f"Recent Session Info",
                color=ctx.author.accent_color
            )
            # Split session info into lines
            session_lines = session_info.strip().split('\n')
            # Extract display title from the first line
            display_title = session_lines[0].split(': ')[1]
            author = session_lines[1].split(': ')[1]
            duration = session_lines[2].split(': ')[1]
            library_ID = session_lines[3].split(': ')[1]
            play_count = session_lines[4].split(': ')[1]
            aggregate_time = session_lines[5].split(': ')[1]

            cover_link = await c.bookshelf_cover_image(library_ID)
            logger.info(f"cover url: {cover_link}")

            # Use display title as the name for the field
            embed_message.add_field(name='Title', value=display_title, inline=False)
            embed_message.add_field(name='Author', value=author, inline=False)
            embed_message.add_field(name='Book Length', value=duration, inline=False)
            embed_message.add_field(name='Aggregate Session Time', value=aggregate_time, inline=False)
            embed_message.add_field(name='Number of Times a Session was Played', value=f'Play Count: {play_count}',
                                    inline=False)
            embed_message.add_field(name='Library Item ID', value=library_ID, inline=False)
            embed_message.add_image(cover_link)

            embeds.append(embed_message)

        paginator = Paginator.create_from_embeds(bot, *embeds, timeout=120)
        await paginator.send(ctx, ephemeral=EPHEMERAL_OUTPUT)

        logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{bot.user} (ID: {bot.user.id}) | Error occurred: {e} | Command Name: recent-sessions')
        print("Error: ", e)


# Retrieves a specific media item and it's progress
@slash_command(name="media-progress",
               description="Searches for the media item's progress")
@slash_option(name="book_title", description="Enter a book title", required=True, opt_type=OptionType.STRING,
              autocomplete=True)
async def search_media_progress(ctx: SlashContext, book_title: str):
    try:
        formatted_data = await c.bookshelf_item_progress(book_title)

        cover_title = await c.bookshelf_cover_image(book_title)

        chapter_progress, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(book_title)

        if bookFinished:
            chapterTitle = "Book Finished"
        else:
            chapterTitle = chapter_progress['title']

        title = formatted_data['title']
        progress = formatted_data['progress']
        finished = formatted_data['finished']
        currentTime = formatted_data['currentTime']
        totalDuration = formatted_data['totalDuration']
        lastUpdated = formatted_data['lastUpdated']

        media_progress = (f"Progress: {progress}\nChapter Title: {chapterTitle}\n "
                          f"Time Progressed: {currentTime} Hours\n "
                          f"Total Duration: {totalDuration} Hours\n")
        media_status = f"Is Finished: {finished}\n " f"Last Updated: {lastUpdated}\n"

        # Create Embed Message
        embed_message = Embed(
            title=f"{title} | Media Progress",
            description=f"Media Progress for {title}",
            color=ctx.author.accent_color
        )
        embed_message.add_field(name="Title", value=title, inline=False)
        embed_message.add_field(name="Media Progress", value=media_progress, inline=False)
        embed_message.add_field(name="Media Status", value=media_status, inline=False)
        embed_message.add_image(cover_title)

        # Send message
        await ctx.send(embed=embed_message, ephemeral=EPHEMERAL_OUTPUT)
        logger.info(f' Successfully sent command: media-progress')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, likely due to no progress found. Please try again later",
                       ephemeral=EPHEMERAL_OUTPUT)
        logger.warning(
            f'User:{bot.user} (ID: {bot.user.id}) | Error occured: {e} | Command Name: media-progress')


# Autocomplete function, looks for the book title
@search_media_progress.autocomplete("book_title")
async def search_media_auto_complete(ctx: AutocompleteContext):
    user_input = ctx.input_text
    choices = []
    print(user_input)
    if user_input == "":
        try:
            formatted_sessions_string, data = await c.bookshelf_listening_stats()

            for sessions in data['recentSessions']:
                title = sessions.get('displayTitle')
                bookID = sessions.get('libraryItemId')
                formatted_item = {"name": title, "value": bookID}

                if formatted_item not in choices:
                    choices.append(formatted_item)

            await ctx.send(choices=choices)

        except Exception as e:
            await ctx.send(choices=choices)
            print(e)

    else:
        try:
            titles_ = await c.bookshelf_title_search(user_input)
            for info in titles_:
                book_title = info["title"]
                book_id = info["id"]
                choices.append({"name": f"{book_title}", "value": f"{book_id}"})

            await ctx.send(choices=choices)

        except Exception as e:  # NOQA
            await ctx.send(choices=choices)
            logger.error(e)
            traceback.print_exc()


# Self-explanatory, pulls all a library's items
@slash_command(name="all-library-items", description=f"Get all library items from the currently signed in ABS user.")
@check(ownership_check)
@option_library_name()
async def all_library_items(ctx: SlashContext, library_name: str):
    try:
        await ctx.defer()
        library_items = await c.bookshelf_all_library_items(library_name)
        print(library_items)
        formatted_info = ""

        for items in library_items:
            print(items)
            title = items['title']
            author = items['author']
            # book_id = items['id']
            formatted_info += f"\nTitle: {title} | Author: {author}\n"

        paginator = Paginator.create_from_string(bot, formatted_info, timeout=120, page_size=2000)

        await paginator.send(ctx, ephemeral=True)

    except Exception as e:
        print(e)
        traceback.print_exc()
        logger.error(e)
        await ctx.send("Could not complete this at the moment, please try again later.")


# Another Library Name autocomplete
@all_library_items.autocomplete("library_name")
async def autocomplete_all_library_items(ctx: AutocompleteContext):
    library_data = await c.bookshelf_libraries()
    choices = []

    for name, (library_id, audiobooks_only) in library_data.items():
        choices.append({"name": name, "value": library_id})

    print(choices)
    if choices:
        await ctx.send(choices=choices)


# Main Loop
if __name__ == '__main__':
    ADMIN = asyncio.run(conn_test())

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
