#==================================================================
# app.py
#
# Author: Davide Pasca, 2023/12/23
# Description: Chat AI Flask app
#==================================================================
import os
import json
import time
from pyexpat.errors import messages
from flask import Flask, redirect, render_template, request, jsonify, session, url_for
from dotenv import load_dotenv
from openai_wrapper import OpenAIWrapper
import datetime
from datetime import datetime
import pytz # For timezone conversion
import inspect
from duckduckgo_search import ddg
from storage import Storage
from io import BytesIO
import re

# References:
# - https://cookbook.openai.com/examples/assistants_api_overview_python

# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)

# Load the instructions
with open(config['assistant_instructions'], 'r') as f:
    assistant_instructions = f.read()

USER_BUCKET_PATH = "user_a_00001"

# Enable for debugging purposes (main overrides this if app.debug is True)
ENABLE_LOGGING = os.getenv('FORCE_ENABLE_LOGGING', '0') == '1'
ENABLE_SLEEP_LOGGING = False

ENABLE_WEBSEARCH = True

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

# Initialize OpenAI API
_oa_wrap = OpenAIWrapper(api_key=os.environ.get("OPENAI_API_KEY"))

#===============================================================================
def logmsg(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"[{caller}] {msg}")

def logerr(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"\033[91m[ERR]\033[0m[{caller}] {msg}")

def show_json(obj):
    try:
        if isinstance(obj, list):
            logmsg(json.dumps(obj))  # Serialize the entire list as JSON
        else:
            logmsg(json.loads(obj.model_dump_json()))  # For objects with model_dump_json
    except AttributeError:
        logerr("Object does not support model_dump_json")
    except:
        logmsg("Object is not JSON serializable, plain print below...")
        logmsg(obj)

def sleepForAPI():
    if ENABLE_LOGGING and ENABLE_SLEEP_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        line = inspect.currentframe().f_back.f_lineno
        print(f"[{caller}:{line}] sleeping...")
    time.sleep(0.5)

#===============================================================================
def prepareUserMessageMeta():
    return f"<{META_TAG}>\nunix_time: {int(time.time())}\n</{META_TAG}>\n"

def stripUserMessageMeta(msg_with_meta):
    # Remove <message_meta> </message_meta> and everything in between
    msg = msg_with_meta
    begin_tag = f"<{META_TAG}>"
    end_tag = f"</{META_TAG}>"
    end_tag_len = len(end_tag)

    while True:
        start = msg.find(begin_tag)
        if start == -1:
            break
        end = msg.find(end_tag)
        if end == -1:
            break

        msg = msg[:start] + msg[end + end_tag_len:]

    return msg

#===============================================================================
# Create the assistant if it doesn't exist
def createAssistant():
    tools = []
    tools.append({"type": "code_interpreter"})

    if ENABLE_WEBSEARCH:
        tools.append(
        {
            "type": "function",
            "function": {
                "name": "perform_web_search",
                "description": "Perform a web search for any unknown or current information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            }
        })

    tools.append(
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": "Get the user info, such as timezone and user-agent (browser)",
        }
    })

    tools.append(
    {
        "type": "function",
        "function": {
            "name": "get_unix_time",
            "description": "Get the current unix time",
        }
    })

    tools.append(
    {
        "type": "function",
        "function": {
            "name": "get_user_local_time",
            "description": "Get the user local time",
        }
    })

    if config["enable_retrieval"]:
        tools.append({"type": "retrieval"})

    logmsg(f"Tools: {tools}")

    full_instructions = (assistant_instructions
        + "\n" + MESSAGEMETA_INSTUCT
        + "\n" + FORMAT_INSTRUCT)

    codename = config["assistant_codename"]

    # Reuse the assistant if it already exists
    for assist in _oa_wrap.ListAssistants().data:
        if assist.name == codename:
            logmsg(f"Found existing assistant with name {codename}")
            # Update the assistant
            _oa_wrap.UpdateAssistant(
                assistant_id=assist.id,
                instructions=full_instructions,
                tools=tools,
                model=config["model_version"])
            return assist

    # Create a new assistant
    logmsg(f"Creating new assistant with name {codename}")
    return _oa_wrap.CreateAssistant(
        name=codename,
        instructions=full_instructions,
        tools=tools,
        model=config["model_version"])

