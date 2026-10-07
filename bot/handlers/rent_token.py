"""Token onboarding: connect the merchant's own BotFather bot ("Connect my bot").

Additive to the rent flow: these handlers only run when the user taps the
"Connect my bot" button (added to rent success / My Rental screens) and do
nothing when config.RENTAL_TOKEN_ONBOARDING is off. The existing rent flow
is untouched.

Two paths (pilot-gated):
- Manual paste (always on): start -> paste token -> validate ->
  [foreign-webhook confirm] -> challenge (code shown) -> merchant sends code
  to THEIR bot -> "I've sent it" -> plan (only if no live subscription) ->
  submit -> connected.
- Express setup (only when config.MANAGED_ONBOARDING_ENABLED and
  config.MANAGER_BOT_USERNAME are set): method choice -> D4 consent screen ->
  tap-to-confirm link -> "I've created it" -> claim via control plane
  (graceful fallback to manual paste until the claim backend exists).

The raw token lives only in FSM memory, is never logged, and is wiped from
state on every terminal path. The pasted message is deleted best-effort so
the token does not linger in chat history.
"""
import logging

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup

import config
from .common import edit_text_safe
from .rent import _get_user_id, _nova
from loader import dp

logger = logging.getLogger(__name__)

# --- Texts (kept local to stay additive; English only) ---
MSG_TOK_START = (
    "To connect your own bot, paste its token here.\n\n"
    "Open @BotFather, send /newbot (or open your existing bot), "
    "copy the token, and paste it in this chat."
)
MSG_TOK_BAD_FORMAT = (
    "That doesn't look like a bot token. It should look like "
    "<code>123456789:AAH...</code> — paste it again, or tap Cancel."
)
MSG_TOK_INVALID = (
    "Telegram rejected this token (it may be wrong or revoked). "
    "Check it in @BotFather and paste it again."
)
MSG_TOK_CONNECTED = (
    "This bot is already connected to a Nova rental. "
    "If this is unexpected, contact support."
)
MSG_TOK_SLOW = (
    "Telegram is being slow right now. Please try again in a moment."
)
MSG_TOK_UNAVAILABLE = "Token onboarding is temporarily unavailable. Please try again later."
MSG_TOK_FOREIGN = (
    "Heads up: this bot already sends updates to\n{url}\n\n"
    "Connecting it here will <b>replace</b> that. Continue?"
)
MSG_TOK_CODE = (
    "Almost done! Send this code to <b>your</b> bot:\n\n"
    "<b>{code}</b>\n\n"
    "Open your bot in Telegram, send the code as a message, "
    "then tap \"I've sent it\". The code expires in 10 minutes."
)
MSG_TOK_WAITING = (
    "Not yet — send the code to your bot first, then tap \"I've sent it\" again."
)
MSG_TOK_FAILED = (
    "The challenge expired or failed. Tap below to start over."
)
MSG_TOK_PLAN = "Which billing plan should activate with your bot?"
MSG_TOK_DONE = (
    "Connected! Your bot {username} is now powered by Nova.\n\n"
    "Manage it any time from My Rental."
)
MSG_TOK_CANCELLED = "Cancelled. Your token was discarded."
MSG_TOK_LINK_NEEDED = "Please link your Telegram account on the website first, then come back here."

BTN_TOK_CANCEL = "Cancel"
BTN_TOK_CONNECT = "\U0001f916 Connect my bot"
BTN_TOK_YES_REPLACE = "Yes, replace it"
BTN_TOK_SENT = "I've sent it \u2705"
BTN_TOK_RESTART = "Start over"
BTN_TOK_MONTHLY = "Monthly \u2014 $8.99/mo"
BTN_TOK_YEARLY = "Yearly \u2014 $89.99/year"

