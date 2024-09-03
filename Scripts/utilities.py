import settings
import asyncio

def time_converter(time_sec: int) -> str:
    """
    :param time_sec:
    :return: a formatted string w/ time_sec + time_format(H,M,S)
    """
    formatted_time = time_sec
    playbackTimeState = 'Seconds'

    if time_sec >= 60 and time_sec < 3600: # NOQA
        formatted_time = round(time_sec / 60, 2)
        playbackTimeState = 'Minutes'
    elif time_sec >= 3600:
        formatted_time = round(time_sec / 3600, 2)
        playbackTimeState = 'Hours'

    formatted_string = f"{formatted_time} {playbackTimeState}"

    return formatted_string