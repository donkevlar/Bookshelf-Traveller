A simple Audiobookshelf discord bot to help you manage your instance :)

You'll need to create your own discord application in order to do this, you can google on how to do that. 

Make sure that you select all intents when setting up your bot and that you have created a url to add it to your desired discord server.

**Permissions for the bot should be done manually, currently with how I have it set up, there aren't any limiting factors, please setup your roles accordingly.**

ENVIRONMENTAL VARS REQUIRED:

| ENV Variables      | Description                                                   |
|--------------------|---------------------------------------------------------------|
| **DISCORD_TOKEN**  | Discord API Token                                             |
| **bookshelfToken** | Bookshelf User Token (being an admin is recommended)          |
| **bookshelfURL**   | Bookshelf url with protocol and port, ex: http://localhost:80 |

bookshelfURL

Docker Container Available:

```
docker pull donkevlar/bookshelf-traveller
```