# Create the thread if it doesn't exist
def createThread(force_new=False):
    # if there are no messages in the session, add the role message
    if ('thread_id' not in session) or (session['thread_id'] is None) or force_new:
        thread = _oa_wrap.CreateThread()
        logmsg("Creating new thread with ID " + thread.id)
        # Save the thread ID to the session
        session['thread_id'] = thread.id
        session.modified = True
    else:
        thread = _oa_wrap.RetrieveThread(session['thread_id'])
        logmsg("Retrieved existing thread with ID " + thread.id)
    return thread.id

# Local messages management (a cache of the thread)
def get_loc_messages():
    # Create or get the session messages list
    return session.setdefault('loc_messages', [])

def append_loc_message(message):
    get_loc_messages().append(message)
    session.modified = True

def isImageAnnotation(a):
    return a.type == "file_path" and a.text.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))

# Replace the file paths with actual URLs
def resolveImageAnnotations(out_msg, annotations, make_file_url):
    new_msg = out_msg
    # Sort annotations by start_index in descending order
    sorted_annotations = sorted(annotations, key=lambda x: x.start_index, reverse=True)

    for a in sorted_annotations:
        if isImageAnnotation(a):
            file_id = a.file_path.file_id

            logmsg(f"Found file {file_id} associated with '{a.text}'")

            # Extract a "simple name" from the annotation text
            # It's likely to be a full-pathname, so we just take the last part
            # If there are no slashes, we take the whole name
            simple_name = a.text.split('/')[-1] if '/' in a.text else a.text
            # Replace any characters that are not alphanumeric, underscore, or hyphen with an underscore
            simple_name = re.sub(r'[^\w\-.]', '_', simple_name)

            file_url = make_file_url(file_id, simple_name)

            logmsg(f"Replacing file path {a.text} with URL {file_url}")

            # Replace the file path with the file URL
            new_msg = new_msg[:a.start_index] + file_url + new_msg[a.end_index:]

    return new_msg

def resolveCiteAnnotations(out_msg, annotations):
    citations = []
    for index, a in enumerate(annotations):

        #if isImageAnnotation(a):
        #    continue

        logmsg(f"Found citation '{a.text}'")
        logmsg(f"out_msg: {out_msg}")
        # Replace the text with a footnote
        out_msg = out_msg.replace(a.text, f' [{index}]')

        logmsg(f"out_msg: {out_msg}")

        # Gather citations based on annotation attributes
        if (file_citation := getattr(a, 'file_citation', None)):
            logmsg(f"file_citation: {file_citation}")
            cited_file = _oa_wrap.client.files.retrieve(file_citation.file_id)
            citations.append(f'[{index}] {file_citation.quote} from {cited_file.filename}')
        elif (file_path := getattr(a, 'file_path', None)):
            logmsg(f"file_path: {file_path}")
            cited_file = _oa_wrap.client.files.retrieve(file_path.file_id)
            citations.append(f'[{index}] Click <here> to download {cited_file.filename}')
            # Note: File download functionality not implemented above for brevity

    # Add footnotes to the end of the message before displaying to user
    out_msg += '\n' + '\n'.join(citations)
    return out_msg

import re

# Deal with the bug where empty annotations are added to the message
# We go and remove all 【*†*】blocks
def stripEmptyAnnotationsBug(out_msg):
    # This pattern matches 【*†*】blocks
    pattern = r'【\d+†.*?】'
    # Remove all occurrences of the pattern
    return re.sub(pattern, '', out_msg)

def message_to_dict(message, make_file_url):
    result = {
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

                out_msg = resolveImageAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations,
                    make_file_url=make_file_url)

                out_msg = resolveCiteAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations)

                out_msg = stripEmptyAnnotationsBug(out_msg)

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

