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

# Return codes
ERR_THREAD_EXPIRED = "ERR_THREAD_EXPIRED"
ERR_THREAD_TIMEOUT = "ERR_THREAD_TIMEOUT"
ERR_RUN_FAILED = "ERR_RUN_FAILED"
SUCCESS = "SUCCESS"

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
def wait_to_use_thread(wrap, thread_id) -> str:
    for i in range(5):
        status, run_id = get_thread_status(wrap, thread_id)
        if status is None:
            return SUCCESS
        logmsg(f"Thread status from last run: {status}")

        # If it's expired, then we just can't use it anymore
        if status == "expired":
            logerr("Thread expired, cannot use it anymore")
            return ERR_THREAD_EXPIRED

        # Acceptable statuses to continue
        if status in ["completed", "failed", "cancelled"]:
            logmsg("Thread is available")
            return SUCCESS

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

    return ERR_THREAD_TIMEOUT

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

        # Add the tools_user_data to the arguments
        arguments["tools_user_data"] = tools_user_data

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
def create_user_message(wrap, thread_id, msg_text, make_file_url):
    msg_with_meta = prepareUserMessageMeta() + msg_text
    logmsg(f"Creating user message: {msg_with_meta}")

    oai_msg = wrap.CreateMessage(thread_id=thread_id, role="user", content=msg_text)
    return MessageToLocMessage(wrap, oai_msg, make_file_url)

def SendUserMessage(
        wrap,
        last_message_id,
        assistant_id,
        thread_id,
        make_file_url,
        on_replies,
        tools_user_data=None) -> str:

    if (ret := wait_to_use_thread(wrap, thread_id)) != SUCCESS:
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
                replies = [MessageToLocMessage(wrap, m, make_file_url) for m in new_messages]
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

# Manage an OpenAI thread
# Starts loading a thread, keeps a local version of the messages
import json
from pydantic import BaseModel
from typing import List, Optional
#from .OpenAIWrapper import OpenAIWrapper
from .ConvoJudge import ConvoJudge

class MsgThread(BaseModel):
    wrap: OpenAIWrapper
    thread_id: str
    messages: List[str] = []
    judge: Optional[ConvoJudge] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def create_thread(cls, wrap: OpenAIWrapper):
        oai_thread = wrap.CreateThread()
        return cls(wrap=wrap, thread_id=oai_thread.id)

    @classmethod
    def from_thread_id(cls, wrap: OpenAIWrapper, thread_id: str):
        wrap.RetrieveThread(thread_id)
        return cls(wrap=wrap, thread_id=thread_id)

    def to_json(self):
        # Convert messages to a serializable format
        serializable_messages = [self.message_to_dict(m) for m in self.messages]
        return json.dumps({
            'thread_id': self.thread_id,
            'messages': serializable_messages})

    def message_to_dict(self, message):
        # Convert a message object to a dictionary
        return {
            'src_id': message['src_id'],
            'created_at': message['created_at'],
            'role': message['role'],
            'content': message['content'],
        }

    def serialize_data(self):
        return self.to_json()

    def deserialize_data(self, data):
        attrs = json.loads(data)
        if attrs['thread_id'] != self.thread_id:
            logerr(f"Thread ID mismatch: {attrs['thread_id']} != {self.thread_id}. Ignoring.")

        self.thread_id = attrs['thread_id']
        self.messages = attrs['messages']

    def fetch_new_messages(self, make_file_url):
        new_oai_messages = self.wrap.ListAllThreadMessages(
            thread_id=self.thread_id,
            order="asc",
            after=self.messages[-1]['src_id'] if self.messages else ''
        )
        if new_oai_messages:
            new_messages = [MessageToLocMessage(self.wrap, m, make_file_url) for m in new_oai_messages]
            self.messages.extend(new_messages)

        return len(new_oai_messages)
    
    def create_judge(self, model, temperature):
        self.judge = ConvoJudge(model=model, temperature=temperature)
        for msg in self.messages:
            self.judge.AddMessage(msg)

    def gen_fact_check(self, tools_user_data=None):
        if self.judge:
            fc = self.judge.GenFactCheck(self.wrap, tools_user_data)
            # Find and remove ```json at start and ``` at end
            if fc.startswith("```json"): fc = fc[7:]
            if fc.endswith("```"): fc = fc[:-3]
            return fc
        else:
            return None

    def add_message(self, msg):
        self.messages.append(msg)
        if self.judge:
            self.judge.AddMessage(msg)

