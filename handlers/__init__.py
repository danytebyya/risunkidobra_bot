from .core import register_handlers as _register_core
from .branches import register_handlers as _register_branches
from .admin_branches import register_handlers as _register_admin_branches


def register_all(dp):
    _register_core(dp)
    _register_branches(dp)
    _register_admin_branches(dp)
