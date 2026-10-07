import asyncio
import logging
from datetime import datetime

import aiohttp
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from .common import edit_text_safe
from loader import dp

logger = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _nova(method, path, params=None, json_body=None):
    if not config.NOVA_API_KEY:
        raise RuntimeError("unavailable")

    url = config.NOVA_API_URL.rstrip("/") + path
    headers = {"x-api-key": config.NOVA_API_KEY}

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.request(
                method, url, params=params, json=json_body, headers=headers
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None

                if resp.status >= 400:
                    detail = ""
                    if isinstance(data, dict):
                        for key in ("detail", "message", "error"):
                            value = data.get(key)
                            if value:
                                detail = value if isinstance(value, str) else str(value)
                                break
                    message = f"http_{resp.status}"
                    if detail:
                        message = f"{message}: {detail}"
                    raise RuntimeError(message)

                if isinstance(data, dict):
                    return data
                return {}
    except RuntimeError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise RuntimeError("unavailable")
    except Exception:
        raise RuntimeError("unavailable")


async def _get_plans():
    data = await _nova("GET", "/api/internal/plans")
    plans = data.get("plans") or []
    # Single rental plan only: Monthly $8.99 / Yearly $89.99.
    order = {"RENTAL_MONTHLY": 0, "RENTAL_YEARLY": 1}
    rental = [p for p in plans if p.get("name") in order]
    rental.sort(key=lambda p: order.get(p.get("name"), 99))
    return rental


async def _get_user_id(tg_id):
    try:
        data = await _nova(
            "GET",
            "/api/internal/users/by-telegram",
            params={"telegram_id": str(tg_id)},
        )
    except RuntimeError as exc:
        if "http_404" in str(exc):
            return None
        raise
    if not isinstance(data, dict):
        return None
    return data.get("user_id")


_PLAN_LABELS = {
    "RENTAL_MONTHLY": "Monthly",
    "RENTAL_YEARLY": "Yearly",
}


def _plan_label(p):
    if isinstance(p, dict):
        return _PLAN_LABELS.get(p.get("name"), str(p.get("name") or "").title())
    return _PLAN_LABELS.get(p, str(p).title())


def _per(p):
    return "/year" if p.get("name") == "RENTAL_YEARLY" else "/mo"


def _price(p):
    return f"${p['priceCents'] / 100:g}"


def _trial(p):
    if p.get("trialHours"):
        return f", {p['trialHours'] // 24}-day free trial"
    return ""


def _period(p):
    if p.get("periodHours"):
        return f"{p['periodHours'] // 24} days"
    return "monthly"


def _fmt_date(v):
    try:
        raw = str(v)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return str(v)


def _plan_keyboard(plans):
    return kb.rent_plans_kb([(p["id"], _plan_label(p)) for p in plans])


def _rent_success_kb():
    """Back-to-rent keyboard, plus the token-onboarding entry when enabled."""
    keyboard = kb.rent_back_kb()
    if getattr(config, "RENTAL_TOKEN_ONBOARDING", True):
        from aiogram.types import InlineKeyboardButton

        keyboard.add(
            InlineKeyboardButton("\U0001f916 Connect my bot", callback_data="rent:token:start")
        )
    return keyboard


def _plans_text(plans):
    lines = [
        texts.MSG_RENT_PLAN_LINE.format(
            name=_plan_label(p), price=_price(p), per=_per(p), trial=_trial(p)
        )
        for p in plans
    ]
    return texts.MSG_RENT_PLANS.format(plans="\n".join(lines))


async def _render_plans_as_new_message(message, tg_id):
    try:
        plans = await _get_plans()
    except RuntimeError:
        await message.answer(texts.MSG_RENT_UNAVAILABLE)
        return

    text = _plans_text(plans)
    await message.answer(
        text,
        reply_markup=_plan_keyboard(plans),
        disable_web_page_preview=True,
    )


@dp.message_handler(text=texts.BTN_RENT)
async def nav_rent(message: types.Message, state: FSMContext):
    await state.finish()
    await _render_plans_as_new_message(message, message.from_user.id)


@dp.callback_query_handler(text="rent:back")
async def cb_rent_back(query: types.CallbackQuery):
    await query.answer()
    try:
        plans = await _get_plans()
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE)
        return

    await edit_text_safe(
        query,
        _plans_text(plans),
        reply_markup=_plan_keyboard(plans),
    )


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rent:plan:"))
async def cb_rent_plan(query: types.CallbackQuery):
    await query.answer()
    parts = query.data.split(":", 2)
    plan_id = parts[2] if len(parts) > 2 else ""

    try:
        plans = await _get_plans()
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    plan = None
    for p in plans:
        if str(p.get("id")) == str(plan_id):
            plan = p
            break

    if plan is None:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    text = texts.MSG_RENT_DETAIL.format(
        name=_plan_label(plan),
        price=_price(plan),
        per=_per(plan),
        period=_period(plan),
        trial=_trial(plan),
    )
    await edit_text_safe(query, text, reply_markup=kb.rent_plan_detail_kb(plan_id))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rent:method:"))
