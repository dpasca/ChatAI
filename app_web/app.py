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
from flask_cors import CORS
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
from Common.MsgThread import MsgThread

USER_BUCKET_PATH = "user_a_00001"
ENABLE_SLEEP_LOGGING = False

#===============================================================================
# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

#===============================================================================
config_file = os.environ.get("CONFIG_FILE", "config_mei.json")

# Load configuration from config.json
with open(config_file) as f:
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
    logmsg(f"Setting new user info: {new_info}")
    sess = get_or_create_app_session(session.sid)
    with sess.lock:
        sess.user_info = new_info

def sess_get_msg_thread(session_id=None):
    if session_id is None:
        session_id = session.sid
    sess = get_or_create_app_session(session_id)
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

def has_usable_msg_thread(session_id=None):
    if session_id is None:
        session_id = session.sid

    if session_id not in _app_sessions:
        return False

    mt = sess_get_msg_thread(session_id)
    return mt is not None

def local_get_user_info(arguments):
    if 'tools_user_data' not in arguments:
        return 'No user info available'
    return sess_get_user_info(arguments['tools_user_data'])

def local_get_main_MsgThread(arguments):
    if 'tools_user_data' not in arguments:
        logerr("No user data in arguments")
        return None
    return sess_get_msg_thread(session_id=arguments['tools_user_data'])

# Create the thread if it doesn't exist
def createThread(force_new=False) -> None:
    # Create or get the thread
    if ('thread_id' not in session) or force_new:
        mt = MsgThread.create_thread(_oa_wrap)
        sess_set_msg_thread(mt)
        logmsg("Creating new thread with ID " + mt.thread_id)
        # Save the thread ID to the session
        session['thread_id'] = mt.thread_id
        if 'msg_thread_data' in session:
            del session['msg_thread_data']
    else:
        mt = MsgThread.from_thread_id(_oa_wrap, session['thread_id'])
        sess_set_msg_thread(mt)
        logmsg("Retrieved existing thread with ID " + mt.thread_id)

    # Get our cached thread messages
    if 'msg_thread_data' in session:
        mt.deserialize_data(session['msg_thread_data'])

    new_n = mt.fetch_new_messages(make_file_url)
    print(f"Found {new_n} new messages in the thread history")
    save_session()

    # Create the sub-agents system for the message-thread
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
_storage = None
if os.getenv("DO_STORAGE_CONTAINER") is not None:
    logmsg("Creating storage...")
    _storage = Storage(
        bucket=os.getenv("DO_STORAGE_CONTAINER"),
        access_key=os.getenv("DO_SPACES_ACCESS_KEY"),
        secret_key=os.getenv("DO_SPACES_SECRET_KEY"),
        endpoint=os.getenv("DO_STORAGE_SERVER"))


# Create the assistant
logmsg("Creating assistant...")
_assistant = ChatAICore.create_assistant(
                wrap=_oa_wrap,
                config=config,
                instructions=assistant_instructions,
                get_main_MsgThread=local_get_main_MsgThread,
                get_user_info=local_get_user_info)

#===============================================================================
# Initialize Flask app
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("CHATAI_FLASK_SECRET_KEY")

    # Determine running environment
    is_production = os.getenv('FLASK_ENV') == 'production'

    # Read the CORS_ORIGINS environment variable
    cors_origins_env = os.getenv('CORS_ORIGINS', '*')

    # Check if CORS_ORIGINS is set to a wildcard or a list of domains
    if cors_origins_env == '*' and not is_production:
        # Allow all origins in non-production environments
        cors_origins = cors_origins_env
    else:
        # Split the CORS_ORIGINS variable into a list
        cors_origins = cors_origins_env.split(',')

    # Configure CORS with the parsed origins or wildcard
    CORS(app, origins=cors_origins, supports_credentials=True)

    # Configure session cookies for cross-origin compatibility
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'None' if is_production else 'Lax'

    # Server-side session configuration
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config.from_object(__name__)
    Session(app)

    return app

app = create_app()

#===============================================================================
@app.after_request
def after_request_func(response):
    if os.getenv('DISABLE_CORS') == '1':
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

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

@app.route('/reset_expired_chat', methods=['POST'])
def reset_expired_chat():
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

    if _storage is None:
        logerr(f"Storage not available for file {file_id} with path {file_path}")
        return file_path

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
                navbar_dev=config["navbar_dev"],
                navbar_dev_url=config["navbar_dev_url"],
                assistant_name=config["assistant_name"],
                assistant_avatar=config["assistant_avatar"],
                favicon_name=config["favicon_name"],
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
    # Send to index page if we don't have a working message thread
    if not has_usable_msg_thread():
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    return jsonify({'messages': sess_get_msg_thread().messages})

#===============================================================================
@app.route('/get_replies', methods=['GET'])
def get_replies():
    # Send to index page if we don't have a working message thread
    if not has_usable_msg_thread():
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    replies = sess_get_replies()
    send_replies = []
    with replies.lock:
        if not replies.is_active():
            #logmsg("No pending work")
            return jsonify({'replies': [], 'message': 'No pending work', 'final': True}), 200

        if replies.get_elapsed() > (60*5):
            #logmsg("Timeout waiting for replies")
            return jsonify({'replies': [], 'message': 'Timeout', 'final': True}), 200

        while not replies.empty():
            reply = replies.get()
            logmsg(f"Got reply: {reply}")
            if reply == 'END':
                # Request fact-checking if enabled
                if config['support_enable_factcheck']:
                    session['generate_fchecks'] = True
                logmsg(f"Reached end of replies")
                sess_set_replies(TaskQueue())
                return jsonify({'replies': send_replies, 'final': True}), 200
            elif reply == 'ERR_THREAD_EXPIRED':
                # Return an error for expired
                return jsonify({'replies': send_replies, 'final': True, 'error': reply}), 500
            else:
                sess_get_msg_thread().add_message(reply)
                send_replies.append(reply)

    #logmsg(f"Sending {len(send_replies)} replies")
    return jsonify({'replies': send_replies, 'final': False}), 200

#===============================================================================
@app.route('/get_addendums', methods=['GET'])
def get_addendums():
    # Send to index page if we don't have a working message thread
    if not has_usable_msg_thread():
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    # Do we have fact-checks to return
    if ('generate_fchecks' not in session) or not session['generate_fchecks']:
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    del session['generate_fchecks']

    # We get the fact checks directly in JSON format
    fc_str = sess_get_msg_thread().gen_fact_check(tools_user_data=session.sid)
    if fc_str is None:
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    logmsg(f"Got fact-checks: {fc_str}")

    try:
        fc = json.loads(fc_str)
    except ValueError as e:
        logerr(f"Error parsing fact-checks: {e}")
        return jsonify({'addendums': [], 'message': 'Error parsing fact-checks', 'final': True}), 200

    logmsg(f"FC JSON {fc}")

    return jsonify({'addendums': [fc], 'final': True}), 200

#===============================================================================
@app.route('/send_message', methods=['POST'])
@timing_decorator
def send_message():
    # Send to index page if we don't have a working message thread
    if not has_usable_msg_thread():
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

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

        if ret_val == ChatAICore.ERR_THREAD_EXPIRED:
            with replies.lock:
                replies.put('ERR_THREAD_EXPIRED')

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

    # Respond with a "processing" status and with the user message ID
    # We need the user message ID to match the addendums/fact-checks
    return jsonify({'status': 'processing',
                    'user_msg_id': user_msg['src_id']})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
