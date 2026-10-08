"""Tenant token-swap applications: apply -> owner approval -> verified swap.

Flow:
1. Tenant taps "Request token swap" in My Rental (needs an active rental).
2. Tenant gives a reason -> application created (status=pending).
3. The bot owner (config.ADMINS) gets a DM with Approve / Deny buttons.
4. On approve: the tenant is notified and taps "Continue" -> pastes the NEW
   bot token.
5. The new token is validated via getMe, then a verified swap is initiated
   via the control plane: proof-of-control challenge (code shown, tenant
   sends it to the NEW bot, taps "I've sent it") -> on pass the swap
   executes automatically (the owner's earlier approval is the safety gate).
6. On deny: the tenant is notified and the application is closed.

Support contact: the tenant can reach support any time via the in-bot ticket
flow (/support) or the public SUPPORT_USERNAME (config), which is also
published in the bot's description.

The raw token lives only in FSM memory, is never logged, and is wiped from
state on every terminal path. The pasted message is deleted best-effort so
the token does not linger in chat history.
"""
import logging
from datetime import datetime, timezone

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from loader import bot, db, dp
from states import SwapFlow
from .common import edit_text_safe, get_or_register, handle_escape, notify_admins
from .rent import _get_user_id, _nova

logger = logging.getLogger(__name__)

# --- Local texts (additive; English only) ---
MSG_SWAP_UNAVAILABLE = "Token swaps are temporarily unavailable. Please try again later."
MSG_SWAP_NO_RENTAL = (
    "You need an active rental subscription to request a token swap."
)
MSG_SWAP_EXPLAIN = (
    "You can apply to replace the bot token connected to your rental.\n\n"
    "How it works:\n"
    "1. Tell us why you need the swap.\n"
    "2. Our support team reviews and approves your request.\n"
    "3. You paste the new token and prove you own the new bot.\n\n"
    "You can also reach support any time at {support} or with /support."
)
MSG_SWAP_ASK_REASON = (
    "Why do you need to swap the token? (e.g. regenerated in @BotFather, "
    "lost access, suspected leak)\n\nSend your reason, or tap Cancel."
)
MSG_SWAP_CONFIRM = (
    "Please confirm your swap application:\n\n"
    "Current bot: {old_bot}\n"
    "Reason: {reason}\n\n"
    "Our support team will review it. Continue?"
)
MSG_SWAP_SENT = (
    "Application sent. Our support team will review it and you'll be "
    "notified here. You can also reach us at {support}."
)
MSG_SWAP_CANCELLED = "Token swap cancelled."
MSG_SWAP_ALREADY_PENDING = (
    "You already have a pending swap application. "
    "Please wait for support to review it."
)
MSG_SWAP_APPROVED_TENANT = (
    "Good news — your token swap was approved by our support team.\n\n"
    "Tap Continue below, then paste the NEW bot token from @BotFather."
)
MSG_SWAP_DENIED_TENANT = (
    "Your token swap application was not approved.\n\n"
    "If you still need help, contact us at {support} or open a ticket with /support."
)
MSG_SWAP_ASK_TOKEN = (
    "Paste the NEW bot token here.\n\n"
    "Open @BotFather, copy the token of your new bot, and paste it in this chat. "
    "It is only used to verify and swap — never stored in chat."
)
MSG_SWAP_BAD_TOKEN = (
    "Telegram rejected this token (it may be wrong or revoked). "
    "Check it in @BotFather and paste it again, or tap Cancel."
)
MSG_SWAP_NEW_BOT = (
    "New bot detected: {username}\n\n"
    "Tap below to start verification. We'll show a code — send it to your "
    "NEW bot, then tap \"I've sent it\"."
)
MSG_SWAP_CODE = (
    "Almost done! Send this code to your NEW bot:\n\n"
    "<b>{code}</b>\n\n"
    "Open the new bot in Telegram, send the code as a message, "
    "then tap \"I've sent it\". The code expires in 10 minutes."
)
MSG_SWAP_WAITING = (
    "Not yet — send the code to your new bot first, then tap \"I've sent it\" again."
)
MSG_SWAP_DONE = (
    "Done! Your rental is now connected to {username}. "
    "The old token was revoked and can no longer be used."
)
MSG_SWAP_FAILED = (
    "The swap could not be completed. Your current bot is unchanged. "
    "Please try again or contact support at {support}."
)
MSG_SWAP_CHALLENGE_EXPIRED = (
    "The verification code expired. Tap below to start over."
)
MSG_ADMIN_SWAP_REQUEST = (
    "Token swap application #{app_id}\n"
    "Tenant: {name} (tg_id={tg_id})\n"
    "Current bot: {old_bot}\n"
    "Reason: {reason}\n\n"
    "Review and approve or deny:"
)
MSG_ADMIN_SWAP_DECIDED = "Application #{app_id} {decision}."
MSG_ADMIN_DENIED = "This action is for bot admins only."

