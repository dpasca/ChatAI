function sendMessage(userInput, assistant_name) {
    // Append user message to chat
    var chatBox = document.getElementById('chatbox');
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
        var converter = new showdown.Converter();
        var html = converter.makeHtml(data.reply); // Convert markdown to HTML
        chatBox.innerHTML += `<div class="ai-message" data-name="${assistant_name}">${html}</div>`;
    });
}

