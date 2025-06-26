from .admin_img import register_admin_img
from .admin_font import register_admin_fonts
from .admin_color import register_admin_colors
from .admin_subscription import register_admin_subscriptions
from .admin_background import register_admin_backgrounds


def register_handlers(dp):
    register_admin_img(dp)
    register_admin_fonts(dp)
    register_admin_colors(dp)
    register_admin_subscriptions(dp)
    register_admin_backgrounds(dp)
