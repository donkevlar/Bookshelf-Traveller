import os
from interactions import *
import bookshelfAPI as c
import logging
import sqlite3

logger = logging.getLogger("bot")

# Create new relative path
db_path = 'db/user_info.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Initialize sqlite3 connection

conn = sqlite3.connect(db_path)
cursor = conn.cursor()


def table_create():
    cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY,
user TEXT NOT NULL,
token TEXT NOT NULL UNIQUE,
discord_id INTEGER NOT NULL,
UNIQUE(user, token)
)
                        ''')


# Initialize table
logger.info("Initializing Sqlite DB")
table_create()


def insert_data(user: str, token: str, discord_id: int):
    try:
        cursor.execute('''
        INSERT INTO users (user, token, discord_id) VALUES (?, ?, ?)''',
                       (str(user), str(token), int(discord_id)))
        conn.commit()
        logger.info(f"Inserted: {user} with token and discord_id")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {user}. User or token already exists.")
        return False


# Function to search for a specific user and token
def search_user_db(discord_id=0, user='', token=''):
    logger.info('Initializing sqlite db search')
    if discord_id != 0 and user == '':
        logger.info('Searching db using discord ID')
        cursor.execute('''
        SELECT token, user FROM users WHERE discord_id = ?
        ''', (discord_id,))
        rows = cursor.fetchall()
        option = 1

    elif token != '':
        logger.info('Searching db using ABS token')
        cursor.execute('''
                SELECT user FROM users WHERE token = ?
                ''', (token,))
        rows = cursor.fetchone()
        option = 2

    elif discord_id != 0 and user != '':
        logger.info('Searching db using discord ID and user')
        cursor.execute('''
                SELECT token FROM users WHERE discord_id = ? AND user = ?
                ''', (discord_id, user))
        rows = cursor.fetchone()
        option = 3
    elif user != '':
        logger.info('Searching db using user')
        cursor.execute('''SELECT token FROM users WHERE user = ?''', (user,))
        rows = cursor.fetchone()
        option = 4

    else:
        logger.info('Searching db for user and token using no arguments')
        cursor.execute('''SELECT user, token FROM users''')

        rows = cursor.fetchall()
        option = 5

    if rows:
        logger.info(f'Successfully found query using option: {option}')
    else:
        logger.warning('Query returned null, an error may follow.')

    return rows


def remove_user_db(user: str):
    logger.warning(f'Attempting to delete user {user} from db!')
    try:
        cursor.execute("DELETE FROM users WHERE user = ?", (user,))
        conn.commit()
        logger.info(f"Successfully deleted user {user} from db!")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error while attempting to delete {user}: {e}")
        return False


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


class MultiUser(Extension):
    def __init__(self, bot):
        pass

    @check(ownership_check)
    @slash_command(name="login", description="Login into ABS", dm_permission=True)
    async def user_login(self, ctx: SlashContext):
        if ctx.voice_state:
            return await ctx.send("Cannot perform login during playback, please use the /stop command and try again.",
                                  ephemeral=True)

        author_discord_id = ctx.author.id

        user_login_modal = Modal(
            ShortText(label="Username", custom_id="modal_username", placeholder="username"),
            ShortText(label="Password", custom_id="modal_password", placeholder="password"),
            title="User Login",
            custom_id="user_login",
        )
        await ctx.send_modal(modal=user_login_modal)

        modal_ctx: ModalContext = await ctx.bot.wait_for_modal(user_login_modal)

        # extract the answers from the responses dictionary
        username_response = modal_ctx.responses["modal_username"]
        password_response = modal_ctx.responses["modal_password"]

        user_info = c.bookshelf_user_login(username_response, password_response)

        abs_token = user_info["token"]
        abs_username = user_info["username"]
        abs_user_type = user_info["type"]
        admin_user = False

        if abs_user_type is None or abs_username == "":
            await modal_ctx.send("Login attempt failed! Please try again.", ephemeral=True)
            return

        if abs_user_type == "admin" or abs_user_type == "root":
            admin_user = True

        logger.info("Attempting to find logged in user...")
        user_result = search_user_db(int(author_discord_id), abs_username)
        print(user_result)

        if not user_result:
            logger.info("SQLite DB search returned nothing, attempting to insert new record.")

            if abs_token != "":
                logger.info(f"Registering user into sqlite db with username: {abs_username}, "
                            f"discord_id: {author_discord_id}")
                insert_result = insert_data(abs_username, abs_token, author_discord_id)
                if insert_result:
                    await modal_ctx.send(f"Successfully logged in as {abs_username}, type: {abs_user_type}",
                                         ephemeral=True)
                    logger.warning(
                        f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                    os.environ['bookshelfToken'] = abs_token

            else:
                await modal_ctx.send("Invalid username or password", ephemeral=True)

        else:
            logger.info("SQLite found associated token, proceeding to update ENV VARS...")
            retrieved_token = [0][0]
            retrieved_token = str(retrieved_token)

            abs_stored_token = os.environ.get('bookshelfToken')

            if retrieved_token == abs_stored_token:
                logger.info("Option 1 executed")
                await modal_ctx.send(content=f"login already registered, registration tied to abs user: {abs_username}",
                                     ephemeral=True)

            elif retrieved_token != abs_stored_token:
                logger.info("Option 2 executed")
                os.environ['bookshelfToken'] = retrieved_token
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {abs_username}')
                await modal_ctx.send(content=f"Successfully logged in as {abs_username}.",
                                     ephemeral=True)
                if admin_user:
                    await ctx.send("Logged in as ABS ADMIN, loading administration module! Important, you may have to "
                                   "reload discord!", ephemeral=True)
                    try:
                        ctx.bot.load_extension("administration")
                    except Exception as e:
                        logger.warning(e)
                else:
                    await ctx.send("Important changing users may require reloading discord!", ephemeral=True)
                    try:
                        ctx.bot.unload_extension("administration")
                    except Exception as e:
                        logger.warning(e)

            else:
                logger.info('Option 4 executed')
                os.environ['bookshelfToken'] = retrieved_token
                info = search_user_db(int(author_discord_id))
                retrieved_user = info[0][1]
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {retrieved_user}')
                await modal_ctx.send(content=f"Successfully logged in as {retrieved_user}.",
                                     ephemeral=True)
                if admin_user:
                    await ctx.send("Logged in as ABS ADMIN, loading administration module! Important, you may have to "
                                   "reload discord!", ephemeral=True)
                    try:
                        ctx.bot.load_extension("administration")
                    except Exception as e:
                        logger.warning(e)
                else:
                    await ctx.send("Important changing users may require reloading discord!", ephemeral=True)
                    try:
                        ctx.bot.unload_extension("administration")
                    except Exception as e:
                        logger.warning(e)

    @check(ownership_check)
    @slash_command(name="select",
                   description="log a user in via db pull")
    @slash_option(name="user", description="Select from previously logged in users.", opt_type=OptionType.STRING,
                  required=True, autocomplete=True)
    async def user_select_db(self, ctx: SlashContext, user):
        if ctx.voice_state:
            return await ctx.send("Cannot perform login during playback, please use the /stop command and try again.",
                                  ephemeral=True)

        abs_stored_token = os.getenv('bookshelfToken')
        user_result = search_user_db(user=user)

        if user_result:
            token = user_result[0]
            user_info = c.bookshelf_user_login(token=token)
            username = user_info['username']
            user_type = user_info['type']
            admin_user = False

            if user_type == "root" or user_type == "admin":
                admin_user = True

            if token == abs_stored_token:
                await ctx.send(content=f"user: {username} already logged in.", ephemeral=True)
                return
            elif username == user:
                os.environ['bookshelfToken'] = token
                logger.warning(f'user {ctx.author} logged in to ABS, changing token to assigned user: {username}')
                await ctx.send(content=f'Successfully logged in as user {username}', ephemeral=True)
                if admin_user:
                    await ctx.send("Logged in as ABS ADMIN, loading administration module! Important, you may have to "
                                   "reload discord!", ephemeral=True)
                    try:
                        ctx.bot.load_extension("administration")
                    except Exception as e:
                        logger.warning(e)
                else:
                    await ctx.send("Important changing users may require reloading discord!", ephemeral=True)
                    try:
                        ctx.bot.unload_extension("administration")
                    except Exception as e:
                        logger.warning(e)
            else:
                await ctx.send(content="Error occured, please try again later.", ephemeral=True)
        else:
            await ctx.send(content="Error occured, please try again later.", ephemeral=True)

    @slash_command(name="remove-user", description="Remove a user from the Bookshelf-Traveller database.")
    @slash_option(name='user', description='Select which user to remove', autocomplete=True, required=True,
                  opt_type=OptionType.STRING)
    async def remove_db_user(self, ctx: SlashContext, user: str):
        user_result = remove_user_db(user)
        if user_result:
            await ctx.send(f'Successfully deleted user: {user} from database!', ephemeral=True)
        else:
            await ctx.send(f'Failed to delete user {user} from database!', ephemeral=True)

    @slash_command(name='user', description="display the currently logged in ABS user", dm_permission=False)
    async def user_check(self, ctx: SlashContext):
        abs_stored_token = os.getenv('bookshelfToken')
        discord_id = ctx.author.id
        result = search_user_db(token=abs_stored_token)
        if result:
            username = result[0]
            await ctx.send(content=f"user {username} is currently logged in.", ephemeral=True)
        else:
            user_call = c.bookshelf_user_login(token=abs_stored_token)
            username = user_call['username']
            if username != '':
                user_insert = insert_data(discord_id=discord_id, token=abs_stored_token, user=username)
                if user_insert:
                    await ctx.send(content=f"user {username} is currently logged in.", ephemeral=True)
            else:
                await ctx.send(content=f"Error occured, please visit logs for details and try again later.",
                               ephemeral=True)

    # Autocomplete Options -------------------------------------

    @user_select_db.autocomplete(option_name="user")
    @remove_db_user.autocomplete(option_name="user")
    async def user_search_autocomplete(self, ctx: AutocompleteContext):
        choices = []
        user_result = search_user_db()
        if user_result:
            for users in user_result:
                username = users[0]
                choices.append({'name': username, "value": username})
        await ctx.send(choices=choices)
