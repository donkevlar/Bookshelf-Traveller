# Bookshelf-Traveller

![GitHub commit activity](https://img.shields.io/github/commit-activity/y/donkevlar/Bookshelf-Traveller)
![GitHub License](https://img.shields.io/github/license/donkevlar/Bookshelf-Traveller)

<a href="https://www.buymeacoffee.com/donkevlar" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-green.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>


A simple Audiobookshelf discord bot to help you manage your instance :)

You'll need to create your own discord application in order to do this, you can google on how to do that. 

Make sure that you select all intents when setting up your bot and that you have created a url to add it to your desired discord server.

**, there aren't any limiting factors, please setup your roles accordingly.**

### Environmental Variables
ENVIRONMENTAL VARS REQUIRED:

| ENV Variables     | Description                                                      | Required? |
|-------------------|------------------------------------------------------|-----------|
| `DISCORD_TOKEN` | Discord API Token                                                | **YES**   |
| `bookshelfToken` | Bookshelf User Token (being an admin is recommended)             | **YES**   |
| `bookshelfURL`  | Bookshelf url with protocol and port, ex: http://localhost:80    | **YES**   |
|`OWNER_ONLY`| Only allow bot owner to user bot. By default this is set to True | **NO**    |

## Installation
**Current Installation method is by docker container, however, you can also run main.py within a project folder.**
### Python Script
Requirements: Python 3.11 or above.

you'll also need an '.env' file for loading the above ENV Variables
```
pip install discord.py
pip install python-dotenv
```
### Docker Container
Docker Container Available:

```
docker pull donkevlar/bookshelf-traveller
```

```
docker run -d \
--name bookshelf-traveller \
-e DISCORD_TOKEN="INSERT_TOKEN" \
-e bookshelfToken="INSERT_TOKEN" \
-e bookshelfURL="http://myurl.domain.com" \
donkevlar/bookshelf-traveller

```

## Bot Commands
The following Commands are available:

**Note: Prefix is also usable, currently set to '$'**

**By default, setup as '/' commands, or a.k.a app commands**

| Command               | Description                                                                     | Additional Information                                                                                                                 |
|-----------------------|---------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `/add-user`              | Will create a user, requires username, password                                 | additional fields: user type, email.                                                                                                   |
| `/all-libraries`         | Displays all current libraries with their ID                                    |                                                                                                                                        |
|`/book-list-csv`  |Get complete list of items in a given library, outputs a csv||
| `/listening-stats`       | Pulls your total listening time                                                 | Will be expanded in the future.                                                                                                        |
| `/media-progress`        | Searches for the media item's progress, note: ***requires Library Item ID***    |                                                                                                                                        |
| `/ping`                  | Displays the latency between your server and the discord server shard           |                                                                                                                                        |
| `/recent-sessions`       | Will display ***up to*** 5 recent sessions in a filtered and formatted way.     |                                                                                                                                        |
| `/user-search`           | Search for a specific user by name                                              | current public release only has name, but ill update it to include search by ID                                                        |
| `/test-connection`       | Will test the connection of your bot to the audioboookshelf server              | Optionally you can test the connection to any url using the URL arg.                                                                   |
