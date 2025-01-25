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
import pickle
import shutil
from datetime import datetime, timedelta
import atexit
import asyncio
from typing import Any, Dict, Optional, Callable, Union, List
import pytz

# Update the path for the modules below
from Common.OpenAIWrapper import OpenAIWrapper
from Common.StorageCloud import StorageCloud as Storage
from Common.logger import *
from Common import OAIUtils
from Common import ChatAICore
from Common.MsgThread import MsgThread
from Common import AssistTools

USER_BUCKET_PATH = "user_a_00001"
DO_REMOVE_USER_AGENT_FROM_META = True
DO_PRINT_MEMORY_USAGE = False

CLIENT_STORAGE_PATH = "_client_storage"
CLIENT_EXPIRY_DAYS = 2

#===============================================================================
# Load the environment variables, override the existing ones
from dotenv import load_dotenv
load_dotenv(override=True)

#===============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

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
# App client object
#===============================================================================
from threading import Lock

class AppClient:
    def __init__(self):
        # Lock to protect the object since assistant replies are async (see stream_openai_response)
        self.lock = Lock()
        # User info (timezone, user_agent, etc.)
        self._user_info = dict()
        # The message thread for this client
        self._msg_thread = None
        # Miscellaneous data / state storage
        self._misc_dict = dict()
        # True if the client is connected via websocket
        self._connected = False
        self._last_access = datetime.now()

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

    def touch(self):
        """Update last access time"""
        with self.lock:
            self._last_access = datetime.now()

    def is_expired(self):
        """Check if client has expired"""
        with self.lock:
            expiry_date = datetime.now() - timedelta(days=CLIENT_EXPIRY_DAYS)
            return self._last_access < expiry_date

    def to_dict(self):
        """Convert to serializable dictionary"""
        with self.lock:
            return {
                'user_info': self._user_info,
                'msg_thread': self._msg_thread.to_dict() if self._msg_thread else None,
                'misc_dict': self._misc_dict,
                'connected': self._connected,
                'last_access': self._last_access
            }

    @classmethod
    def from_dict(cls, data):
        """Create instance from dictionary"""
        instance = cls()
        with instance.lock:
            instance._user_info = data['user_info']
            instance._misc_dict = data['misc_dict']
            instance._connected = data['connected']
            instance._last_access = data['last_access']
            # Reconstruct MsgThread if it exists
            if data['msg_thread']:
                instance._msg_thread = MsgThread.from_dict(data['msg_thread'], wrap=_oa_wrap)
        return instance

# TODO: store this in a database
_app_clients = {}

def get_app_client(client_id):
    global _app_clients
    if client_id not in _app_clients:
        _app_clients[client_id] = AppClient()
    _app_clients[client_id].touch()
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
def dump_memory_usage(msg : str):
    if not DO_PRINT_MEMORY_USAGE:
        return
    import psutil
    process = psutil.Process(os.getpid())
    logmsg(f"Memory usage ({msg}): {process.memory_info().rss / 1024 / 1024:.2f} MB")


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
def local_get_user_info_wrapper(args):
    """Wrapper to match the expected function signature"""
    logmsg(f"[local_get_user_info_wrapper] Called with args: {args}")
    if 'tools_user_data' not in args:
        logwarn("[local_get_user_info_wrapper] No tools_user_data in args")
        return {}
    result = client_get_user_info(client_id=args['tools_user_data'])
    logmsg(f"[local_get_user_info_wrapper] Returning: {result}")
    return result

def local_get_msg_thread_wrapper(args):
    """Wrapper to match the expected function signature"""
    logmsg(f"[local_get_msg_thread_wrapper] Called with args: {args}")
    if 'tools_user_data' not in args:
        logwarn("[local_get_msg_thread_wrapper] No tools_user_data in args")
        return None
    result = client_get_msg_thread(client_id=args['tools_user_data'])
    logmsg(f"[local_get_msg_thread_wrapper] Returning: {result}")
    return result

