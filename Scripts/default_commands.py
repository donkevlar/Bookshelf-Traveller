import os
import logging
import traceback

from interactions.ext.paginators import Paginator
from interactions import *
from datetime import datetime

# Local file imports
import bookshelfAPI as c
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
        self.ephemeral_output = True

    # Slash Commands ----------------------------------------------------
    #

    # Pings the server, can ping other servers, why? IDK, cause why not.
    @slash_command(name="ping", description="Latency of the discord bot server to the discord central shard. Default Command.")
    async def ping(self, ctx: SlashContext):
        latency = round(self.bot.latency * 1000)
        message = f'Discord BOT Server Latency: {latency} ms'
        await ctx.send(message, ephemeral=self.ephemeral_output)
        logger.debug(f' Successfully sent command: ping')

    # Self-explanatory, pulls all a library's items
    @slash_command(name="all-library-items",
                   description=f"Get all library items from the currently signed in ABS user. Default Command.")
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

            await paginator.send(ctx, ephemeral=self.ephemeral_output)

        except Exception as e:
            print(e)
            traceback.print_exc()
            logger.error(e)
            await ctx.send("Could not complete this at the moment, please try again later.")

    # Retrieves a specific media item and it's progress
    @slash_command(name="media-progress",
                   description="Searches for the media item's progress. Default Command.")
    @slash_option(name="book_title", description="Enter a book title", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    async def search_media_progress(self, ctx: SlashContext, book_title: str):
        try:
            formatted_data = await c.bookshelf_item_progress(book_title)

            cover_title = await c.bookshelf_cover_image(book_title)

            chapter_progress, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(book_title)

            if bookFinished:
                chapterTitle = "Book Finished"
            else:
                chapterTitle = chapter_progress['title']

            title = formatted_data['title']
            progress = formatted_data['progress']
            finished = formatted_data['finished']
            currentTime = formatted_data['currentTime']
            totalDuration = formatted_data['totalDuration']
            lastUpdated = formatted_data['lastUpdated']

            media_progress = (f"Progress: **{progress}**\nChapter Title: **{chapterTitle}**\n "
                              f"Time Progressed: **{currentTime}** Hours\n "
                              f"Total Duration: **{totalDuration}** Hours\n")
            media_status = f"Is Finished: **{finished}**\n " f"Last Updated: **{lastUpdated}**\n"

            # Create Embed Message
            embed_message = Embed(
                title=f"{title}",
                description=f"Fun media progress stats :)",
                color=ctx.author.accent_color
            )
            embed_message.add_field(name="Media Progress", value=media_progress, inline=False)
            embed_message.add_field(name="Media Status", value=media_status, inline=False)
            embed_message.add_image(cover_title)
            embed_message.url = f"{os.getenv('bookshelfURL')}/item/{book_title}"

            # Send message
            await ctx.send(embed=embed_message, ephemeral=self.ephemeral_output)
            logger.info(f' Successfully sent command: media-progress')

        except Exception as e:
            await ctx.send(
                "Could not complete this at the moment, likely due to no progress found. Please try again later",
                ephemeral=self.ephemeral_output)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occured: {e} | Command Name: media-progress')

    # Listening Stats, currently pulls the total time listened and converts it to hours
    @slash_command(name="listening-stats", description="Pulls the current ABS user's total listening time. Default Command")
    async def totalTime(self, ctx: SlashContext):
        try:
            formatted_sessions_string, data = await c.bookshelf_listening_stats()
            total_time = round(data.get('totalTime') / 60)  # Convert to Minutes
            if total_time >= 60:
                total_time = round(total_time / 60)  # Convert to hours
                message = f'Total Listening Time : {total_time} Hours'
            else:
                message = f'Total Listening Time : {total_time} Minutes'
            await ctx.send(message, ephemeral=self.ephemeral_output)
            logger.info(f' Successfully sent command: listening-stats')

        except Exception as e:
            await ctx.send("Could not get complete this at the moment, please try again later.")
            print("Error: ", e)
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: listening-stats')

    # Display a formatted list (embedded) of current libraries
    @check(ownership_check)
    @slash_command(name="all-libraries",
                   description="Display all current libraries. Default Command")
    async def show_all_libraries(self, ctx: SlashContext):
        try:
            # Get Library Data from API
            library_data = await c.bookshelf_libraries()
            formatted_data = ""

            # Create Embed Message
            embed_message = Embed(
                title="All Libraries",
                description="This will display all of the current libraries in your audiobookshelf server.",
                color=ctx.author.accent_color
            )

            # Iterate over each key-value pair in the dictionary
            for name, (library_id, audiobooks_only) in library_data.items():
                formatted_data += f'\nName: {name} \nLibraryID: {library_id} \nAudiobooks Only: {audiobooks_only}\n\n'

            embed_message.add_field(name=f"Libraries", value=formatted_data, inline=False)

            await ctx.send(embed=embed_message, ephemeral=self.ephemeral_output)
            logger.info(f' Successfully sent command: recent-sessions')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.")
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occured: {e} | Command Name: all-libraries')
            print("Error: ", e)

    # List the recent sessions, limited to 10 with API. Will merge if books are the same.
    @check(ownership_check)
    @slash_command(name="recent-sessions",
                   description="Display up to 10 recent sessions from the current logged in ABS user. Default Command")
    async def show_recent_sessions(self, ctx: SlashContext):
        try:
            await ctx.defer(ephemeral=self.ephemeral_output)
            formatted_sessions_string, data = await c.bookshelf_listening_stats()

            # Split formatted_sessions_string by newline character to separate individual sessions
            sessions_list = formatted_sessions_string.split('\n\n')
            count = 0
            embeds = []
            # Add each session as a separate field in the embed
            for session_info in sessions_list:
                count = count + 1
                # Split session info into lines
                session_lines = session_info.strip().split('\n')
                # Extract display title from the first line
                display_title = session_lines[0].split(': ')[1]
                author = session_lines[1].split(': ')[1]
                duration = session_lines[2].split(': ')[1]
                library_ID = session_lines[3].split(': ')[1]
                play_count = session_lines[4].split(': ')[1]
                aggregate_time = session_lines[5].split(': ')[1]

                cover_link = await c.bookshelf_cover_image(library_ID)
                logger.info(f"cover url: {cover_link}")

                # Create Embed Message
                embed_message = Embed(
                    title=f"Session {count} | {display_title}",
                    description=f"Recent Session Info",
                    color=ctx.author.accent_color
                )

                # Use display title as the name for the field
                embed_message.add_field(name='Author', value=author, inline=False)
                embed_message.add_field(name='Book Length', value=duration, inline=False)
                embed_message.add_field(name='Aggregate Session Time', value=aggregate_time, inline=False)
                embed_message.add_field(name='Number of Times a Session was Played', value=f'Play Count: {play_count}',
                                        inline=False)
                # embed_message.add_field(name='Library Item ID', value=library_ID, inline=False)
                embed_message.add_image(cover_link)
                embed_message.url = f"{os.getenv('bookshelfURL')}/item/{library_ID}"

                embeds.append(embed_message)

            paginator = Paginator.create_from_embeds(self.bot, *embeds, timeout=120)
            await paginator.send(ctx, ephemeral=self.ephemeral_output)

            logger.info(f' Successfully sent command: recent-sessions')

        except Exception as e:
            await ctx.send("Could not complete this at the moment, please try again later.")
            logger.warning(
                f'User:{self.bot.user} (ID: {self.bot.user.id}) | Error occurred: {e} | Command Name: recent-sessions')
            print("Error: ", e)

    @slash_command(name="search-book", description="Search for a book in your libraries. Default Command.")
    @slash_option(name="book", description="Book Title", autocomplete=True, required=True, opt_type=OptionType.STRING)
    async def search_book(self, ctx: SlashContext, book):
        book_details = await c.bookshelf_get_item_details(book)

        title = book_details['title']
        author = book_details['author']
        series = book_details['series']
        narrators = book_details['narrator']
        duration_seconds = book_details['duration']
        publisher = book_details['publisher']
        publishedYear = book_details['publishedYear']
        genre = book_details['genres']
        language = book_details['language']
        addedDate = book_details['addedDate'] / 1000

        converted_added_date = datetime.utcfromtimestamp(addedDate)
        formatted_addedDate = converted_added_date.strftime('%Y-%m-%d')

        if duration_seconds >= 3600:
            duration = round(duration_seconds / 3600, 2)
            duration = str(duration) + " Hours"

        elif duration_seconds >= 60 < 3600:
            duration = duration_seconds / 60
            duration = str(duration) + " Minutes"

        else:
            duration = str(duration_seconds) + " Seconds"

        add_info = f"Genres: *{genre}*\nDuration: *{duration}*\nLanguage: *{language}*"
        release_info = f"Publisher: *{publisher}*\nPublished Year: *{publishedYear}*\nAdded Date: *{formatted_addedDate}*"

        cover = await c.bookshelf_cover_image(book)

        embed_message = Embed(
            title=title,
            description=series if series != '' else "Author: " + author
        )

        if series:
            embed_message.add_field(name='Author(s)', value=author)

        embed_message.add_field(name='Narrator(s)', value=narrators)
        embed_message.add_field(name="Release Information", value=release_info)
        embed_message.add_field(name="Additional Information", value=add_info)
        embed_message.add_image(cover)

        await ctx.send(content=f"Book details for **{title}**", ephemeral=self.ephemeral_output, embed=embed_message)

    @check(ownership_check)
    @slash_command(name="setup-default-commands", description="Override optional command arguments. Note only affects default commands.")
    @slash_option(name="ephemeral_output", description="force enable/disable ephemeral output for all default commands.", opt_type=OptionType.BOOLEAN)
    async def setup_default_commands(self, ctx: SlashContext, ephemeral_output=None):
        if ephemeral_output is None:
            await ctx.send(f"Ephemeral output currently set to **{self.ephemeral_output}**", ephemeral=True)
            return
        if ephemeral_output and not self.ephemeral_output:
            self.ephemeral_output = True
            success = True

        elif not ephemeral_output and self.ephemeral_output:
            self.ephemeral_output = False
            success = True

        else:
            success = False

        if success:
            result = f"Set ephemeral output to **{self.ephemeral_output}**"
            await ctx.send(f"Operation successful! {result}")
        else:
            await ctx.send(f"Operation failed, output was already set to {ephemeral_output}", ephemeral=True)

    # Autocomplete ----------------------------------------------------------------

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

    # Autocomplete function, looks for the book title
    @search_media_progress.autocomplete("book_title")
    @search_book.autocomplete("book")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        print(user_input)
        if user_input == "":
            try:
                formatted_sessions_string, data = await c.bookshelf_listening_stats()
                count = 0

                for sessions in data['recentSessions']:
                    count += 1
                    mediaMetadata = sessions['mediaMetadata']
                    title = sessions.get('displayTitle')
                    subtitle = mediaMetadata.get('subtitle')
                    display_author = sessions.get('displayAuthor')
                    bookID = sessions.get('libraryItemId')

                    name = f"{title} | {display_author}"

                    if len(name) <= 100:
                        pass
                    elif len(title) <= 100:
                        name = title
                    else:
                        logger.debug(f"Recent Session {count}: Title and Full name were longer than 100 characters, attempting subtitle.")
                        name = f"{subtitle} | {display_author}"

                        if len(name) <= 100:
                            pass
                        else:
                            logger.debug("Recent Session {count}: Subtitle was too long, falling back to recent session")
                            name = f"Recent Session {count}"

                    formatted_item = {"name": name, "value": bookID}

                    if formatted_item not in choices:
                        choices.append(formatted_item)

                await ctx.send(choices=choices)

            except Exception as e:
                await ctx.send(choices=choices)
                logger.error(f"Error occured while loading autocomplete: {e}")

        else:
            try:
                titles_ = await c.bookshelf_title_search(user_input)
                for info in titles_:
                    book_title = info["title"]
                    book_id = info["id"]
                    choices.append({"name": f"{book_title}", "value": f"{book_id}"})

                await ctx.send(choices=choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)
                logger.error(e)
                traceback.print_exc()
