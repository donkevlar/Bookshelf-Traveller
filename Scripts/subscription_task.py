import os
import sqlite3
import time

import bookshelfAPI as c
import settings as s
import logging

from interactions import *
from interactions.api.events import Startup
from datetime import datetime, timedelta
from interactions.ext.paginators import Paginator
from dotenv import load_dotenv
from wishlist import search_wishlist_db, mark_book_as_downloaded

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
server_name TEXT NOT NULL,
UNIQUE(channel_id, task)
)
                        ''')


# Initialize table
logger.info("Initializing tasks table")
table_create()


def insert_data(discord_id: int, channel_id: int, task, server_name):
    try:
        cursor.execute('''
        INSERT INTO tasks (discord_id, channel_id, task, server_name) VALUES (?, ?, ?, ?)''',
                       (int(discord_id), int(channel_id), task, server_name))
        conn.commit()
        logger.debug(f"Inserted: {discord_id} with channel_id and task")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {discord_id} with task {task} already exists.")
        return False


def remove_task_db(task='', discord_id=0, db_id=0):
    logger.warning(f'Attempting to delete task {task} with discord id {discord_id} from db!')
    try:
        if task != '' and discord_id != 0:
            cursor.execute("DELETE FROM tasks WHERE task = ? AND discord_id = ?", (task, int(discord_id)))
            conn.commit()
            logger.info(f"Successfully deleted task {task} with discord id {discord_id} from db!")
            return True
        elif db_id != 0:
            cursor.execute("DELETE FROM tasks WHERE id = ?", (int(db_id),))
            conn.commit()
            logger.info(f"Successfully deleted task with id {db_id}")
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

    elif discord_id != 0 and task != '' and channel_id == 0:
        option = 2
        if not override:
            logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
        cursor.execute('''
                SELECT channel_id, server_name FROM tasks WHERE discord_id = ? AND task = ?
                ''', (discord_id, task))
        rows = cursor.fetchone()

    elif discord_id != 0 and task == '' and channel_id == 0:
        option = 3
        if not override:
            logger.info(f'OPTION {option}: Searching db using discord ID in tasks table.')
        cursor.execute('''
                        SELECT task, channel_id, id FROM tasks WHERE discord_id = ?
                        ''', (discord_id,))
        rows = cursor.fetchall()

    else:
        option = 4
        if not override:
            logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
        cursor.execute('''SELECT discord_id, task, channel_id, server_name FROM tasks''')
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

    libraries = await c.bookshelf_libraries()

    library_count = len(libraries)

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
            try:
                latest_item_provider_id = item.get('asin')
            except Exception as e:
                latest_item_provider_id = ''
                logger.debug("Couldn't fetch asin from item. Likely was not set with metadata.")
                logger.debug(f"Error: {e}")

            if "(Abridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Abridged)", '').strip()
            if "(Unabridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Unabridged)", '').strip()

            formatted_time = latest_item_time_added / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            if latest_item_time_added >= timestamp_minus_delta and latest_item_type == 'book':
                items_added.append({"title": latest_item_title, "addedTime": formatted_time,
                                    "author": latest_item_author, "id": latest_item_bookID,
                                    "provider_id": latest_item_provider_id})

        return items_added


class SubscriptionTask(Extension):
    def __init__(self, bot):
        # Channel object has 3 main properties .name, .id, .type
        self.newBookCheckChannel = None
        self.newBookCheckChannelID = None
        self.ServerNickName = ''
        self.embedColor = None

    async def get_server_name_db(self, discord_id=0, task='new-book-check'):
        cursor.execute('''
                SELECT server_name FROM tasks WHERE discord_id = ? OR task = ?
                ''', (int(discord_id), task))
        rows = cursor.fetchone()
        if rows:
            for row in rows:
                logger.debug(f'Setting server nickname to {row}')
                self.ServerNickName = row
        return rows

    async def send_user_wishlist(self, discord_id: int, title: str, author: str, embed: list):
        user = await self.bot.fetch_user(discord_id)
        result = search_task_db(discord_id=discord_id, task='new-book-check')
        name = ''
        if result:
            try:
                name = result[1]
            except TypeError as error:
                logger.error(f"Couldn't assign server name, {error}")
                name = "Audiobookshelf"

        if len(embed) > 10:
            for emb in embed:
                await user.send(
                    f"Hello {user}, **{title}** by author **{author}** is now available on your Audiobookshelf server: **{name}**! ",
                    embed=emb)
        else:
            await user.send(
                f"Hello {user}, **{title}** by author **{author}** is now available on your Audiobookshelf server: **{name}**! ",
                embeds=embed)  # NOQA

    async def NewBookCheckEmbed(self, task_frequency=TASK_FREQUENCY, enable_notifications=False):  # NOQA
        bookshelfURL = os.environ.get("bookshelfURL")

        if self.ServerNickName == '':
            self.ServerNickName = "Audiobookshelf"

        items_added = await newBookList(task_frequency)

        if items_added:
            count = 0
            total_item_count = len(items_added)
            embeds = []
            wishlist_titles = []
            logger.info(f'{total_item_count} New books found, executing Task!')

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
                    description=f"Recently added books for [{self.ServerNickName}]({bookshelfURL})",
                )
                if self.embedColor:
                    embed_message.color = self.embedColor
                else:
                    embed_message.color = FlatUIColors.ORANGE

                embed_message.add_field(name="Title", value=title, inline=False)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_field(name="Additional Information", value=f"Wishlisted: **{wishlisted}**",
                                        inline=False)
                embed_message.url = f"{os.getenv('bookshelfURL')}/item/{bookID}"
                embed_message.add_image(cover_link)
                embed_message.footer = s.bookshelf_traveller_footer + " | " + self.ServerNickName
                embeds.append(embed_message)

                if wl_search:
                    for user in wl_search:
                        discord_id = user[0]
                        search_title = user[2]
                        if enable_notifications:
                            # Note: Function will send embeds individually if count > 10 due to limit
                            await self.send_user_wishlist(discord_id=discord_id, title=title, author=author,
                                                          embed=embeds)
                            mark_book_as_downloaded(discord_id=discord_id, title=search_title)
                            # remove_book_db(title=search_title, discord_id=discord_id)

            return embeds

    async def embed_color_selector(self, color=0):
        color = int(color)
        selected_color = FlatUIColors.CARROT
        # Yellow
        if color == 1:
            selected_color = FlatUIColors.SUNFLOWER
        # Orange
        elif color == 2:
            selected_color = FlatUIColors.CARROT
        # Purple
        elif color == 3:
            selected_color = FlatUIColors.AMETHYST
        # Turquoise
        elif color == 4:
            selected_color = FlatUIColors.TURQUOISE
        # Red
        elif color == 5:
            selected_color = FlatUIColors.ALIZARIN
        # Green
        elif color == 6:
            selected_color = FlatUIColors.EMERLAND

        return selected_color

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def newBookTask(self):
        logger.info("Initializing new-book-check task!")
        channel_list = []
        search_result = search_task_db()
        if search_result:
            if self.ServerNickName == '':
                await self.get_server_name_db()
            logger.debug(f"search result: {search_result}")
            new_titles = await newBookList()
            if new_titles:
                logger.debug(f"New Titles Found: {new_titles}")

            if len(new_titles) > 10:
                logger.warning("Found more than 10 titles")

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

                        if len(embeds) < 10:
                            msg = await channel_query.send(content="New books have been added to your library!")
                            await msg.edit(embeds=embeds)
                        else:
                            await channel_query.send(content="New books have been added to your library!")
                            for embed in embeds:
                                await channel_query.send(embed=embed)
                        logger.info("Successfully completed new-book-check task!")

            else:
                logger.info("No new books found, marking task as complete.")
        # If active but no result, disable task and send owner message.
        else:
            logger.warning("Task 'new-book-check' was active, but setup check failed.")
            owner = self.bot.owner
            await owner.send(
                "Task 'new-book-check' was active, but setup check failed. Please setup the task again via `/setup-tasks`.")
            self.newBookTask.stop()

    # Slash Commands ----------------------------------------------------

    @slash_command(name="new-book-check",
                   description="Verify if a new book has been added to your library. Can be setup as a task.",
                   dm_permission=True)
    @slash_option(name="minutes", description=f"Lookback period, in minutes. "
                                              f"Defaults to {TASK_FREQUENCY} minutes. DOES NOT AFFECT TASK.",
                  opt_type=OptionType.INTEGER)
    @slash_option(name="color", description="Will override the new book check embed color.", opt_type=OptionType.STRING, autocomplete=True)
    @slash_option(name="enable_task", description="If set to true will enable recurring task.",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="disable_task", description="If set to true, this will disable the task.",
                  opt_type=OptionType.BOOLEAN)
    async def newBookCheck(self, ctx: InteractionContext, minutes=TASK_FREQUENCY, enable_task=False,
                           disable_task=False, color=None):
        if color and minutes == TASK_FREQUENCY:
            self.embedColor = await self.embed_color_selector(color)
            await ctx.send("Successfully updated color!", ephemeral=True)
            return
        if enable_task and not disable_task:
            logger.info('Activating New Book Task! A message will follow.')
            if not self.newBookTask.running:
                operationSuccess = False
                search_result = search_task_db(ctx.author_id, task='new-book-check')
                if search_result:
                    print(search_result)
                    operationSuccess = True

                if operationSuccess:
                    if color:
                        self.embedColor = await self.embed_color_selector(color)

                    await ctx.send(
                        f"Activating New Book Task! This task will automatically refresh every *{TASK_FREQUENCY} minutes*!",
                        ephemeral=True)

                    self.newBookTask.start()
                    return
                else:
                    await ctx.send("Error activating new book task. Please visit logs for more information. "
                                   "Please make sure to setup the task prior to activation by using command **/setup-tasks**",
                                   ephemeral=True)
                    return
            else:
                logger.warning('New book check task was already running, ignoring...')
                await ctx.send('New book check task is already running, ignoring...', ephemeral=True)
                return
        elif disable_task and not enable_task:
            if self.newBookTask.running:
                if color:
                    self.embedColor = await self.embed_color_selector(color)
                await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
                self.newBookTask.stop()
                return
            else:
                pass
        elif disable_task and enable_task:
            await ctx.send(
                "Invalid option entered, please ensure only one option is entered from this command at a time.")
            return
        # Set server nickname
        await self.get_server_name_db(discord_id=ctx.author_id)

        await ctx.send(f'Searching for recently added books in given period of {minutes} minutes.', ephemeral=True)
        if color:
            self.embedColor = await self.embed_color_selector(color)
        embeds = await self.NewBookCheckEmbed(task_frequency=minutes, enable_notifications=False)
        if embeds:
            logger.info(f'Recent books found in given search period of {minutes} minutes!')
            paginator = Paginator.create_from_embeds(self.bot, *embeds)
            await paginator.send(ctx, ephemeral=True)
        else:
            await ctx.send(f"No recent books found in given search period of {minutes} minutes.",
                           ephemeral=True)
            logger.info(f'No recent books found.')

    @check(is_owner())
    @slash_command(name='setup-tasks', description="Setup a task", dm_permission=False)
    @slash_option(name='task', description='The task you wish to setup', required=True, autocomplete=True,
                  opt_type=OptionType.STRING)
    @slash_option(opt_type=OptionType.CHANNEL, name="channel", description="select a channel",
                  channel_types=[ChannelType.GUILD_TEXT], required=True)
    @slash_option(name="server_name",
                  description="Give your Audiobookshelf server a nickname. This will overwrite the previous name.",
                  opt_type=OptionType.STRING, required=True)
    @slash_option(name='color', description='Embed message optional accent color, overrides default author color.',
                  opt_type=OptionType.STRING)
    async def task_setup(self, ctx: SlashContext, task, channel, server_name, color=None):
        task_name = ""
        success = False
        task_instruction = ''

        if int(task) == 1:
            task_name = 'new-book-check'
            task_command = '`/new-book-check disable_task: True`'
            task_instruction = f'Task is now active. To disable, use **{task_command}**'
            result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name,
                                 server_name=server_name)

            if result:
                success = True
                if not self.newBookTask.running:
                    self.newBookTask.start()

        if success:
            if color:
                self.embedColor = self.embed_color_selector(int(color))
            await ctx.send(
                f"Successfully setup task **{task_name}** with channel **{channel.name}**. \nInstructions: {task_instruction}",
                ephemeral=True)

            await self.get_server_name_db(discord_id=ctx.author_id)
        else:
            await ctx.send(
                f"An error occurred while attempting to setup the task **{task_name}**. Most likely due to the task already being setup. "
                f"Please visit the logs for more information.", ephemeral=True)

    @check(is_owner())
    @slash_command(name='remove-task', description="Remove an active task from the task db")
    @slash_option(name='task', description="Active tasks pulled from db.", autocomplete=True, required=True,
                  opt_type=OptionType.STRING)
    async def remove_task_command(self, ctx: SlashContext, task):
        result = remove_task_db(db_id=task)
        if result:
            await ctx.send("Successfully removed task!", ephemeral=True)
        else:
            await ctx.send("Failed to remove task, please visit logs for additional details.", ephemeral=True)

    @slash_command(name="active-tasks", description="View active tasks related to you.")
    async def active_tasks_command(self, ctx: SlashContext):
        embeds = []
        success = False
        result = search_task_db()
        if result:
            for discord_id, task, channel_id, server_name in result:
                channel = await self.bot.fetch_channel(channel_id)
                discord_user = await self.bot.fetch_user(discord_id)
                if channel and discord_user:
                    success = True
                    response = f"Channel: **{channel.name}**\nDiscord User: **{discord_user}**"
                    embed_message = Embed(
                        title="Task",
                        description="All Currently Active Tasks. *Note: this will pull for all channels and users.*",
                        color=ctx.author.accent_color
                    )
                    embed_message.add_field(name="Name", value=task)
                    embed_message.add_field(name="Discord Related Information", value=response)
                    embed_message.footer = s.bookshelf_traveller_footer

                    embeds.append(embed_message)

            if success:
                paginator = Paginator.create_from_embeds(self.client, *embeds)
                await paginator.send(ctx, ephemeral=True)

        else:
            await ctx.send("No currently active tasks found.", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------
    @task_setup.autocomplete('task')
    async def auto_com_task(self, ctx: AutocompleteContext):
        choices = [
            {"name": "new-book-check", "value": "1"}
        ]
        await ctx.send(choices=choices)

    @remove_task_command.autocomplete('task')
    async def remove_task_auto_comp(self, ctx: AutocompleteContext):
        choices = []
        result = search_task_db(discord_id=ctx.author_id)
        if result:
            for task, channel_id, db_id in result:
                channel = await self.bot.fetch_channel(channel_id)
                if channel:
                    response = f"{task} | {channel.name}"
                    choices.append({"name": response, "value": db_id})
        await ctx.send(choices=choices)

    @task_setup.autocomplete('color')
    @newBookCheck.autocomplete('color')
    async def color_embed_bookcheck(self, ctx: AutocompleteContext):
        choices = []
        count = 0
        colors = ['Default', 'Yellow', 'Orange', 'Purple', 'Turquoise', 'Red', 'Green']

        for color in colors:
            choices.append({"name": color, "value": str(count)})
            count += 1

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
