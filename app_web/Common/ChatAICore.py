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

META_TAG = "message_meta"

# Special instructions independent of the basic "role" instructions
MESSAGEMETA_INSTUCT = f"""
The user messages usually begins with metadata in a format like this:
<{META_TAG}>
unix_time: 1620000000
</{META_TAG}>
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
    return f"<{META_TAG}>\nunix_time: {int(time.time())}\n</{META_TAG}>\n"

def stripUserMessageMeta(msg_with_meta):
    msg = msg_with_meta
    begin_tag = f"<{META_TAG}>"
    end_tag = f"</{META_TAG}>"
    end_tag_len = len(end_tag)

    while True:
        start = msg.find(begin_tag)
        if start == -1:
            break
        end = msg.find(end_tag, start)
        if end == -1:
            break

        # Check if the character following the end tag is a newline
        if msg[end + end_tag_len:end + end_tag_len + 1] == "\n":
            msg = msg[:start] + msg[end + end_tag_len + 1:]
        else:
            msg = msg[:start] + msg[end + end_tag_len:]

    return msg

#==================================================================
def MessageToLocMessage(wrap, message, make_file_url):
    result = {
        "src_id": message.id,
        "created_at": message.created_at,
        "role": message.role,
        "content": []
    }
    for content in message.content:
        if content.type == "text":

            # Strip the message meta if it's a user message
            out_msg = content.text.value
            if message.role == "user":
                out_msg = stripUserMessageMeta(out_msg)

            # Apply whatever annotations may be there
            if content.text.annotations is not None:

                logmsg(f"Annotations: {content.text.annotations}")

                out_msg = OAIUtils.ResolveImageAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations,
                    make_file_url=make_file_url)

                out_msg = OAIUtils.ResolveCiteAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations,
                    wrap=wrap)

                out_msg = OAIUtils.StripEmptyAnnotationsBug(out_msg)

            result["content"].append({
                "value": out_msg,
                "type": content.type
            })
        elif content.type == "image_file":
            # Append the content with the image URL
            result["content"].append({
                "value": make_file_url(content.image_file.file_id, "image.png"),
                "type": content.type
            })
        else:
            result["content"].append({
                "value": "<Unknown content type>",
                "type": "text"
            })
    return result

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
def wait_to_use_thread(wrap, thread_id) -> bool:
    for i in range(5):
        status, run_id = get_thread_status(wrap, thread_id)
        if status is None:
            return True
        logmsg(f"Thread status from last run: {status}")

        # If it's expired, then we just can't use it anymore
        if status == "expired":
            logerr("Thread expired, cannot use it anymore")
            return False

        # Acceptable statuses to continue
        if status in ["completed", "failed", "cancelled"]:
            logmsg("Thread is available")
            return True

        # Waitable states
        if status in ["queued", "in_progress", "cancelling"]:
            logmsg("Waiting for thread to become available...")

        logmsg("Status in required action: " + str(status == "requires_action"))

        # States that we cannot handle at this point
        if status in ["requires_action"]:
            logerr("Thread requires action, but we don't know what to do. Cancelling...")
            cancel_thread(wrap, run_id=run_id, thread_id=thread_id)
            continue

        sleepForAPI()

    return False

#==================================================================
# Handle the required action (function calling)
def handle_required_action(wrap, run, thread_id):
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

        # Look up the function in the dictionary and call it
        if name in AssistTools.ToolActions:
            responses = AssistTools.ToolActions[name](arguments)
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
def SendUserMessage(
        wrap,
        msg_text,
        assistant_id,
        thread_id,
        make_file_url,
        on_replies) -> (str, int):

    if wait_to_use_thread(wrap, thread_id) == False:
        return "Thread unavailable", 500

    msg_with_meta = prepareUserMessageMeta() + msg_text
    logmsg(f"Sending message: {msg_with_meta}")

    msg = wrap.CreateMessage(thread_id=thread_id, role="user", content=msg_text)
    run = wrap.CreateRun(thread_id=thread_id, assistant_id=assistant_id)

    last_message_id = msg.id
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
            handle_required_action(wrap, run, thread_id)

        if run.status in ["expired", "cancelling", "cancelled", "failed"]:
            logerr("Run failed")
            return "Run failed", 500

        if run.status == "completed":
            # Check for new messages
            new_messages = wrap.ListAllThreadMessages(
                thread_id=thread_id,
                order="asc",
                after=last_message_id
            )

            if new_messages:
                last_message_id = new_messages[-1].id
                replies = [MessageToLocMessage(wrap, m, make_file_url) for m in new_messages]
                on_replies(replies)

            return "Run completed", 200

#===============================================================================
# Create the assistant if it doesn't exist
def create_assistant(
        wrap: OpenAIWrapper,
        config: dict,
        instructions: str,
        get_user_info: Callable[[], dict]):

    AssistTools.SetSuperGetUserInfoFn(get_user_info)

    tools = []
    tools.append({"type": "code_interpreter"})

    # Setup the tools
    for name, defn in AssistTools.ToolDefinitions.items():
        tools.append({ "type": "function", "function": defn })

    if config["enable_retrieval"]:
        tools.append({"type": "retrieval"})

    logmsg(f"Tools: {tools}")

    full_instructions = (instructions
        + "\n" + MESSAGEMETA_INSTUCT
        + "\n" + FORMAT_INSTRUCT)

    codename = config["assistant_codename"]

    # Create or update the assistant
    assist, was_created = wrap.CreateOrUpdateAssistant(
        name=codename,
        instructions=full_instructions,
        tools=tools,
        model=config["model_version"])

    if was_created:
        logmsg(f"Created new assistant with name {codename}")
    else:
        logmsg(f"Updated existing assistant with name {codename}")

    return assist

