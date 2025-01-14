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
from typing import List, Dict, Union, Any, AsyncGenerator, Iterator
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
def apply_tools(tool_calls, wrap, tools_user_data) -> list:
    logmsg(f"Tool calls: {tool_calls}")
    messages = []
    # Process each tool/function call
    for call in tool_calls:
        if call.function.name is None:
            logwarn(f"Tool call with missing name: {call}")
            continue

        # Special case for OpenAI's bug
        if call.function.name == "multi_tool_use.parallel":
            try:
                messages.extend(handle_multi_tool_use(call, tools_user_data))
            except Exception as e:
                logerr(f"Error handling multi_tool_use.parallel: {e}")
            continue

        name = call.function.name
        try:
            args = json.loads(call.function.arguments) if call.function.arguments else {}
        except:
            logerr(f"Tool call with invalid arguments: {call}")
            continue

        logmsg(f"Tool call: {name}({args})")

        # Add wrap and tools_user_data to the arguments
        #args["wrap"] = wrap
        args["tools_user_data"] = tools_user_data

        # Look up the function in the dictionary and call it
        if name in AssistTools.tool_items_dict:
            function_response = AssistTools.tool_items_dict[name].function(args)
        else:
            function_response = AssistTools.fallback_tool_function(name, args)

        #logmsg(f"Tool respose: {function_response}")

        content = None
        try:
            content = json.dumps(function_response)
        except:
            content = function_response.response

        # Extend conversation with function response
        messages.append({
            "tool_call_id": call.id,
            "role": "tool",
            "name": name,
            "content": content,
        })

    return messages

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

    # Process the stream of responses
    async for response_it in response:
        response_d = response_it.choices[0].delta

        do_stop = (response_d.content is None and
                   response_d.tool_calls is None and
                   response_it.choices[0].finish_reason != "tool_calls")

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
            tools_out = apply_tools(fc_list, wrap, tools_user_data)

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
            messages.append({"role": "assistant", "tool_calls": tc_reqs})
            # Add the tools output right below the request message
            messages += tools_out

            fc_list = []
            full_calls = {}
            already_processed_some_calls = True

            if response_d.content:
                yield response_d.content, True, False
        else:
            if response_d.content:
                yield response_d.content, False, do_stop

#==================================================================
async def completion_with_tools_async(
        wrap: OpenAIWrapper,
        model: str,
        temperature: float,
        instructions: str,
        role_and_content_msgs: List[Dict[str, str]],
        exclude_tools=None,
        tools_user_data=None,
        stream=False) -> AsyncGenerator[str, None]:

    # Get available tools
    tools = get_tools(exclude_tools)
    messages = prepare_messages(instructions, role_and_content_msgs)

    if not stream:
        logmsg("[completion_with_tools_async] Non-streaming path")
        response: Union[ChatCompletion, AsyncGenerator[Dict[str, Any], None]] = await wrap.CreateCompletionAsync(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            stream=False)

        if isinstance(response, AsyncGenerator):
            raise ValueError("Expected ChatCompletion but got AsyncGenerator")

        message = response.choices[0].message
        if not hasattr(message, 'tool_calls') or not message.tool_calls:
            logmsg("[completion_with_tools_async] No tool calls, yielding message content")
            content = message.content or ""
            if instructions and "Reply UNIQUELY with a pure raw JSON string" in instructions:
                try:
                    # Try to parse as JSON to validate
                    json.loads(content)
                    yield content
                except json.JSONDecodeError:
                    # If not valid JSON, try to extract the first JSON object
                    from .ConvoJudge import ConvoJudge
                    fixed_response = ConvoJudge.extract_first_json_object(content)
                    if fixed_response:
                        yield json.dumps(fixed_response)
                    else:
                        yield "{}"
            else:
                yield content
            return

        logmsg("[completion_with_tools_async] Processing tool calls")
        tools_out = apply_tools(message.tool_calls, wrap, tools_user_data)
        msg_dict = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                } for tc in message.tool_calls
            ]
        }
        messages.append(msg_dict)
        messages.extend(tools_out)

        logmsg("[completion_with_tools_async] Making second completion call")
        response2: Union[ChatCompletion, AsyncGenerator[Dict[str, Any], None]] = await wrap.CreateCompletionAsync(
            model=model,
            temperature=temperature,
            messages=messages,
            stream=False)

        if isinstance(response2, AsyncGenerator):
            raise ValueError("Expected ChatCompletion but got AsyncGenerator")

        # For fact-checking, we need to ensure we get a valid JSON response
        content = response2.choices[0].message.content or ""
        if instructions and "Reply UNIQUELY with a pure raw JSON string" in instructions:
            try:
                # Try to parse as JSON to validate
                json.loads(content)
                yield content
            except json.JSONDecodeError:
                # If not valid JSON, try to extract the first JSON object
                from .ConvoJudge import ConvoJudge
                fixed_response = ConvoJudge.extract_first_json_object(content)
                if fixed_response:
                    yield json.dumps(fixed_response)
                else:
                    yield "{}"
        else:
            yield content
        return

    logmsg("[completion_with_tools_async] Starting streaming path")

    # Only make one call initially
    params = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
        "stream": True
    }

    # Only include tools in the first call
    if tools:
        params["tools"] = tools

    response = await wrap.CreateCompletionAsync(**params)

    did_call_tools = False
    async for part, tools_called, stream_do_stop in handle_stream(response, wrap, messages, tools_user_data):
        if part:
            yield part

        if tools_called:
            did_call_tools = True
            # Make one more call without tools to get the final response
            final_response = await wrap.CreateCompletionAsync(
                model=model,
                temperature=temperature,
                messages=messages,
                stream=True
            )
            async for final_part, _, final_stop in handle_stream(final_response, wrap, messages, tools_user_data):
                if final_part:
                    yield final_part
            break

        if stream_do_stop and not did_call_tools:
            break