# --- Managed onboarding (express setup) texts — pilot-gated, English only ---
MSG_TOK_CHOOSE = (
    "How do you want to connect your bot?\n\n"
    "\u26a1 <b>Express setup</b> \u2014 one tap. We create the bot for you "
    "inside Telegram and hold its token securely.\n"
    "\U0001f511 <b>Manual paste</b> \u2014 create the bot in @BotFather yourself "
    "and paste its token here."
)
MSG_TOK_MANAGED_CONSENT = (
    "Before we continue, please confirm you understand:\n\n"
    "\u2022 Nova will create the bot under your Telegram account.\n"
    "\u2022 Nova will <b>hold your bot's token</b> and may rotate it to keep it secure.\n"
    "\u2022 You stay the owner in @BotFather and can reclaim control any time.\n"
    "\u2022 If you cancel, we hand the bot back to you \u2014 we never delete it."
)
MSG_TOK_MANAGED_LINK = (
    "Tap the link below to create your bot in one tap:\n\n"
    "{url}\n\n"
    "Confirm inside Telegram, then come back here and tap "
    "\u201cI've created it\u201d."
)
MSG_TOK_MANAGED_PENDING = (
    "Thanks! Express setup is still being wired up on our side \u2014 "
    "your bot isn't connected yet.\n\n"
    "For now, please use manual paste: create the bot in @BotFather "
    "and paste its token here. It takes about a minute."
)
BTN_TOK_EXPRESS = "\u26a1 Express setup"
BTN_TOK_PASTE = "\U0001f511 Paste token manually"
BTN_TOK_CONSENT_OK = "\u2705 I understand \u2014 continue"
BTN_TOK_CREATED = "\u2705 I've created it"
BTN_TOK_BACK = "Back"


class RentToken(StatesGroup):
    waiting_token = State()


def _enabled() -> bool:
    return bool(getattr(config, "RENTAL_TOKEN_ONBOARDING", True))


def _managed_available() -> bool:
    """Express setup is offered only when the pilot is switched on AND a
    manager bot username is configured. Otherwise the paste-token UI is
    exactly as before — no dead buttons, no dead ends."""
    return bool(getattr(config, "MANAGED_ONBOARDING_ENABLED", False)) and bool(
        getattr(config, "MANAGER_BOT_USERNAME", "")
    )


def _managed_newbot_url() -> str:
    manager = getattr(config, "MANAGER_BOT_USERNAME", "")
    return f"https://t.me/newbot/{manager}"


def _cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
    return kb


def _back_to_rent_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Back to Rent", callback_data="rent:back"))
    return kb


async def _clear(message_or_query, state: FSMContext) -> None:
    try:
        async with state.proxy() as data:
            data.pop("token", None)
            data.pop("nonce", None)
    except Exception:
        pass
    try:
        await state.finish()
    except Exception:
        pass


def _err_text(exc: RuntimeError) -> str:
    msg = str(exc)
    if "http_400" in msg and "invalid_format" in msg:
        return MSG_TOK_BAD_FORMAT
    if "http_401" in msg and ("invalid_token" in msg or "token_revoked" in msg):
        return MSG_TOK_INVALID
    if "http_409" in msg and "already_connected" in msg:
        return MSG_TOK_CONNECTED
    if "http_429" in msg or "telegram_unreachable" in msg:
        return MSG_TOK_SLOW
    return MSG_TOK_UNAVAILABLE


@dp.callback_query_handler(text="rent:token:start")
async def cb_token_start(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled():
        return
    await state.finish()
    if _managed_available():
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(BTN_TOK_EXPRESS, callback_data="rent:token:managed:start"))
        kb.add(InlineKeyboardButton(BTN_TOK_PASTE, callback_data="rent:token:paste"))
        kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
        await query.message.answer(MSG_TOK_CHOOSE, reply_markup=kb)
        return
    await _start_paste(query.message, state)


async def _start_paste(message: types.Message, state: FSMContext) -> None:
    """Original paste-token entry: ForceReply for the token + a Cancel button."""
    await state.finish()
    await RentToken.waiting_token.set()
    await message.answer(MSG_TOK_START, reply_markup=ForceReply(selective=True))
    # append cancel inline button
    await message.answer("Tap Cancel to stop.", reply_markup=_cancel_kb())


