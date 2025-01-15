//==================================================================
// script.js
//
// Author: Davide Pasca, 2023/12/23
// Desc: Support for chat.html
//==================================================================

// Global variables and initialization
(function() {
    // Only declare these if they haven't been declared yet
    if (typeof window.CONNECT_TIMEOUT_MS === 'undefined') {
        window.CONNECT_TIMEOUT_MS = 60000;
    }
    if (typeof window.socket === 'undefined') {
        window.socket = null;
    }
    if (typeof window.connectTimeout === 'undefined') {
        window.connectTimeout = null;
    }
})();

// Utility functions
function showHideButton(buttonId, show) {
    document.getElementById(buttonId).style.display = show ? 'block' : 'none';
}

function handleError(response) {
    if (!response.ok) {
        return response.json().then(err => {
            throw new Error(`Error: ${response.status}. Message: ${err.error || 'Unknown error'}`);
        });
    }
    return response.json();
}

// User info handling
async function postUserInfo() {
    let timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    let userAgent = navigator.userAgent;

    try {
        const response = await fetch(window.SERVER_URL+'/api/user_info', {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                timezone: timeZone,
                user_agent: userAgent
            })
        });

        await handleError(response);
    } catch (error) {
        console.error('Error posting user info:', error);
    }
}

// Socket.IO handling
function initializeSocket() {
    if (window.socket) {
        console.log('Socket already initialized');
        return;
    }

    window.socket = io(window.SERVER_URL, {
        query: { CustomClientId: window.clientId },
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        reconnectionAttempts: 5
    });

    window.socket.on('connect', () => {
        console.log('Connected to server');
        clearTimeout(window.connectTimeout);
        // After connection, load chat history and post user info
        loadChatHistory();
    });

    window.socket.on('connect_error', (error) => {
        console.error('Connection error:', error);
    });

    window.socket.on('disconnect', (reason) => {
        console.log('Disconnected:', reason);
        if (reason === 'io server disconnect') {
            window.socket.connect();
        }
    });

    window.socket.on('message', (data) => {
        console.log('Received message:', data);
        if (data.final) {
            removeWaitingAssistMessage();
        }
        appendMessage(data);
    });

    window.connectTimeout = setTimeout(() => {
        console.error('Connection timeout');
        window.socket.disconnect();
    }, window.CONNECT_TIMEOUT_MS);
}

// Chat history handling
async function loadChatHistory() {
    try {
        await postUserInfo();
        const response = await fetch(window.SERVER_URL+'/get_history', {
            method: 'GET',
            credentials: 'include'
        });
        const data = await handleError(response);

        if (data.messages) {
            for (let message of data.messages) {
                appendMessage(message);
            }
            if (data.messages.length > 0) {
                showHideButton('erase-button', true);
            }
        }
    } catch (error) {
        console.error('Error loading chat history:', error);
    }
}

// Initialize when the page loads
document.addEventListener('DOMContentLoaded', () => {
    initializeSocket();
});

// Instantiate markdown-it with Prism.js for syntax highlighting
const md = window.markdownit({
    highlight: function (str, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                return `<pre class="language-${lang}"><code class="language-${lang}">${hljs.highlight(lang, str).value}</code></pre>`;
            } catch (_) {}
        }
        // use highlight.js's autodetection
        try {
            return `<pre class="language-plaintext"><code>${hljs.highlightAuto(str).value}</code></pre>`;
        } catch (_) {}
        // if all else fails, use the original escaping
        return '<pre class="language-plaintext"><code>' + md.utils.escapeHtml(str) + '</code></pre>';
    }
}).use(math_plugin);

