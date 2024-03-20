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
        args = json.loads(call.function.arguments) if call.function.arguments else {}

        logmsg(f"Tool call: {name}({args})")

        # Add wrap and tools_user_data to the arguments
        args["wrap"] = wrap
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
def handle_non_stream(response, wrap, model, temperature, messages, tools_user_data):
    # Handle the non-stream case
    response_msg = response.choices[0].message
    if response_msg.tool_calls:
        tools_out = apply_tools(response_msg.tool_calls, wrap, tools_user_data)
        messages.append(response_msg)  # Add the response message to the conversation
        messages += tools_out  # Add the messages from the tools
        pt_response = wrap.CreateCompletion(
            model=model,
            temperature=temperature,
            messages=messages,
        )
        return pt_response.choices[0].message.content
    else:
        return response_msg.content

#==================================================================
def handle_stream(response, wrap, model, temperature, messages, tools_user_data):

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

    # Process the stream of responses
    for response_it in response:
        response_d = response_it.choices[0].delta

        # Do we have tool calls ?
        if response_d.tool_calls:
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
            tools_out = apply_tools(fc_list, wrap, tools_user_data)

            # Build the message that details the requested too calls
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
            # Post-tool call completion
            pt_response = wrap.CreateCompletion(
                model=model,
                temperature=temperature,
                messages=messages,
                stream=True)

            for pt_response_it in pt_response:
                yield pt_response_it.choices[0].delta.content
        else:
            yield response_d.content

#==================================================================
def completion_with_tools(
        wrap: OpenAIWrapper,
        model: str,
        temperature: float,
        instructions: str,
        role_and_content_msgs: List[Dict[str, str]],
        tools_user_data=None,
        stream=False) -> Iterator[str]:

    tools = []
    for item in AssistTools.tool_items:
        # NOTE: "assistant" here means our agent system (e.g. research asssitant),
        #  not OpenAI's high level API
        if not item.requires_assistant:
            tools.append({"type": "function", "function": item.definition})

    messages = [
        {"role": "system", "content": instructions},
    ] + role_and_content_msgs

    response = wrap.CreateCompletion(
        model=model,
        temperature=temperature,
        messages=messages,
        tools=tools,
        stream=stream,
    )

    if not stream:
        yield handle_non_stream(response, wrap, model, temperature, messages, tools_user_data)
    else:
        yield from handle_stream(response, wrap, model, temperature, messages, tools_user_data)