@dp.callback_query_handler(text="rent:token:paste")
async def cb_token_paste(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled():
        return
    await _start_paste(query.message, state)


@dp.callback_query_handler(text="rent:token:managed:start")
async def cb_token_managed_start(query: types.CallbackQuery, state: FSMContext):
    """D4 consent screen — the tenant confirms they understand platform
    token custody before we hand them the tap-to-confirm link."""
    await query.answer()
    if not _enabled() or not _managed_available():
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_CONSENT_OK, callback_data="rent:token:managed:consent"))
    kb.add(InlineKeyboardButton(BTN_TOK_BACK, callback_data="rent:token:start"))
    await edit_text_safe(query, MSG_TOK_MANAGED_CONSENT, reply_markup=kb)


@dp.callback_query_handler(text="rent:token:managed:consent")
async def cb_token_managed_consent(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled() or not _managed_available():
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_CREATED, callback_data="rent:token:managed:check"))
    kb.add(InlineKeyboardButton(BTN_TOK_BACK, callback_data="rent:token:start"))
    await edit_text_safe(
        query,
        MSG_TOK_MANAGED_LINK.format(url=_managed_newbot_url()),
        reply_markup=kb,
    )


@dp.callback_query_handler(text="rent:token:managed:check")
async def cb_token_managed_check(query: types.CallbackQuery, state: FSMContext):
    """Claim the managed bot via the control plane. Until the claim backend
    exists (pilot preconditions), degrade gracefully to the manual paste
    flow — never a dead end."""
    await query.answer()
    if not _enabled() or not _managed_available():
        return
    try:
        await _nova(
            "POST",
            "/api/internal/rental/managed/claim",
            json_body={"telegram_id": str(query.from_user.id)},
        )
    except RuntimeError:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(BTN_TOK_PASTE, callback_data="rent:token:paste"))
        kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
        await edit_text_safe(query, MSG_TOK_MANAGED_PENDING, reply_markup=kb)
        return
    # Backend claim path will be completed with the pilot backend
    # (provisioning_mode, manager update stream). Not reachable today.
    await _start_paste(query.message, state)


@dp.message_handler(state=RentToken.waiting_token, content_types=types.ContentType.TEXT)
async def msg_token_pasted(message: types.Message, state: FSMContext):
    if not _enabled():
        await state.finish()
        return
    text = (message.text or "").strip()
    if text.lower() in ("cancel", "/cancel"):
        await _clear(message, state)
        await message.answer(MSG_TOK_CANCELLED, reply_markup=_back_to_rent_kb())
        return

    token = text
    # Remove the token from chat history best-effort.
    try:
        await message.delete()
    except Exception:
        pass

    try:
        user_id = await _get_user_id(message.from_user.id)
    except RuntimeError:
        await _clear(message, state)
        await message.answer(MSG_TOK_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    if not user_id:
        await _clear(message, state)
        await message.answer(MSG_TOK_LINK_NEEDED, reply_markup=_back_to_rent_kb())
        return

    try:
        result = await _nova("POST", "/api/internal/rental/token/validate", json_body={"token": token})
    except RuntimeError as exc:
        await _clear(message, state)
        await message.answer(_err_text(exc), reply_markup=_back_to_rent_kb())
        return

    async with state.proxy() as data:
        data["token"] = token
        data["user_id"] = user_id
        data["bot_username"] = ((result.get("bot") or {}).get("username") or "")

    webhook = result.get("webhook") or {}
    if webhook.get("has_foreign_webhook"):
        url = webhook.get("url_masked") or "(unknown)"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(BTN_TOK_YES_REPLACE, callback_data="rent:token:challenge:confirm"))
        kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
        await message.answer(MSG_TOK_FOREIGN.format(url=url), reply_markup=kb)
        return

    await _issue_challenge(message, state, token, user_id, False)


async def _issue_challenge(message: types.Message, state: FSMContext, token: str, user_id: str, confirm: bool):
    try:
        result = await _nova(
            "POST",
            "/api/internal/rental/token/challenge",
            json_body={
                "token": token,
                "telegram_id": str(message.from_user.id),
                "user_id": user_id,
                "confirm_foreign_webhook": confirm,
            },
        )
    except RuntimeError as exc:
        await _clear(message, state)
        await message.answer(_err_text(exc), reply_markup=_back_to_rent_kb())
        return

    nonce = result.get("challenge_id")
    code = result.get("code")
    if not nonce or not code:
        await _clear(message, state)
        await message.answer(MSG_TOK_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return

    async with state.proxy() as data:
        data["nonce"] = nonce

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_SENT, callback_data="rent:token:check"))
    kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
    await message.answer(MSG_TOK_CODE.format(code=code), reply_markup=kb)


