from .start import register_start_handlers
from .admin import register_admin
from .subscription import register_subscription
from .help import register_help_handlers


def register_handlers(dp):
    register_start_handlers(dp)
    register_admin(dp)
    register_subscription(dp)
    register_help_handlers(dp)
