import time
import logging
from functools import wraps

import bookshelfAPI as c
import settings

# Logger Config
logger = logging.getLogger("bot")


async def ownership_check(ctx):
    """
    Basic ownership check - respects OWNER_ONLY setting.
    Used for info/utility commands.
    """
    ownership = settings.OWNER_ONLY
    if ownership:
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.id == ctx.user.id or ctx.user in ctx.bot.owners:
            logger.info(f"{ctx.user.username}, you are the owner and ownership is enabled!")
            return True
        else:
            logger.warning(f"{ctx.user.username}, is not the owner and ownership is enabled!")
            return False
    else:
        return True


async def is_bot_owner(ctx):
    """Root access - for admin commands only"""
    return ctx.bot.owner.id == ctx.user.id or ctx.user in ctx.bot.owners


async def is_playback_manager(ctx):
    """Can manage any playback session (bot owners + role users)"""
    # Bot owner has full access
    if await is_bot_owner(ctx):
        return True

    # Users with playback role (if configured)
    if settings.PLAYBACK_ROLE:
        try:
            playback_role_id = int(settings.PLAYBACK_ROLE)
            if hasattr(ctx.author, 'roles') and any(role.id == playback_role_id for role in ctx.author.roles):
                return True
        except (ValueError, AttributeError) as e:
            logger.warning(f"Invalid PLAYBACK_ROLE setting: {settings.PLAYBACK_ROLE}, Error: {e}")

    return False


async def can_control_session(ctx, audio_extension, action="control"):
    """
    Universal permission check for session actions.
    
    Args:
        ctx: Discord context
        audio_extension: The audio extension instance  
        action: Type of action - "control", "start", or "announce"
    
    Returns:
        bool: True if user can perform the action
    """
    # Managers can do anything
    if await is_playback_manager(ctx):
        return True

    if action == "start":
        # If OWNER_ONLY is enabled, only privileged users can start
        if settings.OWNER_ONLY:
            return False

        # Regular users can start IF no active session
        if not hasattr(audio_extension, 'activeSessions') or audio_extension.activeSessions == 0:
            return True

        return False

    elif action in ["control", "announce"]:
        # Session owner can control/announce their own session
        if (hasattr(audio_extension, 'sessionOwner') and
                audio_extension.sessionOwner == ctx.author.username):
            return True

        return False

    return False


def check_session_control(action="control"):
    """
    Decorator for session control permissions.
    
    Args:
        action: Type of action - "control", "start", or "announce"
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if not await can_control_session(ctx, self, action):
                # Customize message based on action
                if action == "start":
                    if hasattr(self, 'activeSessions') and self.activeSessions >= 1:
                        if await is_playback_manager(ctx):
                            message = f"A session is currently active (owner: {self.sessionOwner}). You can control it or use `/stop` first if you want to start a new session."
                        else:
                            message = f"A session is currently active (owner: {self.sessionOwner}). Please wait for it to end or ask a manager to stop it."
                    else:
                        message = "You don't have permission to start playback sessions."
                elif action == "announce":
                    message = "Only the session owner or managers can create announcements."
                else:  # action == "control"
                    message = "You don't have permission to control this session."

                await ctx.send(message, ephemeral=True)
                return

            # Permission check passed, call the original function
            return await func(self, ctx, *args, **kwargs)

        return wrapper

    return decorator


async def add_progress_indicators(choices, timeout_seconds=2.5):
    """
    Add ✅ to finished books in autocomplete choices.
    Returns (updated_choices, timed_out)
    """
    if not choices:
        return choices, False

    start_time = time.time()
    updated_choices = []
    timed_out = False
    completed_checks = 0
    finished_count = 0

    for i, choice in enumerate(choices):
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(
                f"Progress check timeout after {elapsed:.2f}s - processed {completed_checks}/{len(choices)} items")
            timed_out = True
            updated_choices.extend(choices[i:])  # Add remaining without checkmarks
            break

        item_id = choice.get('value')
        original_name = choice.get('name', '')
        episode_id = choice.get('episode_id')

        # Skip special items like "random" or items already with checkmarks
        if not item_id or item_id == "random" or "📚" in original_name or original_name.startswith('✅'):
            updated_choices.append(choice)
            continue

        try:
            progress_data = await c.bookshelf_item_progress(item_id, episode_id)
            is_finished = progress_data.get('finished', 'False') == 'True'

            if is_finished:
                new_name = f"✅ {original_name}"

                # If too long, truncate to fit
                if len(new_name) > 100:
                    # "✅ " = 2 chars, so we have 98 chars left for the name
                    new_name = f"✅ {original_name[:98]}"

                # Preserve episode_id if it exists
                updated_choice = {"name": new_name, "value": item_id}
                if episode_id:
                    updated_choice["episode_id"] = episode_id
                choice = updated_choice
                finished_count += 1

            updated_choices.append(choice)
            completed_checks += 1

        except Exception as e:
            logger.debug(f"Error checking progress for {item_id}: {e}")
            updated_choices.append(choice)
            completed_checks += 1

    # Only log if we found finished books or had issues
    if finished_count > 0:
        logger.info(f"Found {finished_count} finished books in autocomplete")
    elif timed_out:
        pass  # Already logged the timeout above

    return updated_choices, timed_out


def get_extension_instance(bot, name: str):
    """
    Safely get a loaded extension instance by name.
    Falls back to instantiating it if only the class is stored.
    Works for interactions.py extensions.
    """
    ext = None

    # Preferred method (newer interactions.py)
    if hasattr(bot, "get_ext"):
        ext = bot.get_ext(name)
    elif hasattr(bot, "ext"):
        ext = bot.ext.get(name)

    if not ext:
        logger.error(f"Extension '{name}' not found in bot.")
        return None

    # If it's a class (not an instance), instantiate it
    if isinstance(ext, type):
        logger.warning(f"Extension '{name}' is a class, instantiating manually.")
        ext = ext(bot)

    return ext
