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

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

from brave import Brave

from .logger import *
from typing import Callable, Optional
from typing import Dict, Any, List, Callable
from .MsgThread import MsgThread as MsgThread
from .ToolItem import ToolItem
from .RAGSystem import RAGSystem

# Directory for persisting llmaindex index data
RAG_INDEX_PERSIST_DIR = "_index_data"
# Directory for persisting Chroma data
RAG_CHROMA_PERSIST_DIR = "_chroma_db"

RAG_IMMEDIATE_SRC_DIR = "rag_immediate_src"

tool_items_dict = {}

#==================================================================
# Define the super_get_user_info function
super_get_user_info: Callable[[Optional[dict]], dict] = lambda arguments=None: None
super_get_main_MsgThread: Callable[[], MsgThread] = lambda: None

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
def ddgsTextSearch(query, max_results=None):
    """
    Perform a text search using the DuckDuckGo Search API.

    Args:
        query (str): The search query string.
        max_results (int, optional): The maximum number of search results to return. If None, returns all available results.

    Returns:
        list of dict: A list of search results, each result being a dictionary.
    """
    max_retries = 2
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = [r for r in ddgs.text(query, max_results=max_results)]
            return results
        except DuckDuckGoSearchException as e:
            if attempt < max_retries - 1:
                logwarn(f"DuckDuckGo search failed. Retrying in 5 seconds. Attempt {attempt + 1}/{max_retries}")
                time.sleep(5)
            else:
                logerr(f"DuckDuckGo search failed after {max_retries} attempts: {str(e)}")
                return []

def braveTextSearch(query, max_results=None):
    """
    Perform a text search using the Brave Search API.
    NOTE: It expects BRAVE_API_KEY to be set in the environment.

    Returns:
        list of dict: A list of search results, each result being a dictionary.
    """
    brave = Brave()
    try:
        results = brave.search(q=query, count=max_results)
        #logmsg(f"Raw Brave search results: {results}")

        formatted_results = []
        if hasattr(results, 'web') and hasattr(results.web, 'results'):
            for result in results.web.results:
                formatted_result = {
                    'title': result.title,
                    'url': str(result.url),
                    'description': result.description,
                    'language': result.language,
                    'family_friendly': result.family_friendly,
                    'thumbnail': result.thumbnail.src if result.thumbnail else ''
                }
                formatted_results.append(formatted_result)
                #logmsg(f"Formatted result: {formatted_result}")
        else:
            logmsg(f"Unexpected results structure: {type(results)}")

        return formatted_results
    except Exception as e:
        logerr(f"Failed to perform Brave search: {str(e)}")
        return []

# Define your functions
def perform_web_search(arguments, max_results=10):
    if isinstance(arguments, dict) and "query" in arguments:
        query = arguments["query"]
        if "max_results" in arguments:
            max_results = arguments["max_results"]
    elif isinstance(arguments, str):
        query = arguments
    else:
        logerr(f"Invalid arguments for perform_web_search: {arguments}")
        return []

    logmsg(f"Performing web search: {query}")

    # If we have a Brave API key, use it. Otherwise, use DuckDuckGo.
    if "BRAVE_API_KEY" in os.environ:
        return braveTextSearch(query, max_results=max_results)
    else:
        return ddgsTextSearch(query, max_results=max_results)

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
    #if not (arguments.get("wrap") or
    if not (arguments.get("query") or
            arguments.get("tools_user_data")):
        logerr("Missing arguments for ask_research_assistant")
        return f"Missing arguments. Got: {arguments}"

    msg_thread = super_get_main_MsgThread(arguments)

    # If there is no main message thread, then perform a simple web search
    if msg_thread is None or msg_thread.judge is None:
        logwarn("No main message thread or judge found. Falling back to web search.")
        return perform_web_search(arguments["query"], max_results=5)

    return msg_thread.judge.gen_research(
                query=arguments["query"],
                tools_user_data=arguments["tools_user_data"])

#==================================================================
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

#==================================================================
def initialize_tools(
        enable_rag=False,
        rag_query_instructions=None,
        enable_web_search=True,
        support_enable_research_assistant=True,
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
                is_available_to_agents=True,
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

    # Print all tool names in the log
    logmsg("Available tools:")
    for item in tool_items:
        logmsg(f"- {item.name} : {item.definition['description']}")
