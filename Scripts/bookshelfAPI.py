import os
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

# Global Vars
keep_active = False

# Bookshelf Server IP
bookshelfURL = os.environ.get("bookshelfURL")
defaultAPIURL = bookshelfURL + "/api"

# Bookshelf Token
# Use Token at the end of the url with query i.e. URL/api/PLACE?token=TOKEN

bookshelfToken = os.environ.get("bookshelfToken")
tokenInsert = "?token=" + bookshelfToken


# Simple Success Message
def successMSG(endpoint, status):
    print(f'Successfully Reached {endpoint} with Status {status}')


# Test initial Connection to Bookshelf Server
def bookshelf_test_connection():
    print("Testing Server Connection")
    print("Server URL ", bookshelfURL, "\n")
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
                print("\nConnection Established!\n")
                return status

            elif status != 200 and count >= 11:
                print("Connection could not be established, Quitting!")
                time.sleep(1)
                exit()

            else:
                print("\nConnection Error, retrying in 5 seconds!")
                time.sleep(5)
                print(f"Retrying! Attempt: {count}")

        except requests.RequestException as e:
            print("Error occured while testing server connection: ", e, "\n")

        except UnboundLocalError:
            print("No URL PROVIDED!\n")


# Authenticate the user with bookshelf server provided
def bookshelf_auth_test():
    print("\nProviding Auth Token to Server\n")
    try:
        endpoint = "/me"
        r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
        if r.status_code == 200:
            # Place data in JSON Format
            data = r.json()

            username = data.get("username", "")
            user_type = data.get('type', "user")
            user_locked = data.get('isLocked', False)

            print(f'Successfully Authenticated as user {username}, type: {user_type}')
            time.sleep(0.5)
            return username, user_type, user_locked
        else:
            print("Error: Could not connect to /me endpoint \n")
            print("Quitting!")
            time.sleep(0.5)
            exit()

    except requests.RequestException as e:
        print("Could not establish connection: ", e)

    finally:
        print("Cleaning up, authentication\n")


def bookshelf_listening_stats():
    endpoint = "/me/listening-stats"
    formatted_sessions = []
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')

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
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
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
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
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
        r = requests.get(f'{defaultAPIURL}{secondary_url}{tokenInsert}')
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
            print(f"\nValid Libraries Found: {valid_library_count}\n")
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
                limit = 6
                endpoint = f"/libraries/{library_iD}/search?q={display_title}&limit={limit}"
                r = requests.get(f'{defaultAPIURL}{endpoint}&token={bookshelfToken}')
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

    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
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
    if user_type in ["guest", "user", "admin"]:
        endpoint = "/users"
        link = f'{defaultAPIURL}{endpoint}{tokenInsert}'
        headers = {'Content-Type': 'application/json'}
        user_params = {'username': username, 'password': str(password), 'type': user_type, 'email': email}

        # Send Post request to generate user
        r = requests.post(url=link, json=user_params, headers=headers)
        if r.status_code == 200:
            data = r.json()
            print(data)

            user_id = data['user']['id']
            username = data['user']['username']

            return user_id, username
        else:
            print(r.status_code)


def bookshelf_library_csv(library_id: str, file_name='books.csv'):
    headers = {'Authorization': f'Bearer {bookshelfToken}'}

    library_items_api_url = defaultAPIURL + '/libraries/' + library_id + '/items?sort=media.metadata.authorName'

    response = requests.get(library_items_api_url, headers=headers)
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
    # Generates Cover Link
    endpoint = f"/items/{item_id}/cover"
    link = f"{defaultAPIURL}{endpoint}{tokenInsert}"
    return link


def bookshelf_all_library_items(library_id):
    found_titles = []
    endpoint = f"/libraries/{library_id}/items"
    r = requests.get(f"{defaultAPIURL}{endpoint}{tokenInsert}&sort=media.metadata.title")
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


def bookshelf_list_backup():
    endpoint = "/backups"
    link = f"{defaultAPIURL}{endpoint}{tokenInsert}"
    backup_IDs = []
    r = requests.post(link)
    if r.status_code == 200:
        data = r.json()
        for item in data['backups']:
            backup_id = item['id']
            backup_IDs.append(backup_id)
        print(backup_IDs)


