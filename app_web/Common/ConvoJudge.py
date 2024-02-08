#==================================================================
# ConvoJudge.py
#
# Author: Davide Pasca, 2024/01/23
# Description: A judge for conversations
#==================================================================

import json
from .logger import *
from .OpenAIWrapper import OpenAIWrapper
from . import AssistTools

class ConvoJudge:
    def __init__(self, model, temperature):
        self.srcMessages = []
        self.model = model
        self.temperature = temperature

        CONVO_DESC = """
You will receive a conversation between User and Assistant (a thid party assistant, not you!)
in the format:
- SUMMARY (optional): [Summary of the conversation so far]
- Message: <id> by <role>:\n<content>
- Message: ...
"""

        self.instructionsForSummary = CONVO_DESC + """
Output a synthesized summary of the conversation in less than 100 words.
Do not prefix with "Summary:" or anything like that, it's implied. 
Output must be optimized for a LLM, human-readability is not important.

Rules for output:
1. Retain key data (names, dates, numbers, stats) in summaries.
2. If large data blocks, condense to essential information only.
"""

        self.instructionsForCritique = CONVO_DESC + """
Assistant is a mind-reading AI based on an LLM. Its goal is to provide total delegation
of the tasks required towards the user's goal.

Generate a critique where Assistant lacked and could have done better towards the goal
of minimizing the user's effort to reach their goal. Be synthetic, direct and concise.
This critique will be related to Assistant, for it to act upon it and improve.
Output must be optimized for a LLM, human-readability not a factor.
Reply in the following format:
{
    "text": <critique text>,
    "requires_action": <true/false>
}
"""

        self.instructionsForFactCheck = CONVO_DESC + """
You are a fact-checker that performs in-depth research on
any given statement of the conversation described above.
Provide a rebuttal with details, clarifications, references,
opposing views and counter-arguments.
Be concise, respond "robotically" but be detailed, exacting, precise, fastidious.
When refuting, provide the reasoning and calculations behind your rebuttal.
Use the web search tool as much as possible.
Use the tool get_user_local_time when the topic of time and dates is involved.
Use all the tools at your disposal as much as possible, they provide accuracy
and your foremost goal is to provide accuracy and correctness.
Ignore checking on political topics.
Beware of the fact that the assistant may have access to information
may not be aware of, such as the user's background, location, etc.

## Output format
You MUST reply in JSON format, no exceptions. Example:
---
{
  "fact_check": [
    {
      "role": <role of the assertion>,
      "msg_id": <message id>,
      "applicable": <true/false>,
      "correctness": <degree of correctness, 0 to 5>
      "rebuttal": <extremely short rebuttal, inclusive of references>,
      "links": [
        {
          "title": <title of the link>,
          "url": <url of the link>
        }
      ]
    }
  ]
}
---
- Do not produce "rebuttal" or "links" if "applicable" is false.
- Any URL link must exist and must be valid.
- Generate only 1 full piece of JSON output.
"""

    def AddMessage(self, srcMsg):
        self.srcMessages.append(srcMsg)

    def ClearMessages(self):
        self.srcMessages = []

    def makeConvoMessage(self, src_id, role, content):
        out = f"- Message: {src_id} by {role}:\n"
        for cont in content:
            out += cont['value'] + "\n"
        return out

    def buildConvoString(self, maxMessages):
        convo = ""
        n = len(self.srcMessages)
        staIdx = max(0, n - maxMessages)
        for index in range(staIdx, n):
            srcMsg = self.srcMessages[index]
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])
        return convo

    @staticmethod
    def apply_tools(response, tools_user_data) -> list:
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

            # Add the tools_user_data to the arguments
            args["tools_user_data"] = tools_user_data

            # Look up the function in the dictionary and call it
            if name in AssistTools.ToolActions:
                function_response = AssistTools.ToolActions[name](args)
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

    def genCompletion(self, wrap, instructions, convo, tools_user_data=None):
        # Setup the tools
        tools = []
        #tools.append({"type": "code_interpreter"})
        #tools.append({"type": "retrieval"})
        for _, defn in AssistTools.ToolDefinitions.items():
            tools.append({ "type": "function", "function": defn })

        #print(f"Sending Conversation:\n{convo}\n------")
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user",   "content": convo}
        ]
        # Generate the first response
        response = wrap.CreateCompletion(
            model=self.model,
            temperature=self.temperature,
            messages=messages,
            tools=tools,
        )

        # See if there are any tools to apply
        if (new_messages := ConvoJudge.apply_tools(response, tools_user_data)):
            logmsg(f"Applying tools: {new_messages}")
            messages += new_messages
            logmsg(f"New conversation with tool answers: {messages}")
            # Post-function-call conversation
            post_tool_response = wrap.CreateCompletion(
                model=self.model,
                temperature=self.temperature,
                messages=messages,
            )
            return post_tool_response.choices[0].message.content

        return response.choices[0].message.content

    def GenSummary(self, wrap):
        convo = self.buildConvoString(1000)
        return self.genCompletion(wrap, self.instructionsForSummary, convo)

    def GenCritique(self, wrap):
        convo = self.buildConvoString(1000)
        return self.genCompletion(wrap, self.instructionsForCritique, convo)

    def GenFactCheck(self, wrap, tools_user_data):
        # The conversation is split into two parts:
        # - the first part is the context, which is not fact-checked
        # - the second part is the actual fact-checking
        CONTEXT_MESSAGES = 8
        FACT_CHECK_MESSAGES = 2
        convo = "## Begin context for fact-checking. Context-only DO NOT fact-check\n"
        n = len(self.srcMessages)
        staIdx = max(0, n - CONTEXT_MESSAGES)
        for index in range(staIdx, n):
            srcMsg = self.srcMessages[index]
            if index == (n-FACT_CHECK_MESSAGES):
                convo += "## Begin statements to fact-check. DO fact-check below\n"
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])

        return self.genCompletion(wrap, self.instructionsForFactCheck, convo, tools_user_data)

