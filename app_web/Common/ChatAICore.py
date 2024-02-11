#==================================================================
# ChatAICore.py
#
# Author: Davide Pasca, 2024/01/27
# Description:
#==================================================================

import json
import time
from .logger import *
from . import AssistTools
from . import OAIUtils
from . import OpenAIWrapper
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

from typing import Callable

sleepForAPI: Callable[[], None] = lambda: None

def SetSleepForAPI(sleepForAPI_: Callable[[], None]):
    global sleepForAPI
    sleepForAPI = sleepForAPI_

#==================================================================
def prepareUserMessageMeta():
    return f"<{MsgThread.META_TAG}>\nunix_time: {int(time.time())}\n</{MsgThread.META_TAG}>\n"

#==================================================================
# Possible run statuses:
#  in_progress, requires_action, cancelling, cancelled, failed, completed, or expired

#==================================================================
def cancel_thread(wrap, run_id, thread_id):
    while True:
        run = wrap.RetrieveRun(run_id=run_id, thread_id=thread_id)
        logmsg(f"Run status: {run.status}")

        if run.status in ["completed", "cancelled", "failed", "expired"]:
            break

        if run.status in ["queued", "in_progress", "requires_action"]:
            logmsg("Cancelling thread...")
            run = wrap.CancelRun(run_id=run_id, thread_id=thread_id)
            sleepForAPI()
            continue

        if run.status == "cancelling":
            sleepForAPI()
            continue

#==================================================================
def get_thread_status(wrap, thread_id):
    data = wrap.ListRuns(thread_id=thread_id, limit=1).data
    if data is None or len(data) == 0:
        return None, None
    return data[0].status, data[0].id

#==================================================================
def wait_to_use_thread(wrap, thread_id) -> str:
    """Wait for the thread to become available.
       Return SUCCESS if available (not locked by an active run)."""
    for i in range(100):
        status, run_id = get_thread_status(wrap, thread_id)
        if status is None:
            return SUCCESS
        logwarn(f"Thread status from last run: {status}")

        # Acceptable statuses to continue
        if status in ["completed", "failed", "cancelled", "expired"]:
            return SUCCESS

        # Statuses that require waiting
        if status in ["queued", "in_progress", "cancelling"]:
            logmsg("Waiting for thread to become available...")

        # Statuses that we cannot handle at this point
        if status == "requires_action":
            logerr("Thread requires action, but we don't know what to do. Cancelling...")
            cancel_thread(wrap, run_id=run_id, thread_id=thread_id)
            continue

        sleepForAPI()

    return ERR_THREAD_IN_USE

#==================================================================
# Handle the required action (function calling)
def handle_required_action(wrap, run, thread_id, tools_user_data):
    if run.required_action is None:
        logerr("run.required_action is None")
        return

    # Resolve the required actions and collect the results in tool_outputs
    tool_outputs = []
    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
        name = tool_call.function.name

        try:
            arguments = json.loads(tool_call.function.arguments)
        except:
            logerr(f"Failed to parse arguments. function: {name}, arguments: {tool_call.function.arguments}")
            continue

        logmsg(f"Function Name: {name}")
        logmsg(f"Arguments: {arguments}")

        # Add wrap and tools_user_data to the arguments
        arguments["wrap"] = wrap
        arguments["tools_user_data"] = tools_user_data

        # Look up the function in the dictionary and call it
        if name in AssistTools.tool_items_dict:
            responses = AssistTools.tool_items_dict[name].function(arguments)
        else:
            responses = AssistTools.fallback_tool_function(name, arguments)

        if responses is not None:
            tool_outputs.append(
                {
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(responses),
                }
            )

    # Submit the tool outputs
    logmsg(f"Tool outputs: {tool_outputs}")
    run = wrap.SubmitToolsOutputs(
        thread_id=thread_id,
        run_id=run.id,
        tool_outputs=tool_outputs,
    )
    logmsg(f"Run status: {run.status}")


#==================================================================
def create_user_message(wrap, thread_id, msg_text, make_file_url):
    msg_with_meta = prepareUserMessageMeta() + msg_text
    logmsg(f"Creating user message: {msg_with_meta}")

    oai_msg = wrap.CreateMessage(thread_id=thread_id, role="user", content=msg_text)
    return MsgThread.MessageToLocMessage(wrap, oai_msg, make_file_url)

def SendUserMessage(
        wrap,
        last_message_id,
        assistant_id,
        thread_id,
        make_file_url,
        on_replies,
        tools_user_data=None) -> str:

    if (ret := wait_to_use_thread(wrap, thread_id)) != SUCCESS:
        logerr(f"Thread not available: {ret}, skipping")
        return ret

    run = wrap.CreateRun(thread_id=thread_id, assistant_id=assistant_id)

    last_printed_status = None
    while True:
        run = wrap.RetrieveRun(thread_id=thread_id, run_id=run.id)
        if run.status != last_printed_status:
            logmsg(f"Run status: {run.status}")
            last_printed_status = run.status

        if run.status in ["queued", "in_progress"]:
            sleepForAPI()

        if run.status == "requires_action":
            # Handle the function-calling
            handle_required_action(wrap, run, thread_id, tools_user_data)

        if run.status in ["expired", "cancelling", "cancelled", "failed"]:
            logerr("Run failed")
            return ERR_RUN_FAILED

        if run.status == "completed":
            # Check for new messages
            new_messages = wrap.ListAllThreadMessages(
                thread_id=thread_id,
                order="asc",
                after=last_message_id
            )

            if new_messages:
                last_message_id = new_messages[-1].id
                replies = [MsgThread.MessageToLocMessage(wrap, m, make_file_url) for m in new_messages]
                on_replies(replies)

            return SUCCESS

#===============================================================================
# Create the assistant if it doesn't exist
def create_assistant(
        wrap: OpenAIWrapper,
        config: dict,
        instructions: str,
        get_user_info: Callable[[], dict]):

    AssistTools.set_super_get_user_info(get_user_info)

    tools = []
    tools.append({"type": "code_interpreter"})

    # Setup the tools
    for item in AssistTools.tool_items:
        if item.usable_by_root_assistant:
            tools.append({ "type": "function", "function": item.definition })

    if config["enable_retrieval"]:
        tools.append({"type": "retrieval"})

    logmsg(f"Tools: {tools}")

    full_instructions = (instructions
        + "\n" + MESSAGEMETA_INSTUCT
        + "\n" + FORMAT_INSTRUCT)

    codename = config["assistant_codename"]

    # Create or update the assistant
    params = OpenAIWrapper.AssistantParams(
        name=codename,
        instructions=full_instructions,
        tools=tools,
        model=config["model_version"])
    assist, was_created = wrap.CreateOrUpdateAssistant(params)

    if was_created:
        logmsg(f"Created new assistant with name {codename}")
    else:
        logmsg(f"Updated existing assistant with name {codename}")

    return assist

