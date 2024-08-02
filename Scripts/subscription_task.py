import os
import time
import bookshelfAPI as c
import settings as s
from interactions import *
import logging
from datetime import datetime, timedelta
from interactions.ext.paginators import Paginator
from dotenv import load_dotenv

# Enable dot env outside of docker
load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# VARS
task_frequency = int(os.getenv('TASK_FREQUENCY', 60))


class SubscriptionTask(Extension):
    def __init__(self, bot):
        pass

    @Task.create(trigger=IntervalTrigger(minutes=task_frequency))
    async def newBookCheck(self, ctx: SlashContext):
        items_added = []
        libraries = c.bookshelf_libraries()
        current_time = datetime.now()

        time_minus_one_hour = current_time - timedelta(minutes=task_frequency)
        timestamp_minus_one_hour = int(time.mktime(time_minus_one_hour.timetuple()) * 1000)

        for name, (library_id, audiobooks_only) in libraries.items():
            library_items = c.bookshelf_all_library_items(library_id, params="sort=addedAt&desc=1")

            for item in library_items:
                latest_item_time_added = int(item.get('addedTime'))
                latest_item_title = item.get('title')
                latest_item_type = item.get('mediaType')
                latest_item_author = item.get('author')
                latest_item_bookID = item.get('id')

                formatted_time = latest_item_time_added / 1000
                formatted_time = datetime.fromtimestamp(formatted_time)
                formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

                if latest_item_time_added >= timestamp_minus_one_hour and latest_item_type == 'book':
                    items_added.append({"title": latest_item_title, "addedTime": formatted_time,
                                        "author": latest_item_author, "id": latest_item_bookID})

        if items_added:
            count = 0
            embeds = []
            logger.info('New books found, executing Task!')

            for item in items_added:
                count += 1
                title = item.get('title')
                author = item.get('author')
                addedTime = item.get('addedTime')
                bookID = item.get('id')

                cover_link = c.bookshelf_cover_image(bookID)

                embed_message = Embed(
                    title=f"Recently Added Book {count}",
                    description=f"Recently added books, this will refresh every 60 minutes!",
                    color=ctx.author.accent_color,
                )
                embed_message.add_field(name="Title", value=title)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_image(cover_link)

                embeds.append(embed_message)

            paginator = Paginator.create_from_embeds(self.bot, *embeds, timeout=120)
            await paginator.send(ctx)

        logger.info('Completed Newly Added Books Task!')

    @slash_command(name="task-new-books",
                   description="Enable/Disable a background task checking for newly added books.")
    @slash_option(name="option", description="", opt_type=OptionType.STRING, autocomplete=True, required=True)
    async def activeBookCheck(self, ctx: SlashContext, option: str):
        if option == 'enable':
            await ctx.send("Activating New Book Task! This task will automatically refresh every *60 minutes*!",
                           ephemeral=True)
            await ctx.send(f"Important: *The task will be sent to where this message originates from!*", ephemeral=True)
            self.newBookCheck.start(ctx)
        elif option == 'disable':
            if self.newBookCheck.running:
                await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
                self.newBookCheck.stop()

            else:
                await ctx.send("The task is currently not active", ephemeral=True)

        else:
            await ctx.send("Invalid option entered!", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------

    @activeBookCheck.autocomplete("option")
    async def autocomplete_book_check(self, ctx: AutocompleteContext):
        choices = [
            {"name": "enable", "value": "enable"},
            {"name": "disable", "value": "disable"}
        ]

        await ctx.send(choices=choices)
