# Bookshelf-Traveller

A simple Audiobookshelf discord bot to help you manage your instance :)

You'll need to create your own discord application in order to do this, you can google on how to do that. 

Make sure that you select all intents when setting up your bot and that you have created a url to add it to your desired discord server.

**Permissions for the bot should be done manually, currently with how I have it set up, there aren't any limiting factors, please setup your roles accordingly.**

### Environmental Variables
ENVIRONMENTAL VARS REQUIRED:

| ENV Variables      | Description                                                   |
|--------------------|---------------------------------------------------------------|
| **DISCORD_TOKEN**  | Discord API Token                                             |
| **bookshelfToken** | Bookshelf User Token (being an admin is recommended)          |
| **bookshelfURL**   | Bookshelf url with protocol and port, ex: http://localhost:80 |


## Docker Container
Docker Container Available:

```
docker pull donkevlar/bookshelf-traveller
```

## Bot Commands
The following Commands are available:

**Note: Prefix is also usable, currently set to '$'**

**By default setup as '/' commands, or a.k.a app commands**

| Command               | Description                                                                     | Additional Information                                                                                                                 |
|-----------------------|---------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| sync                  | Sync commands with discord server                                               | useful if you just updated the bot and discord isn't displaying the full list. Sometimes, however, you simply need to restart discord. |
| sync-status           | Verify if sync command has already been executed since startup, returns boolean |
| add-user              | Will create a user, requires username, password                                 | additional fields: user type, email.                                                                                                   |
| all-libraries         | Displays all current libraries with their ID                                    |                                                                                                                                        |
|book-list-csv|Get complete list of items in a given library, outputs a csv||
| listening-stats       | Pulls your total listening time                                                 | Will be expanded in the future.                                                                                                        |
| media-progress        | Searches for the media item's progress, note: ***requires Library Item ID***    |                                                                                                                                        |
| ping                  | Displays the latency between your server and the discord server shard           |                                                                                                                                        |
| recent-sessions       | Will display ***up to*** 5 recent sessions in a filtered and formatted way.     |                                                                                                                                        |
 | user-search           | Search for a specific user by name                                              | current public release only has name, but ill update it to include search by ID                                                        |
| test-connection       | Will test the connection of your bot to the audioboookshelf server              | Optionally you can test the connection to any url using the URL arg.                                                                   |
