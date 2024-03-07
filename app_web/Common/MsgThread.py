#==================================================================
# MsgThread.py
#
# Author: Davide Pasca, 2024/02/12
# Description:
#==================================================================

import json
import time
import uuid
from .logger import *
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from .OpenAIWrapper import OpenAIWrapper

META_TAG = "message_meta"

class MsgThread(BaseModel):
    wrap: OpenAIWrapper
    thread_id: str
    messages: list = []
    judge: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def create_thread(cls, wrap: OpenAIWrapper):
        return cls(wrap=wrap, thread_id=f"thread_{uuid.uuid4()}")

    @classmethod
    def from_thread_id(cls, wrap: OpenAIWrapper, thread_id: str):
        instance = cls(wrap=wrap, thread_id=thread_id)
        # TODO: Fetch the messages from the server
        return instance

    def to_json(self):
        # Convert messages to a serializable format
        serializable_messages = [self.message_to_dict(m) for m in self.messages]
        return json.dumps({
            'thread_id': self.thread_id,
            'messages': serializable_messages})

    @staticmethod
    def instrument_user_message(msg_text):
        return f"<{META_TAG}>\nunix_time: {int(time.time())}\n</{META_TAG}>\n{msg_text}"

    @staticmethod
    def deinstrument_user_message(msg_with_meta):
        msg = msg_with_meta
        begin_tag = f"<{META_TAG}>"
        end_tag = f"</{META_TAG}>"
        end_tag_len = len(end_tag)

        while True:
            start = msg.find(begin_tag)
            if start == -1:
                break
            end = msg.find(end_tag, start)
            if end == -1:
                break

            # Check if the character following the end tag is a newline
            if msg[end + end_tag_len:end + end_tag_len + 1] == "\n":
                msg = msg[:start] + msg[end + end_tag_len + 1:]
            else:
                msg = msg[:start] + msg[end + end_tag_len:]

        return msg


    def message_to_dict(self, message):
        # Convert each content item in the list to its dictionary representation
        content_list = [{'type': c['type'], 'value': c['value']} for c in message['content']]
        return {
            'src_id': message['src_id'],
            'created_at': message['created_at'],
            'role': message['role'],
            'content': content_list  # Now this is always a list of dictionaries
        }

    def is_valid_message(self, message):
        # Check if the message format is correct, including content being a list of dictionaries
        return ('src_id' in message and
                'created_at' in message and
                'role' in message and
                isinstance(message.get('content'), list) and
                all('type' in c and 'value' in c for c in message.get('content', [])))

    def serialize_data(self):
        return self.to_json()

    def deserialize_data(self, data):
        attrs = json.loads(data)
        if attrs['thread_id'] != self.thread_id:
            logerr(f"Thread ID mismatch: {attrs['thread_id']} != {self.thread_id}. Ignoring.")
            return

        self.thread_id = attrs['thread_id']

        # Deserialize the messages if they are in the correct format
        for msg in attrs['messages']:
            if not self.is_valid_message(msg):
                logerr(f"Invalid message format: {msg}. Ignoring.")
                return

        self.messages = attrs['messages']

    def create_judge(self, model, temperature):
        from .ConvoJudge import ConvoJudge
        self.judge = ConvoJudge(model=model, temperature=temperature)
        for msg in self.messages:
            self.judge.AddMessage(msg)

    def gen_fact_check(self, tools_user_data=None):
        return self.judge.GenFactCheck(self.wrap, tools_user_data)

    def create_message(self, role, content) -> dict:
        # Wrap content in a list containing one dictionary
        message = {
            "src_id": f"msg_{uuid.uuid4()}",
            "created_at": time.time(),
            "role": role,
            "content": [{"type": "text", "value": content}]  # Now a list of dictionaries
        }
        self.add_message(message)
        return message

    def update_message(self, src_id, content) -> dict:
        # Find the message with the given src_id and update its content
        for msg in self.messages:
            if msg['src_id'] == src_id:
                msg['content'] = [{"type": "text", "value": content}]
                return msg

        logerr(f"Message with src_id {src_id} not found. Ignoring update.")
        return None

    def create_user_message(self, content) -> dict:
        return self.create_message("user", MsgThread.instrument_user_message(content))

    def create_assistant_message(self, content) -> dict:
        return self.create_message("assistant", content)

    def add_message(self, msg):
        if not self.is_valid_message(msg):
            logerr(f"Invalid message format: {msg}. Ignoring.")
            return

        self.messages.append(msg)
        if self.judge:
            self.judge.AddMessage(msg)

    def make_messages_for_completion(self, max_n) -> List[Dict[str, str]]:
        """Return a list of simplified dictionaries with 'role' and 'content' where content type is 'text',
        maintaining the first KEEP_HEAD_N messages and the last part to ensure the total is <= max_n."""
        KEEP_HEAD_N = 4

        result = []
        #logmsg(f"Messages: {self.messages}")

        # Determine the number of messages to process based on max_n
        total_messages = len(self.messages)
        if total_messages > max_n:
            # If more than max_n messages, keep the first KEEP_HEAD_N and the last max_n - (KEEP_HEAD_N + 1) messages
            messages_to_process = self.messages[:KEEP_HEAD_N] + self.messages[-(max_n - (KEEP_HEAD_N + 1)):]
            # Insert a placeholder message for redacted content
            result.append({"role": "system", "content": "*** CONTENT REDACTED FOR BREVITY ***"})
        else:
            messages_to_process = self.messages

        for msg in messages_to_process:
            # Extract text type contents and append them as simple 'role': 'content' pairs
            for c in msg['content']:
                if c['type'] == 'text':
                    result.append({"role": msg['role'], "content": c['value']})

        # If messages were reduced, ensure the placeholder is correctly positioned
        if total_messages > max_n:
            # Insert the redacted content notice after the first KEEP_HEAD_N entries
            result = (result[:KEEP_HEAD_N] +
                      [{"role": "system", "content": "*** CONTENT REDACTED FOR BREVITY ***"}] +
                      result[KEEP_HEAD_N:])

        return result

    def make_messages_for_display(self):
        # Return the messages, only modifying the user messages to remove the metadata
        result = []
        for msg in self.messages:
            # Check if it's a user message and remove metadata
            if msg['role'] == 'user':
                cleaned_content = []
                for c in msg['content']:
                    if c['type'] == 'text':
                        # Remove instrumented meta from the user message
                        cleaned_text = MsgThread.deinstrument_user_message(c['value'])
                        cleaned_content.append({'type': 'text', 'value': cleaned_text})
                    else:
                        # If not text, add as is
                        cleaned_content.append(c)

                result.append({
                    'src_id': msg['src_id'],
                    'created_at': msg['created_at'],
                    'role': msg['role'],
                    'content': cleaned_content
                })
            else:
                # For non-user messages, add as is
                result.append(msg)

        return result

