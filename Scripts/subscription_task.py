import os
import sqlite3
import time

import json5

import bookshelfAPI as c
import settings as s
import logging

from interactions import *
from interactions.api.events import Startup
from datetime import datetime, timedelta
from interactions.ext.paginators import Paginator
from dotenv import load_dotenv
from wishlist import search_wishlist_db, remove_book_db

# Enable dot env outside of docker
load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# VARS
TASK_FREQUENCY = 5

# Create new relative path
db_path = 'db/tasks.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Initialize sqlite3 connection

conn = sqlite3.connect(db_path)
cursor = conn.cursor()


def table_create():
    cursor.execute('''
CREATE TABLE IF NOT EXISTS tasks (
id INTEGER PRIMARY KEY,
discord_id INTEGER NOT NULL,
channel_id INTEGER NOT NULL,
task TEXT NOT NULL,
UNIQUE(channel_id, task)
)
                        ''')


# Initialize table
logger.info("Initializing tasks table")
table_create()


def insert_data(discord_id: int, channel_id: int, task):
    try:
        cursor.execute('''
        INSERT INTO tasks (discord_id, channel_id, task) VALUES (?, ?, ?)''',
                       (int(discord_id), int(channel_id), task))
        conn.commit()
        logger.debug(f"Inserted: {discord_id} with channel_id and task")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {discord_id} with task {task} already exists.")
        return False


def remove_task_db(task: str, discord_id):
    logger.warning(f'Attempting to delete task {task} with discord id {discord_id} from db!')
    try:
        cursor.execute("DELETE FROM tasks WHERE task = ? AND discord_id = ?", (task, discord_id))
        conn.commit()
        logger.info(f"Successfully deleted task {task} with discord id {discord_id} from db!")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error while attempting to delete {task}: {e}")
        return False


def search_task_db(discord_id=0, task='', channel_id=0, override_response='') -> ():
    override = False

    if override_response != '':
        response = override_response
        logger.warning(response)
        override = True
    else:
        logger.info('Initializing sqlite db search for subscription task module.')

    if channel_id != 0 and task == '' and discord_id == 0:
        option = 1
        if not override:
            logger.info(f'OPTION {option}: Searching db using channel ID in tasks table.')
        cursor.execute('''
        SELECT discord_id, task FROM tasks WHERE channel_id = ?
        ''', (channel_id, task))
        rows = cursor.fetchall()

    elif discord_id != 0 and task == '' and channel_id == 0:
        option = 2
        if not override:
            logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
        cursor.execute('''
                SELECT channel_id FROM tasks WHERE discord_id = ? AND task = ?
                ''', (discord_id, task))
        rows = cursor.fetchone()

    else:
        option = 3
        if not override:
            logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
        cursor.execute('''SELECT discord_id, task, channel_id FROM tasks''')
        rows = cursor.fetchall()

    if rows:
        if not override:
            logger.info(
                f'Successfully found query using option: {option} using table tasks in subscription task module.')
    else:
        if not override:
            logger.warning('Query returned null using table tasks, an error may follow.')

    return rows


async def newBookList(task_frequency=TASK_FREQUENCY) -> list:
    logger.debug("Initializing NewBookList function")
    items_added = []
    current_time = datetime.now()
    library_count = 0

    libraries = await c.bookshelf_libraries()

    for library in libraries:
        library_count += 1

    logger.debug(f'Found {library_count} libraries')

    time_minus_delta = current_time - timedelta(minutes=task_frequency)
    timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

    for name, (library_id, audiobooks_only) in libraries.items():
        library_items = await c.bookshelf_all_library_items(library_id, params="sort=addedAt&desc=1")

        for item in library_items:
            latest_item_time_added = int(item.get('addedTime'))
            latest_item_title = item.get('title')
            latest_item_type = item.get('mediaType')
            latest_item_author = item.get('author')
            latest_item_bookID = item.get('id')

            if "(Abridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Abridged)", '').strip()
            if "(Unabridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Unabridged)", '').strip()

            formatted_time = latest_item_time_added / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            if latest_item_time_added >= timestamp_minus_delta and latest_item_type == 'book':
                items_added.append({"title": latest_item_title, "addedTime": formatted_time,
                                    "author": latest_item_author, "id": latest_item_bookID})

        return items_added


