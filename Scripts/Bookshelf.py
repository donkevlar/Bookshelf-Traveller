import os
import time

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


import requests


def bookshelf_listening_stats():
    endpoint = "/me/listening-stats"
    formatted_sessions = []
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
    if r.status_code == 200:
        data = r.json()
        sessions = data.get("recentSessions", [])  # Extract sessions from the data
        for session in sessions:
            library_id = session["libraryId"]
            library_item_id = session["libraryItemId"]
            display_title = session["displayTitle"]
            display_author = session["displayAuthor"]
            duration = round(session["duration"] / 60)

            # Create a formatted string for the session
            session_info = (
                f"Display Title: {display_title}\n"
                f"Display Author: {display_author}\n"
                f"Duration: {round(duration / 60)} Hours\n"
                f"Library ID: {library_id}\n"
                f"Library Item ID: {library_item_id}\n"
            )
            formatted_sessions.append(session_info)

        # Join the formatted sessions into a single string with each session separated by a newline
        formatted_sessions_string = "\n".join(formatted_sessions)

        return formatted_sessions_string, data
    else:
        print(f"Error: {r.status_code}")
        return None


# Define your defaultAPIURL and tokenInsert variables here

# Call the function
bookshelf_listening_stats()


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


bookshelf_listening_stats()
