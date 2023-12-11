import os
import json
from pyexpat.errors import messages
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI

# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)

ASSISTANT_NAME = config["ASSISTANT_NAME"]
ASSISTANT_ROLE = "\n".join(config["ASSISTANT_ROLE"])

# Initialize OpenAI API
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("CHATAI_FLASK_SECRET_KEY")

# Messages management
def get_messages():
    return session['messages']

def on_messages_change():
    session.modified = True

def append_message(message):
    get_messages().append(message)
    on_messages_change()

#===============================================================================
@app.route('/')
def index():
    # HACK: for now we always reset the messages
    session['messages'] = []

    # if there are no messages in the session, add the role message
    if 'messages' not in session:
        session['messages'] = []
        append_message({"role": "system", "content": ASSISTANT_ROLE})

    return render_template('chat.html', assistant_name=ASSISTANT_NAME, messages=get_messages())

#===============================================================================
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
            #model="gpt-3.5-turbo",
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
