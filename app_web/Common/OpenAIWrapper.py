#==================================================================
# OpenAIWrapper.py - OpenAI API wrapper
#
# Author: Davide Pasca, 2023/12/23
# Desc: A simple wrapper for OpenAI API
#==================================================================
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from typing import Dict, List, Any, Optional, Union, AsyncGenerator, TypeVar
import asyncio

T = TypeVar('T')

class OpenAIWrapper:
    def __init__(self, api_key):
        # Create both sync and async clients
        # We keep the sync client for backward compatibility with other APIs
        self.client = OpenAI(api_key=api_key)
        self.async_client = AsyncOpenAI(api_key=api_key)

    #==================================================================
    async def CreateCompletion(
            self, 
            model: str,
            messages: List[Dict[str, str]],
            temperature: float = 0.7,
            tools: Optional[List[Dict[str, Any]]] = None,
            stream: bool = False) -> Any:  # Return type is Any to handle both streaming and non-streaming
        """Async version of CreateCompletion"""
        # Cast the parameters to Any to bypass type checking
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": "auto" if tools else None,
            "stream": stream
        }
        
        # The OpenAI API returns either a ChatCompletion or a streamable response
        return await self.async_client.chat.completions.create(**params)

    # Alias for backward compatibility
    CreateCompletionAsync = CreateCompletion

    #==== Files
    async def GetFileContent(self, file_id):
        """Async version of GetFileContent"""
        return await self.async_client.files.content(file_id)

    # Alias for backward compatibility
    GetFileContentAsync = GetFileContent
