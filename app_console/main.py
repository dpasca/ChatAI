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
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../app_web/Common'))
from OpenAIWrapper import OpenAIWrapper
from StorageLocal import StorageLocal as Storage
from logger import *
from ConvoJudge import ConvoJudge
from OAIUtils import *

import locale
# Set the locale to the user's default setting/debug
locale.setlocale(locale.LC_ALL, '')

USER_BUCKET_PATH = "user_a_00001"
ENABLE_SLEEP_LOGGING = False

from SessionDict import SessionDict

session = SessionDict(f'_storage/{USER_BUCKET_PATH}/session.json')
logmsg(f"Session: {session}")

#==================================================================
from prompt_toolkit import prompt, print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.completion import WordCompleter

from rich.console import Console
from rich.markdown import Markdown
from rich.style import Style
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

#===============================================================================
import ChatAICore

def sleepForAPI():
    if ENABLE_LOGGING and ENABLE_SLEEP_LOGGING:
        caller = inspect.currentframe().f_back.f_code.co_name
        line = inspect.currentframe().f_back.f_lineno
        print(f"[{caller}:{line}] sleeping...")
    time.sleep(0.5)

ChatAICore.SetSleepForAPI(sleepForAPI)

#==================================================================
_judge = ConvoJudge(
    model=config["support_model_version"],
    temperature=config["support_model_temperature"]
    )

# Callback to get the user info from the session
def local_get_user_info():
    # Populate the session['user_info'] with local user info (shell locale and timezone)
    currentTime = datetime.now()
    if not 'user_info' in session:
        session['user_info'] = {}
    session['user_info']['timezone'] = str(currentTime.astimezone().tzinfo)
    return session['user_info']

# Create the thread if it doesn't exist
def createThread(force_new=False):
    # if there are no messages in the session, add the role message
    if ('thread_id' not in session) or (session['thread_id'] is None) or force_new:
        thread = _oa_wrap.CreateThread()
        logmsg("Creating new thread with ID " + thread.id)
        # Save the thread ID to the session
        session['thread_id'] = thread.id
        session.save_to_disk()
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

#==================================================================
def index(do_clear=False):
    # Load or create the thread
    thread_id = createThread(force_new=do_clear)

    _judge.ClearMessages()

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
    for msg in getLocMessages():
        _judge.AddMessage(msg)
        printChatMsg(msg)

    #printFactCheck(_judge.GenFactCheck(_oa_wrap)) # For debug

#==================================================================
def printFactCheck(fcRepliesStr: str) -> None:
    try:
        fcReplies = json.loads(fcRepliesStr)
        if len(fcReplies['fact_check']) == 0:
            return
        #console.log(fcReplies)

        outStr = ""
        for reply in fcReplies['fact_check']:
            rebuttal = reply.get('rebuttal') or ''
            links = reply.get('links') or []
            if rebuttal or links:
                outStr += f"> {rebuttal}\n"
                for link in links:
                    readableLink = link if not link.startswith("https://") else link[len("https://"):]
                    outStr += f"> - [{readableLink}]({link})\n"

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
            # Clear the local messages and invalidate the thread ID
            session['loc_messages'] = []
            # Force-create a new thread
            createThread(force_new=True)
            _judge.ClearMessages()
            continue

        # Exit condition (you can define your own)
        if user_input.lower() == '/exit':
            break

        thread_id = session['thread_id']

        def on_replies(replies: list):
            for reply in replies:
                appendLocMessage(reply)
                _judge.AddMessage(reply)
                printChatMsg(reply)
            save_session() # For the local messages

        # Send the user message and get the replies
        _, status_code = ChatAICore.SendUserMessage(
            wrap=_oa_wrap,
            msg_text=user_input,
            assistant_id=_assistant.id,
            thread_id=thread_id,
            make_file_url=make_file_url,
            on_replies=on_replies)

        # Start the fact-checking
        if status_code == 200:
            printFactCheck(_judge.GenFactCheck(_oa_wrap))
        elif status_code == 500:
            logerr("Error or no new messages")


if __name__ == "__main__":
    main()
