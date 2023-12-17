
function appendMessage(message, assistant_name='') {
    if (message === null || typeof message !== 'object') {
        console.error(`Unknown message format for message: ${message} type: ${typeof message}`);
        return;
    }

    var chatBox = document.getElementById('chatbox');

    messageHTML = '';

    if (message.role == 'user') {
        messageHTML += `<div class="user-message">`;
    } else if (message.role == 'assistant') {
        messageHTML += `<div class="ai-message" data-name="${assistant_name}">`;
    }
    else {
        messageHTML += `<div>Unknown role: ${message.role}</div>`;
        console.error("Unknown role:", message.role);
        return;
    }

    if (message.content_type == 'text') {
        // Convert markdown to HTML, only for display
        var converter = new showdown.Converter();
        messageHTML += converter.makeHtml(message.content);
    } else {
        messageHTML += `${message.content_type}: ${message.content}`;
    }
    messageHTML += '</div>';

    console.log("Appending message:", messageHTML);

    chatBox.innerHTML += messageHTML;
}

function appendWaitingAssistMessage(assistant_name) {
    var chatBox = document.getElementById('chatbox');
    var typingDots = '';

    // Create typing dots based on numDots parameter
    var numDots = 4;
    for (let i = 0; i < numDots; i++) {
        typingDots += '<span>.</span>';
    }

    var typingIndicator = `<div class="ai-message" data-name="${assistant_name}">`;
    typingIndicator += `<b>${assistant_name}</b> is typing<span class="typing-dots">${typingDots}</span>`;
    typingIndicator += `</div>`;
    chatBox.innerHTML += typingIndicator;

    // Animate dots
    let dots = document.querySelector('.typing-dots').children;
    let dotIndex = 0;
    setInterval(() => {
        for (let dot of dots) {
            dot.style.opacity = '0.2';
        }
        dots[dotIndex].style.opacity = '1';
        dotIndex = (dotIndex + 1) % dots.length;
    }, 500);
}

function removeAssistMessage() {
    var chatBox = document.getElementById('chatbox');
    var aiMessage = chatBox.getElementsByClassName('ai-message');
    aiMessage[aiMessage.length - 1].remove();
}

// Send message to Flask server and append response to chat
function sendMessage(userInput, assistant_name) {

    var inputBox = document.getElementById('user-input');
    var sendButton = document.getElementById('send-button');

    inputBox.value = ''; // Clear input box
    inputBox.disabled = true; // Disable input box
    sendButton.disabled = true; // Disable send button

    // Construct a message object with the expected format
    const userMessage = {
        role: 'user',
        content_type: 'text',
        content: userInput
    };
    // Append user message to chat
    appendMessage(userMessage);

    // Append a waiting message
    appendWaitingAssistMessage(assistant_name);

    // Send message to Flask server
    fetch('/send_message', {
        method: 'POST',
        body: JSON.stringify({ 'message': userInput }),
        headers: {
            'Content-Type': 'application/json'
        }
    })
    // Get response from Flask server
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    // Append response to chat
    .then(data => {
        //console.log("Processed data: ", data);

        // Remove the waiting message
        removeAssistMessage();

        if (data.replies.length == 0) {
            return;
        }

        inputBox.disabled = false; // Enable input box
        sendButton.disabled = false; // Enable send button
        
        for (let message of data.replies) {
            //console.log("Appending message:", message);
            appendMessage(message, assistant_name);
        }
    });
}

