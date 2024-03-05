#==================================================================
# ChatAICore.py
#
# Author: Davide Pasca, 2024/01/27
# Description:
#==================================================================

from .logger import *
from . import MsgThread

# Return codes
ERR_THREAD_EXPIRED = "ERR_THREAD_EXPIRED"
ERR_THREAD_IN_USE = "ERR_THREAD_IN_USE"
ERR_RUN_FAILED = "ERR_RUN_FAILED"
SUCCESS = "SUCCESS"

# Special instructions independent of the basic "role" instructions
MESSAGEMETA_INSTUCT = f"""
The user messages usually begins with metadata in a format like this:
<{MsgThread.META_TAG}>
unix_time: 1620000000
</{MsgThread.META_TAG}>
The user does not write this. It's injected by the chat app for the assistant to use.
Do not make any mention of this metadata. Simply use it organically when needed (e.g.
when asked about the time, use the unix_time value but do not mention it explicitly).
"""

FORMAT_INSTRUCT = r"""
When asked about equations or mathematical formulas you should use LaTeX formatting.
For each piece of mathematical content:
 1. If the content is inline, use `$` as prefix and postfix (e.g. `$\Delta x$`)
 2. If the content is a block, use `$$` as prefix and postfix (e.g. `\n$$\sigma = \frac{1}{2}at^2$$\n` here the `\n` are newlines)
"""

#==================================================================
def instrument_instructions(msg_text):
    return msg_text + "\n" + MESSAGEMETA_INSTUCT + "\n" + FORMAT_INSTRUCT
