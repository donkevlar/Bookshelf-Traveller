import asyncio
import csv
import logging
import os
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime

import httpx
import requests

from dotenv import load_dotenv
from settings import OPT_IMAGE_URL, SERVER_URL, DEFAULT_PROVIDER

# Logger Config
logger = logging.getLogger("bot")

# DEV ENVIRON VARS
load_dotenv()

keep_active = False

optional_image_url = OPT_IMAGE_URL

def time_converter(time_sec: int) -> str:
    """
    :param time_sec:
    :return: a formatted string w/ time_sec + time_format(H,M,S)
    """
    hours = int(time_sec // 3600)
    minutes = int((time_sec % 3600) // 60)
    seconds = int(time_sec % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

# Simple Success Message
def successMSG(endpoint, status):
    logger.debug(f'Successfully Reached {endpoint} with Status {status}')


async def bookshelf_conn(endpoint: str, Headers=None, Data=None, Token=True, GET=False,
                         POST=False, params=None):
    """
    :param endpoint:
    :param Headers:
    :param Data:
    :param Token:
    :param GET:
    :param POST:
    :param params:
    :return: r -> requests or httpx object if status 200.
    """
    bookshelfURL = SERVER_URL
    API_URL = bookshelfURL + "/api"
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken if Token else ""

    if params is not None:
        additional_params = params
    else:
        additional_params = ''

    link = f'{API_URL}{endpoint}{tokenInsert}{additional_params}'
    if __name__ == '__main__':
        print(link)

    # Create an HTTPX client
    async with httpx.AsyncClient() as client:
        if GET:
            if Headers:
                r = await client.get(link, headers=Headers)
                return r
            else:
                r = await client.get(link)
                return r
        elif POST:
            if Data is not None and Headers is not None:
                r = await client.post(link, headers=Headers, json=Data)
            else:
                r = await client.post(link)
            return r
        else:
            logger.warning('Must include GET, POST or PATCH in arguments')
            raise Exception


# Test initial Connection to Bookshelf Server
def bookshelf_test_connection():
    bookshelfURL = os.environ.get("bookshelfURL")
    logger.info("Testing Server Connection")
    connected = False
    errorCount = 0
    maxCount = int(os.getenv('MAX_CONN_ATTEMPT', 10))

    while not connected:

        try:
            # Using /healthcheck to avoid domain mismatch, since this is an api endpoint in bookshelf
            r = requests.get(f'{bookshelfURL}/healthcheck', timeout=5)
            status = r.status_code
            if status == 200:
                connected = True
                logger.info("Connection Established!")
                return status

        except requests.exceptions.ConnectTimeout:
            errorCount += 1
            if errorCount <= maxCount:
                logger.warning(
                    f"Attempt {errorCount}: Connection time out occured!, attempting to reconnect in 5 seconds...")
                time.sleep(5)

            else:
                logger.error("Max reconnect retries reached, aborting!")
                sys.exit('Connection Timed Out')

        except requests.RequestException:
            errorCount += 1
            if errorCount <= maxCount:
                logger.error(
                    f"Attempt {errorCount}: Error occured while testing server connection, attempting to reconnect in 5 seconds...")
                time.sleep(5)
            else:
                logger.error("Max reconnect retries reached, aborting!")
                sys.exit('Request Exception')

        except UnboundLocalError:
            logger.error("No URL PROVIDED!")
            sys.exit(1)


# Used to retrieve the token for the user logging in
def bookshelf_user_login(username='', password='', token=''):
    """
    :param username:
    :param password:
    :param token:
    :return: user_info(dict) -> keys: username, token, type
    """
    endpoint = "/login"
    token_endpoint = f"/api/authorize?token={token}"
    bookshelfURL = os.environ.get("bookshelfURL")
    url = f"{bookshelfURL}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    d = {"username": username, "password": str(password)}
    user_info = {}
    if token != '':
        r = requests.post(f"{bookshelfURL}{token_endpoint}")
    elif username != '' and password != '':
        r = requests.post(url=f"{url}", json=d, headers=headers)
    else:
        return print("invalid user arguments")

    if r.status_code == 200:
        data = r.json()

        abs_token = data['user']['token']
        abs_username = data['user']['username']
        user_type = data['user']['type']

    else:

        abs_token = ""
        abs_username = ""
        user_type = None

    user_info["username"] = abs_username
    user_info["type"] = user_type
    user_info["token"] = abs_token

    return user_info


# Authenticate the user with bookshelf server provided
async def bookshelf_auth_test():
    logger.info("Providing Auth Token to Server")
    try:
        endpoint = "/me"
        r = await bookshelf_conn(GET=True, endpoint=endpoint)
        if r.status_code == 200:
            # Place data in JSON Format
            data = r.json()

            username = data.get("username", "")
            user_type = data.get('type', "user")
            user_locked = data.get('isLocked', False)

            logger.info("Cleaning up, authentication")
            return username, user_type, user_locked
        else:
            logger.info("Error: Could not connect to /me endpoint")
            logger.info("Quitting!")
            sys.exit(1)

    except requests.RequestException as e:
        logger.warning("Could not establish connection: ", e)


async def bookshelf_get_item_details(book_id) -> dict:
    """
    Fetch book details from Bookshelf API.
    :param book_id:
    :return: formatted_data(dict) -> keys: title,
        author,
        narrator,
        series,
        publisher,
        genres,
        publishedYear,
        description,
        language,
        duration,
        addedDate
    """
    _url = f"/items/{book_id}"
    r = await bookshelf_conn(GET=True, endpoint=_url)

    # Check if response is valid
    if r.status_code != 200:
        logger.error(f"Failed to fetch book details. Status: {r.status_code}, Response: {r.text}")
        return {}

    try:
        data = r.json()
    except Exception as e:
        logger.error(f"Error parsing JSON response: {e}. Raw response: {r.text}")
        return {}

    # Validate required fields
    if not data or "media" not in data or "metadata" not in data["media"]:
        logger.error(f"Invalid response structure: {data}")
        return {}

    logger.debug(data)

    try:
        title = data['media']['metadata'].get('title', 'Unknown Title')
        desc = data['media']['metadata'].get('description', 'No Description')
        language = data['media']['metadata'].get('language', 'Unknown Language')
        publishedYear = data['media']['metadata'].get('publishedYear', 'Unknown Year')
        publisher = data['media']['metadata'].get('publisher', 'Unknown Publisher')
        addedDate = data.get('addedAt', 'Unknown Date')

        authors_list = [author.get('name') for author in data['media']['metadata'].get('authors', [])]
        narrators_list = data['media']['metadata'].get('narrators', [])
        series_raw = data['media']['metadata'].get('series', [])
        files_raw = data['media'].get('audioFiles', [])
        genres_raw = data['media']['metadata'].get('genres', [])

        # Construct series info
        series = ''
        if series_raw:
            series_name = series_raw[0].get('name', 'Unknown Series')
            series_seq = series_raw[0].get('sequence', '0')
            series = f"{series_name}, Book {series_seq}"

        # Calculate total duration
        duration_sec = sum(int(file.get('duration', 0)) for file in files_raw)

        formatted_data = {
            'title': title,
            'author': ', '.join(authors_list),
            'narrator': ', '.join(narrators_list),
            'series': series,
            'publisher': publisher,
            'genres': ', '.join(genres_raw),
            'publishedYear': publishedYear,
            'description': desc,
            'language': language,
            'duration': duration_sec,
            'addedDate': addedDate
        }

        return formatted_data
    except Exception as e:
        logger.error(f"Error processing book data: {e}. Raw data: {data}")
        return {}


async def bookshelf_listening_stats():
    """
    Gets the 10 most recent sessions for the logged in ABS user.
    :return: formatted_session_info, data
    """
    bookshelfToken = os.environ.get("bookshelfToken")
    endpoint = "/me/listening-stats"
    formatted_sessions = []

    r = await bookshelf_conn(GET=True, endpoint=endpoint)

    if r.status_code == 200:
        data = r.json()
        sessions = data.get("recentSessions", [])  # Extract sessions from the data

        # Use a dictionary to count the number of times each session appears
        session_counts = defaultdict(int)

        # Aggregate time matching
        aggregated_time = {}

        # Process each session and count the number of times each session appears
        for session in sessions:

            library_item_id = session["libraryItemId"]
            display_title = session["displayTitle"]

            # Create a unique identifier for the session based on library item ID and title
            session_key = (library_item_id, display_title)

            # Increment the count for this session
            session_counts[session_key] += 1

            # Extract Listening Time
            time_listening = session.get('timeListening')

            if library_item_id in aggregated_time:
                aggregated_time[library_item_id] += time_listening
            else:
                aggregated_time[library_item_id] = time_listening

        # Sort sessions by play count (highest to lowest)
        sorted_sessions = sorted(session_counts.items(), key=lambda x: x[1], reverse=True)

        # Create formatted strings with session info and count
        for session_key, count in sorted_sessions:
            library_item_id, display_title = session_key

            # Retrieve the session from sessions based on library_item_id
            session = next(session for session in sessions if session['libraryItemId'] == library_item_id)

            # Extract author information directly from the session
            display_author = session.get('displayAuthor', 'Unknown')

            # Calculate duration for the session
            duration_seconds = session["duration"]
            duration_hours = round(duration_seconds / 3600, 2)

            # Format session information
            session_info = (
                f"Display Title: {display_title}\n"
                f"Display Author: {display_author}\n"
                f"Duration: {duration_hours} Hours\n"
                f"Library Item ID: {library_item_id}\n"
                f"Number of Times Played: {count}"
            )
            formatted_sessions.append(session_info)

            # Add Session Time to formatted sessions string
            if library_item_id in aggregated_time:
                # Pull session time, seconds
                session_time = int(aggregated_time.get(library_item_id))
                # Convert session time to minutes
                if session_time >= 60 and session_time < 3600:
                    format_time = f"{round(session_time / 60, 2)} Minutes"
                # convert session time to hours
                elif session_time >= 3600:
                    format_time = f"{round(session_time / 3600, 2)} Hours"
                # keep in seconds
                else:
                    format_time = f"{session_time} Seconds"
                formatted_time_string = f"Aggregate Session Time: {str(format_time)}\n"
                formatted_sessions.append(formatted_time_string)

        # Join the formatted sessions into a single string with each session separated by a newline
        formatted_sessions_string = "\n".join(formatted_sessions)

        # print(formatted_sessions_string)

        return formatted_sessions_string, data
    else:
        print(f"Error: {r.status_code}")
        return None


async def bookshelf_libraries():
    endpoint = "/libraries"
    library_data = {}
    r = await bookshelf_conn(GET=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()
        successMSG(endpoint, r.status_code)
        for library in data['libraries']:
            name = library['name']
            library_id = library['id']
            audiobooks_only = library['settings'].get('audiobooksOnly')
            library_data[name] = (library_id, audiobooks_only)

        return library_data


async def bookshelf_item_progress(item_id):
    endpoint = f"/me/progress/{item_id}"
    r = await bookshelf_conn(GET=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()
        # successMSG(endpoint, r.status_code)

        progress = round(data['progress'] * 100)
        isFinished = data['isFinished']

        # Keep as seconds and format with time_converter
        currentTime_seconds = int(data['currentTime'])
        duration_seconds = int(data['duration'])
        
        lastUpdate = data['lastUpdate'] / 1000

        # Convert lastUpdate Time from unix to standard time
        lastUpdate = datetime.fromtimestamp(lastUpdate)
        converted_lastUpdate = lastUpdate.strftime('%Y-%m-%d %H:%M')

        # Get Media Title
        secondary_url = f"/items/{item_id}"
        r = await bookshelf_conn(GET=True, endpoint=secondary_url)
        data = r.json()
        title = data['media']['metadata']['title']
        print(data)

        formatted_info = {
            'title': title,
            'progress': f'{progress}%',
            'finished': f'{isFinished}',
            'currentTime': time_converter(currentTime_seconds),
            'totalDuration': time_converter(duration_seconds),
            'lastUpdated': f'{converted_lastUpdate}'
        }

        return formatted_info


async def bookshelf_mark_book_finished(item_id: str, session_id: str):
    """
    Explicitly mark a book as finished by setting progress to 100% and isFinished to True
    :param item_id: The library item ID
    :param session_id: The current session ID
    :return: True if successful, False otherwise
    """
    try:
        # First, get the book's total duration
        endpoint = f"/items/{item_id}"
        r = await bookshelf_conn(GET=True, endpoint=endpoint)

        if r.status_code != 200:
            logger.error(f"Failed to get book details for {item_id}")
            return False

        data = r.json()

        # Calculate total duration from audio files
        files_raw = data['media'].get('audioFiles', [])
        total_duration = sum(int(file.get('duration', 0)) for file in files_raw)

        if total_duration <= 0:
            logger.error(f"Invalid total duration for book {item_id}")
            return False

        # Update session to mark as finished
        sync_endpoint = f"/session/{session_id}/sync"
        headers = {'Content-Type': 'application/json'}

        # Set the current time to the very end and mark as finished
        session_update = {
            'currentTime': float(total_duration),
            'timeListened': 1.0,  # Small amount to trigger the update
            'duration': float(total_duration)
        }

        r_session_update = await bookshelf_conn(POST=True, endpoint=sync_endpoint,
                                              Data=session_update, Headers=headers)

        if r_session_update.status_code == 200:
            logger.info(f"Successfully marked book {item_id} as finished")

            # Now explicitly set the progress to finished via the progress endpoint
            progress_endpoint = f"/me/progress/{item_id}"
            progress_update = {
                'isFinished': True,
                'progress': 1.0,
                'currentTime': float(total_duration)
            }

            # Use PATCH method for progress update
            async with httpx.AsyncClient() as client:
                bookshelfURL = os.environ.get("bookshelfURL")
                bookshelfToken = os.environ.get("bookshelfToken") 
                api_url = f"{bookshelfURL}/api{progress_endpoint}?token={bookshelfToken}"

                progress_response = await client.patch(api_url, json=progress_update, 
                                                     headers={'Content-Type': 'application/json'})

                if progress_response.status_code == 200:
                    logger.info(f"Successfully updated progress for book {item_id} to finished")
                    return True
                else:
                    logger.warning(f"Failed to update progress endpoint, but session was updated. Status: {progress_response.status_code}")
                    return True  # Session update worked, so consider it successful
        else:
            logger.error(f"Failed to update session for finished book. Status: {r_session_update.status_code}")
            return False

    except Exception as e:
        logger.error(f"Error marking book as finished: {e}")
        return False


async def bookshelf_mark_book_unfinished(item_id: str):
    """
    Mark a book as not finished by setting progress and resetting isFinished to False
    :param item_id: The library item ID
    :return: True if successful, False otherwise
    """
    try:
        # Update progress to mark as not finished
        progress_endpoint = f"/me/progress/{item_id}"
        progress_update = {
            'isFinished': False,
            'progress': 0.0,
            'currentTime': 0.0
        }

        # Use PATCH method for progress update
        async with httpx.AsyncClient() as client:
            bookshelfURL = os.environ.get("bookshelfURL")
            bookshelfToken = os.environ.get("bookshelfToken") 
            api_url = f"{bookshelfURL}/api{progress_endpoint}?token={bookshelfToken}"

            progress_response = await client.patch(api_url, json=progress_update, 
                                                 headers={'Content-Type': 'application/json'})

            if progress_response.status_code == 200:
                logger.info(f"Successfully marked book {item_id} as not finished")
                return True
            else:
                logger.error(f"Failed to mark book as not finished. Status: {progress_response.status_code}")
                return False

    except Exception as e:
        logger.error(f"Error marking book as not finished: {e}")
        return False


async def bookshelf_title_search(display_title: str) -> list:
    """
    :param display_title:
    :return: found_titles(list)
    """
    libraries = await bookshelf_libraries()
    valid_media_types = ['book']

    valid_libraries = []
    valid_library_count = 0
    found_titles = []

    # Get valid libraries
    for name, (library_id, audiobooks_only) in libraries.items():
        # Parse for the library that is only audio
        valid_libraries.append({"id": library_id, "name": name})
        valid_library_count += 1
        logger.debug(f"Valid Libraries Found: {valid_library_count} | Name: {name}\n")

    if valid_library_count > 0:

        # Search the libraries for the title name
        for lib_id in valid_libraries:
            library_iD = lib_id.get('id')
            logger.debug(f"Beginning to search libraries: {lib_id.get('name')} | {library_iD}\n")
            # Search for the title name using endpoint
            try:
                limit = 10
                endpoint = f"/libraries/{library_iD}/search"
                params = f"&q={display_title}&limit={limit}"
                r = await bookshelf_conn(endpoint=endpoint, GET=True, params=params)
                logger.debug(f"status code: {r.status_code}")
                if r.status_code == 200:
                    data = r.json()

                    successMSG(endpoint, r.status_code)
                    dataset = data.get('book', [])
                    for book in dataset:
                        authors_list = []
                        title = book['libraryItem']['media']['metadata']['title']
                        authors_raw = book['libraryItem']['media']['metadata']['authors']

                        for author in authors_raw:
                            name = author.get('name')
                            authors_list.append(name)

                        authors = ', '.join(authors_list)

                        book_id = book['libraryItem']['id']
                        media_type = book['libraryItem']['mediaType']
                        # Add to dict
                        if media_type in valid_media_types:
                            logger.debug(f'accepted: {title} | media type: {media_type}')
                            found_titles.append({'id': book_id, 'title': title, 'author': authors})
                        else:
                            logger.warning(f'rejected: {title}, reason: media-type {media_type} rejected')

                    # Append None to book_titles if nothing is found
                    logger.debug(found_titles)
                    return found_titles

            except Exception as e:
                logger.error(f'Error occured: {e}')
                logger.error(traceback.print_exc())


async def bookshelf_search_users(name):
    endpoint = "/users"

    r = await bookshelf_conn(GET=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()

        # Search users for specified name
        for user in data['users']:
            if user['username'] == name:
                isFound = True
                username = user['username']
                user_id = user['id']
                last_seen = user['lastSeen'] / 1000
                isActive = user['isActive']

                # convert last seen
                c_last_seen = datetime.fromtimestamp(last_seen)
                c_last_seen = c_last_seen.strftime('%Y-%m-%d %H:%M:%S')

                return isFound, username, user_id, c_last_seen, isActive


async def get_users() -> dict:
    endpoint = "/users"

    r = await bookshelf_conn(GET=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()

        return data


async def bookshelf_create_user(username: str, password, user_type: str, email=None):
    user_type = user_type.lower()
    if user_type in ["guest", "user"]:
        endpoint = "/users"
        headers = {'Content-Type': 'application/json'}
        user_params = {'username': username, 'password': str(password), 'type': user_type, 'email': email}

        # Send Post request to generate user
        r = await bookshelf_conn(POST=True, endpoint=endpoint, Headers=headers, Data=user_params)
        if r.status_code == 200:
            data = r.json()
            print(data)

            user_id = data['user']['id']
            username = data['user']['username']

            return user_id, username
        else:
            print(r.status_code)


async def bookshelf_library_csv(library_id: str, file_name='books.csv'):
    bookshelfToken = os.getenv('bookshelfToken')
    endpoint = f'/libraries/{library_id}'
    headers = {'Authorization': f'Bearer {bookshelfToken}'}
    params = '?sort=media.metadata.authorName'

    response = await bookshelf_conn(GET=True, endpoint=endpoint, Headers=headers, params=params)
    if response.status_code == 200:

        data = response.json()['results']

        # CSV file creation
        with open(file_name, 'w', newline='') as file:
            writer = csv.writer(file)
            # Writing the headers
            writer.writerow(["Title", "Author", "Series", "Year"])

            for result in data:
                title = result['media']['metadata']['title']
                author = result['media']['metadata']['authorName']
                series = result['media']['metadata']['seriesName']
                year = result['media']['metadata']['publishedYear']

                # Writing the data
                writer.writerow([title, author, series, year])


async def bookshelf_cover_image(item_id: str):
    """
    :param item_id:
    :return: cover link
    """
    if optional_image_url != '':
        bookshelfURL = optional_image_url
    else:
        bookshelfURL = os.environ.get("bookshelfURL")
    defaultAPIURL = bookshelfURL + '/api'
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken

    # Generates Cover Link
    endpoint = f"/items/{item_id}/cover"
    link = f"{defaultAPIURL}{endpoint}{tokenInsert}"

    return link


async def bookshelf_all_library_items(library_id, params=''):
    found_titles = []
    endpoint = f"/libraries/{library_id}/items"
    if params == '':
        params = '&sort=media.metadata.title'
    else:
        params = '&' + params
    r = await bookshelf_conn(GET=True, endpoint=endpoint, params=params)
    if r.status_code == 200:
        data = r.json()

        dataset = data.get('results', [])
        for items in dataset:
            book_title = items['media']['metadata']['title']
            author = items['media']['metadata'].get('authorName')
            media_type = items['mediaType']
            item_id = items['id']

            # Added time is in linux
            addedTime = items['addedAt']

            try:
                ebook = items['media']['ebookFormat']
            except KeyError:
                found_titles.append({'id': item_id, 'title': book_title, 'author': author, 'addedTime': addedTime,
                                     "mediaType": media_type})

        return found_titles


# NOT CURRENTLY IN USE
async def bookshelf_list_backup():
    endpoint = "/backups"
    backup_IDs = []
    r = await bookshelf_conn(POST=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()
        for item in data['backups']:
            backup_id = item['id']
            backup_IDs.append(backup_id)
        print(backup_IDs)


async def bookshelf_get_current_chapter(item_id: str, current_time=0):
    """
    :param item_id:
    :param current_time:
    :return: foundChapter, chapter_array, book_finished, isPodcast
    """
    try:
        progress_endpoint = f"/me/progress/{item_id}"
        endpoint = f"/items/{item_id}"
        book_finished = False

        progress_r = await bookshelf_conn(GET=True, endpoint=progress_endpoint)

        if progress_r.status_code == 200:
            progress_data = progress_r.json()
            if "currentTime" in progress_data:
                current_time = progress_data.get('currentTime', 0)
                book_finished = progress_data.get('isFinished', False)
            else:
                book_finished = False

        r = await bookshelf_conn(GET=True, endpoint=endpoint)

        if r.status_code == 200:
            # Place data in JSON Format
            data = r.json()
            mediaType = data['mediaType']
            if mediaType == 'podcast':
                isPodcast = True
                foundChapter = {}
                chapter_array = []
                book_finished = False
                return foundChapter, chapter_array, book_finished, isPodcast
            else:
                isPodcast = False

            chapter_array = []
            foundChapter = {}

            for chapters in data['media']['chapters']:
                chapter_array.append(chapters)

            for chapter in chapter_array:
                chapter_start = float(chapter.get('start'))
                chapter_end = float(chapter.get('end'))

                # Verify if in current chapter
                if current_time >= chapter_start and current_time < chapter_end:  # NOQA
                    chapter["currentTime"] = current_time
                    foundChapter = chapter

            if chapter_array and foundChapter is not None:
                return foundChapter, chapter_array, book_finished, isPodcast

            # If no matching chapter found but chapters exist, use the first chapter
            if chapter_array:
                foundChapter = chapter_array[0]
                return foundChapter, chapter_array, book_finished, isPodcast
            
            # If no chapters at all
            return {}, [], book_finished, isPodcast

    except Exception as e:
        logger.error(f"Error in bookshelf_get_current_chapter for item {item_id}: {e}")
        # Return default values instead of None
        return {}, [], False, False  # Default empty values that are unpacked correctly

async def bookshelf_audio_obj(item_id: str, index_id: int = 1):
    """
    Fetches audio playback details for a given book item.

    :param item_id: Book item ID.
    :param index_id: The file number index.
    :return: Tuple containing (onlineURL, currentTime, session_id, bookTitle, bookDuration)
    """

    endpoint = f"/items/{item_id}/play"
    headers = {'Content-Type': 'application/json'}
    data = {
        "deviceInfo": {"clientName": "Bookshelf-Traveller", "deviceId": "Bookshelf-Traveller"},
        "supportedMimeTypes": ["audio/flac", "audio/mp4"],
        "mediaPlayer": "Discord",
        "forceDirectPlay": "true"
    }

    bookshelfURL = os.environ.get("bookshelfURL", "")
    bookshelfToken = os.environ.get("bookshelfToken", "")

    if not bookshelfURL or not bookshelfToken:
        logger.error("Missing Bookshelf URL or Token in environment variables.")
        return None

    defaultAPIURL = f"{bookshelfURL}/api"
    tokenInsert = f"?token={bookshelfToken}"

    # Send request to play
    audio_obj = await bookshelf_conn(POST=True, endpoint=endpoint, Headers=headers, Data=data)

    if not audio_obj or audio_obj.status_code != 200:
        logger.error(f"Failed to retrieve audio data. Status code: {audio_obj.status_code}")
        return None

    try:
        data = audio_obj.json()
    except Exception as e:
        logger.error(f"Error parsing JSON response: {e}")
        return None

    # Extract audio metadata
    library_item = data.get("libraryItem", {})
    audiofiles = library_item.get("media", {}).get("audioFiles", [])
    mediaType = library_item.get("mediaType", "unknown")
    currentTime = data.get("currentTime", 0)
    session_id = data.get("id", "")
    bookTitle = data.get("mediaMetadata", {}).get("title", "Unknown Title")
    bookDuration = data.get("duration", None)

    if not audiofiles:
        logger.warning(f"No audio files found for item {item_id}")
        return None

    logger.debug(f"{len(audiofiles)} audio files found for item {item_id}")

    # Get the requested audio file or fallback to the first one
    selected_file = next((file for file in audiofiles if file.get('index') == index_id), audiofiles[0])
    ino = selected_file.get('ino', '')

    if not ino:
        logger.error(f"Invalid file index {index_id} for item {item_id}.")
        return None

    logger.info(f"Media Type: {mediaType}, Current Time: {currentTime} Seconds")

    onlineURL = f"{defaultAPIURL}/items/{item_id}/file/{ino}{tokenInsert}"
    logger.info(f"Attempting to play: {onlineURL}")

    return onlineURL, currentTime, session_id, bookTitle, bookDuration


async def bookshelf_session_update(session_id: str, item_id: str, current_time: float, next_time=None, mark_finished=False):
    """
    :param session_id:
    :param item_id:
    :param current_time:
    :param next_time:
    :param mark_finished: If True, explicitly mark the book as finished
    :return: if successful: updatedTime, duration, serverCurrentTime, finished_book
    """
    get_session_endpoint = f"/session/{session_id}"
    sync_endpoint = f"/session/{session_id}/sync"

    # Session Checks
    sessionOK = False
    finished_book = False
    updatedTime = 0.0
    serverCurrentTime = 0.0
    duration = 0.0

    if current_time > 1 or mark_finished:

        try:

            # Check if session is open
            r_session_info = await bookshelf_conn(GET=True, endpoint=get_session_endpoint)

            if r_session_info.status_code == 200:
                # Format to JSON
                data = r_session_info.json()
                # Pull Session Info
                duration = float(data.get('duration'))
                serverCurrentTime = float(data.get('currentTime'))
                session_itemID = data.get('libraryItemId')

                # Create Updated Time
                if mark_finished:
                    # Force finish the book
                    updatedTime = duration
                    finished_book = True
                    sessionOK = True
                elif next_time is not None:
                    try:
                        updatedTime = float(next_time)
                    except (TypeError, ValueError):
                        updatedTime = serverCurrentTime + current_time
                        logger.warning("Error, nextTime was not valid, using fallback")
                else:
                    updatedTime = serverCurrentTime + current_time

                # Check if session matches the current item playing
                if item_id == session_itemID and updatedTime <= duration and not mark_finished:
                    sessionOK = True


                # If Updated Time is greater than duration OR mark_finished is True, finish the book
                elif updatedTime > duration or mark_finished:
                    sessionOK = True
                    updatedTime = duration
                    finished_book = True

            if sessionOK:
                headers = {'Content-Type': 'application/json'}
                session_update = {
                    'currentTime': float(updatedTime),  # NOQA
                    'timeListened': float(current_time),
                    'duration': float(duration)  # NOQA
                }

                r_session_update = await bookshelf_conn(POST=True, endpoint=sync_endpoint,
                                                        Data=session_update, Headers=headers)

                if r_session_update.status_code == 200:
                    logger.debug(f'bookshelf session sync successful. {updatedTime}')

                    # If we're marking as finished, make sure to explicitly mark it
                    if finished_book and mark_finished:
                        success = await bookshelf_mark_book_finished(item_id, session_id)
                        if not success:
                            logger.warning("Failed to explicitly mark book as finished, but session was updated")

                    return updatedTime, duration, serverCurrentTime, finished_book
            else:
                logger.warning(f"Session sync failed, sync status: {sessionOK}")

        except Exception as e:
            logger.warning(f"Issue with sync: {e}")

    # If we reach here, something went wrong - return default values
    return updatedTime, duration, serverCurrentTime, finished_book

# Need to  revisit this at some point
async def bookshelf_close_session(session_id: str):
    """
    :param session_id
    :return: None
    """
    endpoint = f"/session/{session_id}/close"
    try:
        r = await bookshelf_conn(endpoint=endpoint, POST=True)
        if r.status_code == 200:
            logger.info(f'Session {session_id} closed successfully')
        else:
            logger.warning(r.status_code)

    except requests.RequestException as e:
        logger.error(f"Failed to close session {session_id}")
        logger.warning(f"Failed to close session: {session_id}, {e}")
        print(f"{e}")

    except Exception as e:
        logger.warning(f"Failed to close session: {session_id}, {e}")


# Closes all sessions that have been opened while bot was connected to voice
async def bookshelf_close_all_sessions(items: int):
    all_sessions_endpoint = f"/me/listening-sessions"

    params = f"&itemsPerPage={items}"
    try:
        r = await bookshelf_conn(GET=True, endpoint=all_sessions_endpoint, params=params)
        if r.status_code == 200:
            data = r.json()

            openSessionCount = 0
            closedSessionCount = 0
            failedSessionCount = 0

            session_array = []

            for session in data['sessions']:
                openSessionCount += 1
                sessionId = session.get('id')
                session_array.append({'id': sessionId})

            if openSessionCount > 0:

                print(f"Attempting to close {openSessionCount} sessions")
                for session in session_array:
                    sessionId = session.get('id')
                    close_session = f"/session/{sessionId}/close"

                    r = await bookshelf_conn(endpoint=close_session, POST=True)
                    if r.status_code == 200:
                        closedSessionCount += 1
                        print(f"Successfully Closed Session with ID: {sessionId}")
                    else:
                        failedSessionCount += 1
                        print(f"Failed to close session with id: {sessionId}")

            logger.info(f"success: {closedSessionCount}, failed: {failedSessionCount}, total: {openSessionCount} ")
            return openSessionCount, closedSessionCount, failedSessionCount

    except Exception as e:
        logger.error(e)


async def bookshelf_search_books(title: str, provider=DEFAULT_PROVIDER, author='') -> list:
    """
    :param title:
    :param provider:
    :param author:
    :returns: data -> item object from ABS api.
    """
    endpoint = '/search/books'
    bookshelfToken = os.environ.get("bookshelfToken")
    bookshelfURL = os.getenv('bookshelfURL')
    bookshelfURL = bookshelfURL + "/api" + endpoint

    logger.info(f'Initializing book search for title {title} using ABS providers.')
    tokenHeaders = {f"Authorization": f"Bearer {bookshelfToken}"}
    providers = ['google', 'openlibrary', 'itunes', 'audible', 'audible.ca', 'audible.uk', 'audible.au', 'audible.fr',
                 'audible.it', 'audible.in', 'audible.es', 'fantlab']
    provider_valid = False

    if provider in providers:
        logger.info(f"Valid provider {DEFAULT_PROVIDER} selected!")
        provider_valid = True
    else:
        logger.warning(f"Provider {DEFAULT_PROVIDER} is not valid, falling back to default!")

    if provider == '' or provider_valid is False:
        provider = providers[1]
        logger.info(f"Fallback to default provider {provider} selected!")

    if author == '':
        params = {"title": title, "provider": provider}
    else:
        params = {"title": title, "author": author, "provider": provider}

    # GET Request for book title
    async with httpx.AsyncClient() as client:
        response = await client.get(url=bookshelfURL, params=params, headers=tokenHeaders)

        if response.status_code == 200:
            data = response.json()
            # Debug
            if __name__ == '__main__':
                print(data)
            return data


async def bookshelf_get_valid_books() -> list:
    """
    :returns: found_books -> a list of all library items which is in a valid audio format.
    """
    libraries = await bookshelf_libraries()
    # Get libraries
    found_books = []
    for name, (library_id, audiobooks_only) in libraries.items():
        books = await bookshelf_all_library_items(library_id)
        for book in books:
            book_title = book.get('title')
            book_id = book.get('id')
            book_authors = book.get('author')
            found_books.append({"title": book_title, "author": book_authors, "id": book_id})

    return found_books


# Test bookshelf api functions below
async def main():
    if __name__ == '__main__':
        print("TESTING COMMENCES")
        books = await bookshelf_get_valid_books()
        print(books)
        data = await get_users()
        users = data['users']

        completed_list = []
        for user in users:
            user_id = user.get('id')
            username = user.get('username')

            endpoint = f'/users/{user_id}'
            r = await bookshelf_conn(endpoint=endpoint, GET=True)
            if r.status_code == 200:
                media_progress_count = 0
                user_data = r.json()

                for media in user_data['mediaProgress']:
                    media_type = media['mediaItemType']
                    libraryItemId = media['libraryItemId']
                    finished = bool(media.get('isFinished'))
                    # Verify it's a book and not a podcast
                    if media_type == 'book' and finished:
                        media['username'] = username
                        print(media)
                        completed_list.append(libraryItemId)
                        media_progress_count += 1
                print("completed media items: ", media_progress_count)


asyncio.run(main())
