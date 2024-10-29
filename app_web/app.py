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
import uuid
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask import make_response
from flask_session import Session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from io import BytesIO
import threading

# Update the path for the modules below
from Common.OpenAIWrapper import OpenAIWrapper
from Common.StorageCloud import StorageCloud as Storage
from Common.logger import *
from Common import OAIUtils
from Common import ChatAICore
from Common.MsgThread import MsgThread
from Common import AssistTools

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
from threading import Lock

class AppClient:
    def __init__(self):
        self.lock = Lock()
        self._user_info = dict()
        self._msg_thread = None
        self._misc_dict = dict()
        self._connected = False

    @property
    def user_info(self):
        with self.lock:
            return self._user_info
    @user_info.setter
    def user_info(self, new_info):
        with self.lock:
            self._user_info = new_info

    @property
    def msg_thread(self):
        with self.lock:
            return self._msg_thread
    @msg_thread.setter
    def msg_thread(self, new_thread):
        with self.lock:
            self._msg_thread = new_thread

    @property
    def connected(self):
        with self.lock:
            return self._connected
    @connected.setter
    def connected(self, new_value):
        with self.lock:
            self._connected = new_value

    def consume_key(self, key):
        with self.lock:
            if key in self._misc_dict:
                value = self._misc_dict[key]
                del self._misc_dict[key]
                return value
            return None

    def set_key(self, key, value):
        with self.lock:
            self._misc_dict[key] = value

# TODO: store this in a database
_app_clients = {}

def get_app_client(client_id):
    global _app_clients
    if client_id not in _app_clients:
        _app_clients[client_id] = AppClient()
    return _app_clients[client_id]

def client_get_user_info(client_id):
    return get_app_client(client_id).user_info

def client_set_user_info(client_id, new_info):
    logmsg(f"Setting new user info: {new_info}")
    get_app_client(client_id).user_info = new_info

def client_get_msg_thread(client_id):
    return get_app_client(client_id).msg_thread

def client_set_msg_thread(client_id, new_thread):
    logmsg(f"Setting new thread: {new_thread.thread_id}")
    get_app_client(client_id).msg_thread = new_thread

def client_has_msg_thread(client_id):
    return client_get_msg_thread(client_id) is not None

def client_consume_key(client_id, key):
    return get_app_client(client_id).consume_key(key)

def client_set_key(client_id, key, value):
    get_app_client(client_id).set_key(key, value)


def local_get_user_info(arguments):
    # NOTE: This function is called by AssistTools and
    # 'tools_user_data' is the Client ID
    if 'tools_user_data' not in arguments:
        return 'No user info available'
    return client_get_user_info(client_id=arguments['tools_user_data'])

def local_get_main_MsgThread(arguments):
    # NOTE: This function is called by AssistTools and
    # 'tools_user_data' is the Client ID
    if 'tools_user_data' not in arguments:
        logerr("No user data in arguments")
        return None
    return client_get_msg_thread(client_id=arguments['tools_user_data'])

# Create the thread if it doesn't exist
def create_msg_thread(client_id, force_new) -> None:
    mt = None if force_new else client_get_msg_thread(client_id)
    if mt is None:
        mt = MsgThread.create_thread(_oa_wrap)
        if greeting := config.get("assistant_greeting"):
            mt.create_assistant_message(greeting)
        client_set_msg_thread(client_id, mt)
        logmsg("Created new thread with ID " + mt.thread_id)

    # Create the sub-agents system for the message-thread
    mt.create_judge(
        model=config["support_model_version"],
        temperature=config["support_model_temperature"])

#===============================================================================
_storage = None
if os.getenv("DO_STORAGE_CONTAINER") is not None:
    logmsg("Creating storage...")
    _storage = Storage(
        bucket=os.getenv("DO_STORAGE_CONTAINER"),
        access_key=os.getenv("DO_SPACES_ACCESS_KEY"),
        secret_key=os.getenv("DO_SPACES_SECRET_KEY"),
        endpoint=os.getenv("DO_STORAGE_SERVER"))

#===============================================================================
# Initialize the tools
AssistTools.initialize_tools(
    enable_rag=config.get('enable_rag', False),
    rag_query_instructions=config.get('rag_query_instructions'),
    enable_web_search=config.get('enable_web_search', False),
    support_enable_research_assistant=config.get('support_enable_research_assistant', True),
    storage=_storage,
    super_get_user_info_=local_get_user_info,
    super_get_main_MsgThread_=local_get_main_MsgThread,
    )

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

async_mode = None  # or 'eventlet' or 'gevent', depending on your async mode preference
app = create_app()
socketio = SocketIO(app, async_mode=async_mode, cors_allowed_origins="*")

#===============================================================================
@app.after_request
def after_request_func(response):
    if os.getenv('DISABLE_CORS') == '1':
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

