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

super_get_user_info: Callable[[Optional[dict]], dict] = lambda arguments=None: None

def set_super_get_user_info(super_get_user_info_: Callable[[Optional[dict]], dict]):
    global super_get_user_info
    super_get_user_info = super_get_user_info_

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

# Tool definitions and actions
ToolDefinitions = {
    "perform_web_search": {
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
    },
    "get_user_info": {
        "name": "get_user_info",
        "description": "Get the user info, such as timezone and user-agent (browser)",
    },
    "get_unix_time": {
        "name": "get_unix_time",
        "description": "Get the current unix time",
    },
    "get_user_local_time": {
        "name": "get_user_local_time",
        "description": "Get the user local time and timezone",
    },
}

ToolActions = {
    "perform_web_search": perform_web_search,
    "get_user_info": get_user_info,
    "get_unix_time": get_unix_time,
    "get_user_local_time": get_user_local_time,
}

def fallback_tool_function(name, arguments):
    logerr(f"Unknown function {name}. Falling back to web search !")
    name_to_human_friendly = name.replace("_", " ")
    query = f"What is {name_to_human_friendly} of " + " ".join(arguments.values())
    logmsg(f"Submitting made-up query: {query}")
    return ddgsTextSearch(query, max_results=3)
