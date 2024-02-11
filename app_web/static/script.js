//==================================================================
// script.js
//
// Author: Davide Pasca, 2023/12/23
// Desc: Support for chat.html
//==================================================================

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

    //console.log("Appending message:", message);
    var chatBox = document.getElementById('chatbox');

    // Check if we have the src_id
    messageHTML = `<div id="${message.src_id}" `;
    //console.log("Using src_id:", message.src_id);

    if (message.role == 'user') {
        messageHTML += `class="user-message">`;
    } else if (message.role == 'assistant') {
        messageHTML += `class="ai-message" data-name="${assistant_name}">`;
    }
    else {
        messageHTML += `>Unknown role: ${message.role}</div>`;
        console.error("Unknown role:", message.role);
        return;
    }

    // For every piece of content
    for (let content of message.content) {
        if (content.type == 'text') {
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
        <b>${assistant_name}</b> is typing<span class="typing-dots">${typingDots}</span>
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
        src_id: 'PLACEHOLDER_USER_MSG_ID',
        content: [{
            type: 'text',
            value: userInput
        }]
    };
    // Append user message to chat
    appendMessage(userMessage);

    // Append a waiting message before sending the request
    appendWaitingAssistMessage(assistant_name);

    // Send message to Flask server
    //console.log("Sending message:", userInput);
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
    .then(data => {
        if (data.status === 'processing') {
            // Extract the user message ID and place it where
            //   the temp ID is
            const tempID = document.getElementById('PLACEHOLDER_USER_MSG_ID');
            if (tempID) {
                //console.log("Found temp ID:", tempID);
                tempID.id = data.user_msg_id;
            }
            else {
                console.error("No temp ID found");
            }
            // Start polling for replies
            pollForReplies(assistant_name);
        }
    })
    .catch(error => {
        console.error('There was a problem with the fetch operation:', error);
        // TODO: have an error message appear in the chat

        removeWaitingAssistMessage(); // Remove the waiting message
        inputBox.disabled = false; // Enable input box
        sendButton.disabled = false; // Enable send button
    });
}

// Poll for replies from the server
function pollForReplies(assistant_name) {
    fetch('/get_replies')
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.replies && data.replies.length > 0) {
            for (let message of data.replies) {
                appendMessage(message, assistant_name);
            }
        }
        //console.log("Polling for replies:", data);
        if (!data.final) {
            // Continue polling if not final
            setTimeout(() => pollForReplies(assistant_name), 500); // Poll every some ms
        } else {
            // Processing is complete
            //console.log("Processing complete");
            document.getElementById('user-input').disabled = false; // Enable input box
            document.getElementById('send-button').disabled = false; // Enable send button
            removeWaitingAssistMessage(); // Remove the waiting message
            document.getElementById('erase-button').style.display = 'block'; // Enable the erase button

            // Start polling for addendums
            //console.log("Starting polling for addendums");
            pollForAddendums();
        }
    })
    .catch(error => {
        console.error('There was a problem with the fetch operation:', error);

        //if (data.error === 'ERR_THREAD_EXPIRED') {
            document.getElementById('reset-expired-chat').style.display = 'block';
            document.getElementById('erase-button').style.display = 'none';
        //}

        removeWaitingAssistMessage(); // Remove the waiting message
        document.getElementById('user-input').disabled = true; // Disable input box
        document.getElementById('send-button').disabled = true; // Disable send button
    });
}

function pollForAddendums() {
    fetch('/get_addendums')
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
                    if (fcheck.applicable) {
                        appendFactCheck(fcheck);
                    }
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
            setTimeout(pollForAddendums, 500); // Poll every 500 ms
        }
    })
    .catch(error => {
        console.error('Error during fetch:', error);
    });
}



// JS version of markdown-it-latex
// Test if potential opening or closing delimieter
// Assumes that there is a "$" at state.src[pos]
function isValidDelim(state, pos) {
    var prevChar, nextChar,
        max = state.posMax,
        can_open = true,
        can_close = true;

    prevChar = pos > 0 ? state.src.charCodeAt(pos - 1) : -1;
    nextChar = pos + 1 <= max ? state.src.charCodeAt(pos + 1) : -1;

    // Check non-whitespace conditions for opening and closing, and
    // check that closing delimeter isn't followed by a number
    if (prevChar === 0x20/* " " */ || prevChar === 0x09/* \t */ ||
            (nextChar >= 0x30/* "0" */ && nextChar <= 0x39/* "9" */)) {
        can_close = false;
    }
    if (nextChar === 0x20/* " " */ || nextChar === 0x09/* \t */) {
        can_open = false;
    }

    return {
        can_open: can_open,
        can_close: can_close
    };
}

