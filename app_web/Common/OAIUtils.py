#==================================================================
# OAIUtils.py
#
# Author: Davide Pasca, 2024/01/23
# Description: Utilities to manage OpenAI API
#==================================================================

import re
from .logger import *
import json
import asyncio
import threading
from .OpenAIWrapper import OpenAIWrapper
from . import AssistTools
from typing import List, Dict, Union, Any, AsyncGenerator, AsyncIterator, Optional
import queue
from openai.types.chat import ChatCompletion

# Thread-local storage for event loops
thread_local = threading.local()

def get_or_create_eventloop() -> asyncio.AbstractEventLoop:
    """Get the event loop for current thread or create a new one if it doesn't exist."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def run_async(coro):
    """Run an async coroutine in the current thread's event loop."""
    try:
        # First try to get the running loop
        loop = asyncio.get_running_loop()
        # We're already in an async context, just return the coroutine
        # This allows the caller to handle it appropriately
        return coro
    except RuntimeError:
        # No running loop, create one or get the existing one
        loop = get_or_create_eventloop()
        return loop.run_until_complete(coro)

# Handle OpenAI's API bug, where multi_tool_use.parallel is exposed
def handle_multi_tool_use(call, tools_user_data):
    messages = []
    args = json.loads(call.function.arguments)
    # args would look like this:
    # {
    #     'tool_uses': [
    #         {'recipient_name': 'functions.perform_web_search', 'parameters': {'query': '中国政治新闻 2024'}},
    #         {'recipient_name': 'functions.perform_web_search', 'parameters': {'query': '中国政治动态 2024'}}
    #     ]
    # }
    for tool_use in args.get('tool_uses', []):
        sub_name = tool_use['recipient_name'].split('.')[-1]  # This would be 'perform_web_search'
        sub_args = tool_use['parameters']  # This would be {'query': '中国政治新闻 2024'} for the first item
        sub_args["tools_user_data"] = tools_user_data

        if sub_name in AssistTools.tool_items_dict:
            function_response = AssistTools.tool_items_dict[sub_name].function(sub_args)
        else:
            function_response = AssistTools.fallback_tool_function(sub_name, sub_args)

        content = json.dumps(function_response) if isinstance(function_response, dict) else function_response.response

        messages.append({
            "tool_call_id": call.id,
            "role": "tool",
            "name": sub_name,
            "content": content,
        })

    return messages

#==================================================================
async def apply_tools(tool_calls, wrap, tools_user_data=None):
    """Apply the tool calls and return the results."""
    results = []
    for tool_call in tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if tools_user_data is not None:
            args['tools_user_data'] = tools_user_data

        logmsg(f"Tool call: {name}({args})")
        try:
            if name in AssistTools.tool_items_dict:
                function = AssistTools.tool_items_dict[name].function
                if asyncio.iscoroutinefunction(function):
                    function_response = await function(args)
                else:
                    function_response = function(args)
            else:
                function_response = AssistTools.fallback_tool_function(name, args)
            results.append(function_response)
        except Exception as e:
            logerr(f"Error in tool call {name}: {e}")
            results.append(f"Error in tool call {name}: {e}")

    return results

#==================================================================
async def handle_stream(response, wrap, messages, tools_user_data):
    """Handle a streaming response from OpenAI API"""
    # A class to store the tool call that can mimic the structure tool_calls in the response
    class ToolCall:
        def __init__(self, id=None, function_name=None, function_arguments=''):
            self.id = id
            self.function = self.Function(name=function_name, arguments=function_arguments)
            self.is_complete = False

        class Function:
            def __init__(self, name=None, arguments=''):
                self.name = name
                self.arguments = arguments

    # Handle the stream case
    full_calls = {}
    cur_call_index = None
    accumulating_calls = False
    already_processed_some_calls = False
    current_content = ""

    # Process the stream of responses
    async for response_it in response:
        response_d = response_it.choices[0].delta
        finish_reason = response_it.choices[0].finish_reason

        do_stop = (response_d.content is None and
                  response_d.tool_calls is None and
                  finish_reason != "tool_calls")

        # Do we have tool calls ?
        if response_d.tool_calls:
            assert not already_processed_some_calls, "Expecting tool_calls in a single batch"
            # Set in "accumulation" state
            accumulating_calls = True
            # Process the tool-call deltas
            for call_d in response_d.tool_calls:
                # Has the index changed ?
                if call_d.index != cur_call_index:
                    # Mark the current call as complete (if any)
                    if cur_call_index is not None:
                        full_calls[cur_call_index].is_complete = True
                    # Start accumulating a new call
                    cur_call_index = call_d.index
                    full_calls[cur_call_index] = ToolCall()

                fc = full_calls[cur_call_index]
                if call_d.id:
                    assert fc.id is None
                    fc.id = call_d.id
                if call_d.function.name:
                    assert fc.function.name is None
                    fc.function.name = call_d.function.name
                if call_d.function.arguments:
                    fc.function.arguments += call_d.function.arguments
        else:
            # No more tool calls, can process the accumulated ones
            accumulating_calls = False
            if full_calls and cur_call_index is not None:
                full_calls[cur_call_index].is_complete = True

        # If we have a complete set of tool calls, process them
        if full_calls and not accumulating_calls:
            fc_list = list(full_calls.values())
            # Processing the calls here
            tools_out = await apply_tools(fc_list, wrap, tools_user_data)

            # Build the message that details the requested tool calls
            tc_reqs = []
            for c in fc_list:
                tc_reqs.append({
                    "id": c.id,
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    },
                    "type": "function",
                })
            messages.append({"role": "assistant", "content": current_content, "tool_calls": tc_reqs})
            # Add the tools output right below the request message
            messages.extend(tools_out)

            fc_list = []
            full_calls = {}
            already_processed_some_calls = True
            current_content = ""

            if response_d.content:
                yield response_d.content, True, False
            else:
                yield "", True, False  # Signal tool calls even without content
        else:
            if response_d.content:
                current_content += response_d.content
                yield response_d.content, False, do_stop

        if do_stop:
            if current_content and not already_processed_some_calls:
                messages.append({"role": "assistant", "content": current_content})
            yield "", False, True

