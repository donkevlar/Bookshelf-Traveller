import time
import logging
import bookshelfAPI as c

# Logger Config
logger = logging.getLogger("bot")


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
            logger.warning(f"Progress check timeout after {elapsed:.2f}s - processed {completed_checks}/{len(choices)} items")
            timed_out = True
            updated_choices.extend(choices[i:])  # Add remaining without checkmarks
            break
        
        item_id = choice.get('value')
        original_name = choice.get('name', '')
        
        # Skip special items like "random" or items already with checkmarks
        if not item_id or item_id == "random" or "📚" in original_name or original_name.startswith('✅'):
            updated_choices.append(choice)
            continue
        
        try:
            progress_data = await c.bookshelf_item_progress(item_id)
            is_finished = progress_data.get('finished', 'False') == 'True'
            
            if is_finished:
                new_name = f"✅ {original_name}"
    
                # If too long, truncate to fit
                if len(new_name) > 100:
                    # "✅ " = 2 chars, so we have 98 chars left for the name
                    new_name = f"✅ {original_name[:98]}"
    
                choice = {"name": new_name, "value": item_id}
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
