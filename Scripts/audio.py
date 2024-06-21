import asyncio
import time
import interactions
from interactions import Extension, slash_command, SlashContext, slash_option, OptionType, AutocompleteContext, Task, \
    BaseTrigger, IntervalTrigger
from interactions.api.voice.audio import AudioVolume

import bookshelfAPI as c


class AudioPlayBack(Extension):
    def __init__(self, bot):
        pass

    @Task.create(IntervalTrigger(seconds=5))
    async def session_update(self, book_title: str, session_id: str, current_time=5):
        print("Initializing Session Sync")
        c.bookshelf_session_update(itemID=book_title, sessionID=session_id, currentTime=current_time)

    @slash_command(name="play", description="Test Play Functionality")
    @slash_option(name="book_title", description="Enter a book title", required=True, opt_type=OptionType.STRING,
                  autocomplete=True)
    async def play_file(self, ctx, book_title: str):
        if not ctx.voice_state:
            # if we haven't already joined a voice channel
            # join the authors vc
            try:
                await ctx.author.voice.channel.connect()
                # Get Bookshelf Playback URI, Starts new session
                audio_obj, currentTime, sessionID = c.bookshelf_audio_obj(book_title)
                # Audio Object Arguments
                audio = AudioVolume(audio_obj)
                audio.buffer_seconds = 15
                audio.locked_stream = True
                audio.ffmpeg_before_args = f"-ss {currentTime}"

                # Start audio playback
                await ctx.voice_state.play_no_wait(audio)
                # Start Session Updates
                self.session_update.start(book_title, sessionID)

            except Exception as e:
                await ctx.voice_state.stop()
                await ctx.author.voice.channel.disconnect()
                await ctx.author.channel.send(f'Issue with playback: {e}')
                print(e)

        # Play Audio, skip connection
        else:
            try:
                print("\nVoice already connected, playing new audio selection.")
                audio_obj, currentTime = c.bookshelf_audio_obj(book_title)
                audio = AudioVolume(audio_obj)
                audio.locked_stream = True
                audio.buffer_seconds = 15
                audio.ffmpeg_before_args = f"-ss {currentTime}"
                await ctx.voice_state.play_no_wait(audio)
                playing = ctx.voice_state.playing()
                print(playing)

            except Exception as e:
                await ctx.voice_state.stop()
                await ctx.author.voice.channel.disconnect()
                await ctx.author.channel.send(f'Issue with playback: {e}')
                print(e)

    @slash_command(name="pause", description="pause audio")
    async def pause_audio(self, ctx: interactions):
        if ctx.voice_state:
            print("Pausing Audio")
            ctx.voice_state.pause()

    @slash_command(name="resume", description="resume audio")
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            print("Resuming Audio")
            ctx.voice_state.resume()

    @play_file.autocomplete("book_title")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        print(user_input)
        if user_input != "":
            try:
                titles_ = c.bookshelf_title_search(user_input)
                for info in titles_:
                    book_title = info["title"]
                    book_id = info["id"]
                    choices.append({"name": f"{book_title}", "value": f"{book_id}"})

                await ctx.send(choices=choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)

        else:
            await ctx.send(choices=choices)

    @slash_command(name="disconnect", description="Will disconnect from the voice channel")
    async def disconnect_voice(self, ctx: SlashContext):
        if ctx.voice_state:
            await ctx.author.voice.channel.disconnect()
            await ctx.author.send("Disconnected from Audio Channel")