#===============================================================================
@app.route('/api/user_info', methods=['POST'])
def user_info():
    logmsg("In route /api/user_info")
    # Store the user info in the app client object
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

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

    client_set_user_info(client_id, user_info)

    return jsonify({'status': 'success'}) if not has_missing_fields else jsonify({'status': 'error'})

#===============================================================================
@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    logmsg("In route /clear_chat")
    # Force-create a new thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    create_msg_thread(client_id, force_new=True)

    return redirect(url_for('index'))

@app.route('/reset_expired_chat', methods=['POST'])
def reset_expired_chat():
    logmsg("In route /reset_expired_chat")
    # Force-create a new thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    create_msg_thread(client_id, force_new=True)

    return redirect(url_for('index'))

#===============================================================================
def make_client_room(client_id):
    return f'client_{client_id}'

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
        _storage.upload_file(data_io, file_path)

    logmsg(f"Getting file url for {file_id}, path: {file_path}")
    return _storage.GetFileURL(file_path)

#==================================================================
def disable_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

#==================================================================
@app.route('/')
def index():
    logmsg("In route /")

    def do_render():
        # Render the chat page
        return render_template(
            config.get("chat_template", "chat.html"),
            app_title=config["app_title"],
            navbar_dev=config["navbar_dev"],
            navbar_dev_url=config["navbar_dev_url"],
            server_url=config.get("server_url", ""),
            assistant_name=config["assistant_name"],
            assistant_avatar=config["assistant_avatar"],
            favicon_name=config["favicon_name"],
            app_version=config["app_version"],
            open_links_in_new_tab=config.get("open_links_in_new_tab", False),
            )

    # Check if we have a custom client ID
    if 'CustomClientId' not in request.cookies:
        # Generate a new custom client ID
        client_id = str(uuid.uuid4())
        logmsg(f"Generated new client ID: {client_id}")
        response = make_response(do_render())
        response.set_cookie('CustomClientId', client_id)
        # Load or create the thread
        create_msg_thread(client_id, force_new=False)
        return disable_cache(response)
    else:
        # Load or create the thread
        client_id = request.cookies.get('CustomClientId')
        logmsg(f"Using existing client ID: {client_id}")
        create_msg_thread(client_id, force_new=False)
        return disable_cache(make_response(do_render()))


#===============================================================================
@app.route('/get_history', methods=['GET'])
def get_history():
    logmsg("In route /get_history")
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return disable_cache(jsonify({'error': 'No client ID found'})), 400

    # Send to index page if we don't have a working message thread
    if not client_has_msg_thread(client_id=client_id):
        return disable_cache(jsonify({'error': 'No message thread loaded, please reload the page.'})), 400

    return disable_cache(jsonify({'messages': client_get_msg_thread(client_id).make_messages_for_display()})), 200

#===============================================================================
@socketio.on('connect')
def handle_connect():
    client_id = request.args.get('CustomClientId')
    get_app_client(client_id).connected = True
    client_room = make_client_room(client_id)
    join_room(client_room)
    logmsg(f"Client connected. Req.Session ID: {request.sid}, Custom Client ID: {client_id}, joined room: {client_room}")

@socketio.on('connect_ack')
def handle_connect_ack():
    client_id = request.args.get('CustomClientId')  # Retrieved from the connection query
    get_app_client(client_id).connected = True
    logmsg(f"Responding to connect_ack. Req.Session ID: {request.sid}, Custom Client ID: {client_id}")
    emit('connected', {'custom_client_id': client_id})

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.args.get('CustomClientId')
    get_app_client(client_id).connected = False
    logmsg(f"Client disconnected. Session ID: {request.sid}")

@socketio.on('reconnect')
def handle_reconnect():
    client_id = request.args.get('CustomClientId')
    get_app_client(client_id).connected = True
    logmsg(f"Client reconnected. Session ID: {request.sid}")

#===============================================================================
@app.route('/get_addendums', methods=['GET'])
def get_addendums():
    logmsg("In route /get_addendums")
    # Send to index page if we don't have a working message thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        logerr("No client ID found")
        return jsonify({'error': 'No client ID found'}), 400

    if not client_has_msg_thread(client_id):
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    # Do we have fact-checks to return
    do_gen_fc = client_consume_key(client_id, 'generate_fchecks')
    logmsg(f"generate_fchecks flag for client {client_id}: {do_gen_fc}")
    if do_gen_fc is None or not do_gen_fc:
        logmsg(f"No pending fact-checks for client {client_id}")
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    # We get the fact checks directly in JSON format
    fc_str = client_get_msg_thread(client_id).gen_fact_check(tools_user_data=client_id)
    if fc_str is None:
        logmsg(f"No fact-checks generated for client {client_id}")
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    logmsg(f"Got fact-checks for client {client_id}: {fc_str}")

    try:
        fc = json.loads(fc_str)
    except ValueError as e:
        logerr(f"Error parsing fact-checks for client {client_id}: {e}")
        return jsonify({'addendums': [], 'message': 'Error parsing fact-checks', 'final': True}), 200

    #logmsg(f"FC JSON {fc}")

    return jsonify({'addendums': [fc], 'final': True}), 200

