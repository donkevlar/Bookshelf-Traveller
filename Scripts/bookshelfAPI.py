import os
import sys
import time
from collections import defaultdict
from datetime import datetime
import traceback
import csv
import logging
from dotenv import load_dotenv
import requests

# Logger Config
logger = logging.getLogger("bot")

# DEV ENVIRON VARS
load_dotenv()

keep_active = False


# Simple Success Message
def successMSG(endpoint, status):
    logger.info(f'Successfully Reached {endpoint} with Status {status}')


def bookshelf_conn(endpoint: str, Headers=None, Data=None, Token=True, GET=False,
                   POST=False, params=None):
    bookshelfURL = os.environ.get("bookshelfURL")
    API_URL = bookshelfURL + "/api"
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken
    if params is not None:
        additional_params = params
    else:
        additional_params = ''

    if Token:
        link = f'{API_URL}{endpoint}{tokenInsert}{additional_params}'
    else:
        link = f'{API_URL}{endpoint}'

    if GET:
        r = requests.get(link)
        return r
    elif POST:
        if Data is not None and Headers is not None:
            r = requests.post(link, headers=Headers, json=Data)
            return r
        else:
            r = requests.post(link)
            return r
    else:
        logger.warning('Must include GET, POST or PATCH in arguments')
        raise Exception


# Test initial Connection to Bookshelf Server
def bookshelf_test_connection():
    bookshelfURL = os.environ.get("bookshelfURL")
    logger.info("Testing Server Connection")
    logger.info(f"Server URL  {bookshelfURL}")
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
def bookshelf_auth_test():
    logger.info("Providing Auth Token to Server")
    try:
        endpoint = "/me"
        r = bookshelf_conn(GET=True, endpoint=endpoint)
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


def bookshelf_listening_stats():
    bookshelfToken = os.environ.get("bookshelfToken")
    endpoint = "/me/listening-stats"
    formatted_sessions = []

    r = bookshelf_conn(GET=True, endpoint=endpoint)

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