function math_inline(state, silent) {
    var start, match, token, res, pos, esc_count;

    if (state.src[state.pos] !== "$") { return false; }

    res = isValidDelim(state, state.pos);
    if (!res.can_open) {
        if (!silent) { state.pending += "$"; }
        state.pos += 1;
        return true;
    }

    // First check for and bypass all properly escaped delimieters
    // This loop will assume that the first leading backtick can not
    // be the first character in state.src, which is known since
    // we have found an opening delimieter already.
    start = state.pos + 1;
    match = start;
    while ( (match = state.src.indexOf("$", match)) !== -1) {
        // Found potential $, look for escapes, pos will point to
        // first non escape when complete
        pos = match - 1;
        while (state.src[pos] === "\\") { pos -= 1; }

        // Even number of escapes, potential closing delimiter found
        if ( ((match - pos) % 2) == 1 ) { break; }
        match += 1;
    }

    // No closing delimter found.  Consume $ and continue.
    if (match === -1) {
        if (!silent) { state.pending += "$"; }
        state.pos = start;
        return true;
    }

    // Check if we have empty content, ie: $$.  Do not parse.
    if (match - start === 0) {
        if (!silent) { state.pending += "$$"; }
        state.pos = start + 1;
        return true;
    }

    // Check for valid closing delimiter
    res = isValidDelim(state, match);
    if (!res.can_close) {
        if (!silent) { state.pending += "$"; }
        state.pos = start;
        return true;
    }

    if (!silent) {
        token         = state.push('math_inline', 'math', 0);
        token.markup  = "$";
        token.content = state.src.slice(start, match);
    }

    state.pos = match + 1;
    return true;
}

function math_block(state, start, end, silent){
    var firstLine, lastLine, next, lastPos, found = false, token,
        pos = state.bMarks[start] + state.tShift[start],
        max = state.eMarks[start]

    if(pos + 2 > max){ return false; }
    if(state.src.slice(pos,pos+2)!=='$$'){ return false; }

    pos += 2;
    firstLine = state.src.slice(pos,max);

    if(silent){ return true; }
    if(firstLine.trim().slice(-2)==='$$'){
        // Single line expression
        firstLine = firstLine.trim().slice(0, -2);
        found = true;
    }

    for(next = start; !found; ){

        next++;

        if(next >= end){ break; }

        pos = state.bMarks[next]+state.tShift[next];
        max = state.eMarks[next];

        if(pos < max && state.tShift[next] < state.blkIndent){
            // non-empty line with negative indent should stop the list:
            break;
        }

        if(state.src.slice(pos,max).trim().slice(-2)==='$$'){
            lastPos = state.src.slice(0,max).lastIndexOf('$$');
            lastLine = state.src.slice(pos,lastPos);
            found = true;
        }

    }

    state.line = next + 1;

    token = state.push('math_block', 'math', 0);
    token.block = true;
    token.content = (firstLine && firstLine.trim() ? firstLine + '\n' : '')
    + state.getLines(start + 1, next, state.tShift[start], true)
    + (lastLine && lastLine.trim() ? lastLine : '');
    token.map = [ start, state.line ];
    token.markup = '$$';
    return true;
}

function math_plugin(md, options) {
    // Default options
    options = options || {};

    // set KaTeX as the renderer for markdown-it-simplemath
    var katexInline = function(latex){
        options.displayMode = false;
        try{
            return katex.renderToString(latex, options);
        }
        catch(error){
            if(options.throwOnError){ console.log(error); }
            return latex;
        }
    };

    var inlineRenderer = function(tokens, idx){
        return katexInline(tokens[idx].content);
    };

    var katexBlock = function(latex){
        options.displayMode = true;
        try{
            return "<p>" + katex.renderToString(latex, options) + "</p>";
        }
        catch(error){
            if(options.throwOnError){ console.log(error); }
            return latex;
        }
    }

    var blockRenderer = function(tokens, idx){
        return  katexBlock(tokens[idx].content) + '\n';
    }

    md.inline.ruler.after('escape', 'math_inline', math_inline);
    md.block.ruler.after('blockquote', 'math_block', math_block, {
        alt: [ 'paragraph', 'reference', 'blockquote', 'list' ]
    });
    md.renderer.rules.math_inline = inlineRenderer;
    md.renderer.rules.math_block = blockRenderer;
};
