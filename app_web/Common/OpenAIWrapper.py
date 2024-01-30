#==================================================================
# OpenAIWrapper.py - OpenAI API wrapper
#
# Author: Davide Pasca, 2023/12/23
# Desc: A simple wrapper, since Assistant API is in beta
#==================================================================
from openai import OpenAI
from typing import Tuple

#==================================================================
class OpenAIWrapper:
    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)

    #==================================================================
    # Assistants
    def CreateAssistant(self, name, instructions, tools, model):
        return self.client.beta.assistants.create(
            name=name,
            instructions=instructions,
            tools=tools,
            model=model)

    def UpdateAssistant(self, assistant_id, instructions, tools, model):
        return self.client.beta.assistants.update(
            assistant_id=assistant_id,
            instructions=instructions,
            tools=tools,
            model=model)

    def ListAssistants(self):
        return self.client.beta.assistants.list()

    # Helper to create or update an assistant
    # Returns assistant, was_created
    def CreateOrUpdateAssistant(self, name, instructions, tools, model) -> Tuple[object, bool]:
        assists = self.ListAssistants()
        for assist in assists:
            if assist.name == name:
                return self.UpdateAssistant(assist.id, instructions, tools, model), False
        return self.CreateAssistant(name, instructions, tools, model), True

    #==== Threads
    def CreateThread(self):
        return self.client.beta.threads.create()

    def RetrieveThread(self, thread_id):
        return self.client.beta.threads.retrieve(thread_id)

    """
    def ListThreadMessages(self, thread_id, order='asc', after=''):
            return self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=100,
                order=order,
                after=after).data
    """

    def ListAllThreadMessages(self, thread_id, order='asc', after='', before=''):
        """Return all messages in a thread, in order, as a list."""
        all_msgs = []
        while True:
            msgs = self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=100,
                order=order,
                after=after,
                before=before)

            if len(msgs.data) == 0:
                break

            all_msgs.extend(msgs.data)

            if order == "asc":
                after = msgs.data[-1].id
            else:
                before = msgs.data[-1].id

        return all_msgs

    def CreateMessage(self, thread_id, role, content):
        return self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role=role,
            content=content)

    #==== Runs
    def CreateRun(self, thread_id, assistant_id):
        return self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id)

    def ListRuns(self, thread_id, limit):
        return self.client.beta.threads.runs.list(thread_id=thread_id, limit=limit)

    def RetrieveRun(self, thread_id, run_id):
        return self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)

    def CancelRun(self, thread_id, run_id):
        return self.client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run_id)

    def SubmitToolsOutputs(self, thread_id, run_id, tool_outputs):
        return self.client.beta.threads.runs.submit_tool_outputs(
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=tool_outputs)

    #==== Files
    def GetFileContent(self, file_id):
        return self.client.files.content(file_id)

    #==== Completions
    def CreateCompletion(self, model, messages, temperature=0.7, tools=None):
        return self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            tools=tools,
            tool_choice="auto" if tools else None)
