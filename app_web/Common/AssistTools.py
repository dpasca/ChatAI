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

#==================================================================
# Define the super_get_user_info function
super_get_user_info: Callable[[Optional[dict]], dict] = lambda arguments=None: None

def set_super_get_user_info(super_get_user_info_: Callable[[Optional[dict]], dict]):
    global super_get_user_info
    super_get_user_info = super_get_user_info_

#==================================================================
super_get_main_MsgThread: Callable[[], MsgThread] = lambda: None

def set_super_get_main_MsgThread(super_get_main_MsgThread_: Callable[[], MsgThread]):
    global super_get_main_MsgThread
    super_get_main_MsgThread = super_get_main_MsgThread_

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

    msg_thread = super_get_main_MsgThread(arguments)

    # If there is no main message thread, then perform a simple web search
    if msg_thread is None or msg_thread.judge is None:
        logwarn("No main message thread or judge found. Falling back to web search.")
        return ddgsTextSearch(arguments["query"], max_results=10)

    return msg_thread.judge.gen_research(
                wrap=arguments["wrap"],
                query=arguments["query"],
                tools_user_data=arguments["tools_user_data"])

from typing import List, Dict, Any
from pydantic import BaseModel

class ToolItem(BaseModel):
    name: str
    function: Callable[[dict], Any]
    requires_assistant: bool = False
    usable_by_root_assistant: bool = False
    definition: Dict[str, Any]

tool_items = [
    ToolItem(
        name="perform_web_search",
        function=perform_web_search,
        requires_assistant=False,
        usable_by_root_assistant=False,
        definition={
            "name": "perform_web_search",
            "description": "Perform a web search for any unknown or current information",
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
    ),
    ToolItem(
        name="get_user_info",
        function=get_user_info,
        requires_assistant=False,
        usable_by_root_assistant=True,
        definition={
            "name": "get_user_info",
            "description": "Get the user info, such as timezone and user-agent (browser)",
        }
    ),
    ToolItem(
        name="get_unix_time",
        function=get_unix_time,
        requires_assistant=False,
        usable_by_root_assistant=True,
        definition={
            "name": "get_unix_time",
            "description": "Get the current unix time",
        }
    ),
    ToolItem(
        name="get_user_local_time",
        function=get_user_local_time,
        requires_assistant=False,
        usable_by_root_assistant=True,
        definition={
            "name": "get_user_local_time",
            "description": "Get the user local time and timezone",
        }
    ),
    ToolItem(
        name="ask_research_assistant",
        function=ask_research_assistant,
        requires_assistant=True,
        usable_by_root_assistant=True,
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
    ),
]

tool_items_dict = {item.name: item for item in tool_items}

def fallback_tool_function(name, arguments):
    logerr(f"Unknown function {name}. Falling back to web search !")
    name_to_human_friendly = name.replace("_", " ")
    query = f"What is {name_to_human_friendly} of " + " ".join(arguments.values())
    logmsg(f"Submitting made-up query: {query}")
    return ddgsTextSearch(query, max_results=3)
