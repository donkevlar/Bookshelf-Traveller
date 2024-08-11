from interactions import *


class ContextMenus(Extension):
    def __init__(self, bot):
        pass

    @message_context_menu(name="Repeat")
    async def repeat(self, ctx: ContextMenuContext):
        message: Message = ctx.target
        await ctx.send(message.content)
