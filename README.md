![bt banner](https://github.com/donkevlar/Bookshelf-Traveller/assets/21166416/69de1291-22e9-49c2-8d3a-e6b15ff1b149)

# Bookshelf Traveller

![GitHub commit activity](https://img.shields.io/github/commit-activity/m/donkevlar/bookshelf-traveller)
![GitHub License](https://img.shields.io/github/license/donkevlar/Bookshelf-Traveller)

<a href="https://www.buymeacoffee.com/donkevlar" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-green.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

**Now in Beta! The commands are feature complete, but you may still encounter errors. If you do please raise an issue.**

A fully featured Audiobookshelf discord bot with playback and administrative functionality. Enjoy your travels! :)

You'll need to create your own discord application in order to do this, this is fairly straight forward, here is a guide:

[Create a Discord App - Getting Started](https://discord.com/developers/docs/getting-started#step-1-creating-an-app)

Make sure that you select all intents when setting up your bot and that you have created a url to add it to your desired discord server.
### Known Limitations
**Podcast playback is currently not supported due to the many differences in pulling the audio sources.**

**Ownership by default will allow you to run all commands (NOT ADMIN), to disable this, use the env variable `OWNER_ONLY`.**

**When using commands that use images, i.e. `/media_progress` or `/recent_sessions`, 
the server must use an `HTTPS` connection due to a requirement from discord's API. If not, no image will be generated.**

### Environmental Variables


| ENV Variables      | Description                                                                                                                                          | Type      | Required? |
|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|-----------|
| `DISCORD_TOKEN`    | Discord API Token                                                                                                                                    | *String*  | **YES**   |
| `bookshelfToken`   | Bookshelf User Token (All user types work, but some will limit your interaction options.)                                                            | *String*  | **YES**   |
| `bookshelfURL`     | Bookshelf url with protocol and port, ex: http://localhost:80                                                                                        | *String*  | **YES**   |
| `OWNER_ONLY`       | By default set to `True`. Only allow bot owner to use bot.                                                                                           | *Boolean* | **NO**    |
| `EPHEMERAL_OUTPUT` | By default set to `True`, this sets all commands to ephemeral (shown only to you)                                                                    | *Boolean* | **NO**    |
| `MULTI_USER`       | By default set to `True`, disable this to re-enable admin controls (Conditional on the user logged in.) and to remove the /login and /select options | *Boolean* | **NO**    |

## Installation
**Current Installation method is by docker container, however, you can also run main.py within a project folder.**

### Docker Container
Docker Container Available:

```
docker pull donkevlar/bookshelf-traveller:latest
```
To run the container, paste the following command:
```
docker run -d \
--name bookshelf-traveller \
-e DISCORD_TOKEN="INSERT_TOKEN" \
-e bookshelfToken="INSERT_TOKEN" \
-e bookshelfURL="http://myurl.domain.com" \
donkevlar/bookshelf-traveller:latest
```

or using docker compose:

```
version: '3.8'  # Specify the version of the Compose file format

services:
  bookshelf-traveller:
    image: donkevlar/bookshelf-traveller:latest
    container_name: bookshelf-traveller
    environment:
      - DISCORD_TOKEN=INSERT_TOKEN
      - bookshelfToken=INSERT_TOKEN
      - bookshelfURL=http://myurl.domain.com
    restart: always  # Optional: ensures the container restarts on failure or system reboot
    detach: true    # Optional: runs the container in detached mode
```

### Python Script
Requirements: Python 3.11 or above.

**FFMPEG Must be installed in the project directory and/or in PATH to run audio commands using the script installation method. If this is too difficult, please use the docker instructions above.**

you'll also need an '.env' file for loading the above [ENV Variables](https://github.com/donkevlar/Bookshelf-Traveller/blob/master/README.md#environmental-variables)
```
pip install discord-py-interactions && pip install discord.py-interactions[voice] && pip install python-dotenv && pip install requests
```

## Bot Commands
The following Commands are available:

**By default, setup as '/' commands, or a.k.a. app commands**

| Command            | Description                                                                                                                  | Arguments                                          | Additional Information                                                                                                                                                                                              | Additional Functionality                |
|--------------------|------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------|
| `/login`           | Login using ABS username and password.                                                                                       | `username`, `password`                             |                                                                                                                                                                                                                     |                                         |
| `/select`          | Switch between logged in ABS users                                                                                           |                                                    |                                                                                                                                                                                                                     |                                         |
| `/user`            | Will display the currently logged in user.                                                                                   |                                                    |                                                                                                                                                                                                                     |                                         |
| `/add-user`        | Will create a user, requires username, password                                                                              | `name`, `password`, `user_type`, optional: `email` | only with ABS admin token. Otherwise disabled. *MULTI_USER must be False.                                                                                                                                           |
| `/play`            | Start a new audio session from server, syncs automatically                                                                   | `book_title`                                       |                                                                                                                                                                                                                     |                                         |
| `/resume`          | Resume audio                                                                                                                 |                                                    |                                                                                                                                                                                                                     |                                         |
| `/pause`           | Pause audio                                                                                                                  |                                                    |                                                                                                                                                                                                                     |                                         |
| `/change-chapter`  | Changes chapter in currently playing audio                                                                                   | `type`: `next`, `previous`                         |                                                                                                                                                                                                                     |                                         |
| `/volume`          | adjusts the bot's volume in the currently connected channel.                                                                 | `volume`: integer between `0 & 100`                | Default volume is set to 50%                                                                                                                                                                                        |                                         |
| `/stop`            | Disconnect bot from channel                                                                                                  |                                                    |                                                                                                                                                                                                                     |                                         |
| `/all-libraries`   | Displays all current libraries with their ID                                                                                 |                                                    |                                                                                                                                                                                                                     |
| `/book-list-csv`   | Get complete list of items in a given library, outputs a csv                                                                 | `libraryid`                                        | only with ABS admin token. Otherwise disabled. *MULTI_USER must be False.                                                                                                                                           | **Autocomplete Enabled & Cover Images** |
| `/listening-stats` | Pulls your total listening time                                                                                              |                                                    |                                                                                                                                                                                                                     |                                         |
| `/media-progress`  | Searches for the media item's progress                                                                                       | `book_title`                                       | Features autocomplete, simply type in the name of the book and it will return the name and ID for you.                                                                                                              | **Autocomplete Enabled & Cover Images** |
| `/ping`            | Displays the latency between your server and the discord server shard                                                        |                                                    |                                                                                                                                                                                                                     |
| `/recent-sessions` | Will display ***up to*** 10 recent sessions in a filtered and formatted way.                                                 |                                                    |                                                                                                                                                                                                                     |
| `/user-search`     | Search for a specific user by name                                                                                           | `name`                                             | Only with ABS admin token. current public release only has name, but ill update it to include search by ID, or by using the autocomplete. only with ABS admin token. Otherwise disabled. *MULTI_USER must be False. | **Autocomplete Enabled**                |
| `/test-connection` | Will test the connection of your bot to the audioboookshelf server                                                           | optional: `opt_url`                                | Optionally you can test the connection to any url.                                                                                                                                                                  |                                         |

### Screenshots
Below are a few examples of the commands shown above.

![img.png](images/img.png)

![img.png](images/mediaprogress.png)

![img.png](images/autocomplete.png)
