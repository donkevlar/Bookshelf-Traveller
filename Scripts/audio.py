import asyncio
import os

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
from settings import TIMEZONE
from ui_components import get_playback_rows, create_playback_embed
from utils import add_progress_indicators
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random

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


def time_converter(time_sec: int) -> str:
    """
    :param time_sec:
    :return: a formatted string w/ time_sec + time_format(H,M,S)
    """
    hours = int(time_sec // 3600)
    minutes = int((time_sec % 3600) // 60)
    seconds = int(time_sec % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

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
        self.announcement_message = None
        self.repeat_enabled = False
        self.needs_restart = False
        self.stream_started = False
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
        # Series playback variables
        self.seriesEnabled = True  # Default to enabled
        self.seriesList = []  # List of book IDs in series order
        self.seriesIndex = None  # Current position in series
        self.previousBookID = None
        self.previousBookTime = None
        self.currentSeries = None  # Series metadata
        self.isLastBookInSeries = False
        self.isFirstBookInSeries = False

    # Tasks ---------------------------------

    async def build_session(self, item_id: str, start_time: float = None, force_restart: bool = False):
        """
        Unified method to build audio session for any playback scenario.
    
        Parameters:
        - item_id: The library item ID to build session for
        - start_time: Optional time to start from (if None, uses server's current time)
        - force_restart: If True, starts from beginning regardless of server progress
    
        Returns:
        - Tuple: (audio_object, current_time, session_id, book_title, book_duration)
        """
        try:
            # Handle force restart by resetting server progress first
            if force_restart:
                try:
                    await c.bookshelf_mark_book_unfinished(item_id)
                    logger.info("Reset server progress to beginning for restart")
                except Exception as e:
                    logger.warning(f"Failed to reset server progress for restart: {e}")

            # Get fresh audio object and session
            audio_obj, server_current_time, session_id, book_title, book_duration = await c.bookshelf_audio_obj(item_id)
        
            # Determine actual start time
            if force_restart:
                actual_start_time = 0.0
                logger.info("Force restart enabled - starting from beginning")
            elif start_time is not None:
                actual_start_time = start_time
                logger.info(f"Using provided start time: {actual_start_time}")
            else:
                actual_start_time = server_current_time

                # Log meaningful information about the resume position
                if server_current_time > 0:
                    formatted_time = time_converter(int(server_current_time))
                    logger.info(f"Respecting server progress - resuming at: {formatted_time} ({actual_start_time}s)")
                else:
                    logger.info("Starting from beginning - no previous progress found")

            if s.FFMPEG_DEBUG:
                # Create ffmpeg logs directory in appdata
                ffmpeg_log_dir = os.path.join("db", "ffmpeg")
                os.makedirs(ffmpeg_log_dir, exist_ok=True)
    
                # Set FFmpeg report environment variable. level=24 for warning. 32 for info. 48 for debug.
                os.environ["FFREPORT"] = f"file={ffmpeg_log_dir}/ffmpeg-%t.log:level=32"
        
            # Build audio object with proper settings
            audio = AudioVolume(audio_obj)
            audio.buffer_seconds = 1
            audio.locked_stream = True
            audio.ffmpeg_before_args = f"-re -ss {actual_start_time}"
            audio.ffmpeg_args = f""
            audio.bitrate = self.bitrate
            self.volume = audio.volume

            # Hook into the audio source to detect when streaming starts
            original_read = audio.read
        
            def stream_detecting_read(*args, **kwargs):
                data = original_read(*args, **kwargs)
                if data and not self.stream_started:
                    self.stream_started = True
                    logger.info("🎵 AUDIO STREAM DETECTED - FFmpeg is now providing data!")
                return data
        
            audio.read = stream_detecting_read
        
            # Update instance variables
            self.sessionID = session_id
            self.bookItemID = item_id
            self.bookTitle = book_title
            self.bookDuration = book_duration
            self.currentTime = actual_start_time
            self.audioObj = audio
        
            # If we're seeking to a specific time, set nextTime for session sync
            if start_time is not None:
                self.nextTime = actual_start_time

            logger.info(f"Built session for '{book_title}' starting at {actual_start_time}s")
        
            return audio, actual_start_time, session_id, book_title, book_duration
        
        except Exception as e:
            logger.error(f"Error building session for item {item_id}: {e}")
            raise

    @Task.create(trigger=IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        # Check for restart flag
        if self.needs_restart:
            self.needs_restart = False
        
            restart_success = await self.restart_media_from_beginning()
            if restart_success and self.audio_context and self.audio_context.voice_state:
                try:
                    await self.audio_context.voice_state.stop()
                    await self.audio_context.voice_state.play(self.audioObj)
                    # Task continues running normally
                except Exception as e:
                    logger.error(f"Error starting playback after restart: {e}")
                    await self.cleanup_session("restart failed")
            else:
                logger.error("Restart failed - cleaning up session")
                await self.cleanup_session("restart failed")

            return  # Exit this iteration, but task keeps running

        # Don't sync until FFmpeg is actually streaming
        if not self.stream_started:
            logger.info("Waiting for FFmpeg to start streaming...")
            return

        logger.debug(f"Initializing Session Sync, current refresh rate set to: {updateFrequency} seconds")
        try:
            self.current_playback_time = self.current_playback_time + updateFrequency
            formatted_time = time_converter(self.current_playback_time)

            # Try to update the session
            try:
                updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                    item_id=self.bookItemID,
                    session_id=self.sessionID,
                    current_time=updateFrequency,
                    next_time=self.nextTime)

                self.currentTime = updatedTime

                logger.info(f"Session sync successful: {updatedTime} | Duration: {duration} | "
                            f"Current Playback Time: {formatted_time} | session ID: {self.sessionID}")

                # If ABS marked it finished, check if we should let it finish naturally
                if finished_book:
                    time_remaining = duration - updatedTime if duration > 0 else 0
                
                    if time_remaining <= 30.0:
                        if time_remaining <= 0:
                            # Book has truly reached the end
                            if self.repeat_enabled:
                                logger.info("Book completed with repeat enabled - triggering restart")
                                self.needs_restart = True
                                return  # Let the restart logic handle it
                            elif self.seriesEnabled and self.currentSeries and not self.isLastBookInSeries:
                                logger.info("Book completed - moving to next book in series")
                    
                                # Store current book as previous
                                self.previousBookID = self.bookItemID
                                self.previousBookTime = self.currentTime
                    
                                # Move to next book
                                success = await self.move_to_series_book("next")
                                if success:
                                    logger.info("Successfully moved to next book in series")
                                    return  # Continue with the new book
                                else:
                                    logger.error("Failed to move to next book in series")
                                    await self.cleanup_session("series progression failed")
                                    return
                            else:
                                logger.info("Stream has reached the end - cleaning up")
                                await self.cleanup_session("natural audio completion")
                                return
                        else:
                            logger.info(f"ABS marked book finished with {time_remaining:.1f}s remaining - letting stream finish naturally")
                            # Don't cleanup yet, let it play out completely
                    else:
                        logger.info("ABS marked book as finished - cleaning up")
                        await self.cleanup_session("book completed by ABS")
                        return

            except TypeError as e:
                logger.warning(f"Session update error: {e} - session may be invalid or closed")
                # Continue with task to allow chapter update even if session update fails

            # Try to get current chapter
            try:
                current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                    self.bookItemID, updatedTime if 'updatedTime' in locals() else None)

                if not isPodcast and current_chapter and self.chapterArray and len(self.chapterArray) > 0:
                    # Check if current_chapter has a title key
                    chapter_title = current_chapter.get('title', 'Chapter 1')
                    logger.debug(f"Current Chapter Sync: {chapter_title}")
                    self.currentChapter = current_chapter
                    self.currentChapterTitle = chapter_title
                elif not isPodcast:
                    # Book has no chapters
                    self.currentChapter = None
                    self.currentChapterTitle = 'No Chapters'

            except Exception as e:
                logger.warning(f"Error getting current chapter: {e}")

            # Update announcement message if it exists  
            if self.announcement_message and self.context_voice_channel:
                try:
                    voice_channel = self.context_voice_channel
                    guild_name = self.announcement_message.guild.name if self.announcement_message.guild else "Unknown Server"
        
                    updated_embed = self.create_announcement_embed(voice_channel, guild_name)

                    # Rate limit updating the card to 10 seconds
                    now = datetime.now()
                    msg_id = self.announcement_message.id
                    if not hasattr(self, '_last_patch_timestamps'):
                        self._last_patch_timestamps = {}
                    last_update = self._last_patch_timestamps.get(msg_id, now.replace(second=0, microsecond=0) - timedelta(seconds=10))

                    if (now - last_update).total_seconds() >= 10:
                        updated_announcement = await self.announcement_message.edit(embed=updated_embed)
                        self.announcement_message = updated_announcement
                        self._last_patch_timestamps[msg_id] = now
                        logger.debug("Updated announcement card")
        
                except Exception as e:
                    logger.warning(f"Failed to update announcement card: {e}")
                    if "Unknown Message" in str(e) or "Not Found" in str(e) or "404" in str(e):
                        logger.info("Announcement message no longer exists, clearing reference")
                        self.announcement_message = None

        except Exception as e:
            logger.error(f"Unhandled error in session_update task: {e}")
            # Don't stop the task on errors, let it continue for the next interval

    async def cleanup_session(self, reason="unknown"):
        """Cleanup method that handles all session ending scenarios"""
        logger.info(f"Cleaning up session - {reason}")

        # Update the announcement card if it exists 
        if self.announcement_message:
            try:
                now = datetime.now(tz=timeZone)
                formatted_time = now.strftime("%m-%d %H:%M:%S")

                # Calculate final progress if we have the data
                final_progress = "Unknown"
                if self.bookDuration and self.currentTime:
                    progress_percentage = min(100, (self.currentTime / self.bookDuration) * 100)
                    final_progress = f"{progress_percentage:.1f}%"

                formatted_duration = time_converter(self.bookDuration) if self.bookDuration else "Unknown"
                formatted_current = time_converter(self.currentTime) if self.currentTime else "Unknown"

                stopped_embed = Embed(
                    title="⏹️ Playback Stopped",
                    description=f"**{self.bookTitle or 'Unknown'}** playback has ended.",
                    color=0x95a5a6  # Gray color for stopped
                )

                # Add playback summary
                playback_summary = (
                    f"**Final Progress:** {final_progress}\n"
                    f"**Time Reached:** {formatted_current}\n"
                    f"**Total Duration:** {formatted_duration}\n"
                    f"**Ended At:** {formatted_time}"
                )
                stopped_embed.add_field(name="📊 Session Summary", value=playback_summary, inline=False)

                # Keep the cover image
                if self.cover_image:
                    stopped_embed.add_image(self.cover_image)

                stopped_embed.footer = f"{s.bookshelf_traveller_footer} | Playback Ended"

                await self.announcement_message.edit(embed=stopped_embed)
                logger.debug("Updated announcement card to stopped state with summary")
            except Exception as e:
                logger.debug(f"Error updating announcement card: {e}")

        # Stop tasks
        if self.session_update.running:
            self.session_update.stop()
            logger.debug("Stopped session_update task")

        if self.auto_kill_session.running:
            self.auto_kill_session.stop()
            logger.debug("Stopped auto_kill_session task")

        # Stop voice playback if active
        try:
            if hasattr(self, 'audio_context') and self.audio_context and self.audio_context.voice_state:
                await self.audio_context.voice_state.channel.voice_state.stop()
                logger.debug("Stopped voice playback")
        except Exception as e:
            logger.debug(f"Error stopping voice playback: {e}")

        # Clean up audio object
        try:
            if hasattr(self, 'audioObj') and self.audioObj:
                self.audioObj.cleanup()
                logger.debug("Cleaned up audio object")
        except Exception as e:
            logger.debug(f"Error cleaning audio object: {e}")

        # Disconnect from voice channel
        try:
            if hasattr(self, 'audio_context') and self.audio_context and self.audio_context.voice_state:
                await self.audio_context.voice_state.channel.disconnect()
                logger.debug("Disconnected from voice channel")
        except Exception as e:
            logger.debug(f"Error disconnecting from voice: {e}")

        # Close ABS session and all sessions
        if hasattr(self, 'sessionID') and self.sessionID:
            try:
                await c.bookshelf_close_session(self.sessionID)
                logger.debug(f"Closed ABS session: {self.sessionID}")
            except Exception as e:
                logger.debug(f"Error closing ABS session: {e}")

       # Clear bot presence
        try:
            if hasattr(self, 'client'):
                await self.client.change_presence(activity=None)
                logger.debug("Cleared bot presence")
        except Exception as e:
            logger.debug(f"Error clearing presence: {e}")

        # Reset all state variables
        try:
            self.sessionID = ''
            self.bookItemID = ''
            self.bookTitle = ''
            self.bookDuration = None
            self.currentTime = 0.0
            self.current_playback_time = 0
            self.activeSessions = max(0, self.activeSessions - 1)  # Prevent negative
            self.sessionOwner = None
            self.play_state = 'stopped'
            self.stream_started = False

            # Clear message references
            self.audio_message = None
            self.announcement_message = None
            self.context_voice_channel = None
            self.current_channel = None
            self.active_guild_id = None

            # Reset chapter variables
            self.currentChapter = None
            self.chapterArray = None
            self.currentChapterTitle = ''
            self.newChapterTitle = ''
            self.found_next_chapter = False
            self.bookFinished = False
            self.nextTime = None

            # Reset series context
            self.seriesEnabled = True  # Reset to default
            self.seriesList = []
            self.seriesIndex = None
            self.previousBookID = None
            self.previousBookTime = None
            self.currentSeries = None
            self.isLastBookInSeries = False
            self.isFirstBookInSeries = False

            # Reset audio variables
            self.volume = 0.0
            self.audioObj = None

            logger.debug("Reset all state variables")
        except Exception as e:
            logger.error(f"Error resetting state variables: {e}")


        # Clear presence
        try:
            await self.client.change_presence(activity=None)
        except:
            pass

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
                self.announcement_message = None
                self.context_voice_channel = None

                if self.session_update.running:
                    self.session_update.stop()

            else:
                logger.debug("Session resumed, aborting task and deleting message!")
                await chan_msg.delete()

            # End loop
            self.auto_kill_session.stop()

    async def restart_media_from_beginning(self):
        """
        Restart the current media (book/podcast) from the beginning while preserving session properties.
        This method handles the complete restart process for both books and podcast episodes.
        """
        if not self.bookItemID:
            logger.error("Cannot restart - no active media session")
            return False
    
        try:
            # Store current session properties we want to preserve
            preserved_book_id = self.bookItemID
            preserved_title = self.bookTitle
            preserved_duration = self.bookDuration
            preserved_cover = self.cover_image
            preserved_chapter_array = self.chapterArray
            preserved_volume = self.volume
            preserved_session_owner = self.sessionOwner
            preserved_context = self.audio_context
            preserved_voice_channel = self.context_voice_channel
            preserved_current_channel = self.current_channel
            preserved_active_guild_id = self.active_guild_id
            preserved_username = self.username
            preserved_user_type = self.user_type
            preserved_is_podcast = self.isPodcast
            preserved_current_playback_time = self.current_playback_time

            preserved_series = self.currentSeries
            preserved_series_list = self.seriesList.copy()
            preserved_series_index = self.seriesIndex
            preserved_series_enabled = self.seriesEnabled
            preserved_is_first = self.isFirstBookInSeries
            preserved_is_last = self.isLastBookInSeries

            # Close current session
            if self.sessionID:
                await c.bookshelf_close_session(self.sessionID)
        
            # Use unified session builder to create new session from beginning
            audio, actual_start_time, session_id, book_title, book_duration = await self.build_session(
                item_id=preserved_book_id,
                force_restart=True
            )
        
            # Restore preserved properties
            self.bookTitle = preserved_title
            self.bookDuration = preserved_duration
            self.cover_image = preserved_cover
            self.chapterArray = preserved_chapter_array
            self.volume = preserved_volume
            self.sessionOwner = preserved_session_owner
            self.audio_context = preserved_context
            self.context_voice_channel = preserved_voice_channel
            self.current_channel = preserved_current_channel
            self.active_guild_id = preserved_active_guild_id
            self.username = preserved_username
            self.user_type = preserved_user_type
            self.isPodcast = preserved_is_podcast
            self.current_playback_time = preserved_current_playback_time

            self.currentSeries = preserved_series
            self.seriesList = preserved_series_list
            self.seriesIndex = preserved_series_index
            self.seriesEnabled = preserved_series_enabled
            self.isFirstBookInSeries = preserved_is_first
            self.isLastBookInSeries = preserved_is_last

            self.currentTime = 0.0
        
            # Set to first chapter if it's a book with chapters
            if not self.isPodcast and self.chapterArray and len(self.chapterArray) > 0:
                self.chapterArray.sort(key=lambda x: float(x.get('start', 0)))
                first_chapter = self.chapterArray[0]
                self.currentChapter = first_chapter
                self.currentChapterTitle = first_chapter.get('title', 'Chapter 1')
        
            # Reset playback state
            self.play_state = 'playing'
            self.audioObj = audio
        
            # Apply preserved volume to new audio object
            audio.volume = preserved_volume
        
            return True
        
        except Exception as e:
            logger.error(f"Error restarting media from beginning: {e}")
            return False

    # Random Functions ------------------------

    # Change Chapter Function
    async def move_chapter(self, target_index=None, relative_move=None):
        """
        Navigate to a chapter by absolute index or relative movement.
    
        Args:
            target_index: Absolute chapter index (0-based) to navigate to
            relative_move: Relative movement (+1 for next, -1 for previous)
    
        Note: Provide either target_index OR relative_move, not both
        """
        logger.info(f"Executing move_chapter with target_index={target_index}, relative_move={relative_move}")

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
            # Get current chapter index
            current_chapter_id = int(self.currentChapter.get('id', 0))
            current_index = next((i for i, ch in enumerate(self.chapterArray) 
                                if int(ch.get('id', 0)) == current_chapter_id), 0)
        
            # Calculate target index
            if target_index is not None:
                next_index = target_index
            elif relative_move is not None:
                next_index = current_index + relative_move
            else:
                logger.error("Must provide either target_index or relative_move")
                self.found_next_chapter = False
                return

            # Handle boundary conditions
            max_index = len(self.chapterArray) - 1

            # Handle going past the end
            if next_index > max_index:
                if self.repeat_enabled:
                    logger.info("Reached final chapter with repeat enabled - restarting book")
                
                    # Stop the session update task before restart
                    if self.session_update.running:
                        self.session_update.stop()
                
                    # Handle restart directly
                    restart_success = await self.restart_media_from_beginning()
                    if restart_success:
                        # Send manual session sync
                        try:
                            updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                                item_id=self.bookItemID, 
                                session_id=self.sessionID,
                                current_time=updateFrequency - 0.5, 
                                next_time=0.0)
                        
                            self.currentTime = updatedTime
                            self.nextTime = None
                        except Exception as e:
                            logger.error(f"Error syncing restart position: {e}")

                        # Set the chapter info for the UI callback to use
                        if self.chapterArray and len(self.chapterArray) > 0:
                            first_chapter = self.chapterArray[0]
                            self.newChapterTitle = first_chapter.get('title', 'Chapter 1')
                        else:
                            self.newChapterTitle = 'Chapter 1'

                        # Restart the session update task
                        self.session_update.start()
                        self.found_next_chapter = True
                        return
                    else:
                        logger.error("Restart failed during chapter navigation")
                        await self.cleanup_session("restart failed")
                        self.found_next_chapter = False
                        return

                elif self.seriesEnabled and self.currentSeries and not self.isLastBookInSeries:
                    logger.info("Reached final chapter - moving to next book in series")                                                                                                                                        # Stop the session update task before moving to next book                                             if self.session_update.running:

                    # Stop the session update task before moving to next book
                    if self.session_update.running:
                        self.session_update.stop()

                    # Mark the book as complete
                    try:
                        await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID)
                        logger.info(f"Successfully marked book {self.bookItemID} as finished before series progression")
                    except Exception as e:
                        logger.warning(f"Failed to mark book as finished before series progression: {e}")

                    success = await self.move_to_series_book("next")                                                                                                                              # Move to next book in series                                                                         success = await self.move_to_next_book_in_series()
                    if success:
                        # Set the chapter info for the UI callback to use
                        self.newChapterTitle = self.currentChapterTitle
                        self.found_next_chapter = True

                        if self.seriesIndex is not None:
                            self.isFirstBookInSeries = self.seriesIndex == 0
                            self.isLastBookInSeries = self.seriesIndex == len(self.seriesList) - 1
                            logger.info(f"Updated series position: book {self.seriesIndex + 1}/{len(self.seriesList)}, first={self.isFirstBookInSeries}, last={self.isLastBookInSeries}")

                        return
                    else:
                        logger.error("Failed to move to next book in series")
                        await self.cleanup_session("series progression failed")
                        self.found_next_chapter = False
                        return
                else:
                    # Normal completion handling
                    logger.info("Skipped past final chapter - marking complete and cleaning up")
                    await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID)
                    await self.cleanup_session("completed via chapter skip")
                    self.found_next_chapter = False
                    return
        
            # Handle going before the beginning
            if next_index < 0:
                logger.info("Attempting to go before first chapter, staying at first chapter")
                next_index = 0
        
            # Get target chapter
            target_chapter = self.chapterArray[next_index]
        
            # Stop current session update task
            self.session_update.stop()

            # Close current session
            await c.bookshelf_close_session(self.sessionID)

            # Get chapter start time
            chapter_start = float(target_chapter.get('start'))
            self.newChapterTitle = target_chapter.get('title', 'Unknown Chapter')

            logger.info(f"Selected Chapter: {self.newChapterTitle}, Starting at: {chapter_start}")

            # Use unified session builder
            audio, currentTime, sessionID, bookTitle, bookDuration = await self.build_session(
                item_id=self.bookItemID,
                start_time=chapter_start
            )

            self.currentChapter = target_chapter
            self.currentChapterTitle = target_chapter.get('title', 'Unknown Chapter')
            logger.info(f"Updated current chapter to: {self.currentChapterTitle}")

            # Send manual session sync with new session ID
            logger.info(f"Updating new session {sessionID} to position {chapter_start}")
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

            # Clear nextTime
            self.nextTime = None

            # Verify chapter information with server
            try:
                verified_chapter, _, _, _ = await c.bookshelf_get_current_chapter(
                    item_id=self.bookItemID, current_time=chapter_start)
    
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
        
        except (TypeError, ValueError) as e:
            logger.error(f"Error in move_chapter: {e}")
            self.found_next_chapter = False

    def modified_message(self, color, chapter):
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")

        # Calculate progress percentage and time progressed
        progress_percentage = 0
        if self.bookDuration and self.bookDuration > 0 and self.currentTime is not None:
            safe_current_time = min(self.currentTime, self.bookDuration)
            progress_percentage = (safe_current_time / self.bookDuration) * 100
            progress_percentage = round(progress_percentage, 1)
            progress_percentage = max(0, min(100, progress_percentage))

        formatted_duration = time_converter(self.bookDuration) if self.bookDuration else "Unknown"
        formatted_current = time_converter(self.currentTime) if self.currentTime is not None else "Unknown"

        # Prepare series info if available
        series_info = None
        if self.currentSeries and self.seriesIndex is not None:
            series_info = {
                'name': self.currentSeries['name'],
                'current': self.seriesIndex + 1,
                'total': len(self.seriesList)
            }

        return create_playback_embed(
            book_title=self.bookTitle or "Unknown Book",
            chapter_title=chapter or "Unknown Chapter",
            progress=f"{progress_percentage}%",
            current_time=formatted_current,
            duration=formatted_duration,
            username=self.username or "Unknown User",
            user_type=self.user_type or "user",
            cover_image=self.cover_image or "",
            color=color,
            volume=self.volume or 0.0,
            timestamp=formatted_time,
            version=s.versionNumber,
            repeat_enabled=self.repeat_enabled,
            series_info=series_info
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

            # Use unified session builder
            audio, currentTime, sessionID, bookTitle, bookDuration = await self.build_session(
                item_id=book,
                # if True, start time will be zero
                force_restart=startover
            )

            self.currentTime = currentTime

            await self.setup_series_context(book)

            if startover:
                if chapter_array and len(chapter_array) > 0:
                    # Book has chapters - use first chapter
                    chapter_array.sort(key=lambda x: float(x.get('start', 0)))
                    first_chapter = chapter_array[0]
                    self.currentChapter = first_chapter
                    self.currentChapterTitle = first_chapter.get('title', 'Chapter 1')
                else:
                    # Book has no chapters - clear chapter info
                    self.currentChapter = None
                    self.currentChapterTitle = 'No Chapters'
            else:
                # Not starting over - use current chapter data or detect no chapters
                if current_chapter and chapter_array and len(chapter_array) > 0:
                    self.currentChapter = current_chapter
                    self.currentChapterTitle = current_chapter.get('title', 'Chapter 1')
                else:
                    # No chapter data available
                    self.currentChapter = None
                    self.currentChapterTitle = 'No Chapters'


            # Get Book Cover URL
            cover_image = await c.bookshelf_cover_image(book)

            # Retrieve current user information
            username, user_type, user_locked = await c.bookshelf_auth_test()

            # Class VARS

            # ABS User Vars
            self.username = username
            self.user_type = user_type
            self.cover_image = cover_image

            # Session Vars
            self.sessionOwner = ctx.author.username
            self.current_playback_time = 0
            self.audio_context = ctx
            self.active_guild_id = ctx.guild_id

            # Chapter Vars
            self.isPodcast = isPodcast
            self.chapterArray = chapter_array
            self.bookFinished = False  # Force locally to False. If it were True, it would've exited sooner. Startover needs this to be False.
            self.current_channel = ctx.channel_id
            self.play_state = 'playing'

            if self.currentTime is None:
                logger.warning(f"currentTime is None after build_session, using 0.0 as fallback")
                self.currentTime = 0.0

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
                        components=self.get_current_playback_buttons()
                    )

                    logger.info(f"Created audio message with ID: {self.audio_message.id} in channel: {self.audio_message.channel.id}")
                    # Store reference to voice channel for updates
                    self.context_voice_channel = ctx.author.voice.channel

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
                    self.audio_message = None
                    self.announcement_message = None
                    self.context_voice_channel = None

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
    @slash_command(name="change-chapter", description="Navigate to a specific chapter or use next/previous.", dm_permission=False)
    @slash_option(name="option", description="Select 'next', 'previous', or enter a chapter number", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return

        if self.isPodcast:
            await ctx.send(content="Item type is not book, chapter skip disabled", ephemeral=True)
            return

        # Check if we have chapter data
        if not self.currentChapter or not self.chapterArray:
            await ctx.send(content="This book doesn't have chapter information. Chapter navigation is not available.", 
                          ephemeral=True)
            return

        # Handle different option types
        if option == "next":
            await self.move_chapter(relative_move=1)
            operation_desc = "next chapter"
        elif option == "previous":
            await self.move_chapter(relative_move=-1)
            operation_desc = "previous chapter"
        elif option.isdigit():
            target_chapter_num = int(option)

            # Validate chapter number (1-based input, convert to 0-based index)
            if not self.chapterArray or target_chapter_num < 1 or target_chapter_num > len(self.chapterArray):
                chapter_count = len(self.chapterArray) if self.chapterArray else 0
                await ctx.send(content=f"Invalid chapter number. This book has {chapter_count} chapters. "
                                      f"Please enter a number between 1 and {chapter_count}.", 
                              ephemeral=True)
                return
        
            target_index = target_chapter_num - 1  # Convert to 0-based
            await self.move_chapter(target_index=target_index)
            operation_desc = f"Chapter {target_chapter_num}"
        else:
            await ctx.send(content="Invalid option. Use 'next', 'previous', or enter a chapter number.", ephemeral=True)
            return

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        # Check if session was cleaned up (book completed)
        session_was_cleaned_up = not self.sessionID

        if self.found_next_chapter:
            await ctx.send(content=f"Moving to {operation_desc}: {self.newChapterTitle}", ephemeral=True)
            await ctx.voice_state.play(self.audioObj)
        elif session_was_cleaned_up:
            # Book completed or restarted - this is success, not failure
            await ctx.send(content="📚 Book completed!", ephemeral=True)
        else:
            # Actual navigation failure
            await ctx.send(content=f"Cannot navigate to {operation_desc}.", ephemeral=True)

        # Reset variable
        self.found_next_chapter = False

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
            await ctx.send(content="Stopping playback.", ephemeral=True)
            await self.cleanup_session("manual stop command")
        else:
            await ctx.send(content="Not connected to voice.", ephemeral=True)

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
            await ctx.send(embed=embed_message, components=self.get_current_playback_buttons(), ephemeral=True)
        else:
            return await ctx.send("Bot not in voice channel or an error has occured. Please try again later!", ephemeral=True)

    @slash_command(name="toggle-series", description="Toggle automatic series progression on/off")
    async def toggle_series_mode(self, ctx: SlashContext):
        if not ctx.voice_state or self.play_state == 'stopped':
            await ctx.send("No active playback session found.", ephemeral=True)
            return
    
        self.seriesEnabled = not self.seriesEnabled
        status = "enabled" if self.seriesEnabled else "disabled"
    
        series_info = ""
        if self.currentSeries and self.seriesEnabled:
            current_pos = self.seriesIndex + 1 if self.seriesIndex is not None else "?"
            total_books = len(self.seriesList)
            series_info = f"\nCurrently playing book {current_pos}/{total_books} in '{self.currentSeries['name']}'"
    
        await ctx.send(f"Series auto-progression {status}.{series_info}", ephemeral=True)
        logger.info(f"Series mode {status} by {ctx.author}")

    @slash_command(name="series-info", description="Show information about the current series")
    async def series_info_command(self, ctx: SlashContext):
        if not ctx.voice_state or self.play_state == 'stopped':
            await ctx.send("No active playback session found.", ephemeral=True)
            return
    
        if not self.currentSeries:
            await ctx.send("Current book is not part of a series.", ephemeral=True)
            return
    
        series_name = self.currentSeries['name']
        current_book = self.seriesIndex + 1 if self.seriesIndex is not None else "?"
        total_books = len(self.seriesList)
        auto_progression = "enabled" if self.seriesEnabled else "disabled"
    
        # Get titles of previous and next books if available
        prev_book_info = ""
        next_book_info = ""
    
        if self.seriesIndex is not None:
            if self.seriesIndex > 0:
                prev_book_id = self.seriesList[self.seriesIndex - 1]
                try:
                    prev_details = await c.bookshelf_get_item_details(prev_book_id)
                    prev_title = prev_details.get('title', 'Unknown')
                    prev_book_info = f"**Previous:** {prev_title}\n"
                except:
                    prev_book_info = "**Previous:** Available\n"
        
            if self.seriesIndex < len(self.seriesList) - 1:
                next_book_id = self.seriesList[self.seriesIndex + 1]
                try:
                    next_details = await c.bookshelf_get_item_details(next_book_id)
                    next_title = next_details.get('title', 'Unknown')
                    next_book_info = f"**Next:** {next_title}\n"
                except:
                    next_book_info = "**Next:** Available\n"
    
        embed = Embed(
            title=f"📚 Series: {series_name}",
            description=f"Currently playing book {current_book} of {total_books}",
            color=ctx.author.accent_color
        )
    
        series_details = (
            f"**Current Book:** {self.bookTitle}\n"
            f"{prev_book_info}"
            f"{next_book_info}"
            f"**Auto-progression:** {auto_progression}"
        )
    
        embed.add_field(name="Series Information", value=series_details, inline=False)
    
        if self.cover_image:
            embed.add_image(self.cover_image)
    
        embed.footer = f"{s.bookshelf_traveller_footer} | Series Info"
    
        await ctx.send(embed=embed, ephemeral=True)

    @check(ownership_check)
    @slash_command(name="announce", description="Create a public announcement card for the current playback session")
    async def announce_playback(self, ctx: SlashContext):
        """
        Creates a public (non-ephemeral) playbook card to invite others to join the listening session.
        Available to bot owner and the user who started the current playback session.
        """
    
        # Check if bot owner OR session owner
        is_bot_owner = ctx.author.id in [ctx.bot.owner.id] + [owner.id for owner in ctx.bot.owners]
        is_session_owner = self.sessionOwner == ctx.author.username
    
        if not (is_bot_owner or is_session_owner):
            await ctx.send("Only the bot owner or the person who started this playback session can use this command.", ephemeral=True)
            return
    
        # Check if bot is in voice and playing
        if not ctx.voice_state or self.play_state == 'stopped':
            await ctx.send("No active playback session found. Start playing audio first.", ephemeral=True)
            return
    
        # Get current voice channel
        voice_channel = ctx.voice_state.channel
        if not voice_channel:
            await ctx.send("Unable to determine current voice channel.", ephemeral=True)
            return
    
        # Create the announcement embed
        embed_message = self.create_announcement_embed(voice_channel, ctx.guild.name)

        try:
            # Get detailed book information
            book_details = await c.bookshelf_get_item_details(self.bookItemID)
            author = book_details.get('author', 'Unknown Author')
            series = book_details.get('series', '')
            narrator = book_details.get('narrator', '')
        
            # Build announcement message
            announcement_parts = ["📢 **Now Playing:**"]
            announcement_parts.append(f"**{self.bookTitle}**")
        
            if series:
                announcement_parts.append(f"*{series}*")
        
            announcement_parts.append(f"by {author}")
        
            if narrator and narrator != 'Unknown Narrator':
                announcement_parts.append(f"Read by {narrator}")
        
            announcement_parts.append(f"\nJoin us in {voice_channel.mention}!")
        
            announcement_content = "\n".join(announcement_parts)
        
        except Exception as e:
            logger.error(f"Error getting book details for announcement: {e}")
            # Fallback to basic announcement
            announcement_content = f"📢 **Now Playing**\n**{self.bookTitle}**\nJoin us in {voice_channel.mention}!"
    
        self.announcement_message = await ctx.send(
            content=announcement_content,
            embed=embed_message,
            ephemeral=False
        )
    
        logger.info(f"Announce command used by {ctx.author} for book: {self.bookTitle}")

    def create_announcement_embed(self, voice_channel, guild_name):
        """Create the announcement embed with current playback info"""
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")
    
        # Calculate progress percentage
        progress_percentage = 0
        if self.bookDuration and self.bookDuration > 0:
            safe_current_time = min(self.currentTime, self.bookDuration)
            progress_percentage = (safe_current_time / self.bookDuration) * 100
            progress_percentage = round(progress_percentage, 1)
            progress_percentage = max(0, min(100, progress_percentage))
    
        # Format duration and current time
        formatted_duration = time_converter(self.bookDuration)
        formatted_current = time_converter(self.currentTime)

        # Dynamic status for title
        status_emoji = {
            'playing': '▶️',
            'paused': '⏸️',
            'stopped': '⏹️'
        }
        current_emoji = status_emoji.get(self.play_state, '🎧')

        # Create announcement embed
        embed_message = Embed(
            title=f"{current_emoji} {self.play_state.upper()}",
            description=f"**{self.bookTitle}**",
            color=0x3498db if self.play_state == 'playing' else (0xe67e22 if self.play_state == 'paused' else 0x95a5a6)
        )
    
        # Add playbook information
        playback_info = (
            f"**Status:** {self.play_state.title()}\n"
            f"**Progress:** {progress_percentage}%\n"
            f"**Chapter:** {self.currentChapterTitle}\n"
            f"**Current Time:** {formatted_current}\n"
            f"**Total Duration:** {formatted_duration}"
        )
        embed_message.add_field(name="📖 Playback Status", value=playback_info, inline=True)
    
        try:
            listener_count = len(voice_channel.voice_members) if voice_channel else 0
            channel_info = (
                f"**Channel:** {voice_channel.mention if voice_channel else 'Unknown'}\n"
                f"**Server:** {guild_name}\n"
                f"**Listeners:** {listener_count}\n"
                f"Click channel name above to join!"
            )
            embed_message.add_field(name="🔊 Channel Info", value=channel_info, inline=True)
        except Exception:
            channel_info = (
                f"**Channel:** Voice channel unavailable\n"
                f"**Server:** {guild_name}\n" 
                f"**Status:** Playback active"
            )
            embed_message.add_field(name="🔊 Channel Info", value=channel_info, inline=True)
    
        # Add cover image if available
        if self.cover_image:
            embed_message.add_image(self.cover_image)
    
        # Add footer
        embed_message.footer = f"Powered by Bookshelf Traveller 🕮 | {s.versionNumber}\nDisplay Last Updated: {formatted_time}"
    
        return embed_message

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

                # Add progress indicators
                choices, timed_out = await add_progress_indicators(choices)
                if timed_out:
                    logger.warning("Autocomplete progress check timed out for recent sessions")

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

                # Add progress indicators
                choices, timed_out = await add_progress_indicators(choices)
                if timed_out:
                    logger.warning("Autocomplete progress check timed out for search results")

                await ctx.send(choices=choices)
                logger.debug(f"Sending {len(choices)} autocomplete choices")

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)
                logger.error(f"Error in autocomplete: {e}")

    @change_chapter.autocomplete("option")
    async def chapter_option_autocomplete(self, ctx: AutocompleteContext):
        choices = [
            {"name": "next", "value": "next"}, 
            {"name": "previous", "value": "previous"}
        ]
    
        # Add chapter numbers if we have chapter data
        if hasattr(self, 'chapterArray') and self.chapterArray:
            chapter_count = len(self.chapterArray)
        
            # Add current chapter info if available
            current_chapter_info = ""
            if hasattr(self, 'currentChapter') and self.currentChapter:
                try:
                    current_index = next((i for i, ch in enumerate(self.chapterArray) 
                                        if ch.get('id') == self.currentChapter.get('id')), None)
                    if current_index is not None:
                        current_chapter_info = f" (Currently: {current_index + 1})"
                except:
                    pass
        
            # Add some chapter number options
            choices.extend([
                {"name": f"Chapter 1 - {self.chapterArray[0].get('title', 'Unknown')[:30]}", "value": "1"},
            ])
        
            # Add middle chapter if book has many chapters
            if chapter_count > 10:
                mid_chapter = chapter_count // 2
                mid_title = self.chapterArray[mid_chapter - 1].get('title', 'Unknown')[:30]
                choices.append({"name": f"Chapter {mid_chapter} - {mid_title}", "value": str(mid_chapter)})
        
            # Add last chapter
            if chapter_count > 1:
                last_title = self.chapterArray[-1].get('title', 'Unknown')[:30]
                choices.append({"name": f"Chapter {chapter_count} - {last_title}", "value": str(chapter_count)})
            
            # Add info about total chapters
            choices.append({"name": f"📖 This book has {chapter_count} chapters{current_chapter_info}", "value": "info"})
        
        await ctx.send(choices=choices)

    # Series Functions ---------------------------

    async def get_series_info(self, item_id: str):
        """
        Fetch series information for a given book.
        Returns: (series_data, series_books_list) or (None, None) if not in series
        """
        try:
            # Get book details to find series info
            book_details = await c.bookshelf_get_item_details(item_id)
            series_info = book_details.get('series', '')
        
            if not series_info:
                logger.debug(f"Book {item_id} is not part of a series")
                return None, None
        
            # Extract series name from the formatted string "Series Name, Book X"
            series_name = series_info.split(',')[0].strip() if ',' in series_info else series_info
            logger.info(f"Searching for all books in series: '{series_name}'")

            series_id, library_id, books = await c.bookshelf_get_series_id(series_name)
    
            if not series_id:
                logger.warning(f"Could not find series ID for '{series_name}'")
                return None, None

            if not books:
                logger.warning(f"No books found in series '{series_name}'")
                return None, None

            # Process books into our format
            series_books = []
            for book in books:
                book_metadata = book.get('media', {}).get('metadata', {})
                book_series = book_metadata.get('series', [])

                # Find the sequence for this specific series
                sequence = 0
                for book_series_entry in book_series:
                    if book_series_entry.get('name', '').strip().lower() == series_name.lower():
                        try:
                            sequence = float(book_series_entry.get('sequence', '0'))
                        except (ValueError, TypeError):
                            sequence = 0
                        break

                book_item = {
                    'id': book.get('id'),
                    'title': book_metadata.get('title', ''),
                    'sequence': sequence,
                    'series_name': series_name
                }
            
                series_books.append(book_item)
                logger.debug(f"Added to series: {book_item['title']} (seq: {sequence})")
    
            # Sort books by sequence number
            series_books.sort(key=lambda x: x['sequence'])
    
            series_data = {
                'name': series_name,
                'total_books': len(series_books)
            }
    
            logger.info(f"Found series '{series_name}' with {len(series_books)} books")
            return series_data, series_books
    
        except Exception as e:
            logger.error(f"Error getting series info for {item_id}: {e}")
            return None, None

    async def setup_series_context(self, item_id: str):
        """Setup series information for the current book"""
        series_data, series_books = await self.get_series_info(item_id)
    
        if series_data and series_books:
            self.currentSeries = series_data
            self.seriesList = [book['id'] for book in series_books]
        
            # Find current book's position in series
            try:
                self.seriesIndex = self.seriesList.index(item_id)
                self.isFirstBookInSeries = self.seriesIndex == 0
                self.isLastBookInSeries = self.seriesIndex == len(self.seriesList) - 1
            
                logger.info(f"Book {self.seriesIndex + 1}/{len(self.seriesList)} in series '{series_data['name']}'")
                return True
            except ValueError:
                logger.warning(f"Current book {item_id} not found in series list")
                return False
        else:
            # Reset series context if book is not in a series
            self.currentSeries = None
            self.seriesList = []
            self.seriesIndex = None
            self.isFirstBookInSeries = False
            self.isLastBookInSeries = False
            return False

    async def move_to_series_book(self, direction: str):
        """
        Move to the next or previous book in the series
    
        Args:
            direction: "next" or "previous"
    
        Returns:
            bool: True if successful, False if failed or at series boundary
        """
        if not self.seriesList or self.seriesIndex is None:
            logger.warning(f"No series context available for {direction} book")
            return False
    
        # Calculate new index based on direction
        if direction == "next":
            if self.seriesIndex >= len(self.seriesList) - 1:
                logger.info("Already at the last book in series")
                return False
            new_index = self.seriesIndex + 1
            target_book_id = self.seriesList[new_index]

            # Check if the target book is finished - if so, start from beginning
            # Otherwise, let build_session respect the server's current position
            try:
                progress_data = await c.bookshelf_item_progress(target_book_id)
                is_finished = progress_data.get('finished', 'False') == 'True'
            
                if is_finished:
                    start_time = 0.0
                    logger.info(f"Target book {target_book_id} is finished - starting from beginning")
                else:
                    start_time = None  # Let build_session use server's current position
                    logger.info(f"Target book {target_book_id} not finished - will respect server position")
                
            except Exception as e:
                logger.warning(f"Error checking next book progress, defaulting to server position: {e}")
                start_time = None  # Let build_session decide

        elif direction == "previous":
            if self.seriesIndex <= 0:
                logger.info("Already at the first book in series")
                return False
            new_index = self.seriesIndex - 1
            target_book_id = self.seriesList[new_index]

            # Check if the target book is finished - if so, start from beginning
            # Otherwise, let build_session respect the server's current position
            try:
                progress_data = await c.bookshelf_item_progress(target_book_id)
                is_finished = progress_data.get('finished', 'False') == 'True'
            
                if is_finished:
                    start_time = 0.0
                    logger.info(f"Target book {target_book_id} is finished - starting from beginning")
                elif target_book_id == self.previousBookID and self.previousBookTime:
                    start_time = self.previousBookTime
                    logger.info(f"Resuming previous book at {start_time}s")
                else:
                    start_time = 0.0
                    logger.info(f"No stored progress for previous book - starting from beginning")
                
            except Exception as e:
                logger.warning(f"Error checking book progress, defaulting to beginning: {e}")
                start_time = 0.0

        else:
            logger.error(f"Invalid direction: {direction}")
            return False
    
        # Store current book info as previous (for next moves)
        if direction == "next":
            self.previousBookID = self.bookItemID
            self.previousBookTime = self.currentTime
    
        target_book_id = self.seriesList[new_index]
        logger.info(f"Moving to {direction} book in series: {target_book_id}")
    
        try:
            # Stop current session
            if self.session_update.running:
                self.session_update.stop()
            await c.bookshelf_close_session(self.sessionID)
        
            # Build session for target book
            audio, currentTime, sessionID, bookTitle, bookDuration = await self.build_session(
                item_id=target_book_id,
                start_time=start_time
            )
        
            # Update series position
            self.seriesIndex = new_index
            self.isFirstBookInSeries = self.seriesIndex == 0
            self.isLastBookInSeries = self.seriesIndex == len(self.seriesList) - 1
        
            # Update audio state
            self.audioObj = audio
            self.currentTime = currentTime
            self.bookItemID = target_book_id
            self.bookTitle = bookTitle
            self.bookDuration = bookDuration
            self.play_state = 'playing'
            self.nextTime = None
        
            # Set up chapter info for target book
            current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(target_book_id, start_time)
            self.currentChapter = current_chapter
            self.chapterArray = chapter_array

            if current_chapter and chapter_array and len(chapter_array) > 0:
                self.currentChapterTitle = current_chapter.get('title', 'Chapter 1')
            else:
                self.currentChapterTitle = 'No Chapters'

            self.isPodcast = isPodcast
            self.bookFinished = False
        
            # Update cover image
            self.cover_image = await c.bookshelf_cover_image(target_book_id)
        
            self.session_update.start()
            return True
        
        except Exception as e:
            logger.error(f"Error moving to {direction} book in series: {e}")
            return False


    # Component Callbacks ---------------------------
    def get_current_playback_buttons(self):
        """Get the current playback buttons based on current state"""
        has_chapters = bool(
            self.currentChapter and 
            self.chapterArray and 
            len(self.chapterArray) > 1 and
            not self.isPodcast
        )

        # Check if current book is part of a series
        is_series = bool(self.currentSeries and len(self.seriesList) > 1)

        return get_playback_rows(
            play_state=self.play_state,
            repeat_enabled=self.repeat_enabled,
            has_chapters=has_chapters,
            is_podcast=self.isPodcast,
            is_series=is_series,
            is_first_book=self.isFirstBookInSeries,
            is_last_book=self.isLastBookInSeries
        )

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
            await ctx.edit_origin(content="Play", components=self.get_current_playback_buttons(), embed=embed_message)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            await ctx.edit_origin(components=self.get_current_playback_buttons(), embed=embed_message)

    @component_callback('repeat_button')
    async def callback_repeat_button(self, ctx: ComponentContext):
        """Toggle repeat mode on/off"""
        self.repeat_enabled = not self.repeat_enabled

        embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
        await ctx.edit_origin(embed=embed_message, components=self.get_current_playback_buttons())

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
            await ctx.edit_origin(components=self.get_current_playback_buttons())

            # Stop current playback
            ctx.voice_state.channel.voice_state.player.stop()

            # Check if we're on the last chapter before moving
            current_index = next((i for i, ch in enumerate(self.chapterArray) 
                                if ch.get('id') == self.currentChapter.get('id')), 0)
            is_last_chapter = current_index >= len(self.chapterArray) - 1

            await self.move_chapter(relative_move=1)

            # Check if session was cleaned up (book completed)
            session_was_cleaned_up = not self.sessionID

            if self.found_next_chapter:
                # Normal successful navigation or restart
                chapter_title = self.newChapterTitle if self.newChapterTitle else self.currentChapterTitle
                embed_message = self.modified_message(color=ctx.author.accent_color, chapter=chapter_title)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                await ctx.edit(embed=embed_message, components=self.get_current_playback_buttons())
                await ctx.voice_state.channel.voice_state.play(self.audioObj)

            elif session_was_cleaned_up and is_last_chapter:
                # Book completed - this is expected, not an error
                await ctx.edit_origin(content="📚 Book completed!")
                # Don't show any error message - this is successful completion
            
            else:
                # Actual navigation failure (not book completion)
                await ctx.send(content="Failed to navigate to next chapter.", ephemeral=True)
                # Restart playback since we stopped it
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Reset variable
            self.found_next_chapter = False
            self.newChapterTitle = ''  # Clear after use
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to previous chapter!')

            if not self.currentChapter or not self.chapterArray:
                logger.warning("No chapter data available for this book. Cannot navigate chapters.")
                await ctx.send(content="This book doesn't have chapter information. Chapter navigation is not available.", 
                              ephemeral=True)
                return  # Return early without stopping playback

            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=self.get_current_playback_buttons())
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=self.get_current_playback_buttons())
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous chapter command, bot not active or voice not connected!', ephemeral=True)
                return

            # Find previous chapter
            await self.move_chapter(relative_move=-1)

            # Check if move_chapter succeeded before proceeding
            if self.found_next_chapter:
                embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                await ctx.edit(embed=embed_message, components=self.get_current_playback_buttons())
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                # Previous chapter navigation failure is always an actual error
                # (since going before first chapter just goes to first chapter)
                await ctx.send(content="Failed to navigate to previous chapter.", ephemeral=True)
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('stop_audio_button')
    async def callback_stop_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            await ctx.edit_origin()
            await ctx.delete()
            await self.cleanup_session("manual stop button")

    @component_callback('next_book_button')
    async def callback_next_book_button(self, ctx: ComponentContext):
        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return
    
        if not self.currentSeries:
            await ctx.send(content="Current book is not part of a series.", ephemeral=True)
            return
    
        await ctx.defer(edit_origin=True)
    
        # Stop current playback
        if self.play_state == 'playing':
            ctx.voice_state.channel.voice_state.player.stop()
    
        # Store current position before moving
        self.previousBookID = self.bookItemID
        self.previousBookTime = self.currentTime
    
        # Move to next book
        success = await self.move_to_series_book("next")
    
        if success:
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
        
            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()
        
            await ctx.edit_origin(embed=embed_message, components=self.get_current_playback_buttons())
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to next book in series.", ephemeral=True)

    @component_callback('previous_book_button')
    async def callback_previous_book_button(self, ctx: ComponentContext):
        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return
    
        if not self.currentSeries:
            await ctx.send(content="Current book is not part of a series.", ephemeral=True)
            return
    
        await ctx.defer(edit_origin=True)
    
        # Stop current playback
        if self.play_state == 'playing':
            ctx.voice_state.channel.voice_state.player.stop()
    
        # Move to previous book
        success = await self.move_to_series_book("previous")
    
        if success:
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
        
            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()
        
            await ctx.edit_origin(embed=embed_message, components=self.get_current_playback_buttons())
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to previous book in series.", ephemeral=True)

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

    async def shared_seek_callback(self, ctx: ComponentContext, seek_amount: float, is_forward: bool):
        """
        Shared logic for all seek component callbacks.
    
        Parameters:
        - ctx: ComponentContext from the button callback
        - seek_amount: Number of seconds to seek (positive value)
        - is_forward: True for forward seeking, False for rewinding
        """
        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return

        await ctx.defer(edit_origin=True)
        ctx.voice_state.channel.voice_state.player.stop()

        # Use the unified method for seeking
        result = await self.shared_seek(seek_amount, is_forward=is_forward)

        if result is None:  # Book completed
            await ctx.edit_origin(content="📚 Book completed!")
            return

        # Update the embedded message with new info
        embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin(embed=embed_message)
        await ctx.voice_state.channel.voice_state.play(self.audioObj)

    @component_callback('forward_button')
    async def callback_forward_button(self, ctx: ComponentContext):
        """30-second forward seek"""
        await self.shared_seek_callback(ctx, 30.0, is_forward=True)

    @component_callback('rewind_button')
    async def callback_rewind_button(self, ctx: ComponentContext):
        """30-second rewind seek"""
        await self.shared_seek_callback(ctx, 30.0, is_forward=False)

    @component_callback('forward_button_large')
    async def callback_forward_button_large(self, ctx: ComponentContext):
        """5-minute forward seek"""
        await self.shared_seek_callback(ctx, 300.0, is_forward=True)

    @component_callback('rewind_button_large')
    async def callback_rewind_button_large(self, ctx: ComponentContext):
        """5-minute rewind seek"""
        await self.shared_seek_callback(ctx, 300.0, is_forward=False)

    async def shared_seek(self, seek_amount, is_forward=True):
        """
        Move playback forward or backward with chapter boundary awareness.

        Parameters:
        - seek_amount: Number of seconds to seek (positive value)
        - is_forward: True for forward seeking, False for rewinding

        Returns audio object ready for playback.
        """
        # Stop current playback and session
        self.session_update.stop()
        await c.bookshelf_close_session(self.sessionID)

        # Use our current tracked position as the baseline for seeking
        current_time = self.currentTime

        # Format timestamps for better readability in logs
        def format_time(seconds):
            minutes = int(seconds) // 60
            secs = int(seconds) % 60
            return f"{minutes}m {secs}s ({seconds:.2f}s)"

        if self.currentTime is None:
            raise RuntimeError("shared_seek called with currentTime=None")

        if self.currentChapter is None or self.chapterArray is None:
            # No chapter data, perform simple seek
            logger.warning("No chapter metadata, falling back to simple seek.")

            if is_forward:
                potential_time = self.currentTime + seek_amount
                if potential_time >= self.bookDuration:
                    if self.repeat_enabled:
                        logger.info("Seeked past book end (no chapters, repeat enabled) - restarting book")
                    
                        # Handle restart directly
                        restart_success = await self.restart_media_from_beginning()
                        if restart_success:
                            # Send manual session sync
                            try:
                                updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                                    item_id=self.bookItemID, 
                                    session_id=self.sessionID,
                                    current_time=updateFrequency - 0.5, 
                                    next_time=0.0)  # Explicitly sync to beginning
                        
                                self.currentTime = updatedTime  # Should be 0.0
                                self.nextTime = None
                                logger.info(f"Manual sync after restart: {updatedTime}")
                            except Exception as e:
                                logger.error(f"Error syncing restart position: {e}")

                            # Restart the session update task
                            self.session_update.start()
                            return self.audioObj
                        else:
                            logger.error("Restart failed during seek")
                            await self.cleanup_session("restart failed")
                            return None

                    elif self.seriesEnabled and self.currentSeries and not self.isLastBookInSeries:
                        logger.info("Seeked past book end (with chapters) - moving to next book in series")
            
                        if self.session_update.running:
                            self.session_update.stop()
            
                        success = await self.move_to_series_book("next")
                        if success:
                            self.session_update.start()
                            return self.audioObj
                        else:
                            logger.error("Failed to move to next book in series during seek")
                            await self.cleanup_session("series progression failed")
                            return None

                    else:
                        logger.info("Seeked past book end (no chapters, no repeat) - marking complete and cleaning up")
                        await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID)
                        await self.cleanup_session("completed via seek past end")
                        return None
        
                self.nextTime = self.currentTime + seek_amount
            else:
                self.nextTime = max(0.0, self.currentTime - seek_amount)

        else:
           # Chapter data is available
            current_chapter = self.currentChapter
            current_index = next((i for i, ch in enumerate(self.chapterArray) if ch.get('id') == current_chapter.get('id')), None)
            prev_chapter = self.chapterArray[current_index - 1] if current_index is not None and current_index > 0 else None
            next_chapter = self.chapterArray[current_index + 1] if current_index is not None and current_index < len(self.chapterArray) - 1 else None

            chapter_start = float(current_chapter.get("start", 0.0))
            time_from_chapter_start = self.currentTime - chapter_start

            if is_forward:
                if next_chapter and (chapter_start + seek_amount) > float(next_chapter.get("start", 0.0)):
                    self.nextTime = float(next_chapter.get("start", 0.0))
                    self.currentChapter = next_chapter
                    self.currentChapterTitle = next_chapter.get("title", "Unknown Chapter")
                    logger.debug("Forward: crossing into next chapter")
                else:
                    # Check if seeking would go past book end BEFORE setting nextTime
                    potential_time = self.currentTime + seek_amount
                    if potential_time >= self.bookDuration:
                        if self.repeat_enabled:
                            logger.info("Seeked past book end (with chapters, repeat enabled) - restarting book")
                    
                            # Handle restart directly
                            restart_success = await self.restart_media_from_beginning()
                            if restart_success:
                                try:
                                    updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                                        item_id=self.bookItemID, 
                                        session_id=self.sessionID,
                                        current_time=updateFrequency - 0.5, 
                                        next_time=0.0)
                            
                                    self.currentTime = updatedTime
                                    self.nextTime = None
                                    logger.info(f"Manual sync after restart (no chapters): {updatedTime}")
                                except Exception as e:
                                    logger.error(f"Error syncing restart position: {e}")

                                # Restart the session update task
                                self.session_update.start()
                                return self.audioObj
                            else:
                                logger.error("Restart failed during seek")
                                await self.cleanup_session("restart failed")
                                return None

                        elif self.seriesEnabled and self.currentSeries and not self.isLastBookInSeries:
                            logger.info("Seeked past book end (with chapters) - moving to next book in series")
            
                            if self.session_update.running:
                                self.session_update.stop()
            
                            success = await self.move_to_series_book("next")
                            if success:
                                self.session_update.start()
                                return self.audioObj
                            else:
                                logger.error("Failed to move to next book in series during seek")
                                await self.cleanup_session("series progression failed")
                                return None

                        else:
                            logger.info("Seeked past book end (with chapters, no repeat) - marking complete and cleaning up")
                            await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID)
                            await self.cleanup_session("completed via seek past end")
                            return None
            
                    self.nextTime = min(self.bookDuration, self.currentTime + seek_amount)
                    logger.debug("Forward: simple time advance")
            else:
                # Backward seeking logic
                if time_from_chapter_start <= 5.0 and prev_chapter:
                    prev_start = float(prev_chapter.get("start", 0.0))
                    prev_end = chapter_start
                    back_time = seek_amount - time_from_chapter_start
                    self.nextTime = max(0.0, prev_end - back_time)
                    self.currentChapter = prev_chapter
                    self.currentChapterTitle = prev_chapter.get("title", "Unknown Chapter")
                    logger.debug("Rewind: jumping into previous chapter")
                elif time_from_chapter_start <= 30.0:
                    self.nextTime = max(0.0, chapter_start)
                    logger.debug("Rewind: returning to start of current chapter")
                else:
                    self.nextTime = max(0.0, self.currentTime - seek_amount)
                    logger.debug("Rewind: simple time rewind")

        # Update the current time to match where we're seeking
        self.currentTime = self.nextTime

        # Use unified session builder
        audio, actual_start_time, session_id, book_title, book_duration = await self.build_session(
            item_id=self.bookItemID,
            start_time=self.nextTime
        )

        # Send manual session sync
        await c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                    current_time=updateFrequency - 0.5, next_time=self.nextTime)

        # Do an explicit check to make sure we have the latest chapter info
        # This is especially important after moving across chapter boundaries
        if not self.isPodcast:
            try:
                current_chapter, _, _, _ = await c.bookshelf_get_current_chapter(
                    item_id=self.bookItemID, current_time=self.currentTime)

                if current_chapter:
                    self.currentChapter = current_chapter
                    self.currentChapterTitle = current_chapter.get('title', 'Unknown Chapter')
                    logger.info(f"Final chapter verification: {self.currentChapterTitle}")
            except Exception as e:
                logger.error(f"Error in final chapter verification: {e}")

        self.audioObj = audio
        self.nextTime = None

        self.session_update.start()
        return audio

    # ----------------------------
    # Other non discord related functions
    # ----------------------------
