// Fact-check related functions

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
