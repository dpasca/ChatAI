//==================================================================
// script.js
//
// Author: Davide Pasca, 2023/12/23
// Desc: Support for chat.html
//==================================================================

// Instantiate markdown-it with Prism.js for syntax highlighting
const md = window.markdownit({
    highlight: function (str, lang) {
        if (lang && Prism.languages[lang]) {
            try {
                return `<pre class="language-${lang}"><code class="language-${lang}">${Prism.highlight(str, Prism.languages[lang], lang)}</code></pre>`;
            } catch (_) {}
        }
        // Use external default escaping
        return '<pre class="language-plaintext"><code>' + md.utils.escapeHtml(str) + '</code></pre>';
    }
});

// Reduce indentation of code blocks for readability
function reformatIndentation(codeString) {
    // Replace every occurrence of four spaces at the beginning of a line with two spaces
    return codeString.replace(/^ {4}/gm, '  ');
}

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

    // For every piece of content
    for (let content of message.content) {
        if (content.type == 'text') {

            // Display as Markdown
            const defaultStyles = `
            <link rel="stylesheet"
                href="https://cdn.jsdelivr.net/gh/sindresorhus/github-markdown-css@4/github-markdown.min.css" />
            <link rel="stylesheet"
                href="https://cdn.jsdelivr.net/gh/PrismJS/prism@1/themes/prism.min.css" />`;

            // The final message
            const reformattedContent = reformatIndentation(content.value);
            const htmlContent = md.render(reformattedContent);
            // Wrap the content in a div with a class for styling
            messageHTML += `<div class="markdown-content">${htmlContent}</div>`;
        } else if (content.type == 'image_file') {
            //messageHTML += `<img src="${content.value}" />`;
            messageHTML += `<img src="${content.value}"`;
            messageHTML += ` style="max-width: 100%; max-height: 400px; object-fit: contain; width: auto; height: auto;" />`;
            //messageHTML += md.render(`![image](${content.value})`);
        } else {
            messageHTML += `${content.type}: ${content.value}`;
        }
    }

    messageHTML += '</div>';

    //console.log("Appending message:", messageHTML);

    chatBox.innerHTML += messageHTML;
    chatBox.lastElementChild.scrollIntoView({ behavior: 'smooth' });
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
    chatBox.lastElementChild.scrollIntoView({ behavior: 'smooth' });

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
        content: [{
            type: 'text',
            value: userInput
        }]
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
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    // Append response to chat
    .then(data => {
        //console.log("Processed data: ", data);

        removeAssistMessage(); // Remove the waiting message
        inputBox.disabled = false; // Enable input box
        sendButton.disabled = false; // Enable send button

        if (data.replies.length == 0) {
            return;
        }
        for (let message of data.replies) {
            //console.log("Appending message:", message);
            appendMessage(message, assistant_name);
        }
        // Enable the erase button
        document.getElementById('erase-button').style.display = 'block';
    })
    .catch(error => {
        console.error('There was a problem with the fetch operation:', error);
        // TODO: have an error message appear in the chat

        removeAssistMessage(); // Remove the waiting message
        inputBox.disabled = false; // Enable input box
        sendButton.disabled = false; // Enable send button
    });
}

