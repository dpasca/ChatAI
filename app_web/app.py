#==================================================================
# app.py
#
# Author: Davide Pasca, 2023/12/23
# Description: Chat AI Flask app
#==================================================================
import os
import sys
import json
import time
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
import datetime
from datetime import datetime
import inspect
from io import BytesIO

# Update the path for the modules below
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Common'))
from OpenAIWrapper import OpenAIWrapper
from StorageCloud import StorageCloud as Storage
from logger import *
from OAIUtils import *

USER_BUCKET_PATH = "user_a_00001"
ENABLE_SLEEP_LOGGING = False

#===============================================================================
# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)

# Load the instructions
with open(config['assistant_instructions'], 'r') as f:
    assistant_instructions = f.read()

# Initialize OpenAI API
_oa_wrap = OpenAIWrapper(api_key=os.environ.get("OPENAI_API_KEY"))

#===============================================================================
import ChatAICore

def sleepForAPI():
    if ENABLE_LOGGING and ENABLE_SLEEP_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        line = inspect.currentframe().f_back.f_lineno
        print(f"[{caller}:{line}] sleeping...")
    time.sleep(0.5)

ChatAICore.SetSleepForAPI(sleepForAPI)

#===============================================================================
#_judge = ConvoJudge(
#    model=config["support_model_version"],
#    temperature=config["support_model_temperature"]
#    )

# Callback to get the user info from the session
def local_get_user_info():
    return session['user_info']

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
def getLocMessages():
    # Create or get the session messages list
    return session.setdefault('loc_messages', [])

def appendLocMessage(message):
    getLocMessages().append(message)

def save_session():
    session.modified = True

#===============================================================================
logmsg("Creating storage...")
_storage = Storage(os.getenv("DO_STORAGE_CONTAINER"))

# Create the assistant
logmsg("Creating assistant...")
_assistant = ChatAICore.create_assistant(
                wrap=_oa_wrap,
                config=config,
                instructions=assistant_instructions,
                get_user_info=local_get_user_info)

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

    if not _storage.FileExists(file_path):
        logmsg(f"Downloading file {file_id} from source...")
        data = _oa_wrap.GetFileContent(file_id)
        data_io = BytesIO(data.read())
        logmsg(f"Uploading file {file_path} to storage...")
        _storage.UploadFile(data_io, file_path)

    logmsg(f"Getting file url for {file_id}, path: {file_path}")
    return _storage.GetFileURL(file_path)

#===============================================================================
def update_messages_history(wrap, thread_id, session, make_file_url):

    # See if we have an existing list in the session, if so, get the last message ID
    if not 'loc_messages' in session:
        session['loc_messages'] = []

    after = ''
    try:
        if len(session['loc_messages']) > 0:
            after = session['loc_messages'][-1]['src_id']
    except:
        logerr("Error getting last message ID")
        pass

    # Get all the messages from the thread
    history = wrap.ListAllThreadMessages(thread_id=thread_id, after=after)
    print(f"Found {len(history)} new messages in the thread history")

    # History in our format
    for (i, msg) in enumerate(history):
        # Append message to messages list
        logmsg(f"Message {i} ({msg.role}): {msg.content}")
        appendLocMessage(
            ChatAICore.MessageToLocMessage(
                wrap=wrap,
                message=msg,
                make_file_url=make_file_url))

#===============================================================================
@app.route('/')
def index():
    # Load or create the thread
    thread_id = createThread(force_new=False)

    #_judge.ClearMessages()

    print(f"Welcome to {config['app_title']}, v{config['app_version']}")
    print(f"Assistant: {config['assistant_name']}")

    update_messages_history(
        wrap=_oa_wrap,
        thread_id=thread_id,
        session=session,
        make_file_url=make_file_url)

    save_session() # For the local messages

    # Process the history messages
    print(f"Total history messages: {len(getLocMessages())}")

    return render_template(
                'chat.html',
                app_title=config["app_title"],
                assistant_name=config["assistant_name"],
                assistant_avatar=config["assistant_avatar"],
                app_version=config["app_version"])

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
@app.route('/get_history', methods=['GET'])
def get_history():
    return jsonify({'messages': getLocMessages()})

#===============================================================================
@app.route('/send_message', methods=['POST'])
@timing_decorator
def send_message():

    msg_text = request.json['message']

    thread_id = session['thread_id']

    new_replies = []
    def on_replies(replies: list):
        new_replies.extend(replies)
        for reply in replies:
            appendLocMessage(reply)
            #_judge.AddMessage(reply)
        save_session() # For the local messages

    # Send the user message and get the replies
    _, status_code = ChatAICore.SendUserMessage(
        wrap=_oa_wrap,
        msg_text=msg_text,
        assistant_id=_assistant.id,
        thread_id=thread_id,
        make_file_url=make_file_url,
        on_replies=on_replies)

    logmsg(f"Replies: {new_replies}")

    if len(new_replies) > 0:
        logmsg(f"Sending {len(new_replies)} replies")
        return jsonify({'replies': new_replies}), status_code
    else:
        logmsg("Sending no replies")
        return jsonify({'replies': []}), status_code

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
