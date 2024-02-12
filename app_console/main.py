#==================================================================
# main.py
#
# Author: Davide Pasca, 2024/01/18
# Description: An agent chat app with fact-checking and web search
#==================================================================
import os
import sys
import json
import time
from pyexpat.errors import messages
from dotenv import load_dotenv
from datetime import datetime
import inspect
from io import BytesIO

# Load environment variables from .env file
load_dotenv()

# Update the path for the modules below
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_web.Common.OpenAIWrapper import OpenAIWrapper
from app_web.Common.StorageLocal import StorageLocal as Storage
from app_web.Common.logger import *
from app_web.Common.OAIUtils import *
from app_web.Common import ChatAICore
from app_web.Common.MsgThread import MsgThread

import locale
# Set the locale to the user's default setting/debug
locale.setlocale(locale.LC_ALL, '')

USER_BUCKET_PATH = "user_a_00001"
ENABLE_SLEEP_LOGGING = False

from app_web.Common.SessionDict import SessionDict

session = SessionDict(f'_storage/{USER_BUCKET_PATH}/session.json')
logmsg(f"Session: {session}")

#==================================================================
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

USE_SOFT_WRAP = False

console = Console(soft_wrap=USE_SOFT_WRAP)

def makePromptColoredRole(role: str) -> list:
    role_colors = {
        "assistant": 'ansigreen',
        "user": 'ansiyellow',
        "other": 'ansiblue'
    }
    color = role_colors.get(role, 'ansiblue')
    return [(color, f"{role}> ")]

def makeRichColoredRole(role):
    role_colors = {
        "assistant": 'green',
        "user": 'yellow',
        "other": 'blue'
    }
    color = role_colors.get(role, 'blue')
    return f"[{color}]{role}>[/{color}] "

from rich import print as rprint
from rich_pixels import Pixels
from PIL import Image

def makeRichImageItems(items: list, url: str) -> None:
    items.append(Text(url + "\n")) # Always add the URL as text
    try:
        # Attempt to open the image, resize it to 28x28 pixels,
        # . and convert it to rich Pixels
        HEAD = "file:///"
        NEW_SIZE = 28

        pathname = url[len(HEAD):] if url.startswith(HEAD) else url
        image = Image.open(pathname)
        resized_image = image.resize((NEW_SIZE, NEW_SIZE))
        pixels = Pixels.from_image(resized_image)
        items.append(pixels)
    except:
        pass

def printChatMsg(msg: dict) -> None:
    items = []
    if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
        for cont in msg['content']:
            #items.append(" | " + msg['role'] + " | " + cont['type'] + ": ")
            items.append(makeRichColoredRole(msg['role']))
            if cont['type'] == "text":
                txt = cont['value']
                if len(txt) == 0:
                    # Add a newline if the text is empty
                    items.append("\n")
                else:
                    # When using hard-wrap, we need to start from col 0
                    use_md = msg['role'] == "assistant"
                    if USE_SOFT_WRAP == False and use_md:
                        items.append("\n")

                    if use_md:
                        items.append(Markdown(txt))
                    else:
                        items.append(Text(txt + "\n"))

            elif cont['type'] == "image_file":
                makeRichImageItems(items, cont['value'])
            else:
                items.append(Text(cont['value'] + "\n"))
    else:
        items.append(Markdown(msg))

    for item in items:
        console.print(item, end='')

def inputChatMsg(role: str, history=None, auto_suggest=None, completer=None) -> str:
    colored = makePromptColoredRole(role)
    return prompt(colored, history=history, auto_suggest=auto_suggest, completer=completer)

#==================================================================
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

#==================================================================
# Callback to get the user info from the session
def local_get_user_info(arguments):
    if 'tools_user_data' not in arguments:
        return 'No user info available'
    # Populate the session['user_info'] with local user info (shell locale and timezone)
    currentTime = datetime.now()
    if not 'user_info' in session:
        session['user_info'] = {}
    session['user_info']['timezone'] = str(currentTime.astimezone().tzinfo)
    return session['user_info']

# Return the main message thread global straight up
def local_get_main_MsgThread(arguments):
    return _msg_thread