class SubscriptionTask(Extension):
    def __init__(self, bot):
        # Channel object has 3 main properties .name, .id, .type
        self.newBookCheckChannel = None
        self.newBookCheckChannelID = None

    async def send_user_wishlist(self, discord_id: int, title: str, author: str, embed: list):
        user = await self.bot.fetch_user(discord_id)

        await user.send(
                f"Hello {user}, {title} by author {author} is now available on your Audiobookshelf server: {os.getenv('bookshelfURL')}! ", embeds=embed) # NOQA

    async def NewBookCheckEmbed(self, task_frequency=TASK_FREQUENCY, enable_notifications=False):  # NOQA
        bookshelfURL = os.environ.get("bookshelfURL")

        items_added = await newBookList(task_frequency)

        if items_added:
            count = 0
            embeds = []
            wishlist_titles = []
            logger.info('New books found, executing Task!')

            if wishlist_titles:
                logger.debug(f"Wishlist Titles: {wishlist_titles}")

            for item in items_added:
                count += 1
                title = item.get('title')
                logger.debug(title)
                author = item.get('author')
                addedTime = item.get('addedTime')
                bookID = item.get('id')

                wishlisted = False

                cover_link = await c.bookshelf_cover_image(bookID)

                wl_search = search_wishlist_db(title=title)
                if wl_search:
                    wishlisted = True

                embed_message = Embed(
                    title=f"Recently Added Book {count}",
                    description=f"Recently added books for {bookshelfURL}",
                )
                embed_message.add_field(name="Title", value=title, inline=False)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_field(name="Additional Information", value=f"Wishlisted: **{wishlisted}**",
                                        inline=False)
                embed_message.add_image(cover_link)

                embeds.append(embed_message)

                if wl_search:
                    for user in wl_search:
                        discord_id = user[0]
                        search_title = user[2]
                        if enable_notifications:
                            await self.send_user_wishlist(discord_id=discord_id, title=title, author=author, embed=embeds)
                            remove_book_db(title=search_title, discord_id=discord_id)

            return embeds

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def newBookTask(self):
        logger.info("Initializing new-book-check task!")
        channel_list = []
        search_result = search_task_db()
        if search_result:
            logger.debug(f"search result: {search_result}")
            new_titles = await newBookList()
            if new_titles:
                logger.debug(f"New Titles Found: {new_titles}")

            embeds = await self.NewBookCheckEmbed(enable_notifications=True)
            if embeds:
                for result in search_result:
                    channel_id = int(result[2])
                    channel_list.append(channel_id)

                for channelID in channel_list:
                    channel_query = await self.bot.fetch_channel(channel_id=channelID, force=True)
                    if channel_query:
                        logger.debug(f"Found Channel: {channelID}")
                        logger.debug(f"Bot will now attempt to send a message to channel id: {channelID}")
                        await channel_query.send(content="A new book has been added to your library!", embeds=embeds,
                                                 ephemeral=True)
                        logger.info("Successfully completed new-book-check task!")

            else:
                logger.info("No new books found, marking task as complete.")

    # Slash Commands ----------------------------------------------------

    @slash_command(name="new-book-check",
                   description="Verify if a new book has been added to your library. Can be setup as a task.",
                   dm_permission=True)
    @slash_option(name="minutes", description=f"Lookback period, in minutes. "
                                              f"Defaults to {TASK_FREQUENCY} minutes. DOES NOT AFFECT TASK.",
                  opt_type=OptionType.INTEGER)
    @slash_option(name="enable_task", description="If set to true will enable recurring task.",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="disable_task", description="If set to true, this will disable the task.",
                  opt_type=OptionType.BOOLEAN)
    async def newBookCheck(self, ctx: InteractionContext, minutes=TASK_FREQUENCY, enable_task=False,
                           disable_task=False):
        if enable_task and not disable_task:
            logger.info('Activating New Book Task! A message will follow.')
            if not self.newBookTask.running:
                operationSuccess = False
                search_result = search_task_db(ctx.author_id, task='new-book-check')
                if search_result:
                    print(search_result)
                    operationSuccess = True

                if operationSuccess:
                    await ctx.send(
                        f"Activating New Book Task! This task will automatically refresh every *{TASK_FREQUENCY} minutes*!",
                        ephemeral=True)

                    self.newBookTask.start()
                    return
                else:
                    await ctx.send("Error activating new book task. Please visit logs for more information. "
                                   "Please make sure to setup the task prior to activation by using command **/setup-tasks**",
                                   ephemeral=True)
            else:
                logger.warning('New book check task was already running, ignoring...')
                await ctx.send('New book check task is already running, ignoring...', ephemeral=True)
                return
        elif disable_task and not enable_task:
            if self.newBookTask.running:
                await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
                self.newBookTask.stop()
                return
            else:
                pass
        elif disable_task and enable_task:
            await ctx.send(
                "Invalid option entered, please ensure only one option is entered from this command at a time.")
            return

        await ctx.send(f'Searching for recently added books in given period of {minutes} minutes.', ephemeral=True)
        embeds = await self.NewBookCheckEmbed(task_frequency=minutes, enable_notifications=False)
        if embeds:
            logger.info(f'Recent books found in given search period of {minutes} minutes!')
            paginator = Paginator.create_from_embeds(self.bot, *embeds)
            await paginator.send(ctx, ephemeral=True)
        else:
            await ctx.send(f"No recent books found in given search period of {minutes} minutes.",
                           ephemeral=True)
            logger.info(f'No recent books found.')

    @slash_command(name='setup-tasks', description="Setup a task")
    @slash_option(name='task', description='The task you wish to setup', required=True, autocomplete=True,
                  opt_type=OptionType.STRING)
    @slash_option(opt_type=OptionType.CHANNEL, name="channel", description="select a channel",
                  channel_types=[ChannelType.GUILD_TEXT], required=True)
    async def task_setup(self, ctx: SlashContext, task, channel):
        task_name = ""
        success = False
        task_instruction = ''

        if int(task) == 1:
            task_name = 'new-book-check'
            task_command = '`/new-book-check enable_task: True`'
            task_instruction = f'To activate the task use **{task_command}**'
            result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name)

            if result:
                success = True

        if int(task) == 2:
            task_name = 'add-book'
            task_command = '`/add-book`'
            task_instruction = f'Once a book is added to the wishlist by using {task_command}, the task will start automatically.'
            result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name)

            if result:
                success = True

        if success:
            await ctx.send(
                f"Successfully setup task **{task_name}** with channel **{channel.name}**. Instructions: {task_instruction}",
                ephemeral=True)
        else:
            await ctx.send(
                f"An error occurred while attempting to setup the task **{task_name}**. Most likely due to the task already being setup. "
                f"Please visit the logs for more information.", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------
    @task_setup.autocomplete('task')
    async def auto_com_task(self, ctx: AutocompleteContext):
        choices = [
            {"name": "new-book-check", "value": "1"}
        ]
        await ctx.send(choices=choices)

    # Auto Start Task if db is populated
    @listen()
    async def tasks_startup(self, event: Startup):
        result = search_task_db(
            override_response="Initialized subscription task module, verifying if any tasks are enabled...")
        task_name = "new-book-check"
        task_list = []
        if result:
            for item in result:
                task = item[1]
                task_list.append(task)
                # Debug stuff
                if s.DEBUG_MODE != "True":
                    logger.debug(f"Tasks db search result: {task}")

            if not self.newBookTask.running and task_name in task_list:
                self.newBookTask.start()
                owner = event.bot.owner
                logger.info(
                    f"Subscription Task db was populated, auto enabling tasks on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")
                # Debug Stuff
                if s.DEBUG_MODE != "True":
                    await owner.send(
                        f"Subscription Task db was populated, auto enabling tasks on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")
