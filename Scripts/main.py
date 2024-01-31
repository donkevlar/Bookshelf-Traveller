import requests

import settings
import discord
from discord.ext import commands
import os
from datetime import datetime
import time
from dotenv import load_dotenv

# File Imports
import commands as c

# Global Vars
SYNC_STATUS = False

# Logger Config
logger = settings.logging.getLogger("bot")

# Version Info
versionNumber = 'Alpha_0.12'
# Print Startup Time
current_time = datetime.now()
logger.info(f'Bot is Starting Up! | Startup Time: {current_time}')

print("\nStartup time:", current_time)

# Pulls from bookshelf file, if DOCKER == True, then this won't load local env file
if not c.DOCKER_VARS:
    load_dotenv()

# Get Discord Token from ENV
token = os.environ.get("DISCORD_TOKEN")

logger.info(f'\nStarting up bookshelf traveller v.{versionNumber}\n')

# Start Server Connection Prior to Running Bot
server_status_code = c.bookshelf_test_connection()

# Quit if server does not respond
if server_status_code != 200:
    logger.warning(f'Current Server Status = {server_status_code}')
    logger.warning("Issue with connecting to Audiobookshelf server!")
    logger.warning("Quitting!")
    time.sleep(0.5)
    exit()

elif server_status_code is None:
    pass

else:
    logger.info(f'Current Server Status = {server_status_code}, Good to go!')

# DEV -> Not recommended when running in a prod instance
# Remove comment to see token
# print(f'\nDiscord Token: {token}\n')

# Will print username when successful
auth_test = c.bookshelf_auth_test()

time.sleep(0.5)

# Bot basic setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = commands.Bot(command_prefix="$", intents=discord.Intents.all())


@client.event
async def on_ready():
    print(f'Bot is ready. Logged in as {client.user}')


