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
def apply_tools(response, wrap, tools_user_data) -> list:
    response_msg = response.choices[0].message
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
        name = call.function.name
        args = json.loads(call.function.arguments)

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
        if (new_messages := apply_tools(response, wrap, tools_user_data)):
            logmsg(f"Applying tools: {new_messages}")
            messages += new_messages
            logmsg(f"New conversation with tool answers: {messages}")
            # Post-function-call conversation
            post_tool_response = wrap.CreateCompletion(
                model=model,
                temperature=temperature,
                messages=messages,
            )
            return post_tool_response.choices[0].message.content

        return response.choices[0].message.content
    else:
        # Generate the first response
        stream_response = wrap.CreateCompletion(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            stream=stream,
        )

        for response in stream_response:  # Process each streamed response
            if 'choices' in response and response['choices']:
                # Process tools and generate new messages
                new_messages = apply_tools(response, wrap, tools_user_data)
                logmsg(f"Applying tools: {new_messages}")
                messages += new_messages

                # Yield the current part of the response
                yield response.choices[0].message.content

                if new_messages:  # Only update if new messages from tools
                    # Update the conversation for the next stream iteration
                    response = wrap.CreateCompletion(
                        model=model,
                        temperature=temperature,
                        messages=messages,
                        tools=tools,
                        stream=False,  # Now handling streaming manually
                    )
                    if 'choices' in response and response['choices']:
                        yield response.choices[0].message.content

