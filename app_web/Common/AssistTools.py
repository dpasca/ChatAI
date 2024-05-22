#==================================================================
# AssistTools.py
#
# Author: Davide Pasca, 2024/01/23
# Description: Tools for the assistant (aka function-calling/actions)
#==================================================================

import json
import time
import pytz
from datetime import datetime
from duckduckgo_search import DDGS
from .logger import *
from typing import Callable, Optional
from .MsgThread import MsgThread as MsgThread
from .ToolItem import ToolItem
from .RAGSystem import RAGSystem

# Directory for persisting llmaindex index data
RAG_INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
RAG_CHROMA_PERSIST_DIR = "_chroma_db"

RAG_IMMEDIATE_SRC_DIR = "rag_immediate_src"

#==================================================================
# Define the super_get_user_info function
super_get_user_info: Callable[[Optional[dict]], dict] = lambda arguments=None: None
super_get_main_MsgThread: Callable[[], MsgThread] = lambda: None

#==================================================================
def ddgsTextSearch(query, max_results=None):
    """
    Perform a text search using the DuckDuckGo Search API.

    Args:
        query (str): The search query string.
        max_results (int, optional): The maximum number of search results to return. If None, returns all available results.

    Returns:
        list of dict: A list of search results, each result being a dictionary.
    """
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=max_results)]
    return results

# Define your functions
def perform_web_search(arguments):
    return ddgsTextSearch(arguments["query"], max_results=10)

def get_user_info(arguments=None):
    return { "user_info": super_get_user_info(arguments) }

def get_unix_time(arguments=None):
    return { "unix_time": int(time.time()) }

def get_user_local_time(arguments=None):
    try:
        uinfo = super_get_user_info(arguments)
        timezone = uinfo['timezone']
        tz_timezone = pytz.timezone(timezone)
        user_time = datetime.now(tz_timezone)
    except:
        timezone = "UTC"
        user_time = datetime.now()
    return {
        "user_local_time": json.dumps(user_time, default=str),
        "user_timezone": timezone }

def ask_research_assistant(arguments=None):

    # Ensure we have all the necessary args
    if not (arguments.get("wrap") or
            arguments.get("query") or
            arguments.get("tools_user_data")):
        logerr("Missing arguments for ask_research_assistant")
        return f"Missing arguments. Got: {arguments}"

    msg_thread = super_get_main_MsgThread(arguments)

    # If there is no main message thread, then perform a simple web search
    if msg_thread is None or msg_thread.judge is None:
        logwarn("No main message thread or judge found. Falling back to web search.")
        return ddgsTextSearch(arguments["query"], max_results=5)

    return msg_thread.judge.gen_research(
                wrap=arguments["wrap"],
                query=arguments["query"],
                tools_user_data=arguments["tools_user_data"])

tool_items = [
    ToolItem(
        name="get_user_info",
        function=get_user_info,
        requires_assistant=False,
        definition={
            "name": "get_user_info",
            "description": "Get the user info, such as timezone and user-agent (browser)",
        }
    ),
    ToolItem(
        name="get_unix_time",
        function=get_unix_time,
        requires_assistant=False,
        definition={
            "name": "get_unix_time",
            "description": "Get the current unix time",
        }
    ),
    ToolItem(
        name="get_user_local_time",
        function=get_user_local_time,
        requires_assistant=False,
        definition={
            "name": "get_user_local_time",
            "description": "Get the user local time and timezone",
        }
    ),
    ToolItem(
        name="ask_research_assistant",
        function=ask_research_assistant,
        requires_assistant=True,
        definition={
            "name": "ask_research_assistant",
            "description": "Ask the research assistant for help",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    )
]

def fallback_tool_function(name, arguments):
    logerr(f"Unknown function {name}. Falling back to web search !")
    name_to_human_friendly = name.replace("_", " ")
    query = f"What is {name_to_human_friendly} of " + " ".join(arguments.values())
    logmsg(f"Submitting made-up query: {query}")
    return ddgsTextSearch(query, max_results=3)

#==================================================================
tool_items_dict = {}

def initialize_tools(
        enable_rag=False,
        rag_query_instructions=None,
        enable_web_search=True,
        storage=None,
        super_get_user_info_: Callable[[Optional[dict]], dict]=None,
        super_get_main_MsgThread_: Callable[[], MsgThread]=None):

    global super_get_main_MsgThread
    super_get_main_MsgThread = super_get_main_MsgThread_

    global super_get_user_info
    super_get_user_info = super_get_user_info_

    if enable_web_search:
        tool_items.append(
            ToolItem(
                name="perform_web_search",
                function=perform_web_search,
                requires_assistant=False,
                definition={
                    "name": "perform_web_search",
                    "description": "Perform a web search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query"
                            }
                        },
                        "required": ["query"]
                    }
                }
            )
        )

    # Try to initialize the RAG
    if enable_rag:
        has_persist_dir = os.path.exists(RAG_INDEX_PERSIST_DIR)
        has_imm_dir = os.path.exists(RAG_IMMEDIATE_SRC_DIR)
        if not (has_persist_dir or has_imm_dir):
            logwarn("RAG directories not found. Disabling RAG.")
            enable_rag = False

        rag_sys = RAGSystem(rag_query_instructions)
        if has_persist_dir:
            rag_sys.add_persistent_storage(RAG_INDEX_PERSIST_DIR, RAG_CHROMA_PERSIST_DIR)
        if has_imm_dir:
            rag_sys.add_immediate_storage(RAG_IMMEDIATE_SRC_DIR)

        tool_items.extend(rag_sys.get_tool_items())

    # Finally initialize the dictionary only with the enabled tools
    global tool_items_dict
    tool_items_dict = {item.name: item for item in tool_items}
