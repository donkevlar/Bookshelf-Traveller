import interactions
from interactions.api.voice.audio import AudioVolume
from interactions import Extension, slash_command, SlashContext

import settings


class AudioPlayBack(Extension):
    # Experimental
    if settings.EXPERIMENTAL:
        @interactions.slash_command(name="play", description="Test Play Functionality")
        async def play_file(self, ctx: interactions.SlashContext):
            if not ctx.voice_state:
                # if we haven't already joined a voice channel
                # join the authors vc
                await ctx.author.voice.channel.connect()
            audio = AudioVolume(settings.TEST_ENV1)
            await ctx.voice_state.play(audio)