def bookshelf_get_current_chapter(itemID: str):
    # Get the formatted data from item progress
    formatted_data = bookshelf_item_progress(itemID)
    # print("\n" + str(formatted_data))
    try:
        book_finished = eval(formatted_data['finished'])

    except TypeError:
        book_finished = False

    # Convert current location time back into seconds from hours
    currentTimeSec = float(formatted_data['currentTime']) * 3600
    # print("\nCurrent Time: " + str(currentTimeSec) + "\n")

    try:
        endpoint = f"/items/{itemID}"
        r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')

        if r.status_code == 200:
            # Place data in JSON Format
            data = r.json()
            chapter_array = []
            foundChapter = {}

            for chapters in data['media']['chapters']:
                chapter_array.append(chapters)

            for chapter in chapter_array:
                chapter_start = float(chapter.get('start'))
                chapter_end = float(chapter.get('end'))

                # Verify if in current chapter
                if currentTimeSec >= chapter_start and currentTimeSec < chapter_end:
                    chapter["currentTime"] = currentTimeSec
                    foundChapter = chapter

            if chapter_array and foundChapter is not None:
                return foundChapter, chapter_array, book_finished

    except requests.RequestException as e:
        print("Could not retrieve item", e)


def bookshelf_audio_obj(itemID: str):
    endpoint = f"/items/{itemID}/play"
    audio_link = f"{defaultAPIURL}{endpoint}{tokenInsert}"

    # Send request to play
    audio_obj = requests.post(audio_link)

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

    onlineURL = f"{defaultAPIURL}/items/{itemID}/file/{ino}{tokenInsert}"
    print("attempting to play: ", onlineURL)

    return onlineURL, currentTime, session_id, bookTitle


def bookshelf_session_update(sessionID: str, itemID: str, currentTime: float, nextTime=None):
    get_session_endpoint = f"/session/{sessionID}"
    sync_endpoint = f"/session/{sessionID}/sync"

    # Session Checks
    sessionOK = False
    finished_book = False
    updatedTime = 0.0

    if currentTime > 1:

        try:

            # Check if session is open
            r_session_info = requests.get(f"{defaultAPIURL}{get_session_endpoint}{tokenInsert}")

            if r_session_info.status_code == 200:
                # Format to JSON
                data = r_session_info.json()
                # Pull Session Info
                duration = float(data['duration'])
                serverCurrentTime = float(data['currentTime'])
                session_itemID = data['libraryItemId']
                # Create Updated Time
                if nextTime is None:
                    updatedTime = serverCurrentTime + currentTime
                elif nextTime is not None:
                    try:
                        updatedTime = float(nextTime)
                    except TypeError:
                        updatedTime = serverCurrentTime + currentTime
                        print("Error, nextTime was not valid")

                logger.info(
                    f"Duration: {duration}, Current Time: {serverCurrentTime}, Updated Time: {updatedTime}, Item ID: {session_itemID}")  # NOQA

                # Check if session matches the current item playing
                if itemID == session_itemID and updatedTime <= duration:
                    sessionOK = True

                # If Updated Time is greater, make updated time duration. (Finish book)
                elif updatedTime > duration:
                    sessionOK = True
                    updatedTime = duration
                    finished_book = True

            if sessionOK:
                session_update = {
                    'currentTime': float(updatedTime),  # NOQA
                    'timeListened': float(currentTime),
                    'duration': float(duration)  # NOQA
                }
                r_session_update = requests.post(f"{defaultAPIURL}{sync_endpoint}{tokenInsert}", data=session_update)
                if r_session_update.status_code == 200:
                    logger.info(f"Successfully synced session to updated time: {updatedTime}")
                    return updatedTime
            else:
                print(f"Session sync failed, sync status: {sessionOK}")

        except requests.RequestException as e:
            logger.warning(f"Issue with sync: \n{e}")
            print(e)

        finally:
            return sessionOK, finished_book


def bookshelf_close_session(sessionID: str):
    endpoint = f"/session/{sessionID}/close"
    try:
        r = requests.post(f'{bookshelfURL}{endpoint}{tokenInsert}')
        if r.status_code == 200:
            print(f'Session {sessionID} closed successfully')

    except requests.RequestException as e:
        print(f"Failed to close session {sessionID}")
        print(f"{e}")


if __name__ == '__main__':
    print("TESTING COMMENCES")
    test_id = os.environ.get("book_id_test")
    if test_id is not None:
        current_chapter, chapter_array, bookFinished = bookshelf_get_current_chapter('43efeb79-3bd4-4aed-882c-6952b36fa6a7')

        print(current_chapter, chapter_array, bookFinished)
    else:
        print("Test ID is None")