@client.hybrid_command(name="sync", description="Re-syncs all of the bots commands")
async def sync_commands(ctx):
    global SYNC_STATUS
    try:
        SYNC_STATUS = True
        await client.tree.sync()
        await ctx.send("Successfully Synced Commands")
        logger.info(f' Successfully Synchronized Commands, for accuracy restart discord | Executed "sync"')
    except Exception as e:
        await ctx.send("Could not get complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: sync')


@client.hybrid_command(name="listening-stats", description="Pulls your total listening time and other useful stats")
async def totalTime(ctx):
    try:
        formatted_sessions_string, data = c.bookshelf_listening_stats()
        total_time = round(data.get('totalTime') / 60)  # Convert to Minutes
        if total_time >= 60:
            total_time = round(total_time / 60)  # Convert to hours
            message = f'Total Listening Time : {total_time} Hours'
        else:
            message = f'Total Listening Time : {total_time} Minutes'
        await ctx.send(message)
        logger.info(f' Successfully sent command: listening-stats')

    except Exception as e:
        ctx.send("Could not get complete this at the moment, please try again later.")
        print("Error: ", e)
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: listening-stats')


@client.hybrid_command(name="ping", description="Latency of the discord bot server to the discord central shard.")
async def ping(ctx):
    latency = round(client.latency * 1000)
    message = f'Discord BOT Server Latency: {latency} ms'
    await ctx.send(message)
    logger.info(f' Successfully sent command: ping')


@client.hybrid_command(name="all-libraries",
                       description="Display all current libraries with their ID and if only audiobooks")
async def show_all_libraries(ctx):
    try:
        # Get Library Data from API
        library_data = c.bookshelf_libraries()
        formatted_data = ""

        # Create Embed Message
        embed_message = discord.Embed(
            title="All Libraries",
            description="This will display all of the current libraries in your audiobookshelf server.",
            color=ctx.author.color
        )

        # Iterate over each key-value pair in the dictionary
        for name, (library_id, audiobooks_only) in library_data.items():
            formatted_data += f'\nName: {name} \nLibraryID: {library_id} \nAudiobooks Only: {audiobooks_only}\n\n'

        embed_message.add_field(name=f"Libraries", value=formatted_data, inline=False)

        await ctx.send(embed=embed_message)
        logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: all-libraries')
        print("Error: ", e)


@client.hybrid_command(name="recent-sessions",
                       description="Display up to 5 recent sessions")
async def show_recent_sessions(ctx):
    try:
        formatted_sessions_string, data = c.bookshelf_listening_stats()

        # Split formatted_sessions_string by newline character to separate individual sessions
        sessions_list = formatted_sessions_string.split('\n\n')
        count = 0
        # Add each session as a separate field in the embed
        for session_info in sessions_list:
            count = count + 1
            # Create Embed Message
            embed_message = discord.Embed(
                title=f"Session {count}",
                description=f"Recent Session Info",
                color=ctx.author.color
            )
            # Split session info into lines
            session_lines = session_info.strip().split('\n')
            # Extract display title from the first line
            display_title = session_lines[0].split(': ')[1]
            author = session_lines[1].split(': ')[1]
            duration = session_lines[2].split(': ')[1]
            library_ID = session_lines[3].split(': ')[1]
            play_count = session_lines[4].split(': ')[1]

            # Use display title as the name for the field
            embed_message.add_field(name='Title', value=display_title, inline=False)
            embed_message.add_field(name='Author', value=author, inline=False)
            embed_message.add_field(name='Duration', value=duration, inline=False)
            embed_message.add_field(name='Number of Times Played', value=f'Play Count: {play_count}', inline=False)
            embed_message.add_field(name='Library Item ID', value=library_ID, inline=False)

            await ctx.send(embed=embed_message)
            logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: recent-sessions')
        print("Error: ", e)


@client.hybrid_command(name="media-progress",
                       description=
                       "Searches for the media item's progress, note: use recent session to find library item id")
async def search_media_progress(ctx, *, libraryitemid: str):
    try:
        formatted_data, title, description = c.bookshelf_item_progress(libraryitemid)

        # Create Embed Message
        embed_message = discord.Embed(
            title=f"{title} | Media Progress",
            description=f"Media Progress for {title}",
            color=ctx.author.color
        )
        embed_message.add_field(name=title, value=formatted_data, inline=False)

        # Send message
        await ctx.send(embed=embed_message)
        logger.info(f' Successfully sent command: media-progress')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: media-progress')


@client.hybrid_command(name="sync-status",
                       description=
                       "returns a boolean for if server commands have synced lately with discord server shard.")
async def sync_status(ctx):
    await ctx.send(f'Current Sync Status: {SYNC_STATUS}')


@client.hybrid_command(name="user-search",
                       description=
                       "Searches for a specific user, case sensitive")
async def search_user(ctx, *, name: str):
    try:
        isFound, username, user_id, last_seen, isActive = c.bookshelf_get_users(name)

        if isFound:
            formatted_data = (
                f'Last Seen: {last_seen}\n'
                f'is Active: {isActive}\n'
            )

            # Create Embed Message
            embed_message = discord.Embed(
                title=f"User Info | {username}",
                description=f"User information for {username}",
                color=ctx.author.color
            )
            embed_message.add_field(name="Username", value=username, inline=False)
            embed_message.add_field(name="User ID", value=user_id, inline=False)
            embed_message.add_field(name="General Information", value=formatted_data, inline=False)

            # Send message
            await ctx.send(embed=embed_message)
            logger.info(f' Successfully sent command: search_user')

    except TypeError as e:
        await ctx.send("Could not find that user, try a different name or make sure that it is spelt correctly.")
        logger.info(f' Successfully sent command: search_user')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: search_user')


@client.hybrid_command(name="add-user",
                       description="Will create a user, user types: 'admin', 'guest', 'user' | Default = user")
async def search_user(ctx, *, name: str, password: str, user_type="user", email=None):
    try:
        user_id, c_username = c.bookshelf_create_user(name, password, user_type)
        await ctx.send(f"Successfully Created User: {c_username} with ID: {user_id}!")
        logger.info(f' Successfully sent command: add-user')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: add-user')


@client.hybrid_command(name="test-connection",
                       description="test the connection between this bot and the audiobookshelf server, "
                                   "optionally can place any url")
async def test_server_connection(ctx, opt_url=None):
    try:
        if opt_url is not None:
            r = requests.get(opt_url)
            status = r.status_code

            await ctx.send(f"Successfully connected to {opt_url} with status: {status}")
        else:
            status = c.bookshelf_test_connection()
            await ctx.send(f"Successfully connected to {c.bookshelfURL} with status: {status}")

        logger.info(f' Successfully sent command: test-connection')

    except Exception as e:
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: add-user')


@client.hybrid_command(name="book-list-csv",
                       description="Get complete list of items in a given library, outputs a csv")
async def library_csv_booklist(ctx, libraryid: str):
    try:
        # Get Current Working Directory
        current_directory = os.getcwd()

        # Create CSV File
        c.bookshelf_library_csv(libraryid)

        # Get Filepath
        file_path = os.path.join(current_directory, 'books.csv')

        await ctx.send(file=discord.File(file_path))
        logger.info(f' Successfully sent command: test-connection')

    except Exception as e:

        await ctx.send("Could not complete this at the moment, please try again later.")

        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: add-user')


class SimpleButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.red)
    async def delete_user(self, interaction: discord.Interaction, Button: discord.ui.Button):
        output = "yes"
        return output

    @discord.ui.button(label="No", style=discord.ButtonStyle.gray)
    async def delete_user(self, interaction: discord.Interaction, Button: discord.ui.Button):
        output = "no"
        return output


# @client.tree.command(name="delete-user", description="Delete a user on your server")
# async def delete_user(ctx, *, name: str):
# pass


client.run(settings.DISCORD_API_SECRET, root_logger=True)