async def cb_rent_method(query: types.CallbackQuery):
    await query.answer()
    parts = query.data.split(":")
    plan_id = parts[2] if len(parts) > 2 else ""
    provider = parts[3] if len(parts) > 3 else ""

    try:
        plans = await _get_plans()
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    plan = None
    for p in plans:
        if str(p.get("id")) == str(plan_id):
            plan = p
            break

    if plan is None:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    method_label = "Balance" if provider == "balance" else "CryptoBot"
    text = texts.MSG_RENT_CONFIRM.format(
        name=_plan_label(plan),
        price=_price(plan),
        per=_per(plan),
        method=method_label,
    )
    await edit_text_safe(query, text, reply_markup=kb.rent_confirm_kb(plan_id, provider))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rent:confirm:"))
async def cb_rent_confirm(query: types.CallbackQuery):
    await query.answer()
    parts = query.data.split(":")
    plan_id = parts[2] if len(parts) > 2 else ""
    provider = parts[3] if len(parts) > 3 else "balance"

    try:
        user_id = await _get_user_id(query.from_user.id)
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    if not user_id:
        await edit_text_safe(
            query, texts.MSG_RENT_LINK_NEEDED, reply_markup=kb.rent_back_kb()
        )
        return

    try:
        result = await _nova(
            "POST",
            "/api/subscriptions",
            json_body={
                "user_id": user_id,
                "plan_id": plan_id,
                "payment_provider": provider,
            },
        )
    except RuntimeError as exc:
        error = str(exc)
        if "http_404" in error:
            await edit_text_safe(
                query, texts.MSG_RENT_LINK_NEEDED, reply_markup=kb.rent_back_kb()
            )
        elif "http_400" in error and "insufficient" in error.lower():
            await edit_text_safe(
                query, texts.MSG_INSUFFICIENT_BALANCE, reply_markup=kb.rent_back_kb()
            )
        else:
            await edit_text_safe(
                query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb()
            )
        return

    sub = result.get("subscription") if isinstance(result.get("subscription"), dict) else {}
    status = sub.get("status")

    if status == "TRIALING" and sub.get("trialEndsAt"):
        text = texts.MSG_RENT_TRIAL_ACTIVE.format(date=_fmt_date(sub["trialEndsAt"]))
        await edit_text_safe(query, text, reply_markup=_rent_success_kb())
        return

    if provider == "balance":
        amount = ""
        try:
            plans = await _get_plans()
            for p in plans:
                if str(p.get("id")) == str(plan_id):
                    amount = _price(p)
                    break
        except RuntimeError:
            amount = ""
        text = texts.MSG_RENT_CHARGED.format(amount=amount)
        await edit_text_safe(query, text, reply_markup=_rent_success_kb())
        return

    try:
        invoice = await _nova(
            "GET",
            f"/api/subscriptions/{sub.get('id')}/invoice",
            params={"user_id": user_id},
        )
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    pay_url = invoice.get("payUrl") if isinstance(invoice, dict) else None
    keyboard = kb.rent_pay_kb(pay_url) if pay_url else kb.rent_back_kb()
    await edit_text_safe(query, texts.MSG_RENT_INVOICE, reply_markup=keyboard)


@dp.callback_query_handler(text="rent:mine")
async def cb_rent_mine(query: types.CallbackQuery):
    await query.answer()

    try:
        user_id = await _get_user_id(query.from_user.id)
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    if not user_id:
        await edit_text_safe(
            query, texts.MSG_RENT_LINK_NEEDED, reply_markup=kb.rent_back_kb()
        )
        return

    try:
        result = await _nova("GET", f"/api/internal/users/{user_id}/subscriptions")
    except RuntimeError:
        await edit_text_safe(query, texts.MSG_RENT_UNAVAILABLE, reply_markup=kb.rent_back_kb())
        return

    subs = result.get("subscriptions") or []
    if not subs:
        await edit_text_safe(query, texts.MSG_RENT_NONE, reply_markup=kb.rent_back_kb())
        return

    sub = subs[0]
    until = sub.get("trialEndsAt") or sub.get("currentPeriodEnd")
    text = texts.MSG_RENT_MINE.format(
        plan=_plan_label(sub.get("planName")),
        status=sub.get("status"),
        until=_fmt_date(until),
    )
    await edit_text_safe(query, text, reply_markup=_rent_success_kb())