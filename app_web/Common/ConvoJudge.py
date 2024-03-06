#==================================================================
# ConvoJudge.py
#
# Author: Davide Pasca, 2024/01/23
# Description: A judge for conversations
#==================================================================

import json
from .logger import *
from .OpenAIWrapper import OpenAIWrapper

class ConvoJudge:
    def __init__(self, model, temperature):
        self.srcMessages = []
        self.model = model
        self.temperature = temperature

        def make_header(role_desc):
            return f"""
You are a {role_desc} tasked with evaluating statements from a conversation between
a User and an Assistant (a third-party assistant, not you). The conversation format
is as follows:
- If present, a summary of the conversation.
- Messages identified by an ID and the role of the sender, followed by the message content.
"""

        self.instructionsForSummary = make_header("summarizer") + """
Output a synthesized summary of the conversation in less than 100 words.
Do not prefix with "Summary:" or anything like that, it's implied. 
Output must be optimized for a LLM, human-readability is not important.

Rules for output:
1. Retain key data (names, dates, numbers, stats) in summaries.
2. If large data blocks, condense to essential information only.
"""

        self.instructionsForCritique = make_header("critc") + """
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

        self.instructionsForFactCheck = make_header("fact-checker") + """

## Reply UNIQUELY with a pure raw JSON string, like the template below:

{
  "fact_checks": [
    {
      "role": "<role of the assertion>",
      "msg_id": "<message id>",
      "correctness": <degree of correctness 0 to 5>,
      "rebuttal": "<extremely short rebuttal, inclusive of references>",
      "links": [
        {
          "title": "<title of the link>",
          "url": "<url of the link>"
        }
      ]
     }
  ]
}

## Rules for output

Use the web search tool to scrutinize the statement being questioned.
Use the tool get_user_local_time when the topic of time and dates is involved.
Be concise, exacting, precise, fastidious in your reply.
When refuting, provide the reasoning and calculations behind your rebuttal.
Do not simply say that something is inaccurate, but show the actual reasoning
behind it in the "rebuttal" field.
"""

        self.instructionsForResearch = make_header("researcher") + """
When presented with a search query, use the web search functionalities
to search that query, as well as another variant.
Be concise, don't worry about niceties.
Produce output in markdown, with bullet lists as much as possible.
Always include URLs in your replies.
To establish the user's details, such us time zone and locale, use the
functions get_user_info, get_user_local_time, and similar.

Report essential facts that are relevant to the conversation, e.g.
if the query is about the weather, do report temperature, and
any other stats that you acquired in your research. Repying
with links for the user to do his/her own research should be
the last resort.
When a question has a specific answer, the links are meant as
a potential form of verification, not as the actual answer.
Do not waste the parent assistant's and the user's time by
telling them to follow some links.
"""

    def AddMessage(self, srcMsg):
        self.srcMessages.append(srcMsg)

    def ClearMessages(self):
        self.srcMessages = []

    def makeConvoMessage(self, src_id, role, content):
        out = f"- Message {src_id} by {role}:\n"
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

    def genCompletion(self, wrap, instructions, convo, tools_user_data=None):
        from .OAIUtils import completion_with_tools
        return completion_with_tools(
                wrap=wrap,
                model=self.model,
                temperature=self.temperature,
                instructions=instructions,
                role_and_content_msgs=[{"role": "user", "content": convo}],
                tools_user_data=tools_user_data,
                stream=False)

    def gen_completion_ret_json(self, wrap, instructions, convo, tools_user_data=None):
        response = self.genCompletion(wrap, self.instructionsForFactCheck, convo, tools_user_data)
        logmsg(f"Response: {response}")
        # Handle the GPT-3.5 bug for when the response is more than one JSON object
        fixed_response = ConvoJudge.extract_first_json_object(response)
        logmsg(f"Fixed response: {fixed_response}")
        # Convert the Python dictionary back to a JSON string if needed
        return json.dumps(fixed_response)

    def GenSummary(self, wrap):
        convo = self.buildConvoString(1000)
        return self.genCompletion(wrap, self.instructionsForSummary, convo)

    def GenCritique(self, wrap):
        convo = self.buildConvoString(1000)
        return self.genCompletion(wrap, self.instructionsForCritique, convo)

    @staticmethod
    def extract_first_json_object(response):
        try:
            open_brackets = 0
            json_start = 0
            json_end = 0
            in_string = False
            escape = False

            for i, char in enumerate(response):
                if char == '"' and not escape:
                    in_string = not in_string
                elif char == '\\' and in_string:
                    escape = not escape
                    continue
                elif char == '{' and not in_string:
                    if open_brackets == 0:
                        json_start = i
                    open_brackets += 1
                elif char == '}' and not in_string:
                    open_brackets -= 1
                    if open_brackets == 0:
                        json_end = i + 1
                        break
                if escape:
                    escape = False

            if json_start < json_end:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                return {}
        except Exception as e:
            logerr(f"Error parsing JSON: {e}")
            return {}

    def GenFactCheck(self, wrap, tools_user_data):
        n = len(self.srcMessages)
        if n == 0:
            logmsg("No source messages found")
            return "{}"

        CONTEXT_MESSAGES = 8
        FACT_CHECK_MESSAGES = 2
        convo = ""
        staIdx = max(0, n - CONTEXT_MESSAGES)
        fcStartIdx = n - FACT_CHECK_MESSAGES

        # Only add context section if there are messages before the fact-checking section
        if staIdx < fcStartIdx:
            convo += "## Begin context for fact-checking. Context-only DO NOT fact-check\n"
            for index in range(staIdx, fcStartIdx):
                srcMsg = self.srcMessages[index]
                convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])

        # Fact-checking section
        convo += "## Begin statements to fact-check. DO fact-check below\n"
        for index in range(fcStartIdx, n):
            srcMsg = self.srcMessages[index]
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])

        return self.gen_completion_ret_json(wrap, self.instructionsForFactCheck, convo, tools_user_data)

    def gen_research(self, wrap, query, tools_user_data):
        """ Generate a research completion
                :param wrap: OpenAIWrapper object
                :param query: The query to research
                :param tools_user_data: The user data to pass to the tools
                :return: The research completion
        """
        n = len(self.srcMessages)
        if n == 0:
            return "{}"

        CONTEXT_MESSAGES = 4
        convo = ""
        staIdx = max(0, n - CONTEXT_MESSAGES)

        # Context section
        convo += "## Begin context for your research. Context-only DO NOT research on this\n"
        for index in range(staIdx, n):
            srcMsg = self.srcMessages[index]
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])

        # Query to research about
        convo += "## Begin query for research. DO research about this\n"
        convo += f"{query}\n"

        response = self.genCompletion(wrap, self.instructionsForResearch, convo, tools_user_data)
        logmsg(f"Research outcome: {response}")
        return response


