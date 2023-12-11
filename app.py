import os
from pyexpat.errors import messages
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI

ASSISTANT_NAME = "Mei"

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

app = Flask(__name__)
app.secret_key = os.environ.get("CHATAI_FLASK_SECRET_KEY")

def get_messages():
    if 'messages' not in session:
        session['messages'] = []
    return session['messages']

def on_messages_change():
    session.modified = True

def append_message(message):
    get_messages().append(message)
    on_messages_change()

@app.route('/')
def index():
    # Add a system message to customize the assistant's behavior
    append_message({
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
    return render_template('chat.html', assistant_name=ASSISTANT_NAME)

def countWordsInMessages():
    count = 0
    for message in get_messages():
        count += len(message["content"].split())
    return count

def logmsg(msg):
    print(msg)

@app.route('/send_message', methods=['POST'])
def send_message():

    # Count the number of words in all the messages
    while countWordsInMessages() > 7900 and len(get_messages()) > 3:
        # remove the second message
        logmsg("Removing message")
        get_messages().pop(1)
        on_messages_change()

    user_message = request.json['message']
    # Append user message to messages list
    append_message({
        "role": "user",
        "content": user_message
    })

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=get_messages(),
        )
    except Exception as e:
        logmsg(f"OpenAI API Error: {e}")
        return jsonify({'reply': 'Error in processing the request.'}), 500

    # Extract AI reply
    if response.choices and response.choices[0].message:
        ai_reply = response.choices[0].message.content

        # Append AI reply to messages list
        append_message({
            "role": "assistant",
            "content": ai_reply
        })

        return jsonify({'reply': ai_reply}), 200
    else:
        return jsonify({'reply': 'No response from API.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
