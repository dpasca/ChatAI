// Append user message to chat
function appendUserMessage(message) {
    var chatBox = document.getElementById('chatbox');
    // Convert markdown to HTML, only for display
    var converter = new showdown.Converter();
    var html = converter.makeHtml(message);
    chatBox.innerHTML += `<div class="user-message">${html}</div>`;
}

// Append assistant message to chat
function appendAssistMessage(assistant_name, message) {
    var converter = new showdown.Converter();
    var html = converter.makeHtml(message); // Convert markdown to HTML
    var chatBox = document.getElementById('chatbox');
    chatBox.innerHTML += `<div class="ai-message" data-name="${assistant_name}">${html}</div>`;
}
function appendWaitingAssistMessage(assistant_name) {
    var chatBox = document.getElementById('chatbox');
    chatBox.innerHTML += `<div class="ai-message waiting-message" data-name="${assistant_name}"></div>`;
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

    appendUserMessage(userInput);

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
    .then(response => response.json())
    // Append response to chat
    .then(data => {
        // Remove the waiting message
        removeAssistMessage();

        inputBox.disabled = false; // Enable input box
        sendButton.disabled = false; // Enable send button
        appendAssistMessage(assistant_name, data.reply);
    });
}

