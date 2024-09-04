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
    count = 0

    while not connected:
        count += 1
        try:
            # Using /healthcheck to avoid domain mismatch, since this is an api endpoint in bookshelf
            r = requests.get(f'{bookshelfURL}/healthcheck')
            status = r.status_code
            if status == 200:
                connected = True
                logger.info("Connection Established!")
                return status

            elif status != 200 and count >= 11:
                logger.error("Connection could not be established, Quitting!")
                time.sleep(1)
                sys.exit(1)

            else:
                print("\nConnection Error, retrying in 5 seconds!")
                time.sleep(5)
                print(f"Retrying! Attempt: {count}")

        except requests.RequestException as e:
            logger.warning("Error occured while testing server connection: ", e, "\n")

        except UnboundLocalError:
            logger.error("No URL PROVIDED!\n")
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

            time.sleep(0.5)
            return username, user_type, user_locked
        else:
            print("Error: Could not connect to /me endpoint \n")
            print("Quitting!")
            time.sleep(0.5)
            sys.exit(1)

    except requests.RequestException as e:
        logger.warning("Could not establish connection: ", e)

    finally:
        logger.info("Cleaning up, authentication")


async def bookshelf_get_item_details(book_id) -> dict:
    """
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
    # Get Media Title
    _url = f"/items/{book_id}"
    r = await bookshelf_conn(GET=True, endpoint=_url)
    data = r.json()
    print(data)

    title = data['media']['metadata']['title']
    desc = data['media']['metadata']['description']
    language = data['media']['metadata']['language']
    publishedYear = data['media']['metadata']['publishedYear']
    publisher = data['media']['metadata']['publisher']
    addedDate = data['addedAt']

    authors_list = []
    narrators_list = []
    duration_sec = 0
    series = ''

    narrators_raw = data['media']['metadata']['narrators']
    authors_raw = data['media']['metadata']['authors']
    series_raw = data['media']['metadata']['series']
    files_raw = data['media']['audioFiles']
    genres_raw = data['media']['metadata']['genres']

    for author in authors_raw:
        name = author.get('name')
        authors_list.append(name)

    for narrator in narrators_raw:
        narrators_list.append(narrator)

    for series in series_raw:
        series_name = series.get('name')
        series_seq = series.get('sequence')
        series = f"{series_name}, Book {series_seq}"

    for file in files_raw:
        file_duration = int(file['duration'])
        duration_sec += file_duration

    authors = ', '.join(authors_list)
    narrators = ', '.join(narrators_list)
    genres = ', '.join(genres_raw)

    formatted_data = {
        'title': title,
        'author': authors,
        'narrator': narrators,
        'series': series,
        'publisher': publisher,
        'genres': genres,
        'publishedYear': publishedYear,
        'description': desc,
        'language': language,
        'duration': duration_sec,
        'addedDate': addedDate
    }

    return formatted_data


async def bookshelf_listening_stats():
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
        currentTime = data['currentTime'] / 3600
        duration = data['duration'] / 3600
        lastUpdate = data['lastUpdate'] / 1000

        # Convert lastUpdate Time from unix to standard time
        # Conversions Below
        lastUpdate = datetime.utcfromtimestamp(lastUpdate)
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
            'currentTime': f'{round(currentTime, 2)}',
            'totalDuration': f'{round(duration, 2)}',
            'lastUpdated': f'{converted_lastUpdate}'
        }

        return formatted_info


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


async def bookshelf_get_users(name):
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
                c_last_seen = datetime.utcfromtimestamp(last_seen)
                c_last_seen = c_last_seen.strftime('%Y-%m-%d %H:%M:%S')

                return isFound, username, user_id, c_last_seen, isActive


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
            author = items['media']['metadata']['authorName']
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

    except requests.RequestException as e:
        print("Could not retrieve item", e)


async def bookshelf_audio_obj(item_id: str):
    """
    :param item_id:
    :return: onlineURL, currentTime, session_id, bookTitle, bookDuration
    """
    endpoint = f"/items/{item_id}/play"
    headers = {'Content-Type': 'application/json'}
    data = {"deviceInfo": {"clientName": "Bookshelf-Traveller", "deviceId": "Bookshelf-Traveller"},
            "supportedMimeTypes": ["audio/flac", "audio/mp4"], "mediaPlayer": "Discord", "forceDirectPlay": "true"}

    bookshelfURL = os.environ.get("bookshelfURL")
    defaultAPIURL = bookshelfURL + "/api"
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken

    # Send request to play
    audio_obj = await bookshelf_conn(POST=True, endpoint=endpoint, Headers=headers, Data=data)

    data = audio_obj.json()

    # Library Vars
    ino = ""
    audiofiles = data['libraryItem']['media']['audioFiles']
    mediaType = data['libraryItem']['mediaType']
    currentTime = data['currentTime']
    session_id = data['id']
    bookTitle = data['mediaMetadata']['title']
    bookDuration = data.get('duration')

    for file in audiofiles:
        ino = file['ino']

    logger.info(f"Media Type:  {mediaType}, Current Time: {currentTime} Seconds")

    onlineURL = f"{defaultAPIURL}/items/{item_id}/file/{ino}{tokenInsert}"
    logger.info(f"attempting to play: {defaultAPIURL}/items/{item_id}/file/{ino}")

    return onlineURL, currentTime, session_id, bookTitle, bookDuration


async def bookshelf_session_update(session_id: str, item_id: str, current_time: float, next_time=None):
    """
    :param session_id:
    :param item_id:
    :param current_time:
    :param next_time:
    :return: if successful: updatedTime, duration, serverCurrentTime, finished_book
    """
    get_session_endpoint = f"/session/{session_id}"
    sync_endpoint = f"/session/{session_id}/sync"

    # Session Checks
    sessionOK = False
    finished_book = False
    updatedTime = 0.0
    serverCurrentTime = 0.0

    if current_time > 1:

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
                if next_time is None:
                    updatedTime = serverCurrentTime + current_time
                elif next_time is not None:
                    try:
                        updatedTime = float(next_time)
                    except TypeError:
                        updatedTime = serverCurrentTime + current_time
                        print("Error, nextTime was not valid")

                logger.info(
                    f"Duration: {duration}, Current Time: {serverCurrentTime}, Updated Time: {updatedTime}")

                # Check if session matches the current item playing
                if item_id == session_itemID and updatedTime <= duration:
                    sessionOK = True

                # If Updated Time is greater, make updated time duration. (Finish book)
                elif updatedTime > duration:
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
                    logger.info(f'session sync successful. {updatedTime}')

                    return updatedTime, duration, serverCurrentTime, finished_book
            else:
                print(f"Session sync failed, sync status: {sessionOK}")

        except requests.RequestException as e:
            logger.warning(f"Issue with sync post request: {e}")
            print(e)

        except Exception as e:
            logger.warning(f"Issue with sync: {e}")


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
        item = await bookshelf_get_item_details("1917bece-b5b8-4355-8c23-6f0769761785")
        print(item)


asyncio.run(main())