BTN_SWAP_CONTINUE = "Continue"
BTN_SWAP_CANCEL = "Cancel"
BTN_SWAP_APPLY = "Apply for token swap"
BTN_SWAP_APPROVE = "Approve"
BTN_SWAP_DENY = "Deny"
BTN_SWAP_SENT = "I've sent it"
BTN_SWAP_RESTART = "Start over"
BTN_CONTACT_SUPPORT = "Contact support"

_SWAP_APP_DDL = (
    "CREATE TABLE IF NOT EXISTS rental_swap_applications("
    " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
    " tenant_id TEXT NOT NULL, reason TEXT NOT NULL,"
    " status TEXT NOT NULL DEFAULT 'pending', swap_id TEXT,"
    " created_at TEXT NOT NULL, decided_at TEXT, decided_by INTEGER)"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _support_handle() -> str:
    return "@" + config.SUPPORT_USERNAME if config.SUPPORT_USERNAME else "/support"


def _back_to_rent_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("My Rental", callback_data="rent:mine"))
    return kb


def _cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
    return kb


async def _ensure_table():
    async with db._db() as conn:
        await conn.execute(_SWAP_APP_DDL)
        await conn.commit()


async def _get_application(app_id: int):
    await _ensure_table()
    async with db._db() as conn:
        async with conn.execute(
            "SELECT id, user_id, tenant_id, reason, status, swap_id, decided_by"
            " FROM rental_swap_applications WHERE id=?",
            (app_id,),
        ) as cur:
            return await cur.fetchone()


async def _pending_application(user_db_id: int):
    await _ensure_table()
    async with db._db() as conn:
        async with conn.execute(
            "SELECT id FROM rental_swap_applications"
            " WHERE user_id=? AND status IN ('pending','approved','verifying')"
            " ORDER BY id DESC LIMIT 1",
            (user_db_id,),
        ) as cur:
            return await cur.fetchone()


async def _create_application(user_db_id: int, tenant_id: str, reason: str) -> int:
    await _ensure_table()
    async with db._db() as conn:
        cur = await conn.execute(
            "INSERT INTO rental_swap_applications"
            " (user_id, tenant_id, reason, status, created_at)"
            " VALUES(?, ?, ?, 'pending', ?)",
            (user_db_id, tenant_id, reason[:500], _now_iso()),
        )
        await conn.commit()
        return cur.lastrowid


async def _set_status(app_id: int, status: str, decided_by: int = None, swap_id: str = None):
    await _ensure_table()
    async with db._db() as conn:
        await conn.execute(
            "UPDATE rental_swap_applications SET status=?, decided_at=?,"
            " decided_by=COALESCE(?, decided_by), swap_id=COALESCE(?, swap_id)"
            " WHERE id=?",
            (status, _now_iso(), decided_by, swap_id, app_id),
        )
        await conn.commit()


def _is_admin(tg_id: int) -> bool:
    return tg_id in config.ADMINS


async def _clear(message, state: FSMContext):
    async with state.proxy() as data:
        data.pop("token", None)
        data.pop("swap_id", None)
        data.pop("nonce", None)
        data.pop("app_id", None)
        data.pop("new_username", None)
    await state.finish()


def _err_text(exc: Exception) -> str:
    msg = str(exc)
    if msg.startswith("http_"):
        return MSG_SWAP_UNAVAILABLE
    return MSG_SWAP_UNAVAILABLE


async def _get_tenant(user_id: str):
    """Resolve the rental tenant for a platform user_id via the control plane."""
    result = await _nova(
        "GET", "/api/internal/rental/tenants/by-user", params={"user_id": user_id}
    )
    return (result.get("tenant") or {}).get("id")