// Add custom renderer for links to open in a new tab
if (window.config.openLinksInNewTab) {
    md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
        tokens[idx].attrPush(['target', '_blank']); // add new attribute
        return self.renderToken(tokens, idx, options);
    };
}

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

    removeWaitingAssistMessage(); // Remove the waiting message

    var chatBox = document.getElementById('chatbox');
    var messageDiv = document.getElementById(message.src_id);

    if (!messageDiv) {
        // Create new message div if it doesn't exist
        messageDiv = document.createElement('div'); // Create a new div element
        messageDiv.id = message.src_id; // Set the id of the new div

        // Set the class of the new message based on the role
        if (message.role == 'user') {
            messageDiv.className = "user-message";
        } else if (message.role == 'assistant') {
            messageDiv.className = "ai-message";
            messageDiv.setAttribute('data-name', assistant_name);
        }

        chatBox.appendChild(messageDiv); // Append the new div to the chatBox
    }

    // Create the content HTML for the new or updated message
    var messageContentHTML = '';
    // For every piece of content
    for (let content of message.content) {
        if (content.type == 'text') {
            // The final message
            const reformattedContent = reformatIndentation(content.value);
            const htmlContent = md.render(reformattedContent);
            // Wrap the content in a div with a class for styling
            messageContentHTML += `<div class="markdown-content">${htmlContent}</div>`;
        } else if (content.type == 'image_file') {
            messageContentHTML += `<img src="${content.value}" style="max-width: 100%; max-height: 400px; object-fit: contain; width: auto; height: auto;" />`;
        } else {
            messageContentHTML += `${content.type}: ${content.value}`;
        }
    }

    // Save any existing fact-check elements
    const factCheckElements = [];
    const existingFactChecks = messageDiv.querySelectorAll('.fact-check-collapsed, .fact-check-expanded');
    existingFactChecks.forEach(el => factCheckElements.push(el));

    // Set the innerHTML of the messageDiv to the new content
    messageDiv.innerHTML = messageContentHTML;

    // Re-add any fact-check elements that were present
    factCheckElements.forEach(el => messageDiv.appendChild(el));
}

function makeDispLink(url) {
    // Cut https:// at the beginning
    return (url.startsWith('https://')) ? url.slice(8) : url;
}
function makeMDLink(title, url) {
    // Make a markdown link
    if (title !== '') {
        title = makeDispLink(title);
    }
    return `[${title}](${url})`;
}

// Call this in the HTML file at document.addEventListener('DOMContentLoaded', ...)
function setupFactCheckEventDelegation() {
    var chatBox = document.getElementById('chatbox');
    if (!chatBox) {
        console.error('Chatbox not found.');
        return;
    }

    chatBox.addEventListener('click', function(e) {
        // Check if the click is on a fact-check icon or its container
        var target = e.target;
        var isFactCheckIcon = target.classList.contains('fact-check-icon') ||
                              target.parentElement.classList.contains('fact-check-collapsed');

        if (isFactCheckIcon) {
            var factCheckId = target.closest('.fact-check-collapsed').id;
            var expandedDivId = factCheckId.replace(FC_COLLAPSE_POSTFIX, FC_EXPAND_POSTFIX);
            var expandedDiv = document.getElementById(expandedDivId);

            if (expandedDiv) {
                expandedDiv.style.display = expandedDiv.style.display === 'none' ? 'block' : 'none';
            }
        }
    });
}

function appendFactCheck(fcheck) {
    // Find the message by the ID
    var messageDiv = document.getElementById(fcheck.msg_id);
    if (messageDiv === null) {
        console.error(`No message found with src_id: ${fcheck.msg_id}`);
        return;
    }

    fullText = "";
    switch (fcheck.correctness) {
    case 0:
    case 1:
    case 2: fullText += '❌'; break;
    case 3:
    case 4:
    case 5: fullText += '✅'; break;
    default: fullText += '❓'; break;
    }

    // if rebuttal is not empty
    if (fcheck.rebuttal !== "") {
        fullText += ` ${fcheck.rebuttal}`;
    }
    else {
        switch (fcheck.correctness) {
        case 0:
        case 1:
        case 2: fullText += ' Not Credible'; break;
        case 3:
        case 4:
        case 5: fullText += ' Credible'; break;
        default: break;
        }
    }
    for (let link of fcheck.links) {
        // Ensure that we have valid links (fields exist), otherwise skip
        if (!link.hasOwnProperty('title') || !link.hasOwnProperty('url')) {
            console.error("Invalid link:", link);
            continue;
        }
        fullText += `\n - ${makeMDLink(link.title, link.url)}\n`;
    }
    // Return if there is no text to display
    if (fullText === "") return;

    //console.log("Fact-check message:", fullText);

    // Convert the fact-check message to HTML
    const reformattedContent = reformatIndentation(fullText);
    const htmlContent = md.render(reformattedContent);

    // Unique ID for the collapsed and expanded divs
    let collapsedDivId = fcheck.msg_id + FC_COLLAPSE_POSTFIX;
    let expandedDivId = fcheck.msg_id + FC_EXPAND_POSTFIX;

    // Check if the collapsedDiv already exists, create if not
    let collapsedDiv = document.getElementById(collapsedDivId);
    if (!collapsedDiv) {
        collapsedDiv = document.createElement('div');
        collapsedDiv.id = collapsedDivId;
        collapsedDiv.className = 'fact-check-collapsed';
        collapsedDiv.innerHTML = `<span class="fact-check-icon flash">${fullText.charAt(0)}</span>`;
        messageDiv.appendChild(collapsedDiv);
    }

    // Check if the expandedDiv already exists, create if not
    let expandedDiv = document.getElementById(expandedDivId);
    if (!expandedDiv) {
        expandedDiv = document.createElement('div');
        expandedDiv.id = expandedDivId;
        expandedDiv.className = 'fact-check-expanded addendum-message';
        expandedDiv.style.display = 'none';
        expandedDiv.innerHTML = `<div class="markdown-content">${htmlContent}</div>`;
        messageDiv.appendChild(expandedDiv);
    }
}

