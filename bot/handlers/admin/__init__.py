"""Admin package: permission-filtered console + management flows."""
from filters import IsAdmin  # noqa: F401  (re-exported for admin handlers)

# P2-3: Explicit exports instead of noqa comment.
__all__ = ["IsAdmin", "mask_of"]

import config
from loader import db


async def mask_of(tg_id: int) -> int:
    """Return the permission bitmask for a Telegram user.

    P0: Fail-closed validation — rejects negative/non-int masks (where
    -1 & PERM_X is truthy for every bit = full root), strips unknown bits,
    and denies banned users.
    P1-4: Root admin access is audit-logged so the bypass has a trail.
    """
    if tg_id in config.ADMINS:
        # P1-4: Even root access gets an audit trail entry.
        try:
            user = await db.get_user_by_tg(tg_id)
            uid = user["id"] if user else 0
            await db.audit(uid, "admin_root_access", f"tg_id={tg_id}")
        except Exception:
            pass  # audit failure must not block admin access
        return config.PERM_ALL
    # P1-3: Fail closed on DB exception — do not propagate, do not grant.
    try:
        user = await db.get_user_by_tg(tg_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("mask_of DB error for %s: %s", tg_id, e)
        return 0
    if not user:
        return 0
    # Banned users get nothing, even with a stored mask.
    if user.get("is_banned"):
        return 0
    mask = user.get("role_mask") or 0
    if not isinstance(mask, int) or mask < 0:
        return 0
    # Strip any bits outside the known set (future bits, corrupt values).
    return mask & config.PERM_ALL


from . import panel, catalog, orders, users, promos, broadcast, maintenance  # noqa: E402
