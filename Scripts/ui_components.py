from interactions import ActionRow, Button, ButtonStyle, Embed

# --- Playback Rows ---

def get_playback_rows(play_state="playing", repeat_enabled=False, is_podcast=False,
                     has_chapters=True, is_series=False, is_first_book=False, is_last_book=False):
    """Build dynamic playback control rows based on state"""
    is_paused = play_state == "paused"
    rows = []

    # Row 1: Volume and time controls
    rows.append(ActionRow(
        Button(style=ButtonStyle.DANGER, label="-", custom_id='volume_down_button'),
        Button(style=ButtonStyle.SUCCESS, label="+", custom_id='volume_up_button'),
        Button(style=ButtonStyle.SECONDARY, label="-30s", custom_id='rewind_button'),
        Button(style=ButtonStyle.SECONDARY, label="+30s", custom_id='forward_button')
    ))

    # Row 2: Main playback controls
    rows.append(ActionRow(
        Button(
            style=ButtonStyle.SECONDARY if not is_paused else ButtonStyle.SUCCESS,
            label="Resume" if is_paused else "Pause",
            custom_id='play_audio_button' if is_paused else 'pause_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS if repeat_enabled else ButtonStyle.SECONDARY,
            label="Repeat",
            custom_id='repeat_button'
        ),
        Button(style=ButtonStyle.DANGER, label="Stop", custom_id='stop_audio_button')
    ))

    # Row 3: Navigation controls - dynamic based on content type and chapter availability
    if is_podcast:
        rows.append(ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="Prior Episode", custom_id='previous_episode_button'),
            Button(style=ButtonStyle.PRIMARY, label="Next Episode", custom_id='next_episode_button')
        ))
    else:  # book
        if has_chapters:
            # Traditional chapter navigation
            rows.append(ActionRow(
                Button(style=ButtonStyle.PRIMARY, label="Prior Chapter", custom_id='previous_chapter_button'),
                Button(style=ButtonStyle.PRIMARY, label="Next Chapter", custom_id='next_chapter_button')
            ))
        else:
            # Large time-based navigation for books without chapters
            rows.append(ActionRow(
               # Uses Braille blank space (U+2800), Discord trims regular spaces
                Button(style=ButtonStyle.PRIMARY, label="⠀⠀⠀-5m⠀⠀⠀", custom_id='rewind_button_large'),
                Button(style=ButtonStyle.PRIMARY, label="⠀⠀⠀+5m⠀⠀⠀", custom_id='forward_button_large')
            ))

    # Row 4: Series controls (only for books in a series)
    if is_series:
        rows.append(ActionRow(
            Button(
                disabled=is_first_book, 
                style=ButtonStyle.PRIMARY, 
                label="Prior Book", 
                custom_id="previous_book_button"
            ),
            Button(
                disabled=is_last_book, 
                style=ButtonStyle.PRIMARY, 
                label="Next Book", 
                custom_id="next_book_button"
            )
        ))

    return rows

# --- Embeds ---

def create_playback_embed(book_title, chapter_title, progress, current_time, duration, 
                           username, user_type, cover_image, color, volume, timestamp, version, 
                           repeat_enabled=False, series_info=None):
    embed = Embed(
        title=book_title,
        description=f"Currently playing {book_title}",
        color=color
    )

    user_info = f"User: **{username}** (**{user_type}**)"
    embed.add_field(name='ABS Information', value=user_info)

    repeat_status = "Enabled" if repeat_enabled else "Disabled"

    playback_info = (
        f"Status: **Playing**\n"
        f"Progress: **{progress}**\n"
        f"Current Chapter: **{chapter_title}**\n"
        f"Current Time: **{current_time}**\n"
        f"Book Duration: **{duration}**\n"
#        f"Repeat: **{repeat_status}\n**"
        f"Current volume: **{round(volume * 100)}%**"
    )

    if series_info:
        series_text = f"Series: **{series_info['name']}** (Book {series_info['current']}/{series_info['total']})"
        playback_info += f"\n{series_text}"

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
