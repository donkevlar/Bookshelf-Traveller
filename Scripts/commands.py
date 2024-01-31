import os
import time
from collections import defaultdict
from datetime import datetime
import csv

import dotenv
from dotenv import load_dotenv

import requests

# Set to true when using Docker
DOCKER_VARS = False

# DEV ENVIRON VARS
if not DOCKER_VARS:
    load_dotenv()

# Global Vars


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

    try:
        # Using /healthcheck to avoid domain mismatch, since this is an api endpoint in bookshelf
        r = requests.get(f'{bookshelfURL}/healthcheck')
        status = r.status_code
        return status

    except requests.RequestException as e:
        print("Error occured while testing server connection: ", e, "\n")

    except UnboundLocalError as e:
        print("No URL PROVIDED!\n")


def bookshelf_auth_test():
    print("\nProviding Auth Token to Server\n")
    time.sleep(0.25)
    try:
        endpoint = "/me"
        r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
        if r.status_code == 200:
            # Place data in JSON Format
            data = r.json()

            username = data.get("username", "")

            print(f'Successfully Authenticated as user {username}')
            time.sleep(1)
            return username
        else:
            print("Error: Could not connect to /me endpoint \n")
            print("Quitting!")
            time.sleep(1)
            exit()

    except requests.RequestException as e:
        print("Could not establish connection using token: ", e)

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

        # Process each session and count the number of times each session appears
        for session in sessions:
            library_item_id = session["libraryItemId"]
            display_title = session["displayTitle"]

            # Create a unique identifier for the session based on library item ID and title
            session_key = (library_item_id, display_title)

            # Increment the count for this session
            session_counts[session_key] += 1

        # Sort sessions by play count (highest to lowest)
        sorted_sessions = sorted(session_counts.items(), key=lambda x: x[1], reverse=True)[:5]  # Take only the top 5

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
                f"Number of Times Played: {count}\n"
            )
            formatted_sessions.append(session_info)

        # Join the formatted sessions into a single string with each session separated by a newline
        formatted_sessions_string = "\n".join(formatted_sessions)

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
        successMSG(endpoint, r.status_code)

        progress = round(data['progress'] * 100)
        isFinished = data['isFinished']
        currentTime = data['currentTime'] / 60
        duration = data['duration'] / 60
        lastUpdate = data['lastUpdate'] / 1000

        # Convert lastUpdate Time from unix to standard time
        lastUpdate = datetime.utcfromtimestamp(lastUpdate)
        converted_lastUpdate = lastUpdate.strftime('%Y-%m-%d %H:%M')

        # Get Media Title
        secondary_url = f"/items/{item_id}"
        r = requests.get(f'{defaultAPIURL}{secondary_url}{tokenInsert}')
        data = r.json()
        title = data['media']['metadata']['title']
        description = data['media']['metadata']['description']

        formatted_info = (
            f'Title: {title}\n'
            f'Progress: {progress}%\n'
            f'Is Finished: {isFinished}\n'
            f'Current Time (time progressed): {round(currentTime) / 60} hours \n'
            f'Total Duration: {round(duration / 60)}\n'
            f'Last Updated: {converted_lastUpdate}\n'

        )

        return formatted_info, title, description


def bookshelf_get_users(name):
    endpoint = f"/users"
    isFound = False

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