import os
import sqlite3
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
logger.info("Initializing Sqlite DB")
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


def search_task_db(discord_id=0, task='', channel_id=0):
    logger.info('Initializing sqlite db search for subscription task module.')

    if channel_id != 0 and task == '' and discord_id == 0:
        option = 1
        logger.info(f'OPTION {option}: Searching db using channel ID in tasks table.')
        cursor.execute('''
        SELECT discord_id, task FROM tasks WHERE channel_id = ?
        ''', (channel_id, task))
        rows = cursor.fetchall()

    elif discord_id != 0 and task == '' and channel_id == 0:
        option = 2
        logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
        cursor.execute('''
                SELECT channel_id FROM tasks WHERE discord_id = ? AND task = ?
                ''', (discord_id, task))
        rows = cursor.fetchone()

    else:
        option = 3
        logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
        cursor.execute('''SELECT discord_id, task, channel_id FROM tasks''')
        rows = cursor.fetchall()

    if rows:
        logger.info(f'Successfully found query using option: {option} using table tasks in subscription task module.')
    else:
        logger.warning('Query returned null using table tasks, an error may follow.')

    return rows


class SubscriptionTask(Extension):
    def __init__(self, bot):
        # Channel object has 3 main properties .name, .id, .type
        self.newBookCheckChannel = None
        self.newBookCheckChannelID = None

    async def NewBookCheckEmbed(self, task_frequency=TASK_FREQUENCY):  # NOQA
        items_added = []
        libraries = await c.bookshelf_libraries()
        current_time = datetime.now()
        bookshelfURL = os.environ.get("bookshelfURL")

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

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def newBookTask(self):
        channel_list = []
        search_result = search_task_db()
        if search_result:
            logger.debug(f"search result: {search_result}")
            embeds = await self.NewBookCheckEmbed()
            if embeds:
                for result in search_result:
                    channel_id = int(result[2])
                    logger.info(f"Bot will now attempt to send a message to channel id: {channel_id}")
                    channel_list.append(channel_id)

                for channelID in channel_list:
                    channel_query = await self.bot.fetch_channel(channel_id=channelID, force=True)
                    if channel_query:
                        await channel_query.send("A new book has been added to your library!", embeds=embeds,
                                                 ephemeral=True)
                        logger.info("Successfully completed new-book-check task!")

            else:
                logger.info("No new books found, marking task as complete.")

    # Slash Commands ----------------------------------------------------

    @slash_command(name="new-book-check",
                   description="Enable/Disable a background task checking for newly added books.", dm_permission=True)
    @slash_option(name="minutes", description=f"Lookback period, in minutes. "
                                              f"Defaults to {TASK_FREQUENCY} minutes. DOES NOT AFFECT TASK.",
                  opt_type=OptionType.INTEGER)
    @slash_option(name="enable_task", description="If set to true will enable recurring task.",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="disable_task", description="If set to true, this will disable the task.", opt_type=OptionType.BOOLEAN)
    async def newBookCheck(self, ctx: InteractionContext, minutes=TASK_FREQUENCY, enable_task=False, disable_task=False):
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
        else:
            await ctx.send("Invalid option entered, please ensure only one option is entered from this command at a time.")
            return

        await ctx.send(f'Searching for recently added books in given period of {minutes} minutes.', ephemeral=True)
        embeds = await self.NewBookCheckEmbed(task_frequency=minutes)
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
        task_command = ""

        if int(task) == 1:
            task_name = 'new-book-check'
            task_command = '`/new-book-check enable_task: True`'
            result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name)

            if result:
                success = True

        if success:
            await ctx.send(
                f"Successfully setup task **{task_name}** with channel **{channel.name}**. To activate the task use **{task_command}**",
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