# Create closure wrappers that match the expected signatures
def create_user_info_wrapper() -> Callable[[Optional[dict]], dict]:
    def wrapper(arguments: Optional[dict] = None) -> dict:
        logmsg(f"[create_user_info_wrapper] Called with args: {arguments}")
        # Get client ID from the arguments
        client_id = None
        if arguments and 'tools_user_data' in arguments:
            client_id = arguments['tools_user_data']

        if not client_id:
            logwarn("[create_user_info_wrapper] No client ID found in arguments")
            return {}
        result = client_get_user_info(client_id=client_id)
        logmsg(f"[create_user_info_wrapper] Returning: {result}")
        return result
    return wrapper

def create_msg_thread_wrapper() -> Callable[[Optional[dict]], MsgThread]:
    thread_local = threading.local()

    def set_client_id(client_id: str) -> None:
        thread_local.client_id = client_id

    def wrapper(arguments: Optional[dict] = None) -> MsgThread:
        logmsg(f"[create_msg_thread_wrapper] Called with args: {arguments}")
        try:
            # First try to get client ID from thread local
            client_id = thread_local.client_id
        except AttributeError:
            # If not in thread local, try to get from arguments
            if arguments and 'tools_user_data' in arguments:
                client_id = arguments['tools_user_data']
                thread_local.client_id = client_id  # Store for future use
            else:
                logwarn("[create_msg_thread_wrapper] No client ID found in arguments or thread local")
                raise ValueError("No client ID set")

        result = client_get_msg_thread(client_id=client_id)
        if not result:
            logwarn("[create_msg_thread_wrapper] No message thread found")
            raise ValueError("No message thread found")
        logmsg(f"[create_msg_thread_wrapper] Returning: {result}")
        return result

    wrapper.set_client_id = set_client_id  # Attach the setter to the wrapper
    return wrapper

# Create the wrappers once at module level
user_info_wrapper = create_user_info_wrapper()
msg_thread_wrapper = create_msg_thread_wrapper()

# Log the available tools before initialization
logmsg("Available tools before initialization:")
for tool in AssistTools.tool_items:
    logmsg(f"  - {tool.name}: {tool.definition}")

# Initialize the tools with proper function signatures
AssistTools.initialize_tools(
    enable_rag=config.get('enable_rag', False),
    rag_query_instructions=config.get('rag_query_instructions'),
    enable_web_search=config.get('enable_web_search', False),
    support_enable_research_assistant=config.get('support_enable_research_assistant', True),
    storage=_storage,
    super_get_user_info_=user_info_wrapper,
    super_get_main_MsgThread_=msg_thread_wrapper,
    )

# Log the available tools after initialization
logmsg("Available tools after initialization:")
for tool in AssistTools.tool_items:
    logmsg(f"  - {tool.name}: {tool.definition}")
logmsg("Tool items dict contents:")
for name, tool in AssistTools.tool_items_dict.items():
    logmsg(f"  - {name}: {tool.function}")

# Log the tools that will be available to the assistant
tools = OAIUtils.get_tools()
logmsg("Tools available to assistant:")
for tool in tools:
    logmsg(f"  - {tool['function']['name']}: {tool['function']['description']}")

#===============================================================================
# Add these functions to handle storage
def save_client(client_id):
    if not os.path.exists(CLIENT_STORAGE_PATH):
        os.makedirs(CLIENT_STORAGE_PATH)

    logmsg(f"Saving client {client_id}")
    file_path = os.path.join(CLIENT_STORAGE_PATH, f"{client_id}.pkl")
    with open(file_path, 'wb') as f:
        client = get_app_client(client_id)
        pickle.dump(client.to_dict(), f)

# Purge expired client files from disk
# NOTE: This only touches files from disk, so should be thread-safe
def purge_expired_client_files():
    if not os.path.exists(CLIENT_STORAGE_PATH):
        return

    expired = [cid for cid, client in _app_clients.items() if client.is_expired()]
    for cid in expired:
        os.remove(os.path.join(CLIENT_STORAGE_PATH, f"{cid}.pkl"))

# Load clients from disk (meant to be called at startup)
def load_clients():
    global _app_clients
    _app_clients = {}

    if not os.path.exists(CLIENT_STORAGE_PATH):
        return

    for filename in os.listdir(CLIENT_STORAGE_PATH):
        if filename.endswith('.pkl'):
            client_id = filename[:-4]  # Remove .pkl
            file_path = os.path.join(CLIENT_STORAGE_PATH, filename)
            try:
                with open(file_path, 'rb') as f:
                    data = pickle.load(f)
                    client = AppClient.from_dict(data)
                    if not client.is_expired():
                        _app_clients[client_id] = client
                    else:
                        os.remove(file_path)
            except (EOFError, pickle.UnpicklingError):
                # Remove corrupted files
                os.remove(file_path)