@dp.callback_query_handler(text="rent:token:challenge:confirm")
async def cb_token_challenge_confirm(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled():
        return
    data = await state.get_data()
    token = data.get("token")
    user_id = data.get("user_id")
    if not token or not user_id:
        await _clear(query, state)
        await edit_text_safe(query, MSG_TOK_FAILED, reply_markup=_back_to_rent_kb())
        return
    # message proxy for _issue_challenge
    await _issue_challenge(query.message, state, token, user_id, True)


@dp.callback_query_handler(text="rent:token:check")
async def cb_token_check(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled():
        return
    data = await state.get_data()
    nonce = data.get("nonce")
    if not nonce:
        await _clear(query, state)
        await edit_text_safe(query, MSG_TOK_FAILED, reply_markup=_back_to_rent_kb())
        return
    try:
        result = await _nova("GET", "/api/internal/rental/token/challenge", params={"nonce": nonce})
    except RuntimeError:
        await edit_text_safe(query, MSG_TOK_UNAVAILABLE, reply_markup=_cancel_kb())
        return

    status = result.get("status")
    if status == "passed":
        await _plan_step(query, state)
        return
    if status == "pending":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(BTN_TOK_SENT, callback_data="rent:token:check"))
        kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
        await edit_text_safe(query, MSG_TOK_WAITING, reply_markup=kb)
        return
    await _clear(query, state)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_RESTART, callback_data="rent:token:start"))
    await edit_text_safe(query, MSG_TOK_FAILED, reply_markup=kb)


async def _plan_step(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id")
    try:
        subs = await _nova("GET", f"/api/internal/users/{user_id}/subscriptions")
    except RuntimeError:
        subs = {}
    live = [
        s for s in (subs.get("subscriptions") or [])
        if str(s.get("status") or "") in ("TRIALING", "ACTIVE", "PAST_DUE", "GRACE")
        and "RENTAL" in str(s.get("planName") or "")
    ]
    if live:
        await _do_submit(query, state, "monthly")
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_TOK_MONTHLY, callback_data="rent:token:plan:monthly"))
    kb.add(InlineKeyboardButton(BTN_TOK_YEARLY, callback_data="rent:token:plan:yearly"))
    kb.add(InlineKeyboardButton(BTN_TOK_CANCEL, callback_data="rent:token:cancel"))
    await edit_text_safe(query, MSG_TOK_PLAN, reply_markup=kb)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rent:token:plan:"))
async def cb_token_plan(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    if not _enabled():
        return
    plan = query.data.split(":")[-1]
    if plan not in ("monthly", "yearly"):
        return
    await _do_submit(query, state, plan)


async def _do_submit(query: types.CallbackQuery, state: FSMContext, plan: str):
    data = await state.get_data()
    token = data.get("token")
    nonce = data.get("nonce")
    user_id = data.get("user_id")
    bot_username = data.get("bot_username") or "your bot"
    if not token or not nonce or not user_id:
        await _clear(query, state)
        await edit_text_safe(query, MSG_TOK_FAILED, reply_markup=_back_to_rent_kb())
        return
    try:
        result = await _nova(
            "POST",
            "/api/internal/rental/token/submit",
            json_body={
                "nonce": nonce,
                "user_id": user_id,
                "plan": plan,
                "token": token,
                "telegram_id": str(query.from_user.id),
            },
        )
    except RuntimeError as exc:
        await _clear(query, state)
        await edit_text_safe(query, _err_text(exc), reply_markup=_back_to_rent_kb())
        return
    await _clear(query, state)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("My Rental", callback_data="rent:mine"))
    await edit_text_safe(query, MSG_TOK_DONE.format(username="@" + bot_username if bot_username else "your bot"), reply_markup=kb)


@dp.callback_query_handler(text="rent:token:cancel")
async def cb_token_cancel(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await _clear(query, state)
    await edit_text_safe(query, MSG_TOK_CANCELLED, reply_markup=_back_to_rent_kb())
