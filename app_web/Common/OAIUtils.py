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
def apply_tools(response_msg, wrap, tools_user_data) -> list:
    calls = response_msg.tool_calls
    logmsg(f"Tool calls: {calls}")
    # Check if the model wanted to call a function
    if not calls:
        return []

    messages = []
    # Extend conversation with assistant's reply
    messages.append(response_msg)

    # Process each tool/function call
    for call in calls:
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

        # Extend conversation with function response
        messages.append({
            "tool_call_id": call.id,
            "role": "tool",
            "name": name,
            "content": json.dumps(function_response),
        })

    return messages

#==================================================================
def completion_with_tools(
        wrap: OpenAIWrapper,
        model : str,
        temperature : float,
        instructions : str,
        role_and_content_msgs : List[Dict[str, str]],
        tools_user_data=None,
        stream=False,
        ) -> Iterator[str]:

    # Setup the tools
    tools = []
    #tools.append({"type": "code_interpreter"})
    #tools.append({"type": "retrieval"})
    for item in AssistTools.tool_items:
        if not item.requires_assistant:
            tools.append({ "type": "function", "function": item.definition })

    messages = [
        {"role": "system", "content": instructions},
    ]
    messages += role_and_content_msgs

    if not stream:
        # Generate the first response
        response = wrap.CreateCompletion(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            stream=stream,
        )

        # See if there are any tools to apply
        if (new_messages := apply_tools(response.choices[0].message, wrap, tools_user_data)):
            logmsg(f"Applying tools: {new_messages}")
            messages += new_messages
            logmsg(f"New conversation with tool answers: {messages}")
            # Post-function-call conversation
            pt_response = wrap.CreateCompletion(
                model=model,
                temperature=temperature,
                messages=messages,
            )
            yield pt_response.choices[0].message.content
        else:
            logmsg(f"Yielding response: {response.choices[0].message.content}")
            yield response.choices[0].message.content
    else:
        # Generate the first response
        logmsg(f"Starting stream")
        stream_response = wrap.CreateCompletion(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            stream=stream,
        )

        logmsg(f"Looping through stream")
        for response in stream_response:  # Process each streamed response
            # Process tools and generate new messages
            new_messages = apply_tools(response.choices[0].delta, wrap, tools_user_data)
            logmsg(f"Applied tools: {response} -> {new_messages}")
            messages += new_messages

            if new_messages:  # Only update if new messages from tools
                # Update the conversation for the next stream iteration
                pt_stream_response = wrap.CreateCompletion(
                    model=model,
                    temperature=temperature,
                    messages=messages,
                    tools=tools,
                    stream=True,  # Now handling streaming manually
                )
                for pt_response in pt_stream_response:
                    logmsg(f"Yielding response: {pt_response.choices[0].delta.content}")
            else:
                logmsg(f"Yielding response: {response.choices[0].delta.content}")
                yield response.choices[0].delta.content

    logmsg("End of stream")

