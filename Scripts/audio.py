import asyncio

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
from settings import TIMEZONE
import logging
from datetime import datetime
from dotenv import load_dotenv
import random

# Import UI component functions
from ui_components import (
    get_playback_rows,
    get_series_playback_rows,
    get_podcast_playback_rows,
    create_playback_embed
)

load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = s.UPDATES

# Default only owner can use this bot
ownership = s.OWNER_ONLY

# Timezone
timeZone = pytz.timezone(TIMEZONE)

# Custom check for ownership
async def ownership_check(ctx: BaseContext):  # NOQA

    logger.info(f'Ownership is currently set to: {ownership}')

    if ownership:
        logger.info('OWNERSHIP is enabled, verifying if user is authorized.')
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.id == ctx.user.id or ctx.user in ctx.bot.owners:
            logger.info('Verified, executing command!')
            return True
        else:
            logger.warning('User is not an owner!')
            return False

    else:
        logger.info('ownership is disabled! skipping!')
        return True


async def time_converter(time_sec: int) -> str:
    """
    :param time_sec:
    :return: a formatted string w/ time_sec + time_format(H,M,S)
    """
    formatted_time = time_sec
    playbackTimeState = 'Seconds'

    if time_sec >= 60 and time_sec < 3600:
        formatted_time = round(time_sec / 60, 2)
        playbackTimeState = 'Minutes'
    elif time_sec >= 3600:
        formatted_time = round(time_sec / 3600, 2)
        playbackTimeState = 'Hours'

    formatted_string = f"{formatted_time} {playbackTimeState}"

    return formatted_string


