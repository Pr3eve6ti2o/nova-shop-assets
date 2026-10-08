""" /start with deep links, main menu rendering. """
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import WebAppInfo

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from .common import get_or_register, main_reply_kb, edit_text_safe


async def home_inline_kb(user_id: int):
    """Slim /start actions: the reply keyboard already covers everything else."""
    k = kb.InlineKeyboardMarkup()
    if config.MINIAPP_URL:
        # C3: pass the per-user TON claim code to the Mini App via startapp
        # so it can embed the code in the TON transfer comment.
        code = await db.tonconnect_claim_code(user_id)
        sep = "&" if "?" in config.MINIAPP_URL else "?"
        url = f"{config.MINIAPP_URL}{sep}startapp=tc_{code}"
        k.add(kb.InlineKeyboardButton(texts.BTN_OPEN_STORE,
                                      web_app=WebAppInfo(url=url)))
    # If the welcome-back text mentions items waiting in the cart, make it
    # actionable: a direct "View cart" button instead of a dead-end reminder.
    try:
        cart_n = await db.cart_count(user_id)
    except Exception:
        cart_n = 0
    if cart_n:
        k.add(kb.InlineKeyboardButton(f"{texts.BTN_CART} ({cart_n})",
                                      callback_data="cart"))
    k.add(kb.InlineKeyboardButton(texts.BTN_SHOP, callback_data="shop"))
    return k


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    args = message.get_args() or ""
    tg_id = message.from_user.id

    referred_by = None
    if args.startswith("ref_"):
        ref = await db.get_user_by_ref_code(args[4:])
        if ref and ref["tg_id"] != tg_id:
            referred_by = ref["id"]

    user, is_new = await get_or_register(tg_id, message.from_user.full_name,
                                         referred_by=referred_by)

    # Backfill the persistent "My Rental" menu button for users who
    # subscribed before the flag existed.
    try:
        from .rent import ensure_rental_flag
        await ensure_rental_flag(tg_id)
    except Exception:
        pass

    # Deep link to a product.
    if args.startswith("p_"):
        try:
            pid = int(args[2:])
        except ValueError:
            pid = 0
        try:
            await message.delete()
        except Exception:
            pass
        from .shop import show_product_detail
        await show_product_detail(message, pid, user)
        return

    # Deep link to an order (instant delivery link).
    if args.startswith("o_"):
        try:
            oid = int(args[2:])
        except ValueError:
            oid = 0
        try:
            await message.delete()
        except Exception:
            pass
        from .orders import show_order_detail
        await show_order_detail(message, oid, user)
        return

    try:
        await message.delete()
    except Exception:
        pass
    if is_new:
        welcome = texts.MSG_WELCOME
    else:
        welcome = await _welcome_back_text(user)
    await message.answer(welcome,
                         reply_markup=await main_reply_kb(tg_id))
    await message.answer(texts.MSG_MENU, reply_markup=await home_inline_kb(user["id"]))


async def _welcome_back_text(user) -> str:
    """Returning-user dashboard: cart count + latest active order."""
    lines = []
    count = await db.cart_count(user["id"])
    if count:
        lines.append(texts.MSG_WELCOME_BACK_LINE_CART.format(n=count))
    orders = await db.list_user_orders(user["id"], limit=5, offset=0)
    active = next((o for o in orders if o["status"] not in
                   ("delivered", "cancelled")), None)
    if active:
        lines.append(texts.MSG_WELCOME_BACK_LINE_ORDER.format(
            oid=active["id"],
            status=texts.STATUS_LABEL.get(active["status"], active["status"])))
    if not lines:
        lines.append(texts.MSG_WELCOME_BACK_LINE_NONE)
    return texts.MSG_WELCOME_BACK.format(summary="\n".join(lines))


@dp.callback_query_handler(text="menu")
async def cb_menu(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    # H4: clear the details share-contact keyboard if we're leaving it behind.
    data = await state.get_data()
    if data.get("details_rkb_mid"):
        from .checkout import _clear_details_prompt
        await _clear_details_prompt(query.message.chat.id, data.get("details_rkb_mid"))
    await state.finish()
    muser, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await edit_text_safe(query, texts.MSG_MENU, await home_inline_kb(muser["id"]))
