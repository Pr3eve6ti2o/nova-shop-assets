"""Admin package: permission-filtered console + management flows."""
from filters import IsAdmin  # noqa: F401  (re-exported for admin handlers)

import config
from loader import db


async def mask_of(tg_id: int) -> int:
    """Return the permission bitmask for a Telegram user.

    P0: Fail-closed validation — rejects negative/non-int masks (where
    -1 & PERM_X is truthy for every bit = full root), strips unknown bits,
    and denies banned users.
    """
    if tg_id in config.ADMINS:
        return config.PERM_ALL
    user = await db.get_user_by_tg(tg_id)
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
