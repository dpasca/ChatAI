#==================================================================
# AssistTools.py
#
# Author: Davide Pasca, 2024/01/23
# Description: Tools for the assistant (aka function-calling/actions)
#==================================================================

import asyncio
import json
import time
import pytz
from datetime import datetime
from typing import Union

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

from brave import Brave

from .logger import *
from typing import Callable, Optional
from typing import Dict, Any, List, Callable
from .MsgThread import MsgThread as MsgThread
from .ToolItem import ToolItem
from .RAGSystem import RAGSystem

import os
import requests

# Directory for persisting llmaindex index data
RAG_INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
RAG_CHROMA_PERSIST_DIR = "_chroma_db"

RAG_IMMEDIATE_SRC_DIR = "rag_immediate_src"

tool_items_dict = {}

#==================================================================
# Define the super_get_user_info function
super_get_user_info: Optional[Callable[[Optional[dict]], dict]] = None
super_get_main_MsgThread: Optional[Callable[[Optional[dict]], Any]] = None

#==================================================================
async def execute_tool(tool_item, parameters: Dict[str, Any]) -> Any:
    """Execute a single tool asynchronously."""
    if asyncio.iscoroutinefunction(tool_item.function):
        return await tool_item.function(parameters)
    else:
        return tool_item.function(parameters)