// Global variable to store a reference to the waiting message element and its state
var waitingMessage = { element: null, isVisible: false };

function appendWaitingAssistMessage(assistant_name) {
    // Check if the waiting message is already visible
    if (waitingMessage.isVisible) return;

    var chatBox = document.getElementById('chatbox');
    var typingDots = '<span>.</span>'.repeat(4);

    var typingIndicator = `<div class="ai-message" data-name="${assistant_name}">
        <b>${assistant_name}</b> ${i18next.t('is_searching')}<span class="typing-dots">${typingDots}</span>
    </div>`;

    chatBox.innerHTML += typingIndicator;
    chatBox.lastElementChild.scrollIntoView({ behavior: 'smooth' });

    // Update the waiting message state
    waitingMessage.element = chatBox.lastElementChild;
    waitingMessage.isVisible = true;

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

function removeWaitingAssistMessage() {
    // Check if the waiting message exists and is visible
    if (waitingMessage.isVisible && waitingMessage.element) {
        waitingMessage.element.remove();
    }
    // Reset the waiting message state
    waitingMessage.element = null;
    waitingMessage.isVisible = false;
}

// Send message to Flask server and append response to chat
function sendMessage(userInput, assistant_name) {

    var inputBox = document.getElementById('user-input');
    var sendButton = document.getElementById('send-button');

    inputBox.value = ''; // Clear input box
    inputBox.disabled = true; // Disable input box
    sendButton.disabled = true; // Disable send button

    // Construct a message object with the expected format
    const clientMsgId = "clientmsg_" + Date.now().toString();
    const userMessage = {
        role: 'user',
        src_id: clientMsgId,
        content: [{
            type: 'text',
            value: userInput
        }]
    };
    // Append user message to chat
    appendMessage(userMessage);

    // Append a waiting message before sending the request
    appendWaitingAssistMessage(assistant_name);

    // Now, emit the message through the WebSocket instead of making an HTTP request
    window.socket.emit('send_message', { message: userInput, src_id: clientMsgId });

    // Reset input area
    var inputBox = document.getElementById('user-input');
    inputBox.value = '';
    inputBox.focus();
}

function pollForAddendums() {
    console.log("Polling for addendums...");
    fetch(window.SERVER_URL+'/get_addendums', {
        method: 'GET',
        credentials: 'include'
    })
    .then(handleError)
    .then(data => {
        //console.log("Found addendums:", data.addendums);
        //console.log("Received addendums data:", data);
        for (let addendum of data.addendums) {
            // Check if the addendim has fact-check array
            if (addendum.hasOwnProperty('fact_checks') && addendum.fact_checks.length > 0) {
                //console.log("Processing fact-checks:", addendum.fact_checks);
                for (let fcheck of addendum.fact_checks) {
                    appendFactCheck(fcheck);
                }
            }
            else {
                //console.log("No fact-checks found in addendum");
            }
        }
        // See if we have a 'message'
        //if (data.hasOwnProperty('message')) {
        //    console.log("Found message:", data.message);
        //}
        if (!data.final) {
            //console.log("Scheduling next addendum poll");
            setTimeout(pollForAddendums, 1000); // Poll at a fixed interval
        } else {
            //console.log("Addendum polling complete");
        }
    })
    .catch(error => {
        console.error('Error during addendum fetch:', error);
    });
}