async def _get_current_bot(tenant_id: str) -> str:
    """Human-readable label of the tenant's currently connected bot."""
    try:
        result = await _nova("GET", f"/api/internal/rental/tenants/{tenant_id}/overview")
    except RuntimeError:
        return "unknown"
    instances = result.get("botInstances") or result.get("instances") or []
    for inst in instances:
        if str(inst.get("status") or "") in ("active", "suspended"):
            username = inst.get("username")
            return "@" + username if username else "connected bot"
    return "no bot connected"


# --- Tenant: application ---


@dp.callback_query_handler(text="rswap:start")
async def cb_swap_start(query: types.CallbackQuery):
    await query.answer()
    try:
        user_id = await _get_user_id(query.from_user.id)
    except RuntimeError:
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    if not user_id:
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if await _pending_application(user["id"]):
        await edit_text_safe(query, MSG_SWAP_ALREADY_PENDING, reply_markup=_back_to_rent_kb())
        return
    try:
        tenant_id = await _get_tenant(user_id)
    except RuntimeError:
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    if not tenant_id:
        await edit_text_safe(query, MSG_SWAP_NO_RENTAL, reply_markup=_back_to_rent_kb())
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_CONTINUE, callback_data="rswap:begin"))
    kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
    await edit_text_safe(
        query, MSG_SWAP_EXPLAIN.format(support=_support_handle()), reply_markup=kb
    )


