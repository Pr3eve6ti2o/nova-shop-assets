"""Custom aiogram 2.x filters (imported and bound before handlers register)."""
from aiogram.dispatcher.filters import BoundFilter

import config
from loader import db


class IsAdmin(BoundFilter):
    """Require an admin permission bit. Usage: @dp.message_handler(is_admin=64)."""
    key = "is_admin"

    def __init__(self, is_admin: int):
        # NB: the parameter name must match `key` — the factory calls
        # IsAdmin(is_admin=<value>).
        self.bit = is_admin

    async def check(self, *args) -> bool:
        obj = args[0]
        tg_id = obj.from_user.id
        if tg_id in config.ADMINS:
            return True
        user = await db.get_user_by_tg(tg_id)
        return bool(user and (user["role_mask"] & self.bit))
