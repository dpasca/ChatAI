function sendMessage() {
    var userInput = document.getElementById('user-input').value;
    // Clear input box
    document.getElementById('user-input').value = '';

    // Append user message to chat
    var chatBox = document.getElementById('chat-box');
    chatBox.innerHTML += '<div class="user-message">' + userInput + '</div>';

    // Send message to Flask server
    fetch('/send_message', {
        method: 'POST',
        body: JSON.stringify({ 'message': userInput }),
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        // Append AI response to chat
        chatBox.innerHTML += '<div class="ai-message">' + data.reply + '</div>';
    });
}

