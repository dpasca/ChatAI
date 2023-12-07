import os
from pyexpat.errors import messages
from flask import Flask, render_template, request, jsonify

from openai import OpenAI

client = OpenAI(
    # This is the default and can be omitted
    api_key=os.environ.get("OPENAI_API_KEY"),
)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('chat.html')

@app.route('/send_message', methods=['POST'])
def send_message():
    user_message = request.json['message']

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": user_message
                }
            ],
        )
    except Exception as e:
        print(f"OpenAI API Error: {e}")
        return jsonify({'reply': 'Error in processing the request.'}), 500

    print("--------------------------------------------------")
    print(response)
    print("--------------------------------------------------")

    if response:
        return jsonify({'reply': response.choices[0].message.content}), 200
    else:
        return jsonify({'reply': 'No response from API.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