#===============================================================================
# Initialize Flask app
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("CHATAI_FLASK_SECRET_KEY")

    global ENABLE_LOGGING
    if app.debug:
        ENABLE_LOGGING = True

    if ENABLE_LOGGING:
        print("Logging is ENABLED")

    return app

app = create_app()

#===============================================================================
logmsg("Creating storage...")
_storage = Storage(os.getenv("DO_STORAGE_CONTAINER"), ENABLE_LOGGING)

# Create the assistant
logmsg("Creating assistant...")
_assistant = createAssistant()

#===============================================================================
@app.route('/api/user_info', methods=['POST'])
def user_info():
    # Store the user info in the session
    user_info = request.get_json()
    session['user_info'] = user_info
    logmsg(f"User info: {user_info}")
    return jsonify({'status': 'success'})

#===============================================================================
@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    # Clear the local messages and invalidate the thread ID
    session['loc_messages'] = []
    # Force-create a new thread
    createThread(force_new=True)

    return redirect(url_for('index'))

#===============================================================================
def make_file_url(file_id, simple_name):
    strippable_prefix = "file-"
    new_name = file_id
    # Strip the initial prefix (if any)
    if new_name.startswith(strippable_prefix):
        new_name = new_name[len(strippable_prefix):]
    new_name += f"_{simple_name}"

    # Out path in the storage is a mix of user ID, file ID and human-readable name
    file_path = f"{USER_BUCKET_PATH}/{new_name}"

    if not _storage.file_exists(file_path):
        logmsg(f"Downloading file {file_id} from source...")
        data = _oa_wrap.GetFileContent(file_id)
        data_io = BytesIO(data.read())
        logmsg(f"Uploading file {file_path} to storage...")
        _storage.upload_file(data_io, file_path)

    logmsg(f"Getting file url for {file_id}, path: {file_path}")
    return _storage.get_file_url(file_path)

#===============================================================================
@app.route('/')
def index():
    # Load or create the thread
    thread_id = createThread(force_new=False)

    # Always clear the local messages, because we will repopulate
    #  from the thread history below
    session['loc_messages'] = []

    # Get all the messages from the thread
    history = _oa_wrap.ListThreadMessages(thread_id=thread_id, order="asc")
    logmsg(f"Found {len(history.data)} messages in the thread history")
    for (i, msg) in enumerate(history.data):

        # Append message to messages list
        logmsg(f"Message {i} ({msg.role}): {msg.content}")
        append_loc_message(
            message_to_dict(
                message=msg,
                make_file_url=make_file_url))

    return render_template(
                'chat.html',
                app_title=config["app_title"],
                assistant_name=config["assistant_name"],
                assistant_avatar=config["assistant_avatar"],
                messages=get_loc_messages(),
                app_version=config["app_version"])