def completion_with_tools(
        wrap: OpenAIWrapper,
        model: str,
        temperature: float,
        instructions: str,
        role_and_content_msgs: List[Dict[str, str]],
        exclude_tools=None,
        tools_user_data=None,
        stream=False) -> Iterator[str]:

    logmsg("[completion_with_tools] Starting")

    try:
        logmsg("[completion_with_tools] Trying to get running loop")
        loop = asyncio.get_running_loop()
        logmsg("[completion_with_tools] In async context")

        # Create a new event loop for synchronous execution
        sync_loop = asyncio.new_event_loop()

        def run_sync():
            asyncio.set_event_loop(sync_loop)
            result_queue = queue.Queue()

            async def process_generator():
                try:
                    async for msg in completion_with_tools_async(
                        wrap, model, temperature, instructions,
                        role_and_content_msgs, exclude_tools,
                        tools_user_data, stream):
                        result_queue.put(('msg', msg))
                    result_queue.put(('done', None))
                except Exception as e:
                    logerr(f"[process_generator] Error: {str(e)}")
                    result_queue.put(('error', e))

            sync_loop.run_until_complete(process_generator())
            return result_queue

        # Run in a separate thread to avoid event loop conflicts
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result_queue = pool.submit(run_sync).result()

        # Yield results from the queue
        while True:
            msg_type, msg = result_queue.get()
            if msg_type == 'error':
                raise msg
            elif msg_type == 'done':
                break
            else:
                yield msg

    except RuntimeError:
        logmsg("[completion_with_tools] No running loop, creating new one")
        loop = get_or_create_eventloop()
        result_queue = queue.Queue()

        async def consume_generator() -> None:
            try:
                async for msg in completion_with_tools_async(
                    wrap, model, temperature, instructions,
                    role_and_content_msgs, exclude_tools,
                    tools_user_data, stream):
                    if stream:
                        logmsg(f"[consume_generator] Streaming message: {msg[:100]}...")
                        result_queue.put(('msg', msg))
                    else:
                        logmsg(f"[consume_generator] Got message: {msg[:100]}...")
                        result_queue.put(('msg', msg))
                        break  # Only take the first message for non-streaming
                result_queue.put(('done', None))
            except Exception as e:
                logerr(f"[consume_generator] Error: {str(e)}")
                result_queue.put(('error', e))

        loop.run_until_complete(consume_generator())

        # For streaming mode, yield each message as it comes
        if stream:
            while True:
                msg_type, msg = result_queue.get()
                if msg_type == 'error':
                    raise msg
                elif msg_type == 'done':
                    break
                else:
                    yield msg
        # For non-streaming mode, return the single message
        else:
            msg_type, msg = result_queue.get()
            if msg_type == 'error':
                raise msg
            elif msg_type == 'msg':
                yield msg

def get_tools(exclude_tools=None):
    tools = []
    for item in AssistTools.tool_items:
        if exclude_tools is None or item.name not in exclude_tools:
            tools.append({"type": "function", "function": item.definition})
    return tools

def prepare_messages(instructions: str, role_and_content_msgs: List[Dict[str, str]]):
    return [
        {"role": "system", "content": instructions},
    ] + role_and_content_msgs