class AudioPlayBack(Extension):
    def __init__(self, bot):
        # ABS Vars
        self.cover_image = ''
        # Session VARS
        self.sessionID = ''
        self.bookItemID = ''
        self.bookTitle = ''
        self.bookDuration = None
        self.currentTime = 0.0
        self.activeSessions = 0
        self.sessionOwner = None
        # Chapter VARS
        self.currentChapter = None
        self.chapterArray = None
        self.currentChapterTitle = ''
        self.newChapterTitle = ''
        self.found_next_chapter = False
        self.bookFinished = False
        self.nextTime = None
        # Audio VARS
        self.audioObj = AudioVolume
        self.context_voice_channel = None
        self.current_playback_time = 0
        self.audio_context = None
        self.bitrate = 128000
        self.volume = 0.0
        self.placeholder = None
        self.playbackSpeed = 1.0
        self.isPodcast = False
        self.updateFreqMulti = updateFrequency * self.playbackSpeed
        self.play_state = 'stopped'
        self.audio_message = None
        # User Vars
        self.username = ''
        self.user_type = ''
        self.current_channel = None
        self.active_guild_id = None

    # Tasks ---------------------------------

    @Task.create(trigger=IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        logger.info(f"Initializing Session Sync, current refresh rate set to: {updateFrequency} seconds")
        try:
            self.current_playback_time = self.current_playback_time + updateFrequency

            formatted_time = await time_converter(self.current_playback_time)

            # Try to update the session
            try:
                updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                    item_id=self.bookItemID,
                    session_id=self.sessionID,
                    current_time=updateFrequency,
                    next_time=self.nextTime)

                self.currentTime = updatedTime
                logger.info(f"Successfully synced session to updated time: {updatedTime} | "
                            f"Current Playback Time: {formatted_time} | session ID: {self.sessionID}")

                # Check if book is finished
                if finished_book:
                    logger.info("Book playback has finished based on session update")
                    # Could add special handling for finished books if problems occur

            except TypeError as e:
                logger.warning(f"Session update error: {e} - session may be invalid or closed")
                # Continue with task to allow chapter update even if session update fails

            # Try to get current chapter
            try:
                current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                    self.bookItemID, updatedTime if 'updatedTime' in locals() else None)

                if not isPodcast and current_chapter:
                    # Check if current_chapter has a title key
                    chapter_title = current_chapter.get('title', 'Unknown Chapter')
                    logger.info(f"Current Chapter Sync: {chapter_title}")
                    self.currentChapter = current_chapter
                    self.currentChapterTitle = chapter_title
                
            except Exception as e:
                logger.warning(f"Error getting current chapter: {e}")

        except Exception as e:
            logger.error(f"Unhandled error in session_update task: {e}")
            # Don't stop the task on errors, let it continue for the next interval

    @Task.create(trigger=IntervalTrigger(minutes=4))
    async def auto_kill_session(self):
        if self.play_state == 'paused' and self.audio_message is not None:
            logger.warning("Auto kill session task active! Playback was paused, verifying if session should be active.")
            voice_state = self.bot.get_bot_voice_state(self.active_guild_id)
            channel = await self.bot.fetch_channel(self.current_channel)

            chan_msg = await channel.send(
                f"Current playback of **{self.bookTitle}** will be stopped in **60 seconds** if no activity occurs.")
            await asyncio.sleep(60)

            if channel and voice_state and self.play_state == 'paused':
                await chan_msg.edit(
                    content=f'Current playback of **{self.bookTitle}** has been stopped due to inactivity.')
                await voice_state.stop()
                await voice_state.disconnect()
                await c.bookshelf_close_session(self.sessionID)
                logger.warning("audio session deleted due to timeout.")

                # Reset Vars and close out loops
                self.current_channel = None
                self.play_state = 'stopped'
                self.audio_message = None
                self.activeSessions -= 1
                self.sessionOwner = None
                self.audioObj.cleanup()  # NOQA

                if self.session_update.running:
                    self.session_update.stop()

            else:
                logger.debug("Session resumed, aborting task and deleting message!")
                await chan_msg.delete()

            # End loop
            self.auto_kill_session.stop()

        # elif self.play_state == 'playing':
        #     logger.info('Verifying if session should be active')
        #     if self.current_channel is not None:
        #         channel = self.bot.fetch_channel(self.current_channel)

    # Random Functions ------------------------
    # Change Chapter Function
    async def move_chapter(self, option: str):
        logger.info(f"executing command /next-chapter")
        CurrentChapter = self.currentChapter

        # Check if chapter data exists
        if not self.currentChapter or not self.chapterArray:
            logger.warning("No chapter data available for this book. Cannot navigate chapters.")
            self.found_next_chapter = False
            return
    
        # Check if bookFinished flag is set
        if self.bookFinished:
            logger.info("Book is already finished, cannot navigate chapters.")
            self.found_next_chapter = False
            return

        try:
            # Safely get the current chapter ID
            currentChapterID = int(CurrentChapter.get('id', 0))

            if option == 'next':
                nextChapterID = currentChapterID + 1
            else:
                nextChapterID = currentChapterID - 1

            # Check if we're going below Chapter 1 (index 0)
            if nextChapterID < 0 and option == 'previous':
                logger.info("Attempting to go before Chapter 1, will restart the book instead")
                # Just use the first chapter (index 0)
                nextChapterID = 0

            found_next = False
            for chapter in self.chapterArray:
                try:
                    chapterID = int(chapter.get('id', -1))

                    if nextChapterID == chapterID:
                        found_next = True
                        self.session_update.stop()
                        await c.bookshelf_close_session(self.sessionID)
                        chapterStart = float(chapter.get('start'))
                        self.newChapterTitle = chapter.get('title', 'Unknown Chapter')

                        self.currentTime = chapterStart

                        logger.info(f"Selected Chapter: {self.newChapterTitle}, Starting at: {chapterStart}")

                        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(
                            self.bookItemID)

                        self.sessionID = sessionID
                        self.currentTime = currentTime
                        self.bookDuration = bookDuration

                        self.currentChapter = chapter
                        self.currentChapterTitle = chapter.get('title', 'Unknown Chapter')
                        logger.info(f"Updated current chapter to: {self.currentChapterTitle}")

                        audio = AudioVolume(audio_obj)
                        audio.ffmpeg_before_args = f"-ss {chapterStart}"
                        audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
                        self.audioObj = audio

                        # Set next time to new chapter time
                        self.nextTime = chapterStart

                        # Send manual next chapter sync with new session ID
                        logger.info(f"Updating new session {sessionID} to position {chapterStart}")
                        try:
                            updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                                item_id=self.bookItemID, 
                                session_id=self.sessionID,
                                current_time=updateFrequency - 0.5, 
                                next_time=self.nextTime)
                    
                            self.currentTime = updatedTime
                            logger.info(f"Session update successful: {updatedTime}")
                        except Exception as e:
                            logger.error(f"Error updating session: {e}")

                        # Reset Next Time to None before starting task again
                        self.nextTime = None
                        logger.info(f"Verifying session ID is set to {self.sessionID} before starting update task")

                        try:
                            verified_chapter, _, _, _ = await c.bookshelf_get_current_chapter(
                                item_id=self.bookItemID, current_time=chapterStart)
                    
                            if verified_chapter:
                                verified_title = verified_chapter.get('title')
                                logger.info(f"Server verified chapter title: {verified_title}")
                        
                                # If there's a mismatch, update to the server's version
                                if verified_title != self.currentChapterTitle:
                                    logger.warning(f"Chapter title mismatch! Local: {self.currentChapterTitle}, Server: {verified_title}")
                                    self.currentChapter = verified_chapter
                                    self.currentChapterTitle = verified_title
                        except Exception as e:
                            logger.error(f"Error verifying chapter info: {e}")

                        self.session_update.start()

                        self.found_next_chapter = True
                        return

                except (TypeError, ValueError) as e:
                    logger.error(f"Error processing chapter ID for chapter: {e}")
                    continue
                
            # If we get here, we didn't find the next chapter
            if not found_next:
                logger.warning(f"Could not find chapter with ID {nextChapterID}")
                self.found_next_chapter = False
            
        except (TypeError, ValueError) as e:
            logger.error(f"Error in move_chapter: {e}")
            self.found_next_chapter = False

    def modified_message(self, color, chapter):
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")

        # Calculate progress percentage and time progressed
        progress_percentage = 0
        if self.bookDuration and self.bookDuration > 0:
            safe_current_time = min(self.currentTime, self.bookDuration)
            progress_percentage = (safe_current_time / self.bookDuration) * 100
            progress_percentage = round(progress_percentage, 1)
            progress_percentage = max(0, min(100, progress_percentage))

        duration = self.bookDuration
        TimeState = 'Seconds'
        _time = duration
        if self.bookDuration >= 60 and self.bookDuration < 3600:
            _time = round(duration / 60, 2)
            TimeState = 'Minutes'
        elif self.bookDuration >= 3600:
            _time = round(duration / 3600, 2)
            TimeState = 'Hours'

        formatted_duration = f"{_time} {TimeState}"
        formatted_current = f"{round(self.currentTime / 60, 2)} Minutes"

        return create_playback_embed(
            book_title=self.bookTitle,
            chapter_title=chapter,
            progress=f"{progress_percentage}%",
            current_time=formatted_current,
            duration=formatted_duration,
            username=self.username,
            user_type=self.user_type,
            cover_image=self.cover_image,
            color=color,
            volume=self.volume,
            timestamp=formatted_time,
            version=s.versionNumber
        )

    # Commands --------------------------------

    # Main play command, place class variables here since this is required to play audio
    @slash_command(name="play", description="Play audio from ABS server", dm_permission=False)
    @slash_option(name="book", description="Enter a book title or 'random' for a surprise", required=True,
                  opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="startover",
                  description="Start the book from the beginning instead of resuming",
                  opt_type=OptionType.BOOLEAN)
    async def play_audio(self, ctx: SlashContext, book: str, startover=False):
        # Check for ownership if enabled
        if ownership:
            if ctx.author.id not in ctx.bot.owners:
                logger.warning(f'User {ctx.author} attempted to use /play, and OWNER_ONLY is enabled!')
                await ctx.send(
                    content="Ownership enabled and you are not authorized to use this command. Contact bot owner.")
                return

        if not self.bot.is_ready or not ctx.author.voice:
            await ctx.send(content="Bot is not ready or author not in voice channel, please try again later.",
                           ephemeral=True)
            return

        logger.info(f"executing command /play")

        # Defer the response right away to prevent "interaction already responded to" errors
        await ctx.defer(ephemeral=True)

        # Handle 'random' book selection here
        random_selected = False
        random_book_title = None
        if book.lower() == 'random':
            logger.info('Random book option selected, selecting a surprise book!')
            try:
                titles_ = await c.bookshelf_get_valid_books()
                titles_count = len(titles_)
                logger.info(f"Total Title Count: {titles_count}")

                if titles_count == 0:
                    await ctx.send(content="No books found in your library to play randomly.", ephemeral=True)
                    return

                random_title_index = random.randint(0, titles_count - 1)
                random_book = titles_[random_title_index]
                random_book_title = random_book.get('title')
                book = random_book.get('id')
                random_selected = True

                logger.info(f'Surprise! {random_book_title} has been selected to play')
            except Exception as e:
                logger.error(f"Error selecting random book: {e}")
                await ctx.send(content="Error selecting a random book. Please try again.", ephemeral=True)
                return

        try:
            # Proceed with the normal playback flow using the book ID
            current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(item_id=book)

            if current_chapter is None:
                await ctx.send(content="Error retrieving chapter information. The item may be invalid or inaccessible.", ephemeral=True)
                return

            if isPodcast:
                await ctx.send(content="The content you attempted to play is currently not supported, aborting.",
                              ephemeral=True)
                return

            if bookFinished and not startover:
                await ctx.send(content="This book is marked as finished. Use the `startover: True` option to play it from the beginning.", ephemeral=True)
                return

            if self.activeSessions >= 1:
                await ctx.send(content=f"Bot can only play one session at a time, please stop your other active session and try again! Current session owner: {self.sessionOwner}", ephemeral=True)
                return

            # Get Bookshelf Playback URI, Starts new session
            audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(book)

            if startover:
                logger.info(f"startover flag is true, setting currentTime to 0 instead of {currentTime}")
                currentTime = 0
                # Also find the first chapter
                if chapter_array and len(chapter_array) > 0:
                    # Sort chapters by start time
                    chapter_array.sort(key=lambda x: float(x.get('start', 0)))
                    first_chapter = chapter_array[0]
                    self.currentChapter = first_chapter
                    self.currentChapterTitle = first_chapter.get('title', 'Chapter 1')
                    logger.info(f"Setting to first chapter: {self.currentChapterTitle}")

            # Get Book Cover URL
            cover_image = await c.bookshelf_cover_image(book)

            # Retrieve current user information
            username, user_type, user_locked = await c.bookshelf_auth_test()

            # Audio Object Arguments
            audio = AudioVolume(audio_obj)
            audio.buffer_seconds = 5
            audio.locked_stream = True
            self.volume = audio.volume
            audio.ffmpeg_before_args = f"-ss {currentTime}"
            audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
            audio.bitrate = self.bitrate

            # Class VARS

            # ABS User Vars
            self.username = username
            self.user_type = user_type
            self.cover_image = cover_image

            # Session Vars
            self.sessionID = sessionID
            self.sessionOwner = ctx.author.username
            self.bookItemID = book
            self.bookTitle = bookTitle
            self.audioObj = audio
            self.currentTime = currentTime
            self.current_playback_time = 0
            self.audio_context = ctx
            self.active_guild_id = ctx.guild_id
            self.bookDuration = bookDuration

            # Chapter Vars
            self.isPodcast = isPodcast
            self.currentChapter = current_chapter if not startover else self.currentChapter  # Use first chapter if startover
            self.currentChapterTitle = current_chapter.get('title') if not startover else self.currentChapterTitle
            self.chapterArray = chapter_array
            self.bookFinished = bookFinished
            self.current_channel = ctx.channel_id
            self.play_state = 'playing'

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            # check if bot currently connected to voice
            if not ctx.voice_state:
                # if we haven't already joined a voice channel
                try:
                    # Connect to voice channel and start task
                    await ctx.author.voice.channel.connect()
                    self.session_update.start()

                    # Customize message based on whether we're using random and/or startover
                    start_message = "Beginning audio stream"
                    if random_selected:
                        start_message = f"🎲 Randomly selected: **{random_book_title}**\n{start_message}"
                    if startover:
                        start_message += " from the beginning!"
                    else:
                        start_message += "!"

                    # Stop auto kill session task
                    if self.auto_kill_session.running:
                        self.auto_kill_session.stop()

                    self.audio_message = await ctx.send(
                        content=start_message,
                        embed=embed_message,
                        components=get_playback_rows("playing")
                    )

                    logger.info(f"Beginning audio stream" + (" from the beginning" if startover else ""))

                    self.activeSessions += 1

                    await self.client.change_presence(activity=Activity.create(name=f"{self.bookTitle}",
                                                                               type=ActivityType.LISTENING))

                    # Start audio playback
                    await ctx.voice_state.play(audio)

                except Exception as e:
                    # Stop Any Associated Tasks
                    if self.session_update.running:
                        self.session_update.stop()
                    # Close ABS session
                    await c.bookshelf_close_session(sessionID)  # NOQA
                    # Cleanup discord interactions
                    if ctx.voice_state:
                        await ctx.author.voice.channel.disconnect()
                    if audio:
                        audio.cleanup()  # NOQA

                    logger.error(f"Error starting playback: {e}")
                    await ctx.send(content=f"Error starting playback: {str(e)}")

        except Exception as e:
            logger.error(f"Unhandled error in play_audio: {e}")
            await ctx.send(content=f"An error occurred while trying to play this content: {str(e)}", ephemeral=True)

    # Pause audio, stops tasks, keeps session active.
    @slash_command(name="pause", description="pause audio", dm_permission=False)
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=True)
            logger.info(f"executing command /pause")
            ctx.voice_state.pause()
            logger.info("Pausing Audio")
            self.play_state = 'paused'
            # Stop Any Tasks Running and start autokill task
            if self.session_update.running:
                self.session_update.stop()
            self.auto_kill_session.start()
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    # Resume Audio, restarts tasks, session is kept open
    @slash_command(name="resume", description="resume audio", dm_permission=False)
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            if self.sessionID != "":
                await ctx.send("Resuming Audio", ephemeral=True)
                logger.info(f"executing command /resume")
                # Resume Audio Stream
                ctx.voice_state.resume()
                logger.info("Resuming Audio")
                # Stop auto kill session task and start session
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()
                self.play_state = 'playing'
                self.session_update.start()
            else:
                await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="change-chapter", description="play next chapter, if available.", dm_permission=False)
    @slash_option(name="option", description="Select 'next or 'previous' as options", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="Item type is not book, chapter skip disabled", ephemeral=True)
                return

            await self.move_chapter(option)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.found_next_chapter:
                await ctx.send(content=f"Moving to chapter: {self.newChapterTitle}", ephemeral=True)
                await ctx.voice_state.play(self.audioObj)
            else:
                await ctx.send(content=f"Cannot navigate chapters - either the book has no chapter information, is finished, or no chapter was found in the requested direction.",
                              ephemeral=True)

            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="volume", description="change the volume for the bot", dm_permission=False)
    @slash_option(name="volume", description="Must be between 1 and 100", required=False, opt_type=OptionType.INTEGER)
    async def volume_adjuster(self, ctx, volume=0):
        if ctx.voice_state:
            audio = self.audioObj
            if volume == 0:
                await ctx.send(content=f"Volume currently set to: {self.volume * 100}%", ephemaral=True)
            elif volume >= 1 < 100:
                volume_float = float(volume / 100)
                audio.volume = volume_float
                self.volume = audio.volume
                await ctx.send(content=f"Volume set to: {volume}%", ephemaral=True)

            else:
                await ctx.send(content=f"Invalid Entry", ephemeral=True)
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.",
                   dm_permission=False)
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
            logger.info(f"executing command /stop")
            await ctx.send(content="Disconnected from audio channel and stopping playback.", ephemeral=True)
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.author.voice.channel.disconnect()
            self.audioObj.cleanup()  # NOQA
            await self.client.change_presence(activity=None)
            # Reset current playback time
            self.current_playback_time = 0
            self.activeSessions -= 1
            self.sessionOwner = None

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.session_update.running:
                self.session_update.stop()
                # self.terminal_clearer.stop()
                self.play_state = 'stopped'
                await c.bookshelf_close_session(self.sessionID)
                await c.bookshelf_close_all_sessions(10)

        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            await c.bookshelf_close_all_sessions(10)

    @check(ownership_check)
    @slash_command(name="close-all-sessions",
                   description="DEBUGGING PURPOSES, close all active sessions. Takes up to 60 seconds.",
                   dm_permission=False)
    @slash_option(name="max_items", description="max number of items to attempt to close, default=100",
                  opt_type=OptionType.INTEGER)
    async def close_active_sessions(self, ctx, max_items=50):
        # Wait for task to complete
        ctx.defer()

        openSessionCount, closedSessionCount, failedSessionCount = await c.bookshelf_close_all_sessions(max_items)

        await ctx.send(content=f"Result of attempting to close sessions. success: {closedSessionCount}, "
                               f"failed: {failedSessionCount}, total: {openSessionCount}", ephemeral=True)

    @check(ownership_check)
    @slash_command(name='refresh', description='re-sends your current playback card.')
    async def refresh_play_card(self, ctx: SlashContext):
        if ctx.voice_state:
            try:
                current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                    self.bookItemID)
                self.currentChapterTitle = current_chapter.get('title')
            except Exception as e:
                logger.error(f"Error trying to fetch chapter title. {e}")

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            if self.play_state == "playing":
                await ctx.send(embed=embed_message, components=get_playback_rows("playing"), ephemeral=True)
            elif self.play_state == "paused":
                await ctx.send(embed=embed_message, components=get_playback_rows("paused"), ephemeral=True)
        else:
            return await ctx.send("Bot not in voice channel or an error has occured. Please try again later!", ephemeral=True)

    # -----------------------------
    # Auto complete options below
    # -----------------------------
    @play_audio.autocomplete("book")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        logger.info(f"Autocomplete input: '{user_input}'")

        if user_input == "":
            try:
                # Add "Random" as the first option
                choices.append({"name": "📚 Random Book (Surprise me!)", "value": "random"})

                # Get recent sessions
                formatted_sessions_string, data = await c.bookshelf_listening_stats()
                valid_session_count = 0
                skipped_session_count = 0

                for session in data.get('recentSessions', []):
                    try:
                        # Get essential IDs
                        bookID = session.get('bookId')
                        itemID = session.get('libraryItemId')

                        # Skip sessions with missing essential data
                        if not itemID or not bookID:
                            logger.info(f"Skipping session with missing itemID or bookID")
                            skipped_session_count += 1
                            continue

                        # Extract metadata
                        mediaMetadata = session.get('mediaMetadata', {})
                        title = session.get('displayTitle')
                        subtitle = mediaMetadata.get('subtitle', '')
                        display_author = session.get('displayAuthor')

                        # Skip if both title and author are None (likely deleted item)
                        if title is None and display_author is None:
                            logger.info(f"Skipping session with no title or author for itemID: {itemID}")
                            skipped_session_count += 1
                            continue

                        # Log and handle None title case specifically
                        if title is None:
                            logger.info(f"Found session with None title for itemID: {itemID}, author: {display_author}")
                            title = 'Untitled Book'

                        # Apply default value for None author
                        if display_author is None:
                            logger.info(f"Found session with None author for itemID: {itemID}, title: {title}")
                            display_author = 'Unknown Author'

                        # Format name with smart truncation
                        name = f"{title} | {display_author}"
                        if len(name) > 100:
                            # First try title only
                            if len(title) <= 100:
                                name = title
                                logger.info(f"Truncated name to title only: {title}")
                            else:
                                # Try smart truncation with author
                                short_author = display_author[:20]
                                available_len = 100 - len(short_author) - 5  # Allow for "... | "
                                trimmed_title = title[:available_len] if available_len > 0 else "Untitled"
                                name = f"{trimmed_title}... | {short_author}"
                                logger.info(f"Smart truncated long title: {title} -> {trimmed_title}...")

                        # Ensure we don't exceed Discord limit
                        name = name.encode("utf-8")[:100].decode("utf-8", "ignore")

                        # Add to choices if not already there
                        formatted_item = {"name": name, "value": itemID}
                        if formatted_item not in choices:
                            choices.append(formatted_item)
                            valid_session_count += 1

                    except Exception as e:
                        logger.info(f"Error processing recent session: {e}")
                        skipped_session_count += 1
                        continue

                logger.info(f"Recent sessions processing complete - Valid: {valid_session_count}, Skipped: {skipped_session_count}")

                if not choices or len(choices) == 1:  # Only random option
                    logger.info("No valid recent sessions found, only showing random option")
                    choices = [{"name": "📚 Random Book (Surprise me!)", "value": "random"}]

                await ctx.send(choices=choices)

            except Exception as e:
                logger.error(f"Error retrieving recent sessions: {e}")
                choices = [{"name": "📚 Random Book (Surprise me!)", "value": "random"}]
                await ctx.send(choices=choices)

        else:
            # Handle user input search
            ctx.deferred = True
            try:
                # Add the random option if typing something that could be "random"
                if user_input == "random":
                    choices.append({"name": "📚 Random Book (Surprise me!)", "value": "random"})

                libraries = await c.bookshelf_libraries()
                valid_libraries = []
                found_titles = []

                # Get valid libraries
                for name, (library_id, audiobooks_only) in libraries.items():
                    valid_libraries.append({"id": library_id, "name": name})
                    logger.debug(f"Valid Library Found: {name} | {library_id}")

                # Search across all libraries, accumulating results
                for lib_id in valid_libraries:
                    library_iD = lib_id.get('id')
                    logger.debug(f"Searching library: {lib_id.get('name')} | {library_iD}")

                    try:
                        limit = 10
                        endpoint = f"/libraries/{library_iD}/search"
                        params = f"&q={user_input}&limit={limit}"
                        r = await c.bookshelf_conn(endpoint=endpoint, GET=True, params=params)

                        if r.status_code == 200:
                            data = r.json()
                            dataset = data.get('book', [])

                            for book in dataset:
                                authors_list = []
                                title = book['libraryItem']['media']['metadata']['title']
                                authors_raw = book['libraryItem']['media']['metadata']['authors']

                                for author in authors_raw:
                                    name = author.get('name')
                                    authors_list.append(name)

                                author = ', '.join(authors_list)
                                book_id = book['libraryItem']['id']

                                # Add to list if not already present (avoid duplicates)
                                new_item = {'id': book_id, 'title': title, 'author': author}
                                if not any(item['id'] == book_id for item in found_titles):
                                    found_titles.append(new_item)

                    except Exception as e:
                        logger.error(f"Error searching library {library_iD}: {e}")
                        continue  # Continue to next library even if this one fails

                # Process all found titles into choices for autocomplete
                for book in found_titles:
                    book_title = book.get('title', 'Unknown').strip()
                    author = book.get('author', 'Unknown').strip()
                    book_id = book.get('id')

                    if not book_id:
                        continue

                    # Handle None values
                    if book_title is None:
                        book_title = 'Untitled Book'
                    if author is None:
                        author = 'Unknown Author'

                    name = f"{book_title} | {author}"
                    if not name.strip():
                        name = "Untitled Book"

                    if len(name) > 100:
                        short_author = author[:20]
                        available_len = 100 - len(short_author) - 3
                        trimmed_title = book_title[:available_len] if available_len > 0 else "Untitled"
                        name = f"{trimmed_title}... | {short_author}"

                    name = name.encode("utf-8")[:100].decode("utf-8", "ignore")

                    if 1 <= len(name) <= 100:
                        choices.append({"name": name, "value": f"{book_id}"})

                await ctx.send(choices=choices)
                logger.info(choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)
                logger.error(f"Error in autocomplete: {e}")

    @change_chapter.autocomplete("option")
    async def chapter_option_autocomplete(self, ctx: AutocompleteContext):
        choices = [
            {"name": "next", "value": "next"}, {"name": "previous", "value": "previous"}
        ]
        await ctx.send(choices=choices)

    # Component Callbacks ---------------------------
    @component_callback('pause_audio_button')
    async def callback_pause_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Pausing Playback!')
            self.play_state = 'paused'
            ctx.voice_state.channel.voice_state.pause()
            self.session_update.stop()
            logger.warning("Auto session kill task running... Checking for inactive session in 5 minutes!")
            self.auto_kill_session.start()
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            await ctx.edit_origin(content="Play", components=get_playback_rows("paused"), embed=embed_message)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await ctx.edit_origin(components=get_playback_rows("playing"), embed=embed_message)

    @component_callback('next_chapter_button')
    async def callback_next_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to next chapter!')

            # Check if chapter data exists before attempting navigation
            if not self.currentChapter or not self.chapterArray:
                logger.warning("No chapter data available for this book. Cannot navigate chapters.")
                await ctx.send(content="This book doesn't have chapter information. Chapter navigation is not available.", 
                              ephemeral=True)
                return  # Return early without stopping playback

            await ctx.defer(edit_origin=True)


            if self.play_state == 'playing':
                await ctx.edit_origin(components=get_playback_rows("playing"))
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=get_playback_rows("paused"))
            ctx.voice_state.channel.voice_state.player.stop()

            # Find next chapter
            await self.move_chapter(option='next')

            # Check if move_chapter succeeded before proceeding
            if self.found_next_chapter:
                embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                await ctx.edit(embed=embed_message)
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                # This shouldn't be reached since we check earlier, but just in case
                await ctx.send(content=f"No next chapter found.", ephemeral=True)
                # Restart playback since we stopped it
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to previous chapter!')

            # Check if chapter data exists before attempting navigation
            if not self.currentChapter or not self.chapterArray:
                logger.warning("No chapter data available for this book. Cannot navigate chapters.")
                await ctx.send(content="This book doesn't have chapter information. Chapter navigation is not available.", 
                              ephemeral=True)
                return  # Return early without stopping playback

            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=get_playback_rows("playing"))
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=get_playback_rows("paused"))
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous chapter command, bot not active or voice not connected!', ephemeral=True)
                return

            # Find previous chapter
            await self.move_chapter(option='previous')

            # Check if move_chapter succeeded before proceeding
            if self.found_next_chapter:
                embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                await ctx.edit(embed=embed_message)
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                # This shouldn't be reached since we check earlier, but just in case
                await ctx.send(content=f"No previous chapter found.", ephemeral=True)
                # Restart playback since we stopped it
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('stop_audio_button')
    async def callback_stop_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Stopping Playback!')
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.edit_origin()
            await ctx.delete()
            # Class VARS
            self.audioObj.cleanup()  # NOQA
            self.session_update.stop()
            self.current_playback_time = 0
            self.activeSessions -= 1
            self.sessionOwner = None
            self.play_state = 'stopped'
            await ctx.voice_state.channel.disconnect()
            await self.client.change_presence(activity=None)
            # Cleanup Session
            await c.bookshelf_close_session(self.sessionID)
            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

    @component_callback('volume_up_button')
    async def callback_volume_up_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1
            # Update Audio OBJ
            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume + adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)
            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('volume_down_button')
    async def callback_volume_down_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1

            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume - adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)

            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('forward_button')
    async def callback_forward_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()
        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA

        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

        self.sessionID = sessionID
        self.currentTime = currentTime

        print(self.currentTime)

        self.nextTime = self.currentTime + 30.0
        logger.info(f"Moving to time using forward:  {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"

        # Send manual next chapter sync
        await c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                         current_time=updateFrequency - 0.5, next_time=self.nextTime)

        self.audioObj = audio
        self.session_update.start()
        self.nextTime = None

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    @component_callback('rewind_button')
    async def callback_rewind_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()
        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA
        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

        self.currentTime = currentTime
        self.sessionID = sessionID
        self.nextTime = self.currentTime - 30.0
        logger.info(f"Moving to time using rewind: {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"

        # Send manual next chapter sync
        await c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                         current_time=updateFrequency - 0.5, next_time=self.nextTime)

        self.audioObj = audio
        self.session_update.start()
        self.nextTime = None

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    # ----------------------------
    # Other non discord related functions
    # ----------------------------
