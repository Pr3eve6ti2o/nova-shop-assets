"""Admin package: permission-filtered console + management flows."""
from filters import IsAdmin  # noqa: F401  (re-exported for admin handlers)

import config
from loader import db


async def mask_of(tg_id: int) -> int:
    if tg_id in config.ADMINS:
        return config.PERM_ALL
    user = await db.get_user_by_tg(tg_id)
    return user["role_mask"] if user else 0


from . import panel, catalog, orders, users, promos, broadcast, maintenance  # noqa: E402
