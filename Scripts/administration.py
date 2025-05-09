from interactions import *
import os
import bookshelfAPI as c
import settings as s
import logging

# Logger Config
logger = logging.getLogger("bot")

EPHEMERAL_OUTPUT = s.EPHEMERAL_OUTPUT


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
async def ownership_check(ctx: BaseContext): # NOQA
    # Default only owner can use this bot
    ownership = settings.OWNER_ONLY
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


class ABSAdmin(Extension):
    def __init__(self, bot):
        pass

    # Slash Commands ---------------------------

    # Searches for a specific user, uses autocomplete to retrieve the inputted name
    @slash_command(name="user-search",
                   description="Searches for a specific user, case sensitive")
    @check(ownership_check)
    @slash_option(name="name", description="enter a valid username", required=True, opt_type=OptionType.STRING)
    async def search_user(self, ctx: SlashContext, name: str):
        try:
            isFound, username, user_id, last_seen, isActive = c.bookshelf_search_users(name)

            if isFound:
                formatted_data = (
                    f'Last Seen: {last_seen}\n'
                    f'is Active: {isActive}\n'
                )

                # Create Embed Message
                embed_message = Embed(
                    title=f"User Info | {username}",
                    description=f"User information for {username}",
                    color=ctx.author.accent_color
                )
                embed_message.add_field(name="Username", value=username, inline=False)
                embed_message.add_field(name="User ID", value=user_id, inline=False)
                embed_message.add_field(name="General Information", value=formatted_data, inline=False)

                # Send message
                await ctx.send(embed=embed_message, ephemeral=EPHEMERAL_OUTPUT)
                logger.info(f' Successfully sent command: search_user')

        except TypeError as e:
            await ctx.send("Could not find that user, try a different name or make sure that it is spelt correctly.",
                           ephemeral=EPHEMERAL_OUTPUT)
            logger.warning(f' Error: {e}')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.", ephemeral=EPHEMERAL_OUTPUT)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: search_user')

    # Create user
    @slash_command(name="add-user",
                   description="Will create a user, user types: 'admin', 'guest', 'user' | Default = user")
    @check(ownership_check)
    @slash_option(name="name", description="enter a valid username", required=True, opt_type=OptionType.STRING)
    @slash_option(name="password", description="enter a unique password, note: CHANGE THIS LATER", required=True,
                  opt_type=OptionType.STRING)
    @slash_option(name="user_type", description="select user type", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="email", description="enter a valid email address", required=False, opt_type=OptionType.STRING)
    async def add_user(self, ctx: SlashContext, name: str, password: str, user_type="user", email=None):
        try:
            user_id, c_username = await c.bookshelf_create_user(name, password, user_type, email=email)
            await ctx.send(f"Successfully Created User: {c_username} with ID: {user_id}", ephemeral=True)
            # Send transaction to owner.
            await ctx.bot.owner.send(f'User Created: {c_username}, with ID: {user_id}. Command issued by {ctx.author}')
            logger.info(f' Successfully sent command: add-user')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.", ephemeral=True)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: add-user')
            logger.error(f"Unexpected error occured while attempting to create user: {e}")

    # Pulls the complete list of items in a library in csv
    @slash_command(name="book-list-csv",
                   description="Get complete list of items in a given library, outputs a csv")
    @check(ownership_check)
    @slash_option(name="library_name", description="enter a valid library name", required=True,
                  opt_type=OptionType.STRING, autocomplete=True)
    async def library_csv_booklist(self, ctx: SlashContext, library_name: str):
        try:
            await ctx.defer(ephemeral=True)
            # Get Current Working Directory
            current_directory = os.getcwd()

            # Create CSV File
            await c.bookshelf_library_csv(library_name)

            # Get Filepath
            file_path = os.path.join(current_directory, 'books.csv')

            await ctx.send(file=File(file_path), ephemeral=EPHEMERAL_OUTPUT)
            logger.info(f' Successfully sent command: test-connection')

        except Exception as e:

            await ctx.send("Could not complete this at the moment, please try again later.", ephemeral=EPHEMERAL_OUTPUT)

            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occured: {e} | Command Name: add-user')

    # tests the connection to the server
    @slash_command(name="test-connection",
                   description="test the connection between this bot and the audiobookshelf server, "
                               "optionally can place any url")
    @check(ownership_check)
    async def test_server_connection(self, ctx: SlashContext):
        try:

            status = c.bookshelf_test_connection()
            await ctx.send(f"Successfully connected to {os.getenv('bookshelfURL')} with status: {status}",
                           ephemeral=EPHEMERAL_OUTPUT)

            logger.info(f' Successfully sent command: test-connection')

        except Exception as e:
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occured: {e} | Command Name: add-user')

    # Autocomplete and Options -----------------------

    # Autocomplete, pulls all the libraries
    @library_csv_booklist.autocomplete("library_name")
    async def autocomplete_library_csv(self, ctx: AutocompleteContext):
        library_data = await c.bookshelf_libraries()
        choices = []

        for name, (library_id, audiobooks_only) in library_data.items():
            choices.append({"name": name, "value": library_id})

        print(choices)
        await ctx.send(choices=choices)

    # Autocomplete searches the username within the abs api
    @search_user.autocomplete("name")
    async def user_search_autocomplete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        isFound, username, user_id, last_seen, isActive = await c.bookshelf_search_users(user_input)
        choice = []
        if user_input.lower() == username.lower() or user_input.lower() in username.lower():
            choice = [{"name": f"{username}", "value": f"{username}"}]

        await ctx.send(choices=choice)

    # Autocomplete for user types, static choices
    @add_user.autocomplete("user_type")
    async def autocomplete_user_search_type(self, ctx: AutocompleteContext):
        choices = [
            {"name": "User", "value": "user"},
            {"name": "Guest", "value": "guest"}
        ]

        await ctx.send(choices=choices)

