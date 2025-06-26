from .chatgpt_congrats import register_congrats_handlers
from .generic_picture import register_generic_picture
from .quotes import register_quote_handlers
from .future_letter import register_future_letter
from .buy_font import register_user_fonts
from .buy_background import register_backgrounds


def register_handlers(dp):
    register_congrats_handlers(dp)
    register_generic_picture(dp)
    register_quote_handlers(dp)
    register_future_letter(dp)
    register_user_fonts(dp)
    register_backgrounds(dp)
