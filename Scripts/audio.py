import asyncio
import os

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume

import bookshelfAPI as c
import settings as s
from settings import TIMEZONE
from ui_components import get_playback_rows, create_playback_embed
from utils import ownership_check, is_bot_owner, check_session_control, can_control_session, add_progress_indicators

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
        # ABS Variables
        self.cover_image = ''
        self.bookItemID = ''
        self.bookTitle = ''
        self.bookDuration = None
        self.bookFinished = False
        # User Variables
        self.username = ''
        self.user_type = ''
        self.current_channel = None
        self.active_guild_id = None
        # Session Variables
        self.sessionID = ''
        self.currentTime = 0.0
        self.nextTime = None
        self.activeSessions = 0
        self.stream_started = False
        self.sessionOwner = None
        self.announcement_message = None
        self.repeat_enabled = False
        self.needs_restart = False
        # Audio Variables
        self.audioObj = AudioVolume
        self.context_voice_channel = None
        self.current_playback_time = 0
        self.audio_context = None
        self.bitrate = 128000
        self.volume = 0.5
        self.placeholder = None
        self.playbackSpeed = 1.0
        self.updateFreqMulti = updateFrequency * self.playbackSpeed
        self.play_state = 'stopped'
        self.audio_message = None
        # Chapter Variables
        self.currentChapter = None
        self.chapterArray = None
        self.currentChapterTitle = ''
        self.newChapterTitle = ''
        self.found_next_chapter = False
        # Series Variables
        self.currentSeries = None  # Series metadata
        self.seriesAutoplay = True  # Auto-progression for book series
        self.seriesList = []  # List of book IDs in series order
        self.seriesIndex = None  # Current position in series
        self.previousBookID = None
        self.previousBookTime = None
        self.isLastBookInSeries = False
        self.isFirstBookInSeries = False
        self.seriesBookCache = {}
        # Podcast Variables
        self.isPodcast = False
        self.podcastAutoplay = True  # Auto-progression for podcast episodes
        self.podcastEpisodes = []
        self.currentEpisodeIndex = None
        self.totalEpisodes = 0
        self.isFirstEpisode = False
        self.isLastEpisode = False
        self.currentEpisodeTitle = ''

    # Tasks ---------------------------------

    async def build_session(self, item_id: str, start_time: float = None, force_restart: bool = False,
                            episode_index: int = 0):
        """
        Unified method to build audio session for any playback scenario.
    
        Parameters:
        - item_id: The library item ID to build session for
        - start_time: Optional time to start from (if None, uses server's current time)
        - force_restart: If True, starts from beginning regardless of server progress
        - episode_index: For podcasts, which episode to play (0 = newest)
    
        Returns:
        - Tuple: (audio_object, current_time, session_id, book_title, book_duration)
        """
        try:
            # Handle force restart by resetting server progress first
            if force_restart:
                try:
                    # First, check if this is a podcast by getting item details
                    item_details = await c.bookshelf_get_item_details(item_id)
                    media_type = item_details.get('mediaType', 'book')

                    if media_type == 'podcast':
                        # For podcasts, we need to get the episode list to find the episode ID
                        if hasattr(self, 'podcastEpisodes') and self.podcastEpisodes and episode_index < len(
                                self.podcastEpisodes):
                            # Use existing episode data if available
                            episode_id = self.podcastEpisodes[episode_index].get('id')
                        else:
                            # Get fresh episode data if not available
                            episodes = await c.bookshelf_get_podcast_episodes(item_id)
                            if episodes and episode_index < len(episodes):
                                episode_id = episodes[episode_index].get('id')
                            else:
                                logger.warning(f"Could not find episode at index {episode_index} for podcast {item_id}")
                                episode_id = None

                        if episode_id:
                            await c.bookshelf_mark_book_unfinished(item_id, episode_id)
                            logger.info(f"Reset server progress for podcast episode {episode_id}")
                        else:
                            logger.warning(
                                f"Could not determine episode ID for podcast restart, skipping unfinished marking")
                    else:
                        # For books, no episode ID needed
                        await c.bookshelf_mark_book_unfinished(item_id)
                        logger.info("Reset server progress to beginning for book restart")

                except Exception as e:
                    logger.warning(f"Failed to reset server progress for restart: {e}")

            # Get fresh audio object and session
            result = await c.bookshelf_audio_obj(item_id, episode_index)
            if not result:
                raise Exception("Failed to get audio object")

            if len(result) == 7:  # Podcast with episode info
                audio_obj, server_current_time, session_id, book_title, book_duration, episode_id, episode_info = result
                self.episodeInfo = episode_info
                self.episodeId = episode_id
            else:
                # Book
                audio_obj, server_current_time, session_id, book_title, book_duration, episode_id = result
                self.episodeInfo = None
                self.episodeId = None

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

            # Reset stream detection for each new session
            self.stream_started = False

            # Build audio object
            preserved_vol = self.volume if hasattr(self, 'volume') and self.volume is not None else 0.5
            audio = AudioVolume(audio_obj)
            audio.buffer_seconds = 1
            audio.locked_stream = True
            audio.ffmpeg_before_args = f"-re -ss {actual_start_time}"
            audio.ffmpeg_args = f""
            audio.bitrate = self.bitrate
            audio._volume = preserved_vol

            # Hook into the audio source to detect when streaming starts
            original_read = audio.read

            def stream_detecting_read(*args, **kwargs):
                data = original_read(*args, **kwargs)
                if data and not self.stream_started:
                    self.stream_started = True
                    logger.info("🎵 AUDIO STREAM DETECTED - FFmpeg is now providing data!")

                    # Apply volume when stream actually starts
                    logger.debug(f"🔧 Before backup: audio._volume = {audio._volume}")
                    audio._volume = preserved_vol
                    logger.debug(f"🔧 After backup: audio._volume = {audio._volume}")
                    logger.debug(f"Applied volume backup: {preserved_vol}")

                return data

            audio.read = stream_detecting_read

            self.volume = preserved_vol

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
                    next_time=self.nextTime,
                    episode_id=getattr(self, 'episodeId', None))

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


                            elif self.podcastAutoplay and self.isPodcast and not self.isLastEpisode:
                                logger.info("Episode completed - moving to next episode")

                                # Move to next episode
                                success = await self.move_to_podcast_episode(relative_move=1)
                                if success:
                                    logger.info("Successfully moved to next episode")
                                    return  # Continue with the new episode
                                else:
                                    logger.error("Failed to move to next episode")
                                    await self.cleanup_session("episode progression failed")
                                    return

                            elif self.seriesAutoplay and self.currentSeries and not self.isLastBookInSeries:
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
                            logger.info(
                                f"ABS marked book finished with {time_remaining:.1f}s remaining - letting stream finish naturally")
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
                    last_update = self._last_patch_timestamps.get(msg_id,
                                                                  now.replace(second=0, microsecond=0) - timedelta(
                                                                      seconds=10))

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
            self.repeat_enabled = False

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
            self.seriesList = []
            self.seriesIndex = None
            self.previousBookID = None
            self.previousBookTime = None
            self.currentSeries = None
            self.isLastBookInSeries = False
            self.isFirstBookInSeries = False
            self.seriesBookCache = {}

            # Reset podcast context
            self.podcastEpisodes = []
            self.currentEpisodeIndex = None
            self.totalEpisodes = 0
            self.isFirstEpisode = False
            self.isLastEpisode = False
            self.currentEpisodeTitle = ''
            self.episodeInfo = None

            # Reset audio variables
            self.volume = 0.5
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
            preserved_current_playback_time = self.current_playback_time

            # Preserve series variables
            preserved_series = self.currentSeries
            preserved_series_list = self.seriesList.copy()
            preserved_series_index = self.seriesIndex
            preserved_series_enabled = self.seriesAutoplay
            preserved_is_first = self.isFirstBookInSeries
            preserved_is_last = self.isLastBookInSeries

            # Preserve podcast variables
            preserved_is_podcast = self.isPodcast
            preserved_podcast_episodes = self.podcastEpisodes.copy() if self.podcastEpisodes else []
            preserved_current_episode_index = self.currentEpisodeIndex
            preserved_total_episodes = self.totalEpisodes
            preserved_is_first_episode = self.isFirstEpisode
            preserved_is_last_episode = self.isLastEpisode
            preserved_current_episode_title = self.currentEpisodeTitle
            preserved_podcast_autoplay = self.podcastAutoplay
            preserved_episode_info = getattr(self, 'episodeInfo', None)

            # Close current session
            current_session_id = self.sessionID
            if current_session_id:
                logger.info(f"Closing current session {current_session_id} before restart")
                await c.bookshelf_close_session(current_session_id)

            # Use unified session builder to create new session from beginning
            if preserved_is_podcast and preserved_current_episode_index is not None:
                # For podcasts, restart the current episode
                audio, actual_start_time, session_id, book_title, book_duration = await self.build_session(
                    item_id=preserved_book_id,
                    force_restart=True,
                    episode_index=preserved_current_episode_index
                )
            else:
                # For books, restart from beginning
                audio, actual_start_time, session_id, book_title, book_duration = await self.build_session(
                    item_id=preserved_book_id,
                    force_restart=True
                )

            logger.info(f"New session created: {session_id} (was: {current_session_id})")

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

            # Restore series variables
            self.currentSeries = preserved_series
            self.seriesList = preserved_series_list
            self.seriesIndex = preserved_series_index
            self.seriesAutoplay = preserved_series_enabled
            self.isFirstBookInSeries = preserved_is_first
            self.isLastBookInSeries = preserved_is_last

            # Restore podcast variables
            self.podcastEpisodes = preserved_podcast_episodes
            self.currentEpisodeIndex = preserved_current_episode_index
            self.totalEpisodes = preserved_total_episodes
            self.isFirstEpisode = preserved_is_first_episode
            self.isLastEpisode = preserved_is_last_episode
            self.currentEpisodeTitle = preserved_current_episode_title
            self.podcastAutoplay = preserved_podcast_autoplay
            if preserved_episode_info:
                self.episodeInfo = preserved_episode_info

            self.currentTime = 0.0

            # Set to first chapter if it's a book with chapters
            if not self.isPodcast and self.chapterArray and len(self.chapterArray) > 0:
                self.chapterArray.sort(key=lambda x: float(x.get('start', 0)))
                first_chapter = self.chapterArray[0]
                self.currentChapter = first_chapter
                self.currentChapterTitle = first_chapter.get('title', 'Chapter 1')
            elif self.isPodcast:
                # For podcasts, set the episode title
                if self.currentEpisodeIndex is not None and self.podcastEpisodes:
                    current_episode = self.podcastEpisodes[self.currentEpisodeIndex]
                    episode_number = current_episode.get('episode')
                    if episode_number is not None:
                        self.currentChapterTitle = f"Episode {episode_number}"
                    else:
                        if self.currentEpisodeIndex == 0:
                            self.currentChapterTitle = "Latest Episode"
                        else:
                            self.currentChapterTitle = f"Episode {self.currentEpisodeIndex + 1}"

            # Reset playback state
            self.play_state = 'playing'
            self.audioObj = audio

            # Apply preserved volume to new audio object
            audio.volume = preserved_volume

            logger.info(f"Successfully restarted media from beginning. New session: {self.sessionID}")
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

                elif self.seriesAutoplay and self.currentSeries and not self.isLastBookInSeries:
                    logger.info(
                        "Reached final chapter - moving to next book in series")  # Stop the session update task before moving to next book                                             if self.session_update.running:

                    # Stop the session update task before moving to next book
                    if self.session_update.running:
                        self.session_update.stop()

                    # Mark the book as complete
                    try:
                        await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID)
                        logger.info(f"Successfully marked book {self.bookItemID} as finished before series progression")
                    except Exception as e:
                        logger.warning(f"Failed to mark book as finished before series progression: {e}")

                    success = await self.move_to_series_book(
                        "next")  # Move to next book in series                                                                         success = await self.move_to_next_book_in_series()
                    if success:
                        # Set the chapter info for the UI callback to use
                        self.newChapterTitle = self.currentChapterTitle
                        self.found_next_chapter = True

                        if self.seriesIndex is not None:
                            self.isFirstBookInSeries = self.seriesIndex == 0
                            self.isLastBookInSeries = self.seriesIndex == len(self.seriesList) - 1
                            logger.info(
                                f"Updated series position: book {self.seriesIndex + 1}/{len(self.seriesList)}, first={self.isFirstBookInSeries}, last={self.isLastBookInSeries}")

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
                        logger.warning(
                            f"Chapter title mismatch! Local: {self.currentChapterTitle}, Server: {verified_title}")
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

        # Prepare series/episode info if available
        series_info = None
        if self.isPodcast and hasattr(self, 'currentEpisodeIndex') and self.currentEpisodeIndex is not None:
            # Get actual episode number if available
            current_episode = self.podcastEpisodes[self.currentEpisodeIndex]
            episode_number = current_episode.get('episode')

            # Position in chronological order (1 = newest, 2 = second newest, etc.)
            position_in_list = self.currentEpisodeIndex + 1

            if episode_number is not None:
                try:
                    # Use actual episode number with chronological position
                    episode_display = f"Episode {episode_number} ({position_in_list} of {self.totalEpisodes})"
                except (ValueError, TypeError):
                    # Fallback to position-based
                    episode_display = f"Episode {position_in_list} ({position_in_list} of {self.totalEpisodes})"
            else:
                # No episode number available, use position-based with context
                if self.currentEpisodeIndex == 0:
                    episode_display = f"Latest Episode (1 of {self.totalEpisodes})"
                else:
                    episode_display = f"Episode {position_in_list} ({position_in_list} of {self.totalEpisodes})"

            series_info = {
                'name': episode_display,
                'current': self.currentEpisodeIndex + 1,
                'total': self.totalEpisodes
            }
        elif self.currentSeries and self.seriesIndex is not None:
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
            series_info=series_info,
            is_podcast=self.isPodcast
        )

    # Audio Core Functions
    async def _play_audio_core(self, ctx, book, startover=False, episode=1):
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
            # First, determine if this is a podcast or book
            item_details = await c.bookshelf_get_item_details(book)
            media_type = item_details.get('mediaType', 'book')

            # Proceed with the normal playback flow using the book ID
            current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                item_id=book)

            if current_chapter is None and not isPodcast:
                await ctx.send(content="Error retrieving chapter information. The item may be invalid or inaccessible.",
                               ephemeral=True)
                return

            if bookFinished and not startover:
                await ctx.send(
                    content="This book is marked as finished. Use the `startover: True` option to play it from the beginning.",
                    ephemeral=True)
                return

            if self.activeSessions >= 1:
                await ctx.send(
                    content=f"Bot can only play one session at a time, please stop your other active session and try again! Current session owner: {self.sessionOwner}",
                    ephemeral=True)
                return

            # Handle episode selection for podcasts
            episode_index = 0  # Default to newest episode
            if isPodcast and episode > 1:
                episode_index = episode - 1  # Convert 1-based to 0-based

            # Use unified session builder
            audio, currentTime, sessionID, bookTitle, bookDuration = await self.build_session(
                item_id=book,
                # if True, start time will be zero
                force_restart=startover,
                episode_index=episode_index
            )

            self.currentTime = currentTime
            self.isPodcast = isPodcast

            # Setup context based on media type
            if isPodcast:
                await self.setup_podcast_context(book, episode_index)
                # Clear chapter variables for podcasts
                self.currentChapter = None
                self.chapterArray = None
                self.currentChapterTitle = 'No Chapters'
            else:
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
            self.chapterArray = chapter_array
            self.bookFinished = False  # Force locally to False. If it were True, it would've exited sooner. Startover needs this to be False.
            self.current_channel = ctx.channel_id
            self.play_state = 'playing'

            if self.currentTime is None:
                logger.warning(f"currentTime is None after build_session, using 0.0 as fallback")
                self.currentTime = 0.0

            # Create embedded message
            display_chapter = self.currentChapterTitle
            if isPodcast:
                current_episode = self.podcastEpisodes[self.currentEpisodeIndex]
                episode_number = current_episode.get('episode')
                position_in_list = self.currentEpisodeIndex + 1

                if episode_number is not None:
                    display_chapter = f"Episode {episode_number}"
                else:
                    if self.currentEpisodeIndex == 0:
                        display_chapter = "Latest Episode"
                    else:
                        display_chapter = f"Episode {position_in_list}"
            else:
                display_chapter = self.currentChapterTitle

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=display_chapter)

            # check if bot currently connected to voice
            if not ctx.voice_state:
                # if we haven't already joined a voice channel
                try:
                    # Connect to voice channel and start task
                    await ctx.author.voice.channel.connect()
                    self.session_update.start()

                    # Customize message based on media type and options
                    if isPodcast:
                        episode_num = episode_index + 1
                        total_eps = self.totalEpisodes
                        start_message = f"🎙️ Starting podcast episode {episode_num}/{total_eps}: **{bookTitle}**"
                    else:
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

                    logger.info(
                        f"Created audio message with ID: {self.audio_message.id} in channel: {self.audio_message.channel.id}")
                    # Store reference to voice channel for updates
                    self.context_voice_channel = ctx.author.voice.channel

                    logger.info(f"Beginning audio stream" + (" from the beginning" if startover else ""))

                    self.activeSessions += 1

                    # Set appropriate presence
                    if isPodcast:
                        await self.client.change_presence(activity=Activity.create(name=f"🎙️ {self.bookTitle}",
                                                                                   type=ActivityType.LISTENING))
                    else:
                        await self.client.change_presence(activity=Activity.create(name=f"{self.bookTitle}",
                                                                                   type=ActivityType.LISTENING))

                    # Start audio playback
                    await ctx.voice_state.play(audio)

                except Exception as e:
                    # Stop Any Associated Tasks
                    if self.session_update.running:
                        self.session_update.stop()
                    # Close ABS session
                    await c.bookshelf_close_session(sessionID)
                    # Cleanup discord interactions
                    if ctx.voice_state:
                        await ctx.author.voice.channel.disconnect()
                    if audio:
                        audio.cleanup()
                    self.audio_message = None
                    self.announcement_message = None
                    self.context_voice_channel = None

                    logger.error(f"Error starting playback: {e}")
                    await ctx.send(content=f"Error starting playback: {str(e)}")

        except Exception as e:
            logger.error(f"Unhandled error in play_audio: {e}")
            await ctx.send(content=f"An error occurred while trying to play this content: {str(e)}", ephemeral=True)

    # Commands --------------------------------

    # Main play command, place class variables here since this is required to play audio
    @slash_command(name="play", description="Play audio from AudiobookShelf", dm_permission=False)
    @slash_option(name="book", description="Enter a book title or 'random' for a surprise", required=True,
                  opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="startover",
                  description="Start the book from the beginning instead of resuming",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="episode",
                  description="For podcasts: episode number to play (1 = newest, 2 = second newest, etc.)",
                  opt_type=OptionType.INTEGER,
                  min_value=1)
    @check_session_control("start")
    async def play_audio(self, ctx: SlashContext, book: str, startover=False, episode=1):
        await self._play_audio_core(ctx, book, startover, episode)

    # Pause audio, stops tasks, keeps session active.
    @slash_command(name="pause", description="pause audio", dm_permission=False)
    @check_session_control()
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
    @check_session_control()
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

    @slash_command(name="change-chapter", description="Navigate to a specific chapter or use next/previous.",
                   dm_permission=False)
    @slash_option(name="option", description="Select 'next', 'previous', or enter a chapter number",
                  opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    @check_session_control()
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

    @slash_command(name="volume", description="change the volume for the bot", dm_permission=False)
    @slash_option(name="volume", description="Must be between 1 and 100", required=False, opt_type=OptionType.INTEGER)
    @check_session_control()
    async def volume_adjuster(self, ctx, volume=-1):
        if ctx.voice_state:
            audio = self.audioObj

            if volume == -1:
                status = "muted" if self.volume == 0 else f"{self.volume * 100}%"
                await ctx.send(content=f"Volume currently set to: {status}", ephemeral=True)
            elif 0 <= volume <= 100:
                volume_float = float(volume / 100)
                audio.volume = volume_float
                self.volume = audio.volume
                status = "muted" if volume == 0 else f"{volume}%"
                await ctx.send(content=f"Volume set to: {status}", ephemeral=True)
            else:
                await ctx.send(content=f"Invalid Entry", ephemeral=True)
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.",
                   dm_permission=False)
    @check_session_control()
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
            logger.info(f"executing command /stop")
            await ctx.send(content="Stopping playback.", ephemeral=True)
            await self.cleanup_session("manual stop command")
        else:
            await ctx.send(content="Not connected to voice.", ephemeral=True)

    @slash_command(name="close-all-sessions",
                   description="DEBUGGING PURPOSES, close all active ABS sessions. Takes up to 60 seconds.",
                   dm_permission=False)
    @slash_option(name="max_items", description="max number of items to attempt to close, default=100",
                  opt_type=OptionType.INTEGER)
    @check(is_bot_owner)
    async def close_active_sessions(self, ctx, max_items=50):
        # Wait for task to complete
        await ctx.defer()

        # Add warning if there's active playback
        if self.activeSessions > 0 and self.sessionID:
            await ctx.send(
                "⚠️ **WARNING**: You have active audio playback running. "
                "This command will close the ABS session, which means:\n"
                "• Audio will continue playing but won't sync progress\n"
                "• You should use `/stop` to properly end playback first\n\n"
                "Proceeding with session cleanup...",
                ephemeral=True
            )

        openSessionCount, closedSessionCount, failedSessionCount = await c.bookshelf_close_all_sessions(max_items)

        await ctx.send(content=f"Result of attempting to close sessions. success: {closedSessionCount}, "
                               f"failed: {failedSessionCount}, total: {openSessionCount}", ephemeral=True)

    @slash_command(name='refresh', description='re-sends your current playback card.')
    @check_session_control()
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
            return await ctx.send("Bot not in voice channel or an error has occured. Please try again later!",
                                  ephemeral=True)

    @slash_command(name="toggle-series-autoplay", description="Toggle automatic series progression on/off")
    @check_session_control()
    async def toggle_series_autoplay(self, ctx: SlashContext):
        if not ctx.voice_state or self.play_state == 'stopped':
            await ctx.send("No active playback session found.", ephemeral=True)
            return

        if self.isPodcast:
            await ctx.send("This command is for book series. Use `/toggle-podcast-autoplay` for podcasts.",
                           ephemeral=True)
            return

        if not self.currentSeries:
            await ctx.send("Current book is not part of a series.", ephemeral=True)
            return

        self.seriesAutoplay = not self.seriesAutoplay
        status = "enabled" if self.seriesAutoplay else "disabled"

        series_info = ""
        if self.currentSeries and self.seriesAutoplay:
            current_pos = self.seriesIndex + 1 if self.seriesIndex is not None else "?"
            total_books = len(self.seriesList)
            series_info = f"\nCurrently playing book {current_pos}/{total_books} in '{self.currentSeries['name']}'"

        await ctx.send(f"Series auto-progression {status}.{series_info}", ephemeral=True)

    @slash_command(name="toggle-podcast-autoplay", description="Toggle automatic podcast episode progression on/off")
    @check_session_control()
    async def toggle_podcast_autoplay(self, ctx: SlashContext):
        if not ctx.voice_state or self.play_state == 'stopped':
            await ctx.send("No active playback session found.", ephemeral=True)
            return

        if not self.isPodcast:
            await ctx.send("This command is for podcasts. Use `/toggle-series-autoplay` for book series.",
                           ephemeral=True)
            return

        self.podcastAutoplay = not self.podcastAutoplay
        status = "enabled" if self.podcastAutoplay else "disabled"

        episode_info = ""
        if self.podcastAutoplay and self.podcastEpisodes:
            current_pos = self.currentEpisodeIndex + 1 if self.currentEpisodeIndex is not None else "?"
            total_episodes = len(self.podcastEpisodes)
            episode_info = f"\nCurrently playing episode {current_pos}/{total_episodes}"

        await ctx.send(f"Podcast auto-progression {status}.{episode_info}", ephemeral=True)

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
        auto_progression = "enabled" if self.seriesAutoplay else "disabled"

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

    @slash_command(name="announce", description="Create a public announcement card for the current playback session")
    @check_session_control("announce")
    async def announce_playback(self, ctx: SlashContext):
        """
        Creates a public (non-ephemeral) playbook card to invite others to join the listening session.
        Available to bot owner and the user who started the current playback session.
        """
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
            # Get detailed information
            item_details = await c.bookshelf_get_item_details(self.bookItemID)
            logger.info(f"Item details for announcement: {item_details}")

            # Build announcement message
            announcement_parts = ["📢 **Now Playing:**"]
            announcement_parts.append(f"**{self.bookTitle}**")

            if self.isPodcast:
                # For podcasts, get podcast title and author
                podcast_author = item_details.get('author', 'Unknown Podcast Host')
                logger.info(f"Podcast author from item_details: '{podcast_author}'")

                # Get the actual podcast title (not episode title)
                podcast_endpoint = f"/items/{self.bookItemID}"
                podcast_response = await c.bookshelf_conn(GET=True, endpoint=podcast_endpoint)
                if podcast_response.status_code == 200:
                    podcast_data = podcast_response.json()
                    podcast_title = podcast_data['media']['metadata'].get('title', 'Unknown Podcast')
                    announcement_parts.append(f"*from {podcast_title}*")

                if podcast_author and podcast_author != 'Unknown Podcast Host':
                    announcement_parts.append(f"hosted by {podcast_author}")
            else:
                # Get detailed book information
                author = item_details.get('author', 'Unknown Author')
                series = item_details.get('series', '')
                narrator = item_details.get('narrator', '')

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

        # Get proper chapter/episode display
        if self.isPodcast:
            current_episode = self.podcastEpisodes[self.currentEpisodeIndex]
            episode_number = current_episode.get('episode')
            position_in_list = self.currentEpisodeIndex + 1

            if episode_number is not None:
                chapter_display = f"Episode {episode_number}"
            else:
                if self.currentEpisodeIndex == 0:
                    chapter_display = "Latest Episode"
                else:
                    chapter_display = f"Episode {position_in_list}"
        else:
            chapter_display = self.currentChapterTitle

        # Add playbook information
        playback_info = (
            f"**Status:** {self.play_state.title()}\n"
            f"**Progress:** {progress_percentage}%\n"
            f"**{'Episode' if self.isPodcast else 'Chapter'}:** {chapter_display}\n"
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
                        episodeID = session.get('episodeId')
                        itemID = session.get('libraryItemId')
                        mediaType = session.get('mediaType')

                        should_skip = False

                        if mediaType == 'book':
                            if not itemID or not bookID:
                                logger.info(f"Skipping book session with missing itemID or bookID")
                                should_skip = True
                        elif mediaType == 'podcast':
                            if not itemID or not episodeID:
                                logger.info(f"Skipping podcast session with missing itemID or episodeID")
                                should_skip = True
                        else:
                            logger.info(f"Skipping session with unknown mediaType: {mediaType}")
                            should_skip = True

                        if should_skip:
                            skipped_session_count += 1
                            continue

                        # Extract metadata
                        mediaMetadata = session.get('mediaMetadata', {})
                        title = session.get('displayTitle')
                        subtitle = mediaMetadata.get('subtitle', '')
                        display_author = session.get('displayAuthor')

                        logger.debug(
                            f"Recent session: title='{title}', mediaType='{mediaType}', episodeID='{episodeID}', itemID='{itemID}'")

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

                        # Add media type indicator to the name for podcasts
                        if mediaType == 'podcast':
                            title = f"🎙️ {title}"  # Add podcast emoji

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

                        # Check if this is a podcast episode (has episodeId structure)
                        episode_id = session.get('episodeId')

                        if episode_id:
                            # Use the full library item ID for podcasts
                            formatted_item = {"name": name, "value": itemID}
                        else:
                            # Regular book session
                            formatted_item = {"name": name, "value": itemID}

                        # Add to choices if not already there
                        formatted_item = {"name": name, "value": itemID}

                        # Add episode_id field for podcasts
                        mediaType = session.get('mediaType')
                        if mediaType == 'podcast':
                            episode_id = session.get('episodeId')
                            if episode_id:
                                formatted_item["episode_id"] = episode_id

                        # Check for duplicates
                        if formatted_item not in choices:
                            choices.append(formatted_item)
                            valid_session_count += 1

                    except Exception as e:
                        logger.info(f"Error processing recent session: {e}")
                        skipped_session_count += 1
                        continue

                logger.info(
                    f"Recent sessions processing complete - Valid: {valid_session_count}, Skipped: {skipped_session_count}")

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

                            book_dataset = data.get('book', [])
                            podcast_dataset = data.get('podcast', [])

                            logger.info(
                                f"Library {lib_id.get('name')} search results: {len(book_dataset)} books, {len(podcast_dataset)} podcasts")

                            # Process books
                            for book in book_dataset:
                                try:
                                    authors_list = []
                                    title = book['libraryItem']['media']['metadata']['title']
                                    authors_raw = book['libraryItem']['media']['metadata'].get('authors', [])

                                    for author in authors_raw:
                                        name = author.get('name')
                                        if name:
                                            authors_list.append(name)

                                    author = ', '.join(authors_list) if authors_list else 'Unknown Author'
                                    book_id = book['libraryItem']['id']

                                    # Add to list if not already present (avoid duplicates)
                                    new_item = {'id': book_id, 'title': title, 'author': author}
                                    if not any(item['id'] == book_id for item in found_titles):
                                        found_titles.append(new_item)
                                        logger.debug(f"Added book: {title}")
                                except Exception as e:
                                    logger.warning(f"Error processing book result: {e}")

                            # Process podcasts
                            for podcast in podcast_dataset:
                                try:
                                    title = podcast['libraryItem']['media']['metadata']['title']
                                    # Podcasts have different author structure
                                    podcast_metadata = podcast['libraryItem']['media']['metadata']
                                    author = podcast_metadata.get('author', 'Unknown Author')
                                    if not author or author == 'Unknown Author':
                                        author = podcast_metadata.get('feedAuthor', 'Unknown Author')

                                    book_id = podcast['libraryItem']['id']

                                    # Add podcast emoji to distinguish in search
                                    title_with_emoji = f"🎙️ {title}"

                                    # Add to list if not already present (avoid duplicates)
                                    new_item = {'id': book_id, 'title': title_with_emoji, 'author': author}
                                    if not any(item['id'] == book_id for item in found_titles):
                                        found_titles.append(new_item)
                                        logger.debug(f"Added podcast: {title}")
                                except Exception as e:
                                    logger.warning(f"Error processing podcast result: {e}")

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

                # Cache series book data for dropdown
                await self._cache_series_book_data()

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
            self.seriesBookCache = {}
            return False

    async def move_to_series_book(self, direction=None, target_index=None):
        """
        Move to another book in the series - supports both direction and index patterns

        Args:
            direction: "next" or "previous" for sequential navigation (optional)
            target_index: Specific index to jump to for menu selection (optional)

        Note: Provide either direction OR target_index, not both

        Returns:
            bool: True if successful, False if failed or at series boundary
        """
        if not self.seriesList or self.seriesIndex is None:
            logger.warning(f"No series context available for {direction} book")
            return False

        # Determine target index based on input pattern
        if direction is not None and target_index is None:
            # Direction-based navigation
            if direction == "next":
                if self.seriesIndex >= len(self.seriesList) - 1:
                    logger.info("Already at the last book in series")
                    return False
                new_index = self.seriesIndex + 1
            elif direction == "previous":
                if self.seriesIndex <= 0:
                    logger.info("Already at the first book in series")
                    return False
                new_index = self.seriesIndex - 1
            else:
                logger.error(f"Invalid direction: {direction}")
                return False
        elif target_index is not None and direction is None:
            # Index-based navigation for menu selection
            if target_index < 0 or target_index >= len(self.seriesList):
                logger.warning(f"Series book index {target_index} out of range (0-{len(self.seriesList) - 1})")
                return False
            new_index = target_index
        else:
            logger.error("Must provide either direction OR target_index, not both or neither")
            return False

        target_book_id = self.seriesList[new_index]
        logger.info(f"Moving to series book at index {new_index}: {target_book_id}")

        try:
            # Determine start time based on navigation type
            if direction == "next":
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
                # For previous books, check if we have stored progress or if it's finished
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
                # For direct index navigation, respect server position
                start_time = None
                logger.debug(f"Direct index navigation - respecting server position")

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
            current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                target_book_id, start_time)
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

    # Podcast Functions ---------------------------

    async def setup_podcast_context(self, item_id: str, episode_index: int = 0):
        """Setup podcast episode context"""
        try:
            episodes = await c.bookshelf_get_podcast_episodes(item_id)
            if not episodes:
                return False

            self.podcastEpisodes = episodes
            self.currentEpisodeIndex = episode_index
            self.totalEpisodes = len(episodes)
            self.isFirstEpisode = episode_index == 0
            self.isLastEpisode = episode_index >= len(episodes) - 1

            current_episode = episodes[episode_index]
            self.currentEpisodeTitle = current_episode.get('title', 'Unknown Episode')

            logger.info(f"Setup podcast context: Episode {episode_index + 1}/{len(episodes)}")
            return True

        except Exception as e:
            logger.error(f"Error setting up podcast context: {e}")
            return False

    async def move_to_podcast_episode(self, target_index=None, relative_move=None):
        """
        Move to an episode by absolute index or relative movement.

        Args:
            target_index: Absolute episode index (0-based) to navigate to
            relative_move: Relative movement (+1 for next, -1 for previous)

        Note: Provide either target_index OR relative_move, not both

        Returns:
            bool: True if successful, False if failed or at episode boundary
        """
        if not self.podcastEpisodes or self.currentEpisodeIndex is None:
            logger.warning(f"No podcast context available for {direction} episode")
            return False

        # Calculate target index based on input
        if target_index is not None:
            new_index = target_index
            operation_desc = f"episode {target_index + 1}"
        elif relative_move is not None:
            if relative_move == 1:  # next
                if self.currentEpisodeIndex >= len(self.podcastEpisodes) - 1:
                    logger.info("Already at the last episode")
                    return False
                new_index = self.currentEpisodeIndex + 1
                operation_desc = "next episode"
            elif relative_move == -1:  # previous
                if self.currentEpisodeIndex <= 0:
                    logger.info("Already at the first episode")
                    return False
                new_index = self.currentEpisodeIndex - 1
                operation_desc = "previous episode"
            else:
                logger.error(f"Invalid relative_move: {relative_move}")
                return False
        else:
            logger.error("Must provide either target_index or relative_move")
            return False

        # Validate the target index
        if new_index < 0 or new_index >= len(self.podcastEpisodes):
            logger.warning(f"Episode index {new_index} out of range (0-{len(self.podcastEpisodes) - 1})")
            return False

        target_episode = self.podcastEpisodes[new_index]
        target_episode_id = target_episode.get('id')
        logger.info(f"Moving to {operation_desc}: {target_episode.get('title')}")

        try:
            # Stop current session
            if self.session_update.running:
                self.session_update.stop()
            await c.bookshelf_close_session(self.sessionID)

            # Build session for target episode - respects server position like series books
            audio, currentTime, sessionID, episodeTitle, episodeDuration = await self.build_session(
                item_id=self.bookItemID,
                episode_index=new_index
            )

            # Update episode position
            self.currentEpisodeIndex = new_index
            self.isFirstEpisode = self.currentEpisodeIndex == 0
            self.isLastEpisode = self.currentEpisodeIndex >= len(self.podcastEpisodes) - 1

            # Update audio state
            self.audioObj = audio
            self.currentTime = currentTime
            self.sessionID = sessionID
            self.bookTitle = episodeTitle  # Update title to episode title
            self.bookDuration = episodeDuration
            self.play_state = 'playing'
            self.nextTime = None

            # Clear chapter info (podcasts don't have chapters)
            self.currentChapter = None
            self.chapterArray = None

            # Set proper episode title for currentChapterTitle
            episode_number = target_episode.get('episode')
            position_in_list = new_index + 1

            if episode_number is not None:
                self.currentChapterTitle = f"Episode {episode_number}"
            else:
                if new_index == 0:
                    self.currentChapterTitle = "Latest Episode"
                else:
                    self.currentChapterTitle = f"Episode {position_in_list}"

            # Update episode title
            self.currentEpisodeTitle = target_episode.get('title', 'Unknown Episode')

            # Update cover image (could be episode-specific or podcast-general)
            self.cover_image = await c.bookshelf_cover_image(self.bookItemID)

            self.session_update.start()
            return True

        except Exception as e:
            logger.error(f"Error moving to {direction} episode: {e}")
            return False

    # Component Callbacks Functions------------------

    def get_current_playback_buttons(self):
        """Get the current playback buttons based on current state"""
        logger.debug(f"get_current_playback_buttons called: seriesIndex={getattr(self, 'seriesIndex', None)}")

        # First check for chapters
        has_chapters = False
        if not self.isPodcast:  # Only books can have chapters
            has_chapters = bool(
                self.currentChapter and
                self.chapterArray and
                len(self.chapterArray) > 1
            )

        # Generate dropdown options
        episode_options = None
        series_options = None

        if self.isPodcast:
            # Generate episode options
            episode_options = self._create_episode_options()
            logger.debug(f"Generated {len(episode_options) if episode_options else 0} episode options")

            # Podcasts get episode navigation
            return get_playback_rows(
                play_state=self.play_state,
                repeat_enabled=self.repeat_enabled,
                is_podcast=True,
                has_chapters=False,  # Podcasts never have chapters
                is_series=False,  # Podcasts don't use series navigation
                is_first_episode=self.isFirstEpisode,
                is_last_episode=self.isLastEpisode,
                podcast_autoplay=self.podcastAutoplay,
                episode_options=episode_options
            )
        else:
            # Books get series navigation
            is_series = bool(self.currentSeries and len(self.seriesList) > 1)

            if is_series:
                # Generate series options
                series_options = self._create_series_options()
                logger.debug(f"Generated {len(series_options) if series_options else 0} series options")

            return get_playback_rows(
                play_state=self.play_state,
                repeat_enabled=self.repeat_enabled,
                is_podcast=False,
                has_chapters=has_chapters,
                is_series=is_series,
                is_first_book=self.isFirstBookInSeries,
                is_last_book=self.isLastBookInSeries,
                series_autoplay=self.seriesAutoplay,
                series_options=series_options
            )

    async def update_callback_embed(self, ctx, update_buttons=True, stop_auto_kill=False):
        """
        Update playback embed for component callbacks with proper chapter/episode display
    
        Args:
            ctx: Component context
            update_buttons: Whether to update the button components as well
            stop_auto_kill: Whether to stop the auto-kill session task
        """
        # Get proper display title
        if self.isPodcast:
            current_episode = self.podcastEpisodes[self.currentEpisodeIndex]
            episode_number = current_episode.get('episode')
            position_in_list = self.currentEpisodeIndex + 1

            if episode_number is not None:
                display_chapter = f"Episode {episode_number}"
            else:
                if self.currentEpisodeIndex == 0:
                    display_chapter = "Latest Episode"
                else:
                    display_chapter = f"Episode {position_in_list}"
        else:
            display_chapter = self.currentChapterTitle

        # Generate embed
        embed_message = self.modified_message(color=ctx.author.accent_color, chapter=display_chapter)

        # Stop auto kill session task if requested
        if stop_auto_kill and self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        # Update UI
        if update_buttons:
            await ctx.edit_origin(embed=embed_message, components=self.get_current_playback_buttons())
        else:
            await ctx.edit_origin(embed=embed_message)

    async def shared_seek_callback(self, ctx: ComponentContext, seek_amount: float, is_forward: bool):
        """
        Shared logic for all seek component callbacks.
    
        Parameters:
        - ctx: ComponentContext from the button callback
        - seek_amount: Number of seconds to seek (positive value)
        - is_forward: True for forward seeking, False for rewinding
        """
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

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

        # Update UI
        await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
        await ctx.voice_state.channel.voice_state.play(self.audioObj)

    def _create_media_options(self, media_type="series"):
        """
        Common function to create selection menus for both series and episodes
    
        Args:
            media_type: "series" or "episode"
    
        Returns:
            list: StringSelectOption objects for the dropdown
        """
        options = []

        if media_type == "series":
            if not self.currentSeries or not self.seriesList:
                return None

            media_list = self.seriesList
            current_index = self.seriesIndex
            cached_data = getattr(self, 'seriesBookCache', {})  # We'll need to add this cache

        elif media_type == "episode":
            if not self.isPodcast or not self.podcastEpisodes:
                return None

            media_list = self.podcastEpisodes
            current_index = self.currentEpisodeIndex
            cached_data = None  # Episodes have all data already
        else:
            return None

        options = []

        for index, item in enumerate(media_list):
            if media_type == "series":
                # Series book handling
                book_id = item  # seriesList contains book IDs

                # Use cached data if available, otherwise use basic info
                if book_id in cached_data:
                    title = cached_data[book_id].get('title', 'Unknown Book')
                    author = cached_data[book_id].get('author', 'Unknown Author')
                else:
                    # Fallback if not cached
                    if index == current_index:
                        title = self.bookTitle
                        author = "Current Book"
                    else:
                        title = "Unknown Book"
                        author = "Unknown Author"

                display_prefix = f"Book {index + 1}"
                extra_info = author

            else:
                # Episode handling
                episode = item  # podcastEpisodes contains episode objects
                title = episode.get('title', 'Unknown Episode')
                episode_number = episode.get('episode')

                # Get Duration
                audio_file = episode.get('audioFile', {})
                episode_duration = audio_file.get('duration', 0) if audio_file else 0

                # Format duration
                if episode_duration and episode_duration > 0:
                    from audio import time_converter
                    extra_info = time_converter(int(episode_duration))
                else:
                    extra_info = "Unknown Duration"

                # Create episode display prefix
                position_in_list = index + 1
                if episode_number is not None:
                    display_prefix = f"Episode {episode_number}"
                else:
                    if index == 0:
                        display_prefix = "Latest Episode"
                    else:
                        display_prefix = f"Episode {position_in_list}"

            # Mark current item
            is_current = index == current_index

            if media_type == "episode":
                # For episodes: use episode title as label, episode number + duration as description
                display_title = title
                if len(display_title) > 100:
                    display_title = display_title[:97] + "..."

                label = display_title
                if is_current:
                    label = f"⭐ {label}"

                if episode_number is not None:
                    description = f"Episode {episode_number} • {extra_info}"
                else:
                    if index == 0:
                        description = f"Latest Episode • {extra_info}"
                    else:
                        description = f"Episode {index + 1} • {extra_info}"
            else:
                # For series: use book number + title as label, author + duration as description
                display_title = title
                book_number = index + 1

                # Format as "Book # - Title"
                full_label = f"Book {book_number} - {display_title}"
                if len(full_label) > 100:
                    # Truncate the title part if too long
                    available_length = 100 - len(f"Book {book_number} - ") - 3
                    display_title = display_title[:available_length] + "..."
                    full_label = f"Book {book_number} - {display_title}"

                label = full_label
                if is_current:
                    label = f"⭐ {label}"

                # Get book duration from cached data if available
                book_id = item
                book_duration = ""
                if book_id in cached_data and 'duration' in cached_data[book_id]:
                    from audio import time_converter
                    duration_seconds = cached_data[book_id]['duration']
                    book_duration = f" • {time_converter(int(duration_seconds))}"

                description = f"{extra_info}{book_duration}"

            # Ensure label isn't too long (Discord limit is 100 chars)
            if len(label) > 100:
                label = label[:97] + "..."

            options.append(StringSelectOption(
                label=label,
                value=str(index),
                description=description,
            ))

        # Discord select menus are limited to 25 options
        if len(options) > 25:
            current_idx = current_index if current_index is not None else 0

            # Show items around current selection
            start_idx = max(0, current_idx - 12)  # 12 before + 1 current + 12 after = 25
            end_idx = min(len(options), start_idx + 25)

            # If we're near the end, adjust start to show last 25 items
            if end_idx - start_idx < 25:
                start_idx = max(0, end_idx - 25)

            options = options[start_idx:end_idx]

        return options

    def _create_episode_options(self):
        """Create episode dropdown options"""
        return self._create_media_options("episode")

    def _create_series_options(self):
        """Create series book dropdown options"""
        return self._create_media_options("series")

    async def _cache_series_book_data(self):
        """Cache book titles and authors for series dropdown"""
        if not self.currentSeries or not self.seriesList:
            return

        self.seriesBookCache = {}

        for book_id in self.seriesList:
            try:
                book_details = await c.bookshelf_get_item_details(book_id)
                self.seriesBookCache[book_id] = {
                    'title': book_details.get('title', 'Unknown Book'),
                    'author': book_details.get('author', 'Unknown Author'),
                    'duration': book_details.get('duration', 0)
                }
            except Exception as e:
                logger.error(f"Error caching series book data for {book_id}: {e}")
                self.seriesBookCache[book_id] = {
                    'title': 'Unknown Book',
                    'author': 'Unknown Author',
                    'duration': 0
                }

    async def handle_media_selection(self, ctx, media_type="series"):
        """
        Common function to handle selection from both series and episode menus
    
        Args:
            ctx: ComponentContext
            media_type: "series" or "episode"
        """
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        try:
            selected_value = ctx.values[0]
            target_index = int(selected_value)

            # Validate selection based on media type
            if media_type == "series":
                if not self.currentSeries or not self.seriesList:
                    await ctx.send("No series information available.", ephemeral=True)
                    return

                if target_index == self.seriesIndex:
                    await ctx.send("This book is already playing!", ephemeral=True)
                    return

                if target_index < 0 or target_index >= len(self.seriesList):
                    await ctx.send("Invalid book selection.", ephemeral=True)
                    return

                # Get target info
                target_id = self.seriesList[target_index]
                target_details = await c.bookshelf_get_item_details(target_id)
                target_name = target_details.get('title', 'Unknown Book')
                display_name = f"Book {target_index + 1}: {target_name}"

            else:  # episode
                if not self.isPodcast or not self.podcastEpisodes:
                    await ctx.send("No podcast episode information available.", ephemeral=True)
                    return

                if target_index == self.currentEpisodeIndex:
                    await ctx.send("This episode is already playing!", ephemeral=True)
                    return

                if target_index < 0 or target_index >= len(self.podcastEpisodes):
                    await ctx.send("Invalid episode selection.", ephemeral=True)
                    return

                # Get target info
                target_episode = self.podcastEpisodes[target_index]
                target_name = target_episode.get('title', 'Unknown Episode')
                episode_number = target_episode.get('episode')

                if episode_number is not None:
                    display_name = f"Episode {episode_number}: {target_name}"
                else:
                    if target_index == 0:
                        display_name = f"Latest Episode: {target_name}"
                    else:
                        display_name = f"Episode {target_index + 1}: {target_name}"

            # Stop current playback
            if ctx.voice_state and self.play_state == 'playing':
                ctx.voice_state.channel.voice_state.player.stop()

            # Move to selected media
            if media_type == "series":
                # Store current position before moving
                self.previousBookID = self.bookItemID
                self.previousBookTime = self.currentTime

                success = await self.move_to_series_book(target_index=target_index)
            else:  # episode
                success = await self.move_to_podcast_episode(target_index=target_index)

            if success:
                logger.info(f"Successfully switched to {display_name}")
                logger.debug(f"Updated series state: seriesIndex={self.seriesIndex}, bookTitle='{self.bookTitle}'")

                # Update UI
                await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)

                # Start new playback
                if ctx.voice_state:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

                logger.info(f"Successfully switched to {display_name}")

            else:
                media_name = "book" if media_type == "series" else "episode"
                await ctx.send(f"Failed to switch to selected {media_name}.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error selecting {media_type}: {e}")
            media_name = "book" if media_type == "series" else "episode"
            await ctx.send(f"Error switching {media_name}s. Please try again.", ephemeral=True)

    # Component Callbacks ---------------------------

    @component_callback('pause_audio_button')
    async def callback_pause_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state:
            logger.info('Pausing Playback!')
            self.play_state = 'paused'
            ctx.voice_state.channel.voice_state.pause()
            self.session_update.stop()
            logger.warning("Auto session kill task running... Checking for inactive session in 5 minutes!")

            self.auto_kill_session.start()

            await self.update_callback_embed(ctx, update_buttons=True)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await self.update_callback_embed(ctx, update_buttons=True)

    @component_callback('repeat_button')
    async def callback_repeat_button(self, ctx: ComponentContext):
        """Toggle repeat mode on/off"""
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        self.repeat_enabled = not self.repeat_enabled
        await self.update_callback_embed(ctx, update_buttons=True)

    @component_callback('next_chapter_button')
    async def callback_next_chapter_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state:
            # Check if chapter data exists before attempting navigation
            if not self.currentChapter or not self.chapterArray:
                logger.warning("No chapter data available for this book. Cannot navigate chapters.")
                await ctx.send(
                    content="This book doesn't have chapter information. Chapter navigation is not available.",
                    ephemeral=True)
                return  # Return early without stopping playback

            await ctx.defer(edit_origin=True)

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
                await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
                await ctx.voice_state.channel.voice_state.play(self.audioObj)
            elif session_was_cleaned_up and is_last_chapter:
                await ctx.edit_origin(content="📚 Book completed!")
            else:
                await ctx.send(content="Failed to navigate to next chapter.", ephemeral=True)
                # Restart playback since we stopped it
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Reset variable
            self.found_next_chapter = False
            self.newChapterTitle = ''
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state:
            # Check if chapter data exists before attempting navigation
            if not self.currentChapter or not self.chapterArray:
                await ctx.send(
                    content="This book doesn't have chapter information. Chapter navigation is not available.",
                    ephemeral=True)
                return  # Return early without stopping playback

            await ctx.defer(edit_origin=True)

            ctx.voice_state.channel.voice_state.player.stop()

            # Find previous chapter
            await self.move_chapter(relative_move=-1)

            # Check if move_chapter succeeded before proceeding
            if self.found_next_chapter:
                await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)
            else:
                await ctx.send(content="Failed to navigate to previous chapter.", ephemeral=True)
                if ctx.voice_state and ctx.voice_state.channel:
                    await ctx.voice_state.channel.voice_state.play(self.audioObj)

            # Reset Variable
            self.found_next_chapter = False
            self.newChapterTitle = ''
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @component_callback('stop_audio_button')
    async def callback_stop_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state:
            await ctx.edit_origin()
            await ctx.delete()
            await self.cleanup_session("manual stop button")

    @component_callback('next_book_button')
    async def callback_next_book_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

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
            await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to next book in series.", ephemeral=True)

    @component_callback('previous_book_button')
    async def callback_previous_book_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

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
            # Update UI
            await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to previous book in series.", ephemeral=True)

    @component_callback('toggle_series_auto_button')
    async def callback_toggle_series_auto_button(self, ctx: ComponentContext):
        """Toggle series auto-progression mode"""
        status = "enabled" if self.seriesAutoplay else "disabled"

        # Update UI
        self.seriesAutoplay = not self.seriesAutoplay
        await self.update_callback_embed(ctx, update_buttons=True)

    @component_callback('next_episode_button')
    async def callback_next_episode_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return

        if not self.isPodcast:
            await ctx.send(content="Current item is not a podcast.", ephemeral=True)
            return

        await ctx.defer(edit_origin=True)

        # Stop current playback
        if self.play_state == 'playing':
            ctx.voice_state.channel.voice_state.player.stop()

        # Move to next episode
        success = await self.move_to_podcast_episode(relative_move=1)

        if success:
            # Update UI
            await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to next episode.", ephemeral=True)

    @component_callback('previous_episode_button')
    async def callback_previous_episode_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if not ctx.voice_state:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            return

        if not self.isPodcast:
            await ctx.send(content="Current item is not a podcast.", ephemeral=True)
            return

        await ctx.defer(edit_origin=True)

        # Stop current playback
        if self.play_state == 'playing':
            ctx.voice_state.channel.voice_state.player.stop()

        # Move to previous episode
        success = await self.move_to_podcast_episode(relative_move=-1)

        if success:
            await self.update_callback_embed(ctx, update_buttons=True, stop_auto_kill=True)
            await ctx.voice_state.channel.voice_state.play(self.audioObj)
        else:
            await ctx.send(content="Failed to move to previous episode.", ephemeral=True)

    @component_callback('toggle_podcast_auto_button')
    async def callback_toggle_podcast_auto_button(self, ctx: ComponentContext):
        """Toggle episode auto-progression mode for podcasts"""
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        # Update UI
        self.podcastAutoplay = not self.podcastAutoplay
        await self.update_callback_embed(ctx, update_buttons=True)

    @component_callback('series_select_menu')
    async def series_select_callback(self, ctx: ComponentContext):
        """Handle book selection from the series dropdown"""
        await self.handle_media_selection(ctx, media_type="series")

    @component_callback('episode_select_menu')
    async def episode_select_callback(self, ctx: ComponentContext):
        """Handle episode selection from the episode dropdown"""
        await self.handle_media_selection(ctx, media_type="episode")

    @component_callback('volume_up_button')
    async def callback_volume_up_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1
            # Update Audio OBJ
            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = min(1.0, self.volume + adjustment)
            self.volume = audio.volume

            # Update UI
            await self.update_callback_embed(ctx, update_buttons=False)
            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('volume_down_button')
    async def callback_volume_down_button(self, ctx: ComponentContext):
        if not await can_control_session(ctx, self):
            await ctx.send("You don't have permission to control this session.", ephemeral=True)
            return

        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1

            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = max(0.0, self.volume - adjustment)
            self.volume = audio.volume

            # Update UI
            await self.update_callback_embed(ctx, update_buttons=False)
            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

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
        # Stop session update
        self.session_update.stop()

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

                    elif self.podcastAutoplay and self.isPodcast and not self.isLastEpisode:
                        # Handle podcast episode progression
                        logger.info("Seeked past episode end - moving to next episode")

                        if self.session_update.running:
                            self.session_update.stop()

                        # Mark current episode as finished
                        episode_id = getattr(self, 'episodeId', None)
                        try:
                            await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID, episode_id)
                            logger.info(f"Successfully marked episode {episode_id} as finished before progression")
                        except Exception as e:
                            logger.warning(f"Failed to mark episode as finished before progression: {e}")

                        # Move to next episode
                        success = await self.move_to_podcast_episode(relative_move=1)
                        if success:
                            self.session_update.start()
                            return self.audioObj
                        else:
                            logger.error("Failed to move to next episode")
                            await self.cleanup_session("episode progression failed")
                            return None

                    elif self.seriesAutoplay and self.currentSeries and not self.isLastBookInSeries:
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
                        # Final fallback - mark as complete and cleanup
                        if self.isPodcast:
                            logger.info("Seeked past final episode - marking complete and cleaning up")
                        else:
                            logger.info("Seeked past book end - marking complete and cleaning up")

                        # Mark as finished while we still have session info
                        episode_id = getattr(self, 'episodeId', None) if self.isPodcast else None
                        try:
                            await c.bookshelf_mark_book_finished(self.bookItemID, self.sessionID, episode_id)
                            logger.info(
                                f"Successfully marked {'episode' if episode_id else 'book'} as finished via session sync")
                        except Exception as e:
                            logger.warning(f"Failed to mark as finished via session sync: {e}")

                        await self.cleanup_session("completed via seek past end")
                        return None

                self.nextTime = self.currentTime + seek_amount
            else:
                self.nextTime = max(0.0, self.currentTime - seek_amount)

        else:
            # Chapter data is available
            current_chapter = self.currentChapter
            current_index = next(
                (i for i, ch in enumerate(self.chapterArray) if ch.get('id') == current_chapter.get('id')), None)
            prev_chapter = self.chapterArray[
                current_index - 1] if current_index is not None and current_index > 0 else None
            next_chapter = self.chapterArray[current_index + 1] if current_index is not None and current_index < len(
                self.chapterArray) - 1 else None

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

                        # Note no podcast logic here as they don't have chapters
                        elif self.seriesAutoplay and self.currentSeries and not self.isLastBookInSeries:
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
                            logger.info(
                                "Seeked past book end (with chapters, no repeat) - marking complete and cleaning up")
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
