"""Handler registration.

Order matters in aiogram 2.x: the first handler whose filters match wins.
State-specific text handlers (checkout, cart promo, search, wizards) are
registered before the generic reply-keyboard text handlers.
"""
from . import start  # noqa: F401  (commands first)
from . import legal  # noqa: F401  (legal commands: /terms /privacy /refund)
from . import checkout  # noqa: F401  (FSM text states: contact/address)
from . import cart  # noqa: F401  (CartPromo state, checkout entry)
from . import payments  # noqa: F401  (pre-checkout, successful payment)
from . import crypto  # noqa: F401  (cryptobot + direct deposits + admin panel)
from . import miniapp  # noqa: F401  (WebApp sendData bridge)
from . import shop  # noqa: F401  (SearchFlow states, catalog)
from . import balance  # noqa: F401  (Balance: /balance, top-up)
from . import support  # noqa: F401  (SupportFlow / AdminReplyFlow states)
from . import orders  # noqa: F401
from . import profile  # noqa: F401
from . import admin  # noqa: F401  (admin console + management)
