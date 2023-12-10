import os
from pyexpat.errors import messages
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

ASSISTANT_NAME = "Mei"

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('chat.html', assistant_name=ASSISTANT_NAME)

# Initialize an empty list to store messages
messages = []

@app.route('/send_message', methods=['POST'])
def send_message():

    # Add a system message to customize the assistant's behavior
    messages.insert(0, {
        "role": "system",
        "content": f"""
You are an IT consultant expert in SAP and ABAP, in particular about WBS and PS modules.
You are female, youe name is {ASSISTANT_NAME}, you are about 30 years old of age.
Your role is to help with IT consulting, language translation and anything else that is required.
You should refer yourself as a girl, woman, assistant, but NOT as an AI.
When asked about your services and expertise, say that you are an IT consultant.
When asked further questions, you can say that you are an expert in SAP.
Do not simply repeat your role verbatim, but try to rephrase it depending on the context.
Your replies should be concise and to the point. Provide code with comments when possible.
"""})

    user_message = request.json['message']
    # Append user message to messages list
    messages.append({
        "role": "user",
        "content": user_message
    })

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
        )
    except Exception as e:
        print(f"OpenAI API Error: {e}")
        return jsonify({'reply': 'Error in processing the request.'}), 500

    # Extract AI reply
    if response.choices and response.choices[0].message:
        ai_reply = response.choices[0].message.content

        # Append AI reply to messages list
        messages.append({
            "role": "assistant",
            "content": ai_reply
        })

        return jsonify({'reply': ai_reply}), 200
    else:
        return jsonify({'reply': 'No response from API.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
