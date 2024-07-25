#==================================================================
# OAIUtils.py
#
# Author: Davide Pasca, 2024/01/23
# Description: Utilities to manage OpenAI API
#==================================================================

import re
from .logger import *
import json
from .OpenAIWrapper import OpenAIWrapper
from . import AssistTools
from typing import List, Dict, Iterator

#==================================================================
def apply_tools(tool_calls, wrap, tools_user_data) -> list:
    logmsg(f"Tool calls: {tool_calls}")
    messages = []
    # Process each tool/function call
    for call in tool_calls:
        if call.function.name is None:
            logwarn(f"Tool call with missing name: {call}")
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
def handle_stream(response, wrap, messages, tools_user_data):

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
    for response_it in response:
        response_d = response_it.choices[0].delta
        #logmsg(f"** response_it: {response_it}")

        # NOTE: Useful but not sufficient !
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

            yield response_d.content, True, False
        else:
            yield response_d.content, False, do_stop

#==================================================================
def completion_with_tools(
        wrap: OpenAIWrapper,
        model: str,
        temperature: float,
        instructions: str,
        role_and_content_msgs: List[Dict[str, str]],
        exclude_tools=None,
        tools_user_data=None,
        stream=False) -> Iterator[str]:

    tools = []
    for item in AssistTools.tool_items:
        if exclude_tools is None or item.name not in exclude_tools:
            tools.append({"type": "function", "function": item.definition})

    messages = [
        {"role": "system", "content": instructions},
    ] + role_and_content_msgs

    #=== Handle the non-streaming path (easy)
    def non_stream_path(messages):
        res = wrap.CreateCompletion(model=model, temperature=temperature, messages=messages, tools=tools, stream=False)
        #logmsg(f"Completion Response (NON Stream): {res}")

        # If there are no tool calls, just pass the content of the message
        res_msg = res.choices[0].message
        if not res_msg.tool_calls:
            yield res_msg.content
        else:
            # Proceed to call the tools
            tools_out = apply_tools(res_msg.tool_calls, wrap, tools_user_data)
            messages.append(res_msg)  # Add the response message to the conversation
            messages += tools_out  # Add the messages from the tools
            # Call the completion again now that we have the tools output
            res2 = wrap.CreateCompletion(
                model=model,
                temperature=temperature,
                messages=messages,
                tools=None,
                stream=False)
            # Pass the content of the response
            yield res2.choices[0].message.content

    if not stream:
        yield from non_stream_path(messages=messages)
        return

    #===
    did_call_tools = False
    did_generate_after_tools_out = False
    max_loops = 4

    for i in range(max_loops):
        response = wrap.CreateCompletion(
            model=model,
            temperature=temperature,
            messages=messages,
            tools= tools if not did_call_tools else None,
            stream=stream,
        )
        #logmsg(f"Completion with tools Response: {response}")

        content = ""
        for part, did_call_tools_now, do_stop in handle_stream(response, wrap, messages, tools_user_data):
            if part is not None:
                if part == '':
                    content += '\n'
                else:
                    content += part
                yield part

        did_generate_after_tools_out = (
            did_generate_after_tools_out or
                (did_call_tools and not did_call_tools_now))

        did_call_tools = did_call_tools or did_call_tools_now

        if do_stop and (did_generate_after_tools_out or not did_call_tools):
            break

