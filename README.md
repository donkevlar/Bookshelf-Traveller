![Banner](https://github.com/donkevlar/Bookshelf-Traveller/assets/21166416/95320d29-8722-4b17-9274-4d539bbc2004)

# Bookshelf Traveller

![GitHub commit activity](https://img.shields.io/github/commit-activity/m/donkevlar/bookshelf-traveller)
![GitHub License](https://img.shields.io/github/license/donkevlar/Bookshelf-Traveller)

<a href="https://www.buymeacoffee.com/donkevlar" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-green.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>


A fully featured Audiobookshelf discord bot with playback and administrative functionality. Enjoy your travels! :)

You'll need to create your own discord application in order to do this, this is fairly straight forward, here is a guide:

[Create a Discord App - Getting Started](https://discord.com/developers/docs/getting-started#step-1-creating-an-app)

Make sure that you select all intents when setting up your bot and that you have created a url to add it to your desired discord server.
### Known Limitations
**1) Ownership by default will allow you to run all commands (NOT ADMIN), to disable this, use the env variable `OWNER_ONLY`. 
No permissions have been setup yet, however, ill be working towards that.**

**2) When using commands that use images, i.e. `/media_progress` or `/recent_sessions`, 
the server must use an `HTTPS` connection due to a requirement from discord's API. If not, no image will be generated.**

### Environmental Variables
ENVIRONMENTAL VARS REQUIRED:

| ENV Variables      | Description                                                                       | Type      | Required? |
|--------------------|-----------------------------------------------------------------------------------|-----------|-----------|
| `DISCORD_TOKEN`    | Discord API Token                                                                 | *String*  | **YES**   |
| `bookshelfToken`   | Bookshelf User Token (being an admin is required)                                 | *String*  | **YES**   |
| `bookshelfURL`     | Bookshelf url with protocol and port, ex: http://localhost:80                     | *String*  | **YES**   |
| `OWNER_ONLY`       | By default set to `True`. Only allow bot owner to use bot.                        | *Boolean* | **NO**    |
| `EPHEMERAL_OUTPUT` | By default set to `True`, this sets all commands to ephemeral (shown only to you) | *Boolean* | **NO**    |

## Installation
**Current Installation method is by docker container, however, you can also run main.py within a project folder.**
### Python Script
Requirements: Python 3.11 or above.

you'll also need an '.env' file for loading the above ENV Variables
```
pip install discord-py-interactions && pip install python-dotenv && pip install requests
```
### Docker Container
Docker Container Available:

```
docker pull donkevlar/bookshelf-traveller
```
To run the container, paste the following command:
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

**By default, setup as '/' commands, or a.k.a app commands**

| Command            | Description                                                                  | Arguments                                          | Additional Information                                                                                        | Additional Functionality                |
|--------------------|------------------------------------------------------------------------------|----------------------------------------------------|---------------------------------------------------------------------------------------------------------------|-----------------------------------------|
| `/add-user`        | Will create a user, requires username, password                              | `name`, `password`, `user_type`, optional: `email` |                                                                                                               |
| `/play`            | Start a new audio session from server, syncs automatically                   | `book_title`                                       |                                                                                                               |                                         |
| `/resume`          | Resume audio                                                                 |                                                    |                                                                                                               |                                         |
| `/pause`           | Pause audio                                                                  |                                                    |                                                                                                               |                                         |
| `/disconnect`      | Disconnect bot from channel                                                  |                                                    |                                                                                                               |                                         |
| `/all-libraries`   | Displays all current libraries with their ID                                 |                                                    |                                                                                                               |
| `/book-list-csv`   | Get complete list of items in a given library, outputs a csv                 | `libraryid`                                        |                                                                                                               | **Autocomplete Enabled & Cover Images** |
| `/listening-stats` | Pulls your total listening time                                              |                                                    | Will be expanded in the future.                                                                               |                                         |
| `/media-progress`  | Searches for the media item's progress                                       | `book_title`                                       | Feautres autocomplete, simply type in the name of the book and it will return the name and ID for you.        | **Autocomplete Enabled & Cover Images** |
| `/ping`            | Displays the latency between your server and the discord server shard        |                                                    |                                                                                                               |
| `/recent-sessions` | Will display ***up to*** 10 recent sessions in a filtered and formatted way. |                                                    |                                                                                                               |
| `/user-search`     | Search for a specific user by name                                           | `name`                                             | current public release only has name, but ill update it to include search by ID, or by using the autocomplete | **Autocomplete Enabled**                |
| `/test-connection` | Will test the connection of your bot to the audioboookshelf server           | optional: `opt_url`                                | Optionally you can test the connection to any url.                                                            |                                         |

### Screenshots
Below are a few examples of the commands shown above.

![img.png](images/img.png)

![img.png](images/mediaprogress.png)

![img.png](images/autocomplete.png)
