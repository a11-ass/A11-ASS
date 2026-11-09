"""Tools package — each tool is a separate module exporting ``register``."""

from .list_pets import register as register_list_pets

__all__ = ["register_list_pets"]
