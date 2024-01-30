import settings
import discord
from discord.ext import commands
import os
from datetime import datetime
import time
from dotenv import load_dotenv

# File Imports
import Bookshelf as b

# Logger Config
logger = settings.logging.getLogger("bot")

# Version Info
versionNumber = 'Alpha_0.10'
# Print Startup Time
current_time = datetime.now()
logger.info(f'Bot is Starting Up! | Startup Time: {current_time}')

print("\nStartup time:", current_time)

# Pulls from bookshelf file, if DOCKER == True, then this won't load local env file
if not b.DOCKER_VARS:
    load_dotenv()

# Get Discord Token from ENV
token = os.environ.get("DISCORD_TOKEN")

print(f'\nStarting up bookshelf traveller v.{versionNumber}\n')

# Start Server Connection Prior to Running Bot
server_status_code = b.bookshelf_test_connection()

# Quit if server does not respond
if server_status_code != 200:
    print(f'Current Server Status = {server_status_code}')
    print("Issue with connecting to Audiobookshelf server!")
    print("Quitting!")
    time.sleep(1)
    exit()

elif server_status_code is None:
    pass

else:
    print(f'Current Server Status = {server_status_code}, Good to go!')

# DEV -> Not recommended when running in a prod instance
# Remove comment to see token
# print(f'\nDiscord Token: {token}\n')

# Will print username when successful
auth_test = b.bookshelf_auth_test()

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
    await client.tree.sync()
    await ctx.send("Successfully Synced Commands")
    logger.info(f' Successfully Synchronized Commands, for accuracy restart discord | Executed "sync"')


@client.hybrid_command(name="listening-stats", description="Pulls your total listening time and other useful stats")
async def totalTime(ctx):
    try:
        formatted_sessions_string, data = b.bookshelf_listening_stats()
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
        library_data = b.bookshelf_libraries()
        formatted_data = ""

        # Iterate over each key-value pair in the dictionary
        for name, (library_id, audiobooks_only) in library_data.items():
            formatted_data += f'\nName: {name}, \nLibraryID: {library_id}, \nAudiobooks Only: {audiobooks_only}\n\n'

        # Now you have the formatted data in the 'formatted_data' string
        # You can use it later in your program
        print(formatted_data)

        # Create Embed Message
        embed_message = discord.Embed(
            title="All Libraries",
            description="This will display all of the current libraries in your audiobookshelf server.",
            color=ctx.author.color
        )
        # Add Embed Field
        embed_message.add_field(name="Libraries", value=formatted_data, inline=False)

        await ctx.send(embed=embed_message)
        logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: all-libraries')
        print("Error: ", e)


@client.hybrid_command(name="recent-sessions",
                       description="Display last 5 sessions")
async def show_recent_sessions(ctx):
    try:
        formatted_sessions_string, data = b.bookshelf_listening_stats()

        # Create Embed Message
        embed_message = discord.Embed(
            title="Recent Sessions",
            description="Display last 5 sessions.",
            color=ctx.author.color
        )

        # Split formatted_sessions_string by newline character to separate individual sessions
        sessions_list = formatted_sessions_string.split('\n\n')

        # Add each session as a separate field in the embed
        for session_info in sessions_list:
            # Split session info into lines
            session_lines = session_info.strip().split('\n')
            # Extract display title from the first line
            display_title = session_lines[0].split(': ')[1]
            # Use display title as the name for the field
            embed_message.add_field(name=display_title, value=session_info, inline=False)

        await ctx.send(embed=embed_message)
        logger.info(f' Successfully sent command: recent-sessions')

    except Exception as e:
        await ctx.send("Could not complete this at the moment, please try again later.")
        logger.warning(
            f'User:{client.user} (ID: {client.user.id}) | Error occured: {e} | Command Name: recent-sessions')
        print("Error: ", e)


client.run(settings.DISCORD_API_SECRET, root_logger=True)
