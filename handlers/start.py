from maxapi import Router
from maxapi.filters.command import CommandStart
from maxapi.types import MessageCreated, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

router = Router(router_id="start")


@router.message_created(CommandStart())
async def start(event: MessageCreated):
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        OpenAppButton(
            text="MiniApp",
            web_app=event.bot.me.username,
            contact_id=event.bot.me.user_id,
        )
    )

    await event.message.answer(
        "start-handler",
        attachments=[keyboard.as_markup()],
    )
