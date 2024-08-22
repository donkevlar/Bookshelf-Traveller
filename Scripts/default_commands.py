import os

import logging
import traceback
import bookshelfAPI as c

from interactions.ext.paginators import Paginator
from interactions import *
import settings

# Logger Config
logger = logging.getLogger("bot")

# Global VARS
# Controls if ALL commands are ephemeral
EPHEMERAL_OUTPUT = settings.EPHEMERAL_OUTPUT


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


class PrimaryCommands(Extension):
    def __init__(self, bot):
        pass

    # Slash Commands --------------------------------------------------
    #

    # Pings the server, can ping other servers, why? IDK, cause why not.
    @slash_command(name="ping", description="Latency of the discord bot server to the discord central shard.")
    async def ping(self, ctx: SlashContext):
        latency = round(self.bot.latency * 1000)
        message = f'Discord BOT Server Latency: {latency} ms'
        await ctx.send(message, ephemeral=EPHEMERAL_OUTPUT)
        logger.debug(f' Successfully sent command: ping')

    # Self-explanatory, pulls all a library's items
    @check(ownership_check)
    @slash_command(name="all-library-items",
                   description=f"Get all library items from the currently signed in ABS user.")
    @option_library_name()
    async def all_library_items(self, ctx: SlashContext, library_name: str):
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

            paginator = Paginator.create_from_string(self.bot, formatted_info, timeout=120, page_size=2000)

            await paginator.send(ctx, ephemeral=True)

        except Exception as e:
            print(e)
            traceback.print_exc()
            logger.error(e)
            await ctx.send("Could not complete this at the moment, please try again later.")

    # Listening Stats, currently pulls the total time listened and converts it to hours
    @slash_command(name="listening-stats", description="Pulls your total listening time and other useful stats")
    async def totalTime(self, ctx: SlashContext):
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
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: listening-stats')

    # Autocomplete -------------------------------------------------------------

    # Another Library Name autocomplete
    @all_library_items.autocomplete("library_name")
    async def autocomplete_all_library_items(self, ctx: AutocompleteContext):
        library_data = await c.bookshelf_libraries()
        choices = []

        for name, (library_id, audiobooks_only) in library_data.items():
            choices.append({"name": name, "value": library_id})

        print(choices)
        if choices:
            await ctx.send(choices=choices)
