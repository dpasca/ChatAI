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
AssistTools.set_super_get_main_MsgThread(local_get_main_MsgThread)
AssistTools.set_super_get_user_info(local_get_user_info)

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
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

#===============================================================================
@app.route('/api/user_info', methods=['POST'])
def user_info():
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
    # Force-create a new thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    create_msg_thread(client_id, force_new=True)

    return redirect(url_for('index'))

@app.route('/reset_expired_chat', methods=['POST'])
def reset_expired_chat():
    # Force-create a new thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    create_msg_thread(client_id, force_new=True)

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
    print(f"Welcome to {config['app_title']}, v{config['app_version']}")
    print(f"Assistant: {config['assistant_name']}")

    def do_render():
        # Render the chat page
        return render_template(
            'chat.html',
            app_title=config["app_title"],
            navbar_dev=config["navbar_dev"],
            navbar_dev_url=config["navbar_dev_url"],
            assistant_name=config["assistant_name"],
            assistant_avatar=config["assistant_avatar"],
            favicon_name=config["favicon_name"],
            app_version=config["app_version"])

    # Check if we have a custom client ID
    if 'CustomClientId' not in request.cookies:
        # Generate a new custom client ID
        client_id = str(uuid.uuid4())
        logmsg(f"Generated new client ID: {client_id}")
        response = make_response(do_render())
        response.set_cookie('CustomClientId', client_id)
        # Load or create the thread
        create_msg_thread(client_id, force_new=False)
        return response
    else:
        # Load or create the thread
        client_id = request.cookies.get('CustomClientId')
        logmsg(f"Using existing client ID: {client_id}")
        create_msg_thread(client_id, force_new=False)
        return do_render()


#===============================================================================
@app.route('/get_history', methods=['GET'])
def get_history():
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    # Send to index page if we don't have a working message thread
    if not client_has_msg_thread(client_id=client_id):
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    return jsonify({'messages': client_get_msg_thread(client_id).make_messages_for_display()}), 200

#===============================================================================
@socketio.on('connect')
def handle_connect():
    ws_session_id = request.sid  # request.sid for WebSocket session management
    client_id = request.args.get('customClientId')  # Retrieved from the connection query
    join_room(ws_session_id)
    emit('connected', {'ws_session_id': ws_session_id, 'custom_client_id': client_id})
    logmsg(f"Client connected. WebSocket Session ID: {ws_session_id}, Custom Client ID: {client_id}")

@socketio.on('disconnect')
def handle_disconnect():
    # Handle client disconnecting, if necessary
    logmsg(f"Client disconnected. Session ID: {request.sid}")

#===============================================================================
@app.route('/get_addendums', methods=['GET'])
def get_addendums():
    # Send to index page if we don't have a working message thread
    if (client_id := request.cookies.get('CustomClientId')) is None:
        return jsonify({'error': 'No client ID found'}), 400

    if not client_has_msg_thread(client_id):
        return jsonify({'error': 'No message thread loaded, please reload the page.'}), 400

    # Do we have fact-checks to return
    do_gen_fc = client_consume_key(client_id, 'generate_fchecks')
    if do_gen_fc is None or not do_gen_fc:
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    # We get the fact checks directly in JSON format
    fc_str = client_get_msg_thread(client_id).gen_fact_check(tools_user_data=client_id)
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
@socketio.on('send_message')
def handle_send_message(json, methods=['GET', 'POST']):

    ws_session_id = request.sid  # Get the session ID from the WebSocket connection

    client_id = request.args.get('customClientId')

    msg_text = json['message']

    # Ensure there's an active message thread
    if not client_has_msg_thread(client_id):
        emit('stream', {'text': 'No message thread loaded, please reload the page.', 'isError': True}, room=ws_session_id)
        return  # Exit if there's no usable message thread

    # Create the user message (will be used as context for the completion)
    user_msg = client_get_msg_thread(client_id).create_user_message(msg_text)

    def stream_openai_response(client_id, ws_session_id):

        mt = client_get_msg_thread(client_id)

        response = OAIUtils.completion_with_tools(
            wrap=_oa_wrap,
            model=config["model_version"],
            temperature=config["model_temperature"],
            instructions=ChatAICore.instrument_instructions(assistant_instructions),
            role_and_content_msgs=mt.make_messages_for_completion(20),
            tools_user_data=client_id,
            stream=True  # Enable streaming
        )

        # Create the assistant message, which will be added to the message thread
        assist_msg = mt.create_assistant_message("")
        src_id = assist_msg['src_id']

        # Send the response in parts and collect the full text
        reply_text = ""
        for part in response:
            if part is None:
                #print("<END>")
                continue
            reply_text += part
            #print(part, end="")
            socketio.emit('stream', {'src_id': src_id, 'text': part}, room=ws_session_id)
        #print("")

        # End the stream with a special signal, e.g., 'END'
        socketio.emit('stream', {'src_id': src_id, 'text': 'END'}, room=ws_session_id)

        mt.update_message(src_id, reply_text)

        if config['support_enable_factcheck']:
            client_set_key(client_id, 'generate_fchecks', True)

    # Call this new streaming function instead of appending replies directly
    threading.Thread(
        target=stream_openai_response,
        args=(client_id, ws_session_id)
        ).start()

    # Respond with a "processing" status and with the user message ID
    # We need the user message ID to match the addendums/fact-checks
    return jsonify({'status': 'processing',
                    'user_msg_id': user_msg['src_id']})

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=8080, debug=True)
    socketio.run(app, host='0.0.0.0', port=8080, debug=True, allow_unsafe_werkzeug=True)
