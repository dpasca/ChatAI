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
from flask_session import Session
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

#===============================================================================
def sleepForAPI():
    if ENABLE_LOGGING and ENABLE_SLEEP_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        line = inspect.currentframe().f_back.f_lineno
        print(f"[{caller}:{line}] sleeping...")
    time.sleep(0.5)

ChatAICore.SetSleepForAPI(sleepForAPI)

#===============================================================================
from queue import Queue
import time

class TaskQueue:
    def __init__(self, start_time=0):
        self.start_time = start_time
        self.queue = Queue()
        self.lock = threading.Lock()

    def is_active(self):
        return self.start_time != 0

    def get_elapsed(self):
        return int(time.time()) - self.start_time

    def put(self, item):
        self.queue.put(item)

    def get(self):
        return self.queue.get()

    def empty(self):
        return self.queue.empty()

#===============================================================================
from threading import Lock

class AppSession:
    def __init__(self):
        self.lock = Lock()
        self.user_info = dict()
        self.msg_thread = None
        self.replies = TaskQueue()

_app_sessions = {}

def get_or_create_app_session(sid):
    global _app_sessions
    if sid not in _app_sessions:
        _app_sessions[sid] = AppSession()
    return _app_sessions[sid]

def sess_get_lock():
    sess = get_or_create_app_session(session.sid)
    return sess.lock

def sess_get_user_info(session_id=None):
    if session_id is None:
        session_id = session.sid
    sess = get_or_create_app_session(session_id)
    with sess.lock:
        return sess.user_info

def sess_set_user_info(new_info):
    sess = get_or_create_app_session(session.sid)
    with sess.lock:
        sess.user_info = new_info

def sess_get_msg_thread():
    logmsg(f"Getting thread")
    sess = get_or_create_app_session(session.sid)
    with sess.lock:
        return sess.msg_thread

def sess_set_msg_thread(new_thread):
    logmsg(f"Setting new thread: {new_thread}")
    sess = get_or_create_app_session(session.sid)
    with sess.lock:
        sess.msg_thread = new_thread

def sess_get_replies(session_id=None):
    if session_id is None:
        session_id = session.sid
    sess = get_or_create_app_session(session_id)
    with sess.lock:
        return sess.replies

def sess_set_replies(new_replies):
    sess = get_or_create_app_session(session.sid)
    with sess.lock:
        sess.replies = new_replies

def sess_extend_replies(new_list, session_id):
    sess = get_or_create_app_session(session_id)
    with sess.lock:
        with sess.replies.lock:
            for item in new_list:
                sess.replies.put(item)

def local_get_user_info(arguments):
    return sess_get_user_info(arguments['tools_user_data'])

# Create the thread if it doesn't exist
def createThread(force_new=False) -> None:
    # Create or get the thread
    if ('thread_id' not in session) or force_new:
        mt = ChatAICore.MsgThread.create_thread(_oa_wrap)
        sess_set_msg_thread(mt)
        logmsg("Creating new thread with ID " + mt.thread_id)
        # Save the thread ID to the session
        session['thread_id'] = mt.thread_id
        if 'msg_thread_data' in session:
            del session['msg_thread_data']
    else:
        mt = ChatAICore.MsgThread.from_thread_id(_oa_wrap, session['thread_id'])
        sess_set_msg_thread(mt)
        logmsg("Retrieved existing thread with ID " + mt.thread_id)

    # Get our cached thread messages
    if 'msg_thread_data' in session:
        mt.deserialize_data(session['msg_thread_data'])

    new_n = mt.fetch_new_messages(make_file_url)
    print(f"Found {new_n} new messages in the thread history")
    save_session()

    # Optional: create the judge for the thread
    if config["support_enable_factcheck"]:
        mt.create_judge(
            model=config["support_model_version"],
            temperature=config["support_model_temperature"])

def save_session():
    # When saving the session, we serialize our local thread data to the session obj
    if (mt := sess_get_msg_thread()) is not None:
        session['msg_thread_data'] = mt.serialize_data()
    # Save the session (?)
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

    # Serve-side session
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config.from_object(__name__)
    Session(app)

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

    sess_set_user_info(user_info)

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
    print(f"Total history messages: {len(sess_get_msg_thread().messages)}")

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
    return jsonify({'messages': sess_get_msg_thread().messages})

#===============================================================================
@app.route('/get_replies', methods=['GET'])
def get_replies():

    replies = sess_get_replies()
    send_replies = []
    with replies.lock:
        if not replies.is_active():
            #logmsg("No pending work")
            return jsonify({'message': 'No pending work', 'final': True}), 200

        if replies.get_elapsed() > (60*2):
            #logmsg("Timeout waiting for replies")
            return jsonify({'message': 'Timeout', 'final': True}), 200 

        while not replies.empty():
            reply = replies.get()
            logmsg(f"Got reply: {reply}")
            if reply == 'END':
                logmsg(f"Reached end of replies")
                sess_set_replies(TaskQueue())
                return jsonify({'replies': send_replies, 'final': True}), 200 
            else:
                sess_get_msg_thread().add_message(reply)
                send_replies.append(reply)

    #logmsg(f"Sending {len(send_replies)} replies")
    return jsonify({'replies': send_replies, 'final': False}), 200 

#===============================================================================
@app.route('/send_message', methods=['POST'])
@timing_decorator
def send_message():
    msg_text = request.json['message']
    thread_id = session['thread_id']

    # Create the user message
    user_msg = ChatAICore.create_user_message(_oa_wrap, thread_id, msg_text, make_file_url)
    # Add the message to the thread
    sess_get_msg_thread().add_message(user_msg)

    def send_message_task(thread_id, user_msg_id, session_id):
        def on_replies(src_replies: list):
            sess_extend_replies(src_replies, session_id)

        # Send the user message and get the replies
        ret_val = ChatAICore.SendUserMessage(
            wrap=_oa_wrap,
            last_message_id=user_msg_id,
            assistant_id=_assistant.id,
            thread_id=thread_id,
            make_file_url=make_file_url,
            on_replies=on_replies,
            tools_user_data=session_id)

        # Mark the completion of message processing
        replies = sess_get_replies(session_id)
        with replies.lock:
            replies.put('END')

        if ret_val != ChatAICore.SUCCESS:
            logerr(f"Error sending user message: {ret_val}")

    # Create a new queue for this message thread
    sess_set_replies(TaskQueue(start_time=int(time.time())))

    # NOTE: this `thread` is not the same as `thread_id` above,
    #  it's a Python thread, while `thread_id` is the OpenAI thread ID
    thread = threading.Thread(
                target=send_message_task,
                args=(thread_id, user_msg['src_id'], session.sid))
    thread.start()

    return jsonify({'status': 'processing'}), 202

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