#===============================================================================
# Add periodic save functionality
_last_periodic_check = datetime.now()
def periodic_check():
    global _last_periodic_check
    now = datetime.now()
    if now - _last_periodic_check > timedelta(minutes=5):
        _last_periodic_check = now
        purge_expired_client_files()

#===============================================================================
# Initialize Flask app
def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(script_dir, 'templates'),
        static_folder=os.path.join(script_dir, 'static'),
    )

    # Purge expired clients first
    purge_expired_client_files()
    # Load the clients' state
    load_clients()

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

    create_msg_thread(client_id, force_new=True) # Create a new empty thread
    save_client(client_id) # Save the client with the empty thread

    return redirect(url_for('index'))

#@app.route('/reset_expired_chat', methods=['POST'])
#def reset_expired_chat():
#    logmsg("In route /reset_expired_chat")
#    # Force-create a new thread
#    if (client_id := request.cookies.get('CustomClientId')) is None:
#        return jsonify({'error': 'No client ID found'}), 400
#
#    create_msg_thread(client_id, force_new=True) # Create a new empty thread
#    save_client(client_id) # Save the client with the empty thread
#
#    return redirect(url_for('index'))

#===============================================================================
def make_client_room(client_id: str) -> str:
    """Create a room name for a client ID"""
    if not client_id:
        raise ValueError("Client ID cannot be None or empty")
    return f"client_{client_id}"

#===============================================================================
async def get_file_content_bytes(file_id: str) -> bytes:
    """Get file content as bytes from OpenAI"""
    response = await _oa_wrap.GetFileContent(file_id)
    return await response.aread()

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
        data = asyncio.run(get_file_content_bytes(file_id))
        data_io = BytesIO(data)
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
def get_client_id_from_request() -> Optional[str]:
    """Get the client ID from the request arguments."""
    client_id = request.args.get('CustomClientId')  # type: ignore
    if not client_id:
        logerr("No client ID found in request")
        return None
    return client_id

@socketio.on('connect')
def handle_connect():
    client_id = get_client_id_from_request()
    if not client_id:
        return

    get_app_client(client_id).connected = True
    client_room = make_client_room(client_id)
    join_room(client_room)
    logmsg(f"Client connected. Req.Session ID: {request.sid}, Custom Client ID: {client_id}, joined room: {client_room}")  # type: ignore

@socketio.on('connect_ack')
def handle_connect_ack():
    client_id = get_client_id_from_request()
    if not client_id:
        return

    get_app_client(client_id).connected = True
    logmsg(f"Responding to connect_ack. Req.Session ID: {request.sid}, Custom Client ID: {client_id}")  # type: ignore
    emit('connected', {'custom_client_id': client_id})

@socketio.on('disconnect')
def handle_disconnect():
    client_id = get_client_id_from_request()
    if not client_id:
        return

    get_app_client(client_id).connected = False
    logmsg(f"Client disconnected. Session ID: {request.sid}")  # type: ignore

@socketio.on('reconnect')
def handle_reconnect():
    client_id = get_client_id_from_request()
    if not client_id:
        return

    get_app_client(client_id).connected = True
    logmsg(f"Client reconnected. Session ID: {request.sid}")  # type: ignore

#===============================================================================
@app.route('/get_addendums', methods=['GET'])
async def get_addendums():
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
    fc_str = await client_get_msg_thread(client_id).gen_fact_check(tools_user_data=client_id)
    if fc_str is None:
        logmsg(f"No fact-checks generated for client {client_id}")
        return jsonify({'addendums': [], 'message': 'No pending fact-checks', 'final': True}), 200

    logmsg(f"Got fact-checks for client {client_id}: {fc_str}")

    try:
        fc = json.loads(fc_str)
    except ValueError as e:
        logerr(f"Error parsing fact-checks for client {client_id}: {e}")
        return jsonify({'addendums': [], 'message': 'Error parsing fact-checks', 'final': True}), 200

    return jsonify({'addendums': [fc], 'final': True}), 200

