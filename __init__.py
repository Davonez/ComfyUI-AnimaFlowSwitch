"""Anima 流程总开关 + 控制网开关（独立包）。

只包含两个节点，和 ComfyUI-MuteBypassSwitch 里的同名节点是同一份实现。

License: MIT
"""

__version__ = "1.0.0"

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]
