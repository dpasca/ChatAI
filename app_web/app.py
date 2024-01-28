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
import threading

# Update the path for the modules below
from Common.OpenAIWrapper import OpenAIWrapper
from Common.StorageCloud import StorageCloud as Storage
from Common.logger import *
from Common.OAIUtils import *
from Common import ChatAICore

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

# Create the thread manager
_msg_thread = None

#===============================================================================
def sleepForAPI():
    if ENABLE_LOGGING and ENABLE_SLEEP_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        line = inspect.currentframe().f_back.f_lineno
        print(f"[{caller}:{line}] sleeping...")
    time.sleep(0.5)

ChatAICore.SetSleepForAPI(sleepForAPI)

#===============================================================================
_user_info = dict()
_user_info_lock = threading.Lock()

# Callback to get the user info from the session
def local_get_user_info():
    # Return a copy of the user info
    with _user_info_lock:
        return _user_info.copy()

# Create the thread if it doesn't exist
def createThread(force_new=False) -> None:
    global _msg_thread

    # Create or get the thread
    if ('thread_id' not in session) or (session['thread_id'] is None) or force_new:
        _msg_thread = ChatAICore.MsgThread.create_thread(_oa_wrap)
        logmsg("Creating new thread with ID " + _msg_thread.thread_id)
        # Save the thread ID to the session
        session['thread_id'] = _msg_thread.thread_id
        if 'msg_thread_data' in session:
            del session['msg_thread_data']
    else:
        _msg_thread = ChatAICore.MsgThread.from_thread_id(_oa_wrap, session['thread_id'])
        logmsg("Retrieved existing thread with ID " + _msg_thread.thread_id)

    # Get our cached thread messages
    if 'msg_thread_data' in session:
        _msg_thread.deserialize_data(session['msg_thread_data'])

    new_n = _msg_thread.fetch_new_messages(make_file_url)
    print(f"Found {new_n} new messages in the thread history")
    save_session()

    # Optional: create the judge for the thread
    if config["support_enable_factcheck"]:
        _msg_thread.create_judge(
            model=config["support_model_version"],
            temperature=config["support_model_temperature"])

def save_session():
    session['msg_thread_data'] = _msg_thread.serialize_data()
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
    logmsg(f"User info: {user_info}")

    # ensure it has the required fields
    has_missing_fields = False
    if not 'timezone' in user_info:
        logerr("Missing timezone in user info")
        has_missing_fields = True
        user_info['timezone'] = 'UTC'

    if not 'user_agent' in user_info:
        logerr("Missing user_agent in user info")
        has_missing_fields = True
        user_info['user_agent'] = 'Unknown'

    with _user_info_lock:
        global _user_info # Declare to make writeable !
        _user_info = user_info

    return jsonify({'status': 'success'}) if not has_missing_fields else jsonify({'status': 'error'})

#===============================================================================
@app.route('/clear_chat', methods=['POST'])
def clear_chat():
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

#==================================================================
@app.route('/')
def index():
    # Load or create the thread
    createThread(force_new=False)

    print(f"Welcome to {config['app_title']}, v{config['app_version']}")
    print(f"Assistant: {config['assistant_name']}")

    # Process the history messages
    print(f"Total history messages: {len(_msg_thread.messages)}")

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
    return jsonify({'messages': _msg_thread.messages})

#===============================================================================
from collections import defaultdict
from queue import Queue
import time

_replies = defaultdict(lambda: {'queue': Queue(), 'start_time': {}})
_replies_lock = threading.Lock()

#===============================================================================
@app.route('/get_replies', methods=['GET'])
def get_replies():
    # NOTE: this is the thread ID, not the Python thread
    thread_id = session['thread_id']

    send_replies = []
    with _replies_lock:
        #logmsg(f"Checking replies for thread {thread_id}")
        if thread_id not in _replies:
            # No replies available yet
            print(f"No replies available for thread {thread_id}")
            return jsonify({'message': 'No pending work', 'final': True}), 200

        #logmsg(f"Found {_replies[thread_id]['queue'].qsize()} replies for thread {thread_id}")
        did_reach_end = False
        while not _replies[thread_id]['queue'].empty():
            reply = _replies[thread_id]['queue'].get()
            logmsg(f"Got reply: {reply}")
            if reply == 'END':
                logmsg(f"Reached end of replies for thread {thread_id}")
                del _replies[thread_id]  # Remove the thread entry
                did_reach_end = True
                break
            else:
                send_replies.append(reply)

        if not did_reach_end:
            # Check if we have been waiting for too long
            if (int(time.time()) - _replies[thread_id]['start_time']) > (60*2):
                logerr(f"Reached timeout for thread {thread_id}")
                del _replies[thread_id]
                # Force to say that we reached the end (a timout message would be nice)
                did_reach_end = True

    for reply in send_replies:
        _msg_thread.add_message(reply)

    #logmsg(f"Sending {len(send_replies)} replies for thread {thread_id}")
    return jsonify({'replies': send_replies, 'final': did_reach_end}), 200 

#===============================================================================
@app.route('/send_message', methods=['POST'])
@timing_decorator
def send_message():
    msg_text = request.json['message']
    thread_id = session['thread_id']

    # Create the user message
    user_msg = ChatAICore.create_user_message(_oa_wrap, thread_id, msg_text, make_file_url)
    # Add the message to the thread
    _msg_thread.add_message(user_msg)

    def send_message_task(thread_id, user_msg_id):
        def on_replies(replies: list):
            with _replies_lock:
                for reply in replies:
                    _replies[thread_id]['queue'].put(reply)

        # Send the user message and get the replies
        ret_val = ChatAICore.SendUserMessage(
            wrap=_oa_wrap,
            last_message_id=user_msg_id,
            assistant_id=_assistant.id,
            thread_id=thread_id,
            make_file_url=make_file_url,
            on_replies=on_replies)

        # Mark the completion of message processing
        with _replies_lock:
            _replies[thread_id]['queue'].put('END')

        if ret_val != ChatAICore.SUCCESS:
            logerr(f"Error sending user message: {ret_val}")

    # Create a new queue for this message thread
    with _replies_lock:
        _replies[thread_id]['start_time'] = int(time.time())
        _replies[thread_id]['queue'] = Queue()

    # NOTE: this `thread` is not the same as `thread_id` above,
    #  it's a Python thread, while `thread_id` is the OpenAI thread ID
    thread = threading.Thread(target=send_message_task, args=(thread_id, user_msg['src_id']))
    thread.start()

    return jsonify({'status': 'processing'}), 202

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