async def multi_tool_use_parallel(tool_uses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute multiple tools in parallel."""
    tasks = []

    for tool_use in tool_uses:
        recipient_name = tool_use.get('recipient_name', '')
        function_name = recipient_name.split('.')[-1]  # Extract the actual function name

        if function_name in tool_items_dict:
            tool_item = tool_items_dict[function_name]
            parameters = tool_use.get('parameters', {})
            tasks.append(execute_tool(tool_item, parameters))
        else:
            tasks.append(asyncio.create_task(asyncio.sleep(0)))  # Dummy task for invalid tools

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        f"result_{i}": str(result) if not isinstance(result, Exception) else f"Error: {str(result)}"
        for i, result in enumerate(results)
    }

def fallback_tool_function(name: str, arguments: Any) -> Any:
    logmsg(f"Fallback tool function: {name}({arguments})")
    # NOTE: Sometimes OpenAI exposes a call to multi_tool_use.parallel as a bug
    #  https://community.openai.com/t/model-tries-to-call-unknown-function-multi-tool-use-parallel/490653
    if name in ["multi_tool_use.parallel", "multi_tool_use_parallel"]:
        logmsg(f"Handling multi_tool_use.parallel")
        try:
            if isinstance(arguments, str):
                args = json.loads(arguments)
            else:
                args = arguments
            tool_uses = args.get('tool_uses', [])
            results = asyncio.run(multi_tool_use_parallel(tool_uses))
            return json.dumps(results)
        except Exception as e:
            return json.dumps({"error": f"Failed to execute multi_tool_use.parallel: {str(e)}"})

    # Existing fallback logic for other unknown functions
    if isinstance(arguments, dict):
        query = " ".join(str(value) for value in arguments.values() if not isinstance(value, object))
        logmsg(f"Query built from dict: {query}")
    elif isinstance(arguments, str):
        query = arguments
        logmsg(f"Query built from string: {query}")
    else:
        query = str(arguments)
        logmsg(f"Query built from object: {query}")

    name_to_human_friendly = name.replace("_", " ")
    full_query = f"What is {name_to_human_friendly} of {query}"
    logmsg(f"Full query: {full_query}")
    return perform_web_search({"query": full_query})

#==================================================================
def ddgsTextSearch(query: str, max_results: int = 10) -> list:
    """Perform a DuckDuckGo text search."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results if results else []
    except Exception as e:
        logerr(f"DuckDuckGo search failed: {str(e)}")
        return []

def braveTextSearch(query: str, max_results: Optional[int] = None) -> list:
    """Perform a text search using the Brave Search API."""
    if "BRAVE_API_KEY" not in os.environ:
        return []

    try:
        headers = {
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
            "Accept": "application/json",
        }
        params = {"q": query}
        if max_results:
            params["count"] = str(max_results)

        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        
        results = []
        if "web" in data and "results" in data["web"]:
            results = data["web"]["results"]
            if max_results:
                results = results[:max_results]
        return results
    except Exception as e:
        logerr(f"Brave search failed: {str(e)}")
        return []

# Define your functions
def perform_web_search(arguments: Union[dict, str], max_results: int = 5) -> str:
    """Perform a web search and return the results as a string."""
    try:
        # Extract query from arguments
        if isinstance(arguments, dict):
            if "query" not in arguments:
                return "No query provided in arguments"
            query = arguments["query"]
            if "max_results" in arguments:
                max_results = arguments["max_results"]
        else:
            query = arguments

        # Perform the search
        results = ddgsTextSearch(query)
        if not results:
            return "No results found"

        # Take only the first max_results
        results = results[:max_results]
        
        # Format the results as a string
        formatted_results = []
        for result in results:
            title = result.get('title', '')
            url = result.get('url', '')
            if title and url:
                formatted_results.append(f"- {title}: {url}")
        
        return "\n".join(formatted_results) if formatted_results else "No results found"
    except Exception as e:
        logerr(f"Error in web search: {e}")
        return f"Error performing web search: {e}"

"""
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
"""

async def ask_research_assistant(arguments: Optional[dict] = None) -> str:
    """Ask the research assistant for help."""
    # Ensure we have all the necessary args
    if not arguments or not (arguments.get("query") or arguments.get("tools_user_data")):
        logerr("Missing arguments for ask_research_assistant")
        return f"Missing arguments. Got: {arguments}"

    # Get the message thread
    msg_thread = None
    if super_get_main_MsgThread is not None:
        msg_thread = super_get_main_MsgThread(arguments)

    # If there is no main message thread, then perform a simple web search
    if msg_thread is None or not hasattr(msg_thread, 'judge') or msg_thread.judge is None:
        logwarn("No main message thread or judge found. Falling back to web search.")
        return perform_web_search(arguments)

    try:
        result = await msg_thread.judge.gen_research(
            query=arguments["query"],
            tools_user_data=arguments["tools_user_data"])
        return str(result) if result is not None else "No research results available"
    except Exception as e:
        logerr(f"Error in research assistant: {e}")
        return f"Error performing research: {e}"

#==================================================================
tool_items: List[ToolItem] = []
# These info are now provided as metadata in user messages
# No need to have function calls about them
"""
tool_items = [
    ToolItem(
        name="get_user_info",
        function=get_user_info,
        is_available_to_agents=True,
        definition={
            "name": "get_user_info",
            "description": "Get the user info, such as timezone and user-agent (browser)",
        }
    ),
    ToolItem(
        name="get_unix_time",
        function=get_unix_time,
        is_available_to_agents=True,
        definition={
            "name": "get_unix_time",
            "description": "Get the current unix time",
        }
    ),
    ToolItem(
        name="get_user_local_time",
        function=get_user_local_time,
        is_available_to_agents=True,
        definition={
            "name": "get_user_local_time",
            "description": "Get the user local time and timezone",
        }
    ),
]
"""

#==================================================================
def initialize_tools(
    enable_rag: bool = False,
    rag_query_instructions: Optional[str] = None,
    enable_web_search: bool = False,
    support_enable_research_assistant: bool = True,
    storage: Optional[Any] = None,
    super_get_user_info_: Optional[Callable[[Optional[dict]], dict]] = None,
    super_get_main_MsgThread_: Optional[Callable[[Optional[dict]], Any]] = None,
    ) -> None:
    """Initialize the tools with the given parameters."""
    global _storage
    global super_get_user_info
    global super_get_main_MsgThread

    _storage = storage
    super_get_user_info = super_get_user_info_
    super_get_main_MsgThread = super_get_main_MsgThread_

    if enable_web_search:
        tool_items.append(
            ToolItem(
                name="perform_web_search",
                function=perform_web_search,
                is_available_to_agents=True,
                definition={
                    "name": "perform_web_search",
                    "description": "Perform a web search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query. Use language best suited for the research."
                            }
                        },
                        "required": ["query"]
                    }
                }
            )
        )

    if support_enable_research_assistant:
        logmsg("Adding research assistant tool")
        tool_items.append(
            ToolItem(
                name="ask_research_assistant",
                function=ask_research_assistant,
                is_available_to_agents=True,
                definition={
                    "name": "ask_research_assistant",
                    "description": "Perform any kind of research on the Internet and general expert consulting.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query. Use language best suited for the research."
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

    # Print all tool names in the log
    logmsg("Available tools:")
    for item in tool_items:
        logmsg(f"- {item.name} : {item.definition['description']}")

def get_user_info(arguments: Optional[dict] = None) -> dict:
    """Get user info from the super function if available."""
    if super_get_user_info is None:
        return {}
    return super_get_user_info(arguments)

def get_main_MsgThread(arguments: Optional[dict] = None) -> Any:
    """Get message thread from the super function if available."""
    if super_get_main_MsgThread is None:
        return None
    return super_get_main_MsgThread(arguments)
