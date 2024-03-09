//==================================================================
// script.js
//
// Author: Davide Pasca, 2023/12/23
// Desc: Support for chat.html
//==================================================================

function showHideButton(buttonId, show) {
    document.getElementById(buttonId).style.display = show ? 'block' : 'none';
}

function postUserInfo() {
// Send the user's time zone and user agent to the server
let timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
let userAgent = navigator.userAgent;
fetch('/api/user_info', {
    method: 'POST',
    credentials: 'include',
    headers: {
    'Content-Type': 'application/json'
    },
    body: JSON.stringify({
    timezone: timeZone,
    user_agent: userAgent
    })
}
);
}

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
    } else {
        // If updating an existing message, clear its content first
        messageDiv.innerHTML = ''; // This clears the existing content
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

    // Set the innerHTML of the messageDiv to the new content
    messageDiv.innerHTML = messageContentHTML;

    // Ensure the last message is scrolled into view
    //messageDiv.scrollIntoView({ behavior: 'auto' });
    // Scroll to the bottom after the new message has been added and rendered
    //requestAnimationFrame(() => {
    //    chatBox.scrollTop = chatBox.scrollHeight;
    //});
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

//
const FC_COLLAPSE_POSTFIX = '_fc_coll';
const FC_EXPAND_POSTFIX = '_fc_expa';

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
    const userMessage = {
        role: 'user',
        src_id: "PLACEHOLDER_" + Date.now().toString(),
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
    socket.emit('send_message', { message: userInput });

    // Reset input area
    var inputBox = document.getElementById('user-input');
    inputBox.value = '';
    inputBox.focus();
}

function pollForAddendums() {
    fetch('/get_addendums', {
        method: 'GET',
        credentials: 'include'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        //console.log("Found addendums:", data.addendums);
        for (let addendum of data.addendums) {
            // Check if the addendim has fact-check array
            if (addendum.hasOwnProperty('fact_checks') && addendum.fact_checks.length > 0) {
                //console.log("Found fact-checks:", addendum.fact_checks);
                for (let fcheck of addendum.fact_checks) {
                    appendFactCheck(fcheck);
                }
            }
            else {
                //console.log("No fact-checks found !!");
            }
        }
        // See if we have a 'message'
        //if (data.hasOwnProperty('message')) {
        //    console.log("Found message:", data.message);
        //}
        if (!data.final) {
            setTimeout(pollForAddendums, 1000); // Poll at a fixed interval
        }
    })
    .catch(error => {
        console.error('Error during fetch:', error);
    });
}