def bookshelf_libraries():
    endpoint = "/libraries"
    library_data = {}
    r = bookshelf_conn(GET=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()
        successMSG(endpoint, r.status_code)
        for library in data['libraries']:
            name = library['name']
            library_id = library['id']
            audiobooks_only = library['settings'].get('audiobooksOnly')
            library_data[name] = (library_id, audiobooks_only)

        print(library_data)
        return library_data


def bookshelf_item_progress(item_id):
    endpoint = f"/me/progress/{item_id}"
    r = bookshelf_conn(GET=True, endpoint=endpoint)
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
        r = bookshelf_conn(GET=True, endpoint=secondary_url)
        data = r.json()
        title = data['media']['metadata']['title']

        formatted_info = {
            'title': f'{title}',
            'progress': f'{progress}%',
            'finished': f'{isFinished}',
            'currentTime': f'{round(currentTime, 2)}',
            'totalDuration': f'{round(duration, 2)}',
            'lastUpdated': f'{converted_lastUpdate}'
        }

        return formatted_info


def bookshelf_title_search(display_title: str, only_audio=True):
    libraries = bookshelf_libraries()

    valid_libraries = []
    valid_library_count = 0
    found_titles = []

    # Get valid libraries using filter only_audio
    for name, (library_id, audiobooks_only) in libraries.items():
        # Parse for the library that is only audio
        if only_audio and audiobooks_only:
            valid_libraries.append({"id": library_id, "name": name})
            valid_library_count += 1
            print(f"\nValid Libraries Found: {valid_library_count} | Name: {name}\n")
        # Parse for the library that is anything
        elif only_audio is False and audiobooks_only is False:
            valid_libraries.append({"id": library_id, "name": name})
            valid_library_count += 1
            print(f"Valid Libraries Found: {valid_library_count}\n")

    if valid_library_count > 0:

        # Search the libraries for the title name
        for lib_id in valid_libraries:
            library_iD = lib_id.get('id')
            print(f"Beginning to search libraries: {lib_id.get('name')} | {library_iD}\n")
            # Search for the title name using endpoint
            try:
                limit = 10
                endpoint = f"/libraries/{library_iD}/search"
                params = f"&q={display_title}&limit={limit}"
                r = bookshelf_conn(endpoint=endpoint, GET=True, params=params)
                print(f"\nstatus code: {r.status_code}")
                if r.status_code == 200:
                    data = r.json()

                    # print(f"returned data: {data}")

                    successMSG(endpoint, r.status_code)
                    dataset = data.get('book', [])
                    for book in dataset:
                        title = book['libraryItem']['media']['metadata']['title']
                        book_id = book['libraryItem']['id']
                        # Add to dict
                        found_titles.append({'id': book_id, 'title': title})

                    # Append None to book_titles if nothing is found
                    print(found_titles)
                    return found_titles

            except Exception as e:
                print(f'Error occured: {e}')
                traceback.print_exc()


def bookshelf_get_users(name):
    endpoint = "/users"

    r = bookshelf_conn(GET=True, endpoint=endpoint)
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


def bookshelf_create_user(username: str, password, user_type: str, email=None):
    user_type = user_type.lower()
    if user_type in ["guest", "user"]:
        endpoint = "/users"
        headers = {'Content-Type': 'application/json'}
        user_params = {'username': username, 'password': str(password), 'type': user_type, 'email': email}

        # Send Post request to generate user
        r = bookshelf_conn(POST=True, endpoint=endpoint, Headers=headers, Data=user_params)
        if r.status_code == 200:
            data = r.json()
            print(data)

            user_id = data['user']['id']
            username = data['user']['username']

            return user_id, username
        else:
            print(r.status_code)


def bookshelf_library_csv(library_id: str, file_name='books.csv'):
    bookshelfToken = os.getenv('bookshelfToken')
    endpoint = f'/libraries/{library_id}'
    headers = {'Authorization': f'Bearer {bookshelfToken}'}
    params = '?sort=media.metadata.authorName'

    response = bookshelf_conn(GET=True, endpoint=endpoint, Headers=headers, params=params)
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


def bookshelf_cover_image(item_id: str):
    bookshelfURL = os.environ.get("bookshelfURL")
    defaultAPIURL = bookshelfURL + '/api'
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken

    # Generates Cover Link
    endpoint = f"/items/{item_id}/cover"
    link = f"{defaultAPIURL}{endpoint}{tokenInsert}"

    return link


def bookshelf_all_library_items(library_id):
    found_titles = []
    endpoint = f"/libraries/{library_id}/items"
    params = '&sort=media.metadata.title'
    r = bookshelf_conn(GET=True, endpoint=endpoint, params=params)
    if r.status_code == 200:
        data = r.json()

        dataset = data.get('results', [])
        for items in dataset:
            book_title = items['media']['metadata']['title']
            author = items['media']['metadata']['authorName']
            book_id = items['media']['id']

            found_titles.append({'id': book_id, 'title': book_title, 'author': author})

        print(found_titles)
        return found_titles


# NOT CURRENTLY IN USE
def bookshelf_list_backup():
    endpoint = "/backups"
    backup_IDs = []
    r = bookshelf_conn(POST=True, endpoint=endpoint)
    if r.status_code == 200:
        data = r.json()
        for item in data['backups']:
            backup_id = item['id']
            backup_IDs.append(backup_id)
        print(backup_IDs)


def bookshelf_get_current_chapter(item_id: str, current_time=0):
    try:
        progress_endpoint = f"/me/progress/{item_id}"
        endpoint = f"/items/{item_id}"
        book_finished = False

        progress_r = bookshelf_conn(GET=True, endpoint=progress_endpoint)

        if progress_r.status_code == 200:
            progress_data = progress_r.json()
            if "currentTime" in progress_data:
                current_time = progress_data.get('currentTime', 0)
                book_finished = progress_data.get('isFinished', False)
            else:
                book_finished = False

        r = bookshelf_conn(GET=True, endpoint=endpoint)

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


def bookshelf_audio_obj(item_id: str):
    endpoint = f"/items/{item_id}/play"
    params = "&forceDirectPlay=true&mediaPlayer=discord"

    bookshelfURL = os.environ.get("bookshelfURL")
    defaultAPIURL = bookshelfURL + "/api"
    bookshelfToken = os.environ.get("bookshelfToken")
    tokenInsert = "?token=" + bookshelfToken

    # Send request to play
    audio_obj = bookshelf_conn(POST=True, params=params, endpoint=endpoint)

    data = audio_obj.json()

    # Library Vars
    ino = ""
    audiofiles = data['libraryItem']['media']['audioFiles']
    mediaType = data['libraryItem']['mediaType']
    currentTime = data['currentTime']
    session_id = data['id']
    bookTitle = data['mediaMetadata']['title']

    for file in audiofiles:
        ino = file['ino']

    print("Media Type: ", mediaType)
    print("Current Time: ", currentTime, "Seconds")

    onlineURL = f"{defaultAPIURL}/items/{item_id}/file/{ino}{tokenInsert}"
    print("attempting to play: ", onlineURL)

    return onlineURL, currentTime, session_id, bookTitle


def bookshelf_session_update(session_id: str, item_id: str, current_time: float, next_time=None):
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
            r_session_info = bookshelf_conn(GET=True, endpoint=get_session_endpoint)

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
                r_session_update = bookshelf_conn(POST=True, endpoint=sync_endpoint,
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
def bookshelf_close_session(session_id: str):
    endpoint = f"/session/{session_id}/close"
    try:
        r = bookshelf_conn(endpoint=endpoint, POST=True)
        if r.status_code == 200:
            print(f'Session {session_id} closed successfully')
        else:
            print(r.status_code)

    except requests.RequestException as e:
        print(f"Failed to close session {session_id}")
        logger.warning(f"Failed to close session: {session_id}, {e}")
        print(f"{e}")

    except Exception as e:
        logger.warning(f"Failed to close session: {session_id}, {e}")


# Closes all sessions that have been opened while bot was connected to voice
def bookshelf_close_all_sessions(items: int):
    all_sessions_endpoint = f"/me/listening-sessions"

    params = f"&itemsPerPage={items}"

    r = bookshelf_conn(POST=True, endpoint=all_sessions_endpoint, params=params)
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

                r = bookshelf_conn(endpoint=close_session, POST=True)
                if r.status_code == 200:
                    closedSessionCount += 1
                    print(f"Successfully Closed Session with ID: {sessionId}")
                else:
                    failedSessionCount += 1
                    print(f"Failed to close session with id: {sessionId}")

        logger.info(f"success: {closedSessionCount}, failed: {failedSessionCount}, total: {openSessionCount} ")
        return openSessionCount, closedSessionCount, failedSessionCount


# Test bookshelf api functions below
if __name__ == '__main__':
    print("TESTING COMMENCES")
    bookshelf_title_search("dreadgod")
