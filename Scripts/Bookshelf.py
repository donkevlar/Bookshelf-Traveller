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


def bookshelf_listening_stats():
    endpoint = "/me/listening-stats"
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
    if r.status_code == 200:
        data = r.json()
        successMSG(endpoint, r.status_code)
        return data

    else:
        print(r.status_code)
        return None


def bookshelf_libraries():
    endpoint = "/libraries"
    r = requests.get(f'{defaultAPIURL}{endpoint}{tokenInsert}')
    if r.status_code == 200:
        data = r.json()
        successMSG(endpoint, r.status_code)
        print(data)


if __name__ == 'main':
    pass