#===============================================================================
def submit_message(assistant_id, thread_id, msg_text):
    msg = _oa_wrap.CreateMessage(
        thread_id=thread_id, role="user", content=msg_text
    )
    run = _oa_wrap.CreateRun(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    return msg, run

# Possible run statuses:
#  in_progress, requires_action, cancelling, cancelled, failed, completed, or expired

#===============================================================================
def get_thread_status(thread_id):
    data = _oa_wrap.ListRuns(thread_id=thread_id, limit=1).data
    if data is None or len(data) == 0:
        return None, None
    return data[0].status, data[0].id

#===============================================================================
def cancel_thread(run_id, thread_id):
    while True:
        run = _oa_wrap.RetrieveRun(run_id=run_id, thread_id=thread_id)
        logmsg(f"Run status: {run.status}")

        if run.status in ["completed", "cancelled", "failed", "expired"]:
            break

        if run.status in ["queued", "in_progress", "requires_action"]:
            logmsg("Cancelling thread...")
            run = _oa_wrap.CancelRun(run_id=run_id, thread_id=thread_id)
            sleepForAPI()
            continue

        if run.status == "cancelling":
            sleepForAPI()
            continue

#===============================================================================
def wait_to_use_thread(thread_id):
    for i in range(5):
        status, run_id = get_thread_status(thread_id)
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
            cancel_thread(run_id=run_id, thread_id=thread_id)
            continue

        sleepForAPI()

    return False

#===============================================================================
def handle_required_action(run, thread_id):
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

        responses = None
        if name == "perform_web_search":
            responses = ddg(arguments["query"], max_results=10)
        elif name == "get_user_info":
            responses = { "user_info": session['user_info'] }
        elif name == "get_unix_time":
            responses = { "unix_time": int(time.time()) }
            logmsg(f"Unix time: {responses['unix_time']}")
        elif name == "get_user_local_time":
            timezone = session['user_info']['timezone']
            tz_timezone = pytz.timezone(timezone)
            logmsg(f"User timezone: {timezone}, pytz timezone: {tz_timezone}")
            user_time = datetime.now(tz_timezone)
            logmsg(f"User local time: {user_time}")
            responses = { "user_local_time": json.dumps(user_time, default=str) }
        else:
            logerr(f"Unknown function {name}. Falling back to web search !")
            name_to_human_friendly = name.replace("_", " ")
            query = f"What is {name_to_human_friendly} of " + " ".join(arguments.values())
            logmsg(f"Submitting made-up query: {query}")
            responses = ddg(query, max_results=3)

        if responses is not None:
            tool_outputs.append(
                {
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(responses),
                }
            )

    # Submit the tool outputs
    logmsg(f"Tool outputs: {tool_outputs}")
    run = _oa_wrap.SubmitToolsOutputs(
        thread_id=thread_id,
        run_id=run.id,
        tool_outputs=tool_outputs,
    )
    logmsg(f"Run status: {run.status}")

#===============================================================================
def timing_decorator(func):
    def wrapper(*args, **kwargs):
        start = datetime.now()
        result = func(*args, **kwargs)
        end = datetime.now()
        logmsg(f"Function {func.__name__} took {end - start} to complete")
        return result
    return wrapper

#===============================================================================
@app.route('/send_message', methods=['POST'])
@timing_decorator
def send_message():

    msg_text = request.json['message']

    thread_id = session['thread_id']

    # Wait or fail if the thread is stuck
    if wait_to_use_thread(thread_id) == False:
        return jsonify({'replies': []}), 500

    msg_with_meta = prepareUserMessageMeta() + msg_text

    # Add the new message to the thread
    logmsg(f"Sending message: {msg_with_meta}")
    msg, run = submit_message(_assistant.id, thread_id, msg_with_meta)

    # Wait for the run to complete
    last_printed_status = None
    while True:
        run = _oa_wrap.RetrieveRun(thread_id=thread_id, run_id=run.id)
        if run.status != last_printed_status:
            logmsg(f"Run status: {run.status}")
            last_printed_status = run.status

        if run.status == "queued" or run.status == "in_progress":
            sleepForAPI()
            continue

        # Handle possible request for action (function calling)
        if run.status == "requires_action":
            handle_required_action(run, thread_id)

        # See if any error occurred so far
        if run.status is ["expired", "cancelling", "cancelled", "failed"]:
            logerr("Run failed")
            return jsonify({'replies': []}), 500

        # All good
        if run.status == "completed":
            break

    # Retrieve all the messages added after our last user message
    new_messages = _oa_wrap.ListThreadMessages(
        thread_id=thread_id,
        order="asc",
        after=msg.id
    )
    logmsg(f"Received {len(new_messages.data)} new messages")

    replies = []
    for msg in new_messages.data:
        # Append message to messages list
        message_dict = message_to_dict(msg, make_file_url)

        append_loc_message(message_dict)
        # We only want the content of the message
        replies.append(message_dict)

    logmsg(f"Replies: {replies}")

    if len(replies) > 0:
        logmsg(f"Sending {len(replies)} replies")
        return jsonify({'replies': replies}), 200
    else:
        logmsg("Sending no replies")
        return jsonify({'replies': []}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