@dp.callback_query_handler(text="rswap:begin")
async def cb_swap_begin(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await SwapFlow.waiting_reason.set()
    await query.message.answer(MSG_SWAP_ASK_REASON, reply_markup=_cancel_kb())


@dp.message_handler(state=SwapFlow.waiting_reason)
async def msg_swap_reason(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    reason = (message.text or "").strip()
    if not reason:
        return
    try:
        user_id = await _get_user_id(message.from_user.id)
        tenant_id = await _get_tenant(user_id) if user_id else None
    except RuntimeError:
        await state.finish()
        await message.answer(MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    if not tenant_id:
        await state.finish()
        await message.answer(MSG_SWAP_NO_RENTAL, reply_markup=_back_to_rent_kb())
        return
    old_bot = await _get_current_bot(tenant_id)
    async with state.proxy() as data:
        data["reason"] = reason
        data["tenant_id"] = tenant_id
        data["old_bot"] = old_bot
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_APPLY, callback_data="rswap:confirm"))
    kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
    await message.answer(
        MSG_SWAP_CONFIRM.format(old_bot=old_bot, reason=reason[:300]), reply_markup=kb
    )
    # State stays open: the confirm button below reads reason/tenant_id from it.


@dp.callback_query_handler(text="rswap:confirm")
async def cb_swap_confirm(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    reason = data.get("reason")
    tenant_id = data.get("tenant_id")
    old_bot = data.get("old_bot") or "connected bot"
    if not reason or not tenant_id:
        await edit_text_safe(query, MSG_SWAP_CANCELLED, reply_markup=_back_to_rent_kb())
        return
    app_id = await _create_application(user["id"], tenant_id, reason)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_APPROVE, callback_data=f"rswap:approve:{app_id}"))
    kb.add(InlineKeyboardButton(BTN_SWAP_DENY, callback_data=f"rswap:deny:{app_id}"))
    try:
        await notify_admins(
            MSG_ADMIN_SWAP_REQUEST.format(
                app_id=app_id,
                name=user["name"] or "?",
                tg_id=user["tg_id"],
                old_bot=old_bot,
                reason=reason[:300],
            ),
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning("swap application notify_admins failed: %s", e)
    await state.finish()
    await edit_text_safe(
        query, MSG_SWAP_SENT.format(support=_support_handle()), reply_markup=_back_to_rent_kb()
    )


@dp.callback_query_handler(text="rswap:cancel")
async def cb_swap_cancel(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await _clear(query.message, state)
    await edit_text_safe(query, MSG_SWAP_CANCELLED, reply_markup=_back_to_rent_kb())


# --- Owner: approve / deny ---


async def _admin_only(query: types.CallbackQuery) -> bool:
    tg_id = query.from_user.id
    if _is_admin(tg_id):
        return True
    u = await db.get_user_by_tg(tg_id)
    if u and u["role_mask"]:
        return True
    await query.answer(MSG_ADMIN_DENIED, show_alert=True)
    return False


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rswap:approve:"))
async def cb_swap_approve(query: types.CallbackQuery):
    await query.answer()
    if not await _admin_only(query):
        return
    app_id = int(query.data.split(":")[2])
    app = await _get_application(app_id)
    if not app or app["status"] != "pending":
        await query.answer("Already decided.", show_alert=True)
        return
    await _set_status(app_id, "approved", decided_by=query.from_user.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_CONTINUE, callback_data=f"rswap:continue:{app_id}"))
    try:
        tenant_user = await db.get_user(app["user_id"])
        if tenant_user:
            await bot.send_message(
                tenant_user["tg_id"],
                MSG_SWAP_APPROVED_TENANT,
                reply_markup=kb,
            )
    except Exception as e:
        logger.warning("swap approve notify tenant failed: %s", e)
    await edit_text_safe(query, MSG_ADMIN_SWAP_DECIDED.format(app_id=app_id, decision="approved"))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rswap:deny:"))
async def cb_swap_deny(query: types.CallbackQuery):
    await query.answer()
    if not await _admin_only(query):
        return
    app_id = int(query.data.split(":")[2])
    app = await _get_application(app_id)
    if not app or app["status"] != "pending":
        await query.answer("Already decided.", show_alert=True)
        return
    await _set_status(app_id, "denied", decided_by=query.from_user.id)
    try:
        tenant_user = await db.get_user(app["user_id"])
        if tenant_user:
            await bot.send_message(
                tenant_user["tg_id"],
                MSG_SWAP_DENIED_TENANT.format(support=_support_handle()),
                reply_markup=_back_to_rent_kb(),
            )
    except Exception as e:
        logger.warning("swap deny notify tenant failed: %s", e)
    await edit_text_safe(query, MSG_ADMIN_SWAP_DECIDED.format(app_id=app_id, decision="denied"))


# --- Tenant: verified swap after approval ---


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rswap:continue:"))
async def cb_swap_continue(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    app_id = int(query.data.split(":")[2])
    app = await _get_application(app_id)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if not app or app["user_id"] != user["id"] or app["status"] != "approved":
        await edit_text_safe(query, MSG_SWAP_CANCELLED, reply_markup=_back_to_rent_kb())
        return
    async with state.proxy() as data:
        data["app_id"] = app_id
        data["tenant_id"] = app["tenant_id"]
        data["decided_by"] = app["decided_by"]
    await _set_status(app_id, "verifying")
    await SwapFlow.waiting_token.set()
    await query.message.answer(MSG_SWAP_ASK_TOKEN, reply_markup=_cancel_kb())


@dp.message_handler(state=SwapFlow.waiting_token, content_types=types.ContentType.TEXT)
async def msg_swap_token(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.lower() in ("cancel", "/cancel"):
        await _clear(message, state)
        await message.answer(MSG_SWAP_CANCELLED, reply_markup=_back_to_rent_kb())
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
        await message.answer(MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return
    if not user_id:
        await _clear(message, state)
        await message.answer(MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return

    try:
        result = await _nova(
            "POST", "/api/internal/rental/token/validate", json_body={"token": token}
        )
    except RuntimeError:
        await _clear(message, state)
        await message.answer(MSG_SWAP_BAD_TOKEN, reply_markup=_cancel_kb())
        await SwapFlow.waiting_token.set()
        return

    new_username = ((result.get("bot") or {}).get("username") or "").strip()
    async with state.proxy() as data:
        data["token"] = token
        data["new_username"] = "@" + new_username if new_username else "your new bot"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Start verification", callback_data="rswap:verify"))
    kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
    await message.answer(
        MSG_SWAP_NEW_BOT.format(username="@" + new_username if new_username else "your new bot"),
        reply_markup=kb,
    )
    # State stays open: the verify button below reads the token from it.


@dp.callback_query_handler(text="rswap:verify")
async def cb_swap_verify(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    token = data.get("token")
    app_id = data.get("app_id")
    tenant_id = data.get("tenant_id")
    if not token or not app_id or not tenant_id:
        await edit_text_safe(
            query,
            MSG_SWAP_CHALLENGE_EXPIRED,
            reply_markup=_back_to_rent_kb(),
        )
        return
    try:
        user_id = await _get_user_id(query.from_user.id)
    except RuntimeError:
        await _clear(query.message, state)
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return

    try:
        result = await _nova(
            "POST",
            "/api/internal/rental/support/swaps",
            json_body={
                "tenant_id": tenant_id,
                "new_token": token,
                "ticket_ref": f"bot-swap-app-{app_id}",
                "actor": f"tg:{query.from_user.id}",
                "owner_telegram_id": str(query.from_user.id),
                "owner_user_id": user_id,
            },
        )
    except RuntimeError as exc:
        await _clear(query.message, state)
        await edit_text_safe(query, _err_text(exc), reply_markup=_back_to_rent_kb())
        return

    swap_id = result.get("swap_id")
    code = result.get("code")
    if not swap_id or not code:
        await _clear(query.message, state)
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_back_to_rent_kb())
        return

    async with state.proxy() as sdata:
        sdata["swap_id"] = swap_id
        sdata["nonce"] = result.get("challenge_id")
        sdata["app_id"] = app_id
        sdata["decided_by"] = data.get("decided_by")
        sdata["new_username"] = data.get("new_username")
        # Token no longer needed: the vault holds it now. Wipe immediately.
        sdata.pop("token", None)
    await _set_status(app_id, "verifying", swap_id=swap_id)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_SENT, callback_data="rswap:check"))
    kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
    await edit_text_safe(query, MSG_SWAP_CODE.format(code=code), reply_markup=kb)


@dp.callback_query_handler(text="rswap:check")
async def cb_swap_check(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    nonce = data.get("nonce")
    swap_id = data.get("swap_id")
    app_id = data.get("app_id")
    if not nonce or not swap_id:
        await _clear(query.message, state)
        await edit_text_safe(
            query, MSG_SWAP_CHALLENGE_EXPIRED, reply_markup=_back_to_rent_kb()
        )
        return
    try:
        result = await _nova(
            "GET", "/api/internal/rental/token/challenge", params={"nonce": nonce}
        )
    except RuntimeError:
        await edit_text_safe(query, MSG_SWAP_UNAVAILABLE, reply_markup=_cancel_kb())
        return

    if result.get("status") == "passed":
        await _execute_swap(query, state, data)
        return
    if result.get("status") == "pending":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(BTN_SWAP_SENT, callback_data="rswap:check"))
        kb.add(InlineKeyboardButton(BTN_SWAP_CANCEL, callback_data="rswap:cancel"))
        await edit_text_safe(query, MSG_SWAP_WAITING, reply_markup=kb)
        return
    await _clear(query.message, state)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(BTN_SWAP_RESTART, callback_data="rswap:start"))
    await edit_text_safe(
        query,
        MSG_SWAP_CHALLENGE_EXPIRED.format(support=_support_handle()),
        reply_markup=kb,
    )


async def _execute_swap(query: types.CallbackQuery, state: FSMContext, data: dict):
    swap_id = data.get("swap_id")
    app_id = data.get("app_id")
    approver = data.get("decided_by")
    new_username = data.get("new_username") or "your new bot"
    try:
        await _nova(
            "POST",
            f"/api/internal/rental/support/swaps/{swap_id}/execute",
            json_body={
                "actor": f"tg:{query.from_user.id}",
                # Dual control: the owner already approved the application.
                "approver_2": str(approver) if approver else None,
            },
        )
    except RuntimeError as exc:
        logger.warning("swap execute failed for %s: %s", swap_id, exc)
        await _clear(query.message, state)
        if app_id:
            await _set_status(app_id, "failed")
        await edit_text_safe(
            query,
            MSG_SWAP_FAILED.format(support=_support_handle()),
            reply_markup=_back_to_rent_kb(),
        )
        return
    await _clear(query.message, state)
    if app_id:
        await _set_status(app_id, "done")
    try:
        await notify_admins(f"Token swap completed for application #{app_id}.")
    except Exception as e:
        logger.warning("swap done notify_admins failed: %s", e)
    await edit_text_safe(
        query, MSG_SWAP_DONE.format(username=new_username), reply_markup=_back_to_rent_kb()
    )
