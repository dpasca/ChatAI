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
        self.oa_wrap = OpenAIWrapper(api_key=os.environ.get("OPENAI_API_KEY"))

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
      "msg_id": "<exact message id as provided in the input>",
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
When presented with a search query, generate 3 variations and search
all of them with the web search tool.
One of the variations should be always in the language relative to the topic.
For example, if the topic is about the weather in Paris, you must perform at
least one search in French.
Be concise, don't worry about niceties.
Produce output in markdown, with bullet lists as much as possible.
Always include verbatim URLs in your replies.
Use tools like get_user_info, get_user_local_time to support the context
of the user's query.

Relevant tags:
  - <research_context>: The context in which the research is performed.
  - <research_query>: The original query for the research.

Report essential facts that are relevant to the conversation, e.g.
if the query is about the weather, do report temperature, and
any other stats that you acquired in your research. Give immediate
factual information as to minimize the effort of the user.
When a question has a specific answer, the links are meant as
a potential form of verification, not as the actual answer.
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

    def genCompletion(self, instructions, convo, exclude_tools, tools_user_data=None):
        from .OAIUtils import completion_with_tools
        response = completion_with_tools(
                wrap=self.oa_wrap,
                model=self.model,
                temperature=self.temperature,
                instructions=instructions,
                role_and_content_msgs=[{"role": "user", "content": convo}],
                exclude_tools=exclude_tools,
                tools_user_data=tools_user_data,
                stream=False)  # Always false for tool-related completions

        # For non-streaming, we expect a single response
        response_text = next(response)
        logmsg(f"Full response (len={len(response_text)}): {response_text}")
        return response_text

    def gen_completion_ret_json(
            self, instructions, convo,
            exclude_tools, tools_user_data=None):
        response = self.genCompletion(
            instructions=instructions,
            convo=convo,
            exclude_tools=exclude_tools,
            tools_user_data=tools_user_data)
        logmsg(f"Raw completion response (len={len(response)}): {response}")

        # First try to parse the entire response as JSON
        try:
            # Remove any leading/trailing whitespace
            response = response.strip()
            logmsg(f"Attempting to parse as JSON (stripped): {response}")
            json_obj = json.loads(response)
            logmsg("Successfully parsed entire response as JSON")
            return json.dumps(json_obj)
        except json.JSONDecodeError as e:
            logmsg(f"Failed to parse entire response as JSON: {str(e)}")

        # Handle the GPT-3.5 bug for when the response is more than one JSON object
        fixed_response = ConvoJudge.extract_first_json_object(response)
        logmsg(f"Extracted JSON object: {fixed_response}")

        # Check if the fixed_response is empty
        if not fixed_response:
            logwarn(f"Could not extract JSON object from response (len={len(response)})")
            logwarn(f"Response content: {response}")
            return "{}"

        # Convert the Python dictionary back to a JSON string if needed
        json_response = json.dumps(fixed_response)
        logmsg(f"Final JSON response (len={len(json_response)}): {json_response}")
        return json_response

    def GenSummary(self):
        convo = self.buildConvoString(1000)
        return self.genCompletion(self.instructionsForSummary, convo, None)

    def GenCritique(self):
        convo = self.buildConvoString(1000)
        return self.genCompletion(self.instructionsForCritique, convo, None)

    @staticmethod
    def extract_first_json_object(response):
        try:
            open_brackets = 0
            json_start = 0
            json_end = 0
            in_string = False
            escape = False

            # Log the first few characters to help debug
            logmsg(f"First 50 chars of response: {response[:50]}")

            for i, char in enumerate(response):
                if char == '"' and not escape:
                    in_string = not in_string
                elif char == '\\' and in_string:
                    escape = not escape
                    continue
                elif char == '{' and not in_string:
                    if open_brackets == 0:
                        json_start = i
                        logmsg(f"Found JSON start at position {i}")
                    open_brackets += 1
                elif char == '}' and not in_string:
                    open_brackets -= 1
                    if open_brackets == 0:
                        json_end = i + 1
                        logmsg(f"Found JSON end at position {i}")
                        break
                if escape:
                    escape = False

            if json_start < json_end:
                json_str = response[json_start:json_end]
                logmsg(f"Extracted JSON string (len={len(json_str)}): {json_str}")
                return json.loads(json_str)
            else:
                logwarn(f"No valid JSON object found in response (len={len(response)})")
                logwarn(f"Response content: {response}")
                return {}
        except Exception as e:
            logerr(f"Error parsing JSON: {str(e)}")
            return {}

    def GenFactCheck(self, tools_user_data):
        n = len(self.srcMessages)
        logmsg(f"GenFactCheck: Total messages: {n}")
        if n == 0:
            logmsg("No source messages found")
            return "{}"

        CONTEXT_MESSAGES = 8
        FACT_CHECK_MESSAGES = 2
        convo = ""
        staIdx = max(0, n - CONTEXT_MESSAGES)
        fcStartIdx = n - FACT_CHECK_MESSAGES

        logmsg(f"GenFactCheck: Context start index: {staIdx}, Fact-check start index: {fcStartIdx}")

        # Only add context section if there are messages before the fact-checking section
        if staIdx < fcStartIdx:
            #convo += "## Begin context for fact-checking. Context-only DO NOT fact-check\n"
            convo += "<context_for_fact_checking>\n"
            for index in range(staIdx, fcStartIdx):
                srcMsg = self.srcMessages[index]
                convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])
            convo += "</context_for_fact_checking>\n"

        # Fact-checking section
        #convo += "## Begin statements to fact-check. DO fact-check below\n"
        convo += "<statements_to_fact_check>\n"
        for index in range(fcStartIdx, n):
            srcMsg = self.srcMessages[index]
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])
        convo += "</statements_to_fact_check>\n"

        #logmsg(f"GenFactCheck: Conversation for fact-checking:\n{convo}")

        return self.gen_completion_ret_json(
            instructions=self.instructionsForFactCheck,
            convo=convo,
            exclude_tools=None, # All tools for fact-checking
            tools_user_data=tools_user_data)

    def gen_research(self, query, tools_user_data):
        """ Generate a research completion
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
        convo += "<research_context>\n"
        for index in range(staIdx, n):
            srcMsg = self.srcMessages[index]
            convo += self.makeConvoMessage(srcMsg['src_id'], srcMsg['role'], srcMsg['content'])

        # Query to research about
        convo += "</research_context>\n"
        convo += "<research_query>\n"
        convo += f"{query}\n"
        convo += "</research_query>\n"

        exclude_tools = ["ask_research_assistant"]
        #logmsg(f"Conversation for research:\n{convo}")
        response = self.genCompletion(
            instructions=self.instructionsForResearch,
            convo=convo,
            exclude_tools=exclude_tools,
            tools_user_data=tools_user_data)
        logmsg(f"Research outcome: {response}")
        return response