#==================================================================
async def completion_with_tools_async(
    wrap,
    model: str,
    temperature: float,
    instructions: str,
    role_and_content_msgs: list,
    exclude_tools: Optional[list] = None,
    tools_user_data: Optional[str] = None,
    stream: bool = False,
    ) -> AsyncGenerator[str, None]:
    """
    Create a completion with tools, async version.
    """
    logmsg("[completion_with_tools_async] Starting streaming path")

    # Get the tools list
    tools = get_tools(exclude_tools)

    # Create the messages list
    messages = prepare_messages(instructions, role_and_content_msgs)

    # Create the completion
    response = await wrap.CreateCompletion(
        model=model,
        messages=messages,
        tools=tools,
        temperature=temperature,
        stream=stream)

    if stream:
        # Streaming path
        async for content, has_tool_calls, is_done in handle_stream(response, wrap, messages, tools_user_data):
            if content:
                yield content
            if is_done:
                break
    else:
        # Non-streaming path
        logmsg("[completion_with_tools_async] Non-streaming path")
        message = response.choices[0].message
        if message.content:
            logmsg("[completion_with_tools_async] No tool calls, yielding message content")
            yield message.content
        elif message.tool_calls:
            logmsg("[completion_with_tools_async] Processing tool calls")
            tools_out = await apply_tools(message.tool_calls, wrap, tools_user_data)
            # Create a new completion with the tool results
            new_messages = messages.copy()
            new_messages.append({
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    } for tc in message.tool_calls
                ]
            })
            for i, tool_out in enumerate(tools_out):
                new_messages.append({
                    "role": "tool",
                    "tool_call_id": message.tool_calls[i].id,
                    "name": message.tool_calls[i].function.name,
                    "content": str(tool_out)
                })

            # Make the second completion call
            logmsg("[completion_with_tools_async] Making second completion call")
            second_response = await wrap.CreateCompletion(
                model=model,
                messages=new_messages,
                temperature=temperature,
                stream=stream)

            second_message = second_response.choices[0].message
            yield second_message.content

#==================================================================
async def completion_with_tools(
        wrap: OpenAIWrapper,
        model: str,
        temperature: float,
        instructions: str,
        role_and_content_msgs: List[Dict[str, str]],
        exclude_tools=None,
        tools_user_data=None,
        stream=False) -> AsyncGenerator[str, None]:
    """Async version of completion_with_tools that uses async/await throughout"""
    return completion_with_tools_async(
        wrap=wrap,
        model=model,
        temperature=temperature,
        instructions=instructions,
        role_and_content_msgs=role_and_content_msgs,
        exclude_tools=exclude_tools,
        tools_user_data=tools_user_data,
        stream=stream)

def get_tools(exclude_tools=None):
    tools = []
    for item in AssistTools.tool_items:
        if exclude_tools is None or item.name not in exclude_tools:
            tools.append({"type": "function", "function": item.definition})
    return tools

def prepare_messages(instructions: str, role_and_content_msgs: list) -> list:
    """Prepare messages for completion."""
    messages = []
    if instructions:
        messages.append({
            "role": "system",
            "content": instructions
        })
    messages.extend(role_and_content_msgs)
    return messages
