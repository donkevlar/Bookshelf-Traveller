from interactions import ActionRow, Button, ButtonStyle, Embed

# --- Playback Rows ---

def get_playback_rows(play_state="playing"):
    """Return the appropriate button rows for a normal book."""
    is_paused = play_state == "paused"
    return [
        # Row 1: Volume and playback controls
        ActionRow(
            Button(style=ButtonStyle.DANGER, label="-", custom_id='volume_down_button'),
            Button(style=ButtonStyle.SUCCESS, label="+", custom_id='volume_up_button'),
            Button(
                style=ButtonStyle.SECONDARY if not is_paused else ButtonStyle.SUCCESS,
                label="Resume" if is_paused else "Pause",
                custom_id='play_audio_button' if is_paused else 'pause_audio_button'
            ),
            Button(style=ButtonStyle.DANGER, label="Stop", custom_id='stop_audio_button')
        ),
        # Row 2: Chapter navigation
        ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="Prior Chapter", custom_id='previous_chapter_button'),
            Button(style=ButtonStyle.PRIMARY, label="Next Chapter", custom_id='next_chapter_button')
        ),
        # Row 3: Time controls
        ActionRow(
            Button(style=ButtonStyle.SECONDARY, label="-30s", custom_id='rewind_button'),
            Button(style=ButtonStyle.SECONDARY, label="+30s", custom_id='forward_button')
        )
    ]

def get_series_playback_rows(play_state="playing", is_first_book=False, is_last_book=False):
    """Return playback rows for a book in a series."""
    rows = get_playback_rows(play_state)
    rows.append(
        ActionRow(
            Button(disabled=is_first_book, style=ButtonStyle.PRIMARY, label="Prior Book", custom_id="previous_book_button"),
            Button(disabled=is_last_book, style=ButtonStyle.PRIMARY, label="Next Book", custom_id="next_book_button")
        )
    )
    return rows

def get_podcast_playback_rows(play_state="playing"):
    """Return playback rows for podcast content."""
    is_paused = play_state == "paused"
    return [
        # Row 1: Volume and playback controls
        ActionRow(
            Button(style=ButtonStyle.DANGER, label="-", custom_id='volume_down_button'),
            Button(style=ButtonStyle.SUCCESS, label="+", custom_id='volume_up_button'),
            Button(
                style=ButtonStyle.SECONDARY if not is_paused else ButtonStyle.SUCCESS,
                label="Resume" if is_paused else "Pause",
                custom_id='play_audio_button' if is_paused else 'pause_audio_button'
            ),
            Button(style=ButtonStyle.DANGER, label="Stop", custom_id='stop_audio_button')
        ),
        # Row 2: Episode navigation (replaces chapter buttons)
        ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="Prior Episode", custom_id='previous_episode_button'),
            Button(style=ButtonStyle.PRIMARY, label="Next Episode", custom_id='next_episode_button')
        ),
        # Row 3: Time controls
        ActionRow(
            Button(style=ButtonStyle.SECONDARY, label="-30s", custom_id='rewind_button'),
            Button(style=ButtonStyle.SECONDARY, label="+30s", custom_id='forward_button')
        )
    ]

# --- Embeds ---

def create_playback_embed(book_title, chapter_title, progress, current_time, duration, 
                           username, user_type, cover_image, color, volume, timestamp, version):
    embed = Embed(
        title=book_title,
        description=f"Currently playing {book_title}",
        color=color
    )

    user_info = f"Username: **{username}**\nUser Type: **{user_type}**"
    embed.add_field(name='ABS Information', value=user_info)

    playback_info = (
        f"Current State: **PLAYING**\n"
        f"Progress: **{progress}**\n"
        f"Current Time: **{current_time}**\n"
        f"Current Chapter: **{chapter_title}**\n"
        f"Book Duration: **{duration}**\n"
        f"Current volume: **{round(volume * 100)}%**"
    )
    embed.add_field(name='Playback Information', value=playback_info)

    embed.add_image(cover_image)
    embed.footer = f"Powered by Bookshelf Traveller 🕮 | {version}\nDisplay Last Updated: {timestamp}"

    return embed

def create_book_info_embed(title, author, series, description, cover_url, color, additional_info=None):
    embed = Embed(title=title, description=description, color=color)
    embed.add_field(name="Author", value=author, inline=False)
    if series:
        embed.add_field(name="Series", value=series, inline=False)
    if additional_info:
        embed.add_field(name="Details", value=additional_info, inline=False)
    embed.add_image(cover_url)
    embed.footer = "Powered by Bookshelf Traveller 🕮"
    return embed

# --- Common Buttons ---

def get_confirmation_buttons(confirm_id="confirm_button", cancel_id="cancel_button"):
    return ActionRow(
        Button(style=ButtonStyle.SUCCESS, label="Confirm", custom_id=confirm_id),
        Button(style=ButtonStyle.DANGER, label="Cancel", custom_id=cancel_id)
    )

def get_wishlist_buttons(request_id="request_button", cancel_id="cancel_button"):
    return ActionRow(
        Button(style=ButtonStyle.PRIMARY, label="Request", custom_id=request_id),
        Button(style=ButtonStyle.SECONDARY, label="Cancel", custom_id=cancel_id)
    )