# Create the thread if it doesn't exist
def createThread(force_new=False) -> None:
    global _msg_thread

    # Create or get the thread
    if ('thread_id' not in session) or (session['thread_id'] is None) or force_new:
        _msg_thread = MsgThread.create_thread(_oa_wrap)
        logmsg("Creating new thread with ID " + _msg_thread.thread_id)
        # Save the thread ID to the session
        session['thread_id'] = _msg_thread.thread_id
        if 'msg_thread_data' in session:
            del session['msg_thread_data']
    else:
        _msg_thread = MsgThread.from_thread_id(_oa_wrap, session['thread_id'])
        logmsg("Retrieved existing thread with ID " + _msg_thread.thread_id)

    # Get our cached thread messages
    if 'msg_thread_data' in session:
        _msg_thread.deserialize_data(session['msg_thread_data'])

    new_n = _msg_thread.fetch_new_messages(make_file_url)
    print(f"Found {new_n} new messages in the thread history")
    save_session()

    # Optional: create the judge for the thread
    # Create the sub-agents system for the message-thread
    _msg_thread.create_judge(
        model=config["support_model_version"],
        temperature=config["support_model_temperature"])

def save_session():
    session['msg_thread_data'] = _msg_thread.serialize_data()
    session.save_to_disk()

#==================================================================
logmsg("Creating storage...")
_storage = Storage("_storage")

# Create the assistant
logmsg("Creating assistant...")
_assistant = ChatAICore.create_assistant(
                wrap=_oa_wrap,
                config=config,
                instructions=assistant_instructions,
                get_main_MsgThread=local_get_main_MsgThread,
                get_user_info=local_get_user_info)

#==================================================================
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
def index(do_clear=False):
    # Load or create the thread
    createThread(force_new=do_clear)

    print(f"Welcome to {config['app_title']}, v{config['app_version']}")
    print(f"Assistant: {config['assistant_name']}")

    # Process the history messages
    print(f"Total history messages: {len(_msg_thread.messages)}")
    for msg in _msg_thread.messages:
        printChatMsg(msg)

    #printFactCheck(_msg_thread.gen_fact_check()) # For debugging

#==================================================================
def printFactCheck(fcRepliesStr: str) -> None:
    if fcRepliesStr is None:
        return

    logmsg(f"Fact-check replies: {fcRepliesStr}")
    try:
        fcReplies = json.loads(fcRepliesStr)
        if len(fcReplies['fact_checks']) == 0:
            return
        #console.log(fcReplies)

        outStr = ""
        for reply in fcReplies['fact_checks']:
            if len(outStr) > 0:
                outStr += "\n"

            corr = reply.get('correctness') or 0
            true_icon = "✅"
            false_icon = "❌"
            outStr += "> "
            if   corr == 0: outStr += false_icon
            elif corr == 1: outStr += false_icon
            elif corr == 2: outStr += false_icon
            elif corr == 3: outStr += true_icon
            elif corr == 4: outStr += true_icon
            elif corr == 5: outStr += true_icon
            outStr += "\n"

            rebuttal = reply.get('rebuttal') or ''
            links = reply.get('links') or []
            if rebuttal or links:
                outStr += f"> {rebuttal}\n"
                for link in links:
                    url = link.get('url') or ""
                    title = link.get('title') or url
                    outStr += f"> - [{title}]({url})\n"

        if outStr:
            console.print(Markdown(outStr))
    except json.JSONDecodeError:
        logerr("Error decoding JSON response")
        console.print(Markdown("> " + fcRepliesStr))

#==================================================================
# Main loop for console app
import argparse

def main():

    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--clear', action='store_true',
                        help='clear the chat at the start')

    args = parser.parse_args()

    print(f"Logging is {'Enabled' if ENABLE_LOGGING else 'Disabled'}")

    index(args.clear)

    completer = None #WordCompleter(["/clear", "/exit"])

    while True:
        # Get user input
        user_input = inputChatMsg("user", completer=completer)

        if user_input == "/clear":
            # Force-create a new thread
            createThread(force_new=True)
            continue

        # Exit condition (you can define your own)
        if user_input.lower() == '/exit':
            break

        thread_id = session['thread_id']

        # Create the user message
        user_msg = ChatAICore.create_user_message(_oa_wrap, thread_id, user_input, make_file_url)
        # Add the message to the thread
        _msg_thread.add_message(user_msg)

        def on_replies(replies: list):
            for reply in replies:
                _msg_thread.add_message(reply)
                printChatMsg(reply)
            save_session() # For the local messages

        # Send the user message and get the replies
        ret_val = ChatAICore.SendUserMessage(
            wrap=_oa_wrap,
            last_message_id=user_msg['src_id'],
            assistant_id=_assistant.id,
            thread_id=thread_id,
            make_file_url=make_file_url,
            on_replies=on_replies)

        # Start the fact-checking
        if ret_val == ChatAICore.SUCCESS:
            # Request fact-checking if enabled
            if config['support_enable_factcheck']:
                printFactCheck(_msg_thread.gen_fact_check())
        else:
            logerr(f"Error sending user message: {ret_val}")


if __name__ == "__main__":
    main()