#===============================================================================
async def stream_openai_response(client_id):
    # Set the client ID in the thread-local storage for the message thread wrapper
    msg_thread_wrapper.set_client_id(client_id)

    mt = client_get_msg_thread(client_id)

    # Get the async generator from completion_with_tools
    response_gen = await OAIUtils.completion_with_tools(
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

    # Use socketio.emit for background tasks
    socketio.emit('stream', {'src_id': src_id, 'text': '$DUMMY_TOKEN$'}, room=client_room)  # type: ignore

    # Send the response in parts and collect the full text
    reply_text = ""
    try:
        async for part in response_gen:
            if part is None:
                continue
            reply_text += part

            try:
                socketio.emit('stream', {'src_id': src_id, 'text': part}, room=client_room)  # type: ignore
            except Exception as e:
                logerr(f"Error sending message to session {client_room}: {e}")
                break

        mt.update_message(src_id, reply_text)

        # End the stream with a special signal
        socketio.emit('stream', {'src_id': src_id, 'text': '$END_TOKEN$'}, room=client_room)  # type: ignore

        # Save the client
        save_client(client_id)

        # Do periodic checks
        periodic_check()
    except Exception as e:
        logerr(f"Error in stream_openai_response: {e}")
        socketio.emit('stream', {'src_id': src_id, 'text': '$ERROR_TOKEN$'}, room=client_room)  # type: ignore
    finally:
        if config['support_enable_factcheck']:
            client_set_key(client_id, 'generate_fchecks', True)
            logmsg(f"Set generate_fchecks to True for client {client_id}")

#==================================================================
import pytz
from datetime import datetime

def make_user_metadata_dict(client_id) -> Dict[str, Any]:
    # Create a dictionary with the current Unix timestamp
    msg_metadata: Dict[str, Any] = {'unix_time': int(time.time())}

    if uinfo := client_get_user_info(client_id):
        logmsg(f"User info: {uinfo}")

        # Add the existing user info as-is
        msg_metadata.update(uinfo)

        # Remove user_agent if requested
        if DO_REMOVE_USER_AGENT_FROM_META and 'user_agent' in uinfo:
            msg_metadata.pop('user_agent', None)

        # Add the local time as a string like 2024-10-17T16:27:28.924857+09:00
        tz_timezone = pytz.timezone(uinfo['timezone'])
        loc_time = datetime.now(tz_timezone)
        msg_metadata['user_local_time'] = loc_time.isoformat()

    return msg_metadata

#==================================================================
@socketio.on('send_message')
def handle_send_message(json, methods=['GET', 'POST']):
    dump_memory_usage("send_message START")

    client_id = request.args.get('CustomClientId')
    if not client_id:
        logerr("No client ID found in request")
        return jsonify({'status': 'error', 'message': 'No client ID found'})

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
            socketio.emit('stream', {'text': 'No message thread loaded, please reload the page.', 'isError': True}, room=client_room)  # type: ignore
            dump_memory_usage("send_message END")
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

        # Start the async streaming response in the background
        # We need to wrap the coroutine in a function that handles the event loop
        def run_stream():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Create and run the task
                task = loop.create_task(stream_openai_response(client_id))
                loop.run_until_complete(task)
            except Exception as e:
                logerr(f"Error in run_stream: {e}")
            finally:
                try:
                    # Clean up any pending tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                        try:
                            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
                        except asyncio.CancelledError:
                            pass
                finally:
                    loop.close()

        socketio.start_background_task(run_stream)

        dump_memory_usage("send_message END")

        # Respond with a "processing" status and with the user message ID
        # We need the user message ID to match the addendums/fact-checks
        return jsonify({'status': 'processing',
                        'user_msg_id': user_msg['src_id']})
    except Exception as e:
        logerr(f"KeyError: {str(e)}")
        socketio.emit('stream', {'text': 'The session has been disconnected. Please reload the page.', 'isError': True}, room=client_room)  # type: ignore
        dump_memory_usage("send_message END")
        return jsonify({'status': 'error', 'message': 'Session disconnected'})

## Add cleanup on shutdown
#@atexit.register
#def cleanup():
#    save_clients()

if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=8080, debug=True)
    socketio.run(app, host='0.0.0.0', port=8080, debug=True, allow_unsafe_werkzeug=True)
