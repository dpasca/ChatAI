import os
import json
import time
from pyexpat.errors import messages
from flask import Flask, redirect, render_template, request, jsonify, session, url_for
from openai import OpenAI
import datetime
import hashlib
import inspect

# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)

# Enable for debugging purposes
ENABLE_LOGGING = False

ASSISTANT_NAME = config["ASSISTANT_NAME"]
ASSISTANT_ROLE = "\n".join(config["ASSISTANT_ROLE"])

# Initialize OpenAI API
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

#===============================================================================
def logmsg(msg):
    if ENABLE_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        print(f"[{caller}] {msg}")

def show_json(obj):
    try:
        if isinstance(obj, list):
            logmsg(json.dumps(obj))  # Serialize the entire list as JSON
        else:
            logmsg(json.loads(obj.model_dump_json()))  # For objects with model_dump_json
    except AttributeError:
        logmsg("Object does not support model_dump_json")
    except:
        logmsg("Object is not JSON serializable, plain print below...")
        logmsg(obj)

#===============================================================================
# Create the assistant if it doesn't exist
def createAssistant():
    # Make an unique string based on the hash of the name and the role
    def_str = ASSISTANT_NAME
    def_str += ASSISTANT_ROLE
    def_str += config["model_version"]
    unique_name = ASSISTANT_NAME + "_" + hashlib.sha256(def_str.encode()).hexdigest()

    assist_list = client.beta.assistants.list()
    for assist in assist_list.data:
        if assist.name == unique_name:
            logmsg(f"Found existing assistant with name {unique_name}")
            return client.beta.assistants.retrieve(assist.id)

    logmsg(f"Creating new assistant with name {unique_name}")
    return client.beta.assistants.create(
        name=unique_name,
        instructions=ASSISTANT_ROLE,
        tools=[{"type": "code_interpreter"}],
        model=config["model_version"])

assistant = createAssistant()

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

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("CHATAI_FLASK_SECRET_KEY")

# Local messages management (a cache of the thread)
def get_loc_messages():
    # Create or get the session messages list
    return session.setdefault('loc_messages', [])

def append_loc_message(message):
    get_loc_messages().append(message)
    session.modified = True

def message_to_dict(message):
    #show_json(message)
    content_text = ""
    for content in message.content:
        if content.type == "text":
            content_text = content.text.value

    return {
        "role": message.role,
        "content": content_text
    } 

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
                assistant_name=ASSISTANT_NAME,
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
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id,
        )
        time.sleep(0.5)
    return run

#===============================================================================
@app.route('/send_message', methods=['POST'])
def send_message():

    msg_text = request.json['message']

    thread_id = session['thread_id']

    # Add the new message to the thread
    msg, run = submit_message(assistant.id, thread_id, msg_text)

    wait_on_run(run, thread_id)

    # Retrieve all the messages added after our last user message
    new_messages = client.beta.threads.messages.list(
        thread_id=thread_id,
        order="asc",
        after=msg.id
    )
    logmsg(f"Received {len(new_messages.data)} new messages")

    plain_replies = []
    for msg in new_messages.data:
        # Append message to messages list
        message_dict = message_to_dict(msg)
        append_loc_message(message_dict)
        # We only want the content of the message
        plain_replies.append(message_dict["content"])

    logmsg(f"Replies: {plain_replies}")

    if len(plain_replies) > 0:
        logmsg(f"Sending {len(plain_replies)} replies")
        return jsonify({'reply': plain_replies}), 200
    else:
        logmsg("Sending no reply")
        return jsonify({'reply': ["*No reply*"]}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
