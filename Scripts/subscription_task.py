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
TASK_FREQUENCY = 5


class SubscriptionTask(Extension):
    def __init__(self, bot):
        pass

    async def NewBookCheck(self, task_frequency=TASK_FREQUENCY):  # NOQA
        items_added = []
        libraries = await c.bookshelf_libraries()
        current_time = datetime.now()
        bookshelfURL = os.environ.get("bookshelfURL")

        time_minus_delta = current_time - timedelta(days=task_frequency)
        timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

        for name, (library_id, audiobooks_only) in libraries.items():
            library_items = await c.bookshelf_all_library_items(library_id, params="sort=addedAt&desc=1")

            for item in library_items:
                latest_item_time_added = int(item.get('addedTime'))
                latest_item_title = item.get('title')
                latest_item_type = item.get('mediaType')
                latest_item_author = item.get('author')
                latest_item_bookID = item.get('id')

                formatted_time = latest_item_time_added / 1000
                formatted_time = datetime.fromtimestamp(formatted_time)
                formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

                if latest_item_time_added >= timestamp_minus_delta and latest_item_type == 'book':
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

                cover_link = await c.bookshelf_cover_image(bookID)

                embed_message = Embed(
                    title=f"Recently Added Book {count}",
                    description=f"Recently added books for {bookshelfURL}",
                )
                embed_message.add_field(name="Title", value=title)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_image(cover_link)

                embeds.append(embed_message)

            return embeds

    # @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    # async def newBookTask(self, ctx: BaseContext):
    #     embeds = self.NewBookCheck()
    #     if embeds:
    #         paginator = Paginator.create_from_embeds(self.bot, *embeds, timeout=120)
    #         await paginator.send(ctx)
    #
    #     logger.info('Completed Newly Added Books Task!')

    @slash_command(name="new-book-check",
                   description="Enable/Disable a background task checking for newly added books.", dm_permission=True)
    @slash_option(name="days", description="Lookback period, in days. Defaults to 1 day",
                  opt_type=OptionType.INTEGER, autocomplete=False, required=False)
    async def activeBookCheck(self, ctx: InteractionContext, days=1):
        # if option == 'enable':
        #     logger.info('Activating New Book Task! A message will follow.')
        #     if not self.newBookCheck.running:
        #         await ctx.send(
        #             f"Activating New Book Task! This task will automatically refresh every *{TASK_FREQUENCY} minutes*!",
        #             ephemeral=True)
        #
        #         self.newBookCheck.start(ctx)
        #     else:
        #         logger.warning('New book check task was already running, ignoring...')
        #         await ctx.send('New book check task is already running, ignoring...', ephemeral=True)
        await ctx.send(f'Searching for recently added books in given period of {days} days.', ephemeral=True)
        embeds = await self.NewBookCheck(task_frequency=days)
        if embeds:
            logger.info(f'Recent books found in given search period of {days} days!')
            paginator = Paginator.create_from_embeds(self.bot, *embeds)
            await paginator.send(ctx, ephemeral=True)
        else:
            await ctx.send(f"No recent books found in given search period of {days} days.",
                           ephemeral=True)
            logger.info(f'No recent books found.')

        # elif option == 'disable':
        #     if self.newBookCheck.running:
        #         await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
        #         self.newBookCheck.stop()
        #
        #     else:
        #         await ctx.send("The task is currently not active", ephemeral=True)

        # else:
        #     await ctx.send("Invalid option entered!", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------

    # @activeBookCheck.autocomplete("option")
    # async def autocomplete_book_check(self, ctx: AutocompleteContext):
    #     choices = [
    #         {"name": "enable", "value": "enable"},
    #         {"name": "disable", "value": "disable"},
    #         {"name": "view", "value": "view"}
    #     ]
    #
    #     await ctx.send(choices=choices)