#===============================================================================
def stream_openai_response(client_id):

    mt = client_get_msg_thread(client_id)

    response = OAIUtils.completion_with_tools(
        wrap=_oa_wrap,
        model=config["model_version"],
        temperature=config["model_temperature"],
        instructions=ChatAICore.instrument_instructions(assistant_instructions),
        role_and_content_msgs=mt.make_messages_for_completion(20),
        exclude_tools=None, # At top level we don't exclude any tools
        tools_user_data=client_id,
        stream=True  # Enable streaming
    )

    # Create the assistant message, which will be added to the message thread
    assist_msg = mt.create_assistant_message("")
    src_id = assist_msg['src_id']

    client_room = make_client_room(client_id)
    logmsg(f"Streaming to room {client_room}")

    socketio.emit('stream', {'src_id': src_id, 'text': '$DUMMY_TOKEN$'}, room=client_room)

    # Send the response in parts and collect the full text
    reply_text = ""
    def send_full_reply():
        socketio.emit('stream', {'src_id': src_id, 'text': reply_text, 'is_full_msg': True}, room=client_room)

    part_cnt = 0
    for part in response:
        if part is None:
            #print("$END_TOKEN$")
            continue
        reply_text += part
        #print(part, end="")
        
        # Resend the full text for the first few parts
        # This is a HACK for the issue of the first part getting an error
        part_cnt += 1
        if part_cnt <= 10:
            send_full_reply()
            continue

        try:
            socketio.emit('stream', {'src_id': src_id, 'text': part}, room=client_room)
        except Exception as e:
            logerr(f"Error sending message to session {client_room}: {e}")
            break

    mt.update_message(src_id, reply_text)

    # HACK: Set the full reply at the end once again
    send_full_reply()

    # End the stream with a special signal, e.g., '$END_TOKEN$'
    try:
        socketio.emit('stream', {'src_id': src_id, 'text': '$END_TOKEN$'}, room=client_room)
    except Exception as e:
        logerr(f"Error sending $END_TOKEN$ message to session {client_room}: {e}")

    if config['support_enable_factcheck']:
        client_set_key(client_id, 'generate_fchecks', True)
        logmsg(f"Set generate_fchecks to True for client {client_id}")

#==================================================================
import pytz
from datetime import datetime

def make_user_metadata_dict(client_id):
    # Create a dictionary with the current Unix timestamp
    msg_metadata = {'unix_time': int(time.time())}

    if uinfo := client_get_user_info(client_id):
        logmsg(f"User info: {uinfo}")
        # Add the existing user info as-is
        msg_metadata.update(uinfo)
        # Add the local time as a string like 2024-10-17T16:27:28.924857+09:00
        tz_timezone = pytz.timezone(uinfo['timezone'])
        loc_time = datetime.now(tz_timezone)
        msg_metadata['user_local_time'] = loc_time.isoformat()

    return msg_metadata

#==================================================================
@socketio.on('send_message')
def handle_send_message(json, methods=['GET', 'POST']):

    client_id = request.args.get('CustomClientId')

    client_room = make_client_room(client_id)

    if not get_app_client(client_id).connected:
        logerr(f"Client {client_id} is not connected.")
        #socketio.emit('reconnect_request', room=client_room)

    # Text of the message from the client
    msg_text = json['message']
    # Unique ID for the message, provided by the client itself
    # NOTE: This should not conflict with unique IDs generated by MsgThread
    client_src_id = json['src_id']

    try:
        # Ensure there's an active message thread
        if not client_has_msg_thread(client_id):
            emit('stream', {'text': 'No message thread loaded, please reload the page.', 'isError': True}, room=client_room)
            return  # Exit if there's no usable message thread

        # Create a dictionary with the user metadata
        msg_metadata = make_user_metadata_dict(client_id)
        logmsg(f"Message metadata: {msg_metadata}")

        # Create the user message (will be used as context for the completion)
        user_msg = client_get_msg_thread(client_id).create_user_message(
            content=msg_text,
            src_id=client_src_id,
            msg_metadata=msg_metadata)

        logmsg(f"User message: {user_msg}")

        # Call this new streaming function instead of appending replies directly
        threading.Thread(
            target=stream_openai_response,
            args=(client_id,) # NOTE: needs the comma to make it a tuple
            ).start()

        # Respond with a "processing" status and with the user message ID
        # We need the user message ID to match the addendums/fact-checks
        return jsonify({'status': 'processing',
                        'user_msg_id': user_msg['src_id']})
    except Exception as e:
        logerr(f"KeyError: {str(e)}")
        emit('stream', {'text': 'The session has been disconnected. Please reload the page.', 'isError': True}, room=client_room)
        return jsonify({'status': 'error', 'message': 'Session disconnected'})

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=8080, debug=True)
    socketio.run(app, host='0.0.0.0', port=8080, debug=True, allow_unsafe_werkzeug=True)
