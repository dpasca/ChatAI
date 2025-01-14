#==================================================================
# OpenAIWrapper.py - OpenAI API wrapper
#
# Author: Davide Pasca, 2023/12/23
# Desc: A simple wrapper for OpenAI API
#==================================================================
from openai import OpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from typing import Dict, List, Any, Optional, Union, AsyncGenerator, TypeVar

T = TypeVar('T')

class OpenAIWrapper:
    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)

    #==================================================================
    # Async versions of the API calls
    async def CreateCompletionAsync(
            self, 
            model: str,
            messages: List[Dict[str, str]],
            temperature: float = 0.7,
            tools: Optional[List[Dict[str, Any]]] = None,
            stream: bool = False) -> Union[ChatCompletion, AsyncGenerator[Dict[str, Any], None]]:
        """Async version of CreateCompletion that matches the sync version's interface"""
        # Cast the parameters to Any to bypass type checking
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": "auto" if tools else None,
            "stream": stream
        }
        # For streaming, we need to handle the response differently
        response = self.client.chat.completions.create(**params)
        if stream:
            async def response_generator() -> AsyncGenerator[Dict[str, Any], None]:
                for chunk in response:
                    yield chunk
            return response_generator()
        else:
            return response

    #==================================================================
    # Sync version for backward compatibility
    def CreateCompletion(self, model, messages, temperature=0.7, tools=None, stream=False):
        """Synchronous version of CreateCompletion for backward compatibility"""
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": "auto" if tools else None,
            "stream": stream
        }
        return self.client.chat.completions.create(**params)

    #==== Files
    def GetFileContent(self, file_id):
        return self.client.files.content(file_id)
