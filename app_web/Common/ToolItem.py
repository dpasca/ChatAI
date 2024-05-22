#==================================================================
# ToolItem.py
#
# Author: Davide Pasca, 2024/05/20
# Description:
#==================================================================

from typing import Callable

from typing import Dict, Any
from pydantic import BaseModel

class ToolItem(BaseModel):
    name: str
    function: Callable[[dict], Any]
    requires_assistant: bool = False
    definition: Dict[str, Any]
