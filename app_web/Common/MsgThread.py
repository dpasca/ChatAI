#==================================================================
# MsgThread.py
#
# Author: Davide Pasca, 2024/02/12
# Description:
#==================================================================

import json
import time
from .logger import *
from pydantic import BaseModel
from typing import List, Optional, Any
from .OpenAIWrapper import OpenAIWrapper
from . import AnnotUtils

META_TAG = "message_meta"

def stripUserMessageMeta(msg_with_meta):
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

#==================================================================
def MessageToLocMessage(wrap, message, make_file_url):
    result = {
        "src_id": message.id,
        "created_at": message.created_at,
        "role": message.role,
        "content": []
    }
    for content in message.content:
        if content.type == "text":

            # Strip the message meta if it's a user message
            out_msg = content.text.value
            if message.role == "user":
                out_msg = stripUserMessageMeta(out_msg)

            # Apply whatever annotations may be there
            if content.text.annotations is not None:

                logmsg(f"Annotations: {content.text.annotations}")

                out_msg = AnnotUtils.ResolveImageAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations,
                    make_file_url=make_file_url)

                out_msg = AnnotUtils.ResolveCiteAnnotations(
                    out_msg=out_msg,
                    annotations=content.text.annotations,
                    wrap=wrap)

                out_msg = AnnotUtils.StripEmptyAnnotationsBug(out_msg)

            result["content"].append({
                "value": out_msg,
                "type": content.type
            })
        elif content.type == "image_file":
            # Append the content with the image URL
            result["content"].append({
                "value": make_file_url(content.image_file.file_id, "image.png"),
                "type": content.type
            })
        else:
            result["content"].append({
                "value": "<Unknown content type>",
                "type": "text"
            })
    return result


# Starts loading a thread, keeps a local version of the messages
class MsgThread(BaseModel):
    wrap: OpenAIWrapper
    thread_id: str
    messages: List[str] = []
    judge: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def create_thread(cls, wrap: OpenAIWrapper):
        oai_thread = wrap.CreateThread()
        return cls(wrap=wrap, thread_id=oai_thread.id)

    @classmethod
    def from_thread_id(cls, wrap: OpenAIWrapper, thread_id: str):
        try:
            # Attempt to retrieve the thread; assuming RetrieveThread returns the thread or None
            th = wrap.RetrieveThread(thread_id)
            if th is not None:
                return cls(wrap=wrap, thread_id=thread_id)
            else:
                logerr(f"Thread with ID {thread_id} not found.")
                return None
        except Exception as e:
            logerr(f"Failed to retrieve thread with ID {thread_id}: {e}")
            return None

    def to_json(self):
        # Convert messages to a serializable format
        serializable_messages = [self.message_to_dict(m) for m in self.messages]
        return json.dumps({
            'thread_id': self.thread_id,
            'messages': serializable_messages})

    def message_to_dict(self, message):
        # Convert a message object to a dictionary
        return {
            'src_id': message['src_id'],
            'created_at': message['created_at'],
            'role': message['role'],
            'content': message['content'],
        }

    def serialize_data(self):
        return self.to_json()

    def deserialize_data(self, data):
        attrs = json.loads(data)
        if attrs['thread_id'] != self.thread_id:
            logerr(f"Thread ID mismatch: {attrs['thread_id']} != {self.thread_id}. Ignoring.")

        self.thread_id = attrs['thread_id']
        self.messages = attrs['messages']

    def fetch_new_messages(self, make_file_url):
        new_oai_messages = self.wrap.ListAllThreadMessages(
            thread_id=self.thread_id,
            order="asc",
            after=self.messages[-1]['src_id'] if self.messages else ''
        )
        if new_oai_messages:
            new_messages = [MessageToLocMessage(self.wrap, m, make_file_url) for m in new_oai_messages]
            self.messages.extend(new_messages)

        return len(new_oai_messages)
 
    def create_judge(self, model, temperature):
        from .ConvoJudge import ConvoJudge
        self.judge = ConvoJudge(model=model, temperature=temperature)
        for msg in self.messages:
            self.judge.AddMessage(msg)

    def gen_fact_check(self, tools_user_data=None):
        return self.judge.GenFactCheck(self.wrap, tools_user_data)

    def add_message(self, msg):
        self.messages.append(msg)
        if self.judge:
            self.judge.AddMessage(msg)

