import os
import json
import time
from pyexpat.errors import messages
from flask import Flask, redirect, render_template, request, jsonify, session, url_for
from openai import OpenAI
import datetime
import hashlib
import inspect
from duckduckgo_search import ddg

# References:
# - https://cookbook.openai.com/examples/assistants_api_overview_python

# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)

# Enable for debugging purposes (main overrides this if app.debug is True)
ENABLE_LOGGING = False

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

# Initialize OpenAI API
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

#===============================================================================
def logmsg(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"[{caller}] {msg}")

def logerr(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"\033[91m[ERR][{caller}] {msg}\033[0m")

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

    if config["enable_retrieval"]:
        tools.append({"type": "retrieval"})

    logmsg(f"Tools: {tools}")

    full_instructions = "\n".join(config["assistant_instructions"]) + "\n" + MESSAGEMETA_INSTUCT

    codename = config["assistant_codename"]

    # Reuse the assistant if it already exists
    for assist in client.beta.assistants.list().data:
        if assist.name == codename:
            logmsg(f"Found existing assistant with name {codename}")
            # Update the assistant
            client.beta.assistants.update(
                assistant_id=assist.id,
                instructions=full_instructions,
                tools=tools,
                model=config["model_version"])
            return assist

    # Create a new assistant
    logmsg(f"Creating new assistant with name {codename}")
    return client.beta.assistants.create(
        name=codename,
        instructions=full_instructions,
        tools=tools,
        model=config["model_version"])

# Create the thread if it doesn't exist
def createThread(force_new=False):
    # if there are no messages in the session, add the role message
    if ('thread_id' not in session) or (session['thread_id'] is None) or force_new:
        thread = client.beta.threads.create()
        logmsg("Creating new thread with ID " + thread.id)
        # Save the thread ID to the session
        session['thread_id'] = thread.id
        session.modified = True
    else:
        thread = client.beta.threads.retrieve(session['thread_id'])
        logmsg("Retrieved existing thread with ID " + thread.id)
    return thread.id

# Local messages management (a cache of the thread)
def get_loc_messages():
    # Create or get the session messages list
    return session.setdefault('loc_messages', [])

def append_loc_message(message):
    get_loc_messages().append(message)
    session.modified = True

def message_to_dict(message):
    result = {
        "role": message.role,
        "content": []
    }
    for content in message.content:
        if content.type == "text":

            # Strip the message meta if it's a user message
            val = content.text.value
            if message.role == "user":
                val = stripUserMessageMeta(val)

            result["content"].append({
                "value": val,
                "type": content.type
            })
        elif content.type == "image_file":
            result["content"].append({
                "value": content.image_file.file_id,
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
        print("Logging enabled.")
    
    return app

app = create_app()

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
@app.route('/')
def index():
    # Load or create the thread
    thread_id = createThread(force_new=False)

    # Always clear the local messages, because we will repopulate
    #  from the thread history below
    session['loc_messages'] = []

    # Get all the messages from the thread
    history = client.beta.threads.messages.list(thread_id=thread_id, order="asc")
    logmsg(f"Found {len(history.data)} messages in the thread history")
    for (i, msg) in enumerate(history.data):
        # Append message to messages list
        logmsg(f"Message {i} ({msg.role}): {msg.content}")
        append_loc_message(message_to_dict(msg))

    return render_template(
                'chat.html',
                assistant_name=config["assistant_name"],
                messages=get_loc_messages(),
                app_version=config["app_version"])

#===============================================================================
def submit_message(assistant_id, thread_id, msg_text):
    msg = client.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=msg_text
    )
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    return msg, run

def get_response(thread):
    return client.beta.threads.messages.list(thread_id=thread.id, order="asc")

def wait_on_run(run, thread_id):
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run.status == "queued" or run.status == "in_progress":
            time.sleep(0.5)
        else:
            break

# Possible run statuses:
#  in_progress, requires_action, cancelling, cancelled, failed, completed, or expired

#===============================================================================
def get_thread_status(thread_id):
    data = client.beta.threads.runs.list(thread_id=thread_id, limit=1).data
    if data is None or len(data) == 0:
        return None, None
    return data[0].status, data[0].id

#===============================================================================
def cancel_thread(run_id, thread_id):
    while True:
        run = client.beta.threads.runs.retrieve(run_id=run_id, thread_id=thread_id)
        logmsg(f"Run status: {run.status}")

        if run.status in ["completed", "cancelled", "failed", "expired"]:
            break

        if run.status in ["queued", "in_progress", "requires_action"]:
            logmsg("Cancelling thread...")
            run = client.beta.threads.runs.cancel(run_id=run_id, thread_id=thread_id)
            time.sleep(0.5)
            continue

        if run.status == "cancelling":
            time.sleep(0.5)
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

        time.sleep(0.5)

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
        arguments = json.loads(tool_call.function.arguments)
        logmsg(f"Function Name: {name}")
        logmsg(f"Arguments: {arguments}")

        responses = None
        if name == "perform_web_search":
            responses = ddg(arguments["query"], max_results=10)
        elif name == "get_user_info":
            responses = { "user_info": session['user_info'] }
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
    run = client.beta.threads.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run.id,
        tool_outputs=tool_outputs,
    )
    logmsg(f"Run status: {run.status}")

#===============================================================================
@app.route('/send_message', methods=['POST'])
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
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if run.status != last_printed_status:
            logmsg(f"Run status: {run.status}")
            last_printed_status = run.status

        if run.status == "queued" or run.status == "in_progress":
            time.sleep(0.5)
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
    new_messages = client.beta.threads.messages.list(
        thread_id=thread_id,
        order="asc",
        after=msg.id
    )
    logmsg(f"Received {len(new_messages.data)} new messages")

    replies = []
    for msg in new_messages.data:
        # Append message to messages list
        message_dict = message_to_dict(msg)
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
