// static/script.js
document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chat-container');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const pdfBox = document.getElementById('pdf-box');
    const chatBox = document.getElementById('chat-box');

    let activeTypeController = null;
    const CHAT_ENDPOINT = '/chat';

    /* ---------- Utility Functions ---------- */
    function updateSendButton() {
        if (activeTypeController) {
            sendButton.textContent = 'Stop';
            sendButton.classList.add('stop-mode');
        } else {
            sendButton.textContent = '➤';
            sendButton.classList.remove('stop-mode');
        }
    }

    function scrollToBottom() {
        chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
    }

    function attachLinkHandlers(element) {
        const links = element.querySelectorAll('a');
        links.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                openPDFInBox(link.href);
            });
        });
    }

    /* ---------- PDF Viewer ---------- */
    function openPDFInBox(url) {
        pdfBox.innerHTML = `
            <button class="close-pdf" onclick="closePDF()">✕</button>
            <iframe id="pdfViewer" src="${url}" allowfullscreen></iframe>
        `;
        pdfBox.classList.remove('hidden');
        pdfBox.classList.add('expanded');
        chatBox.classList.add('pdf-open');
    }

    window.closePDF = function () {
        pdfBox.classList.add('hidden');
        pdfBox.classList.remove('expanded');
        chatBox.classList.remove('pdf-open');
    };

    /* ---------- Append Message ---------- */
    function appendMessage(text, sender, isTyping = false) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender === 'user' ? 'user-message' : 'bot-message');
        messageDiv.style.opacity = '0'; // for fade-in animation

        const messageText = document.createElement('div');
        messageText.classList.add('message-text');

        if (isTyping) {
            messageText.classList.add('typing-indicator');
            messageText.textContent = 'Typing...';
        } else {
            messageText.innerHTML = marked.parse(text || '');
            attachLinkHandlers(messageText);
        }

        messageDiv.appendChild(messageText);
        chatContainer.appendChild(messageDiv);

        // Smooth fade-in
        requestAnimationFrame(() => {
            messageDiv.style.transition = 'opacity 0.4s ease';
            messageDiv.style.opacity = '1';
        });

        scrollToBottom();
        return { messageDiv, messageText };
    }

    /* ---------- Typewriter Effect ---------- */
    function typeText(element, rawText, speed = 20, onDone = () => {}) {
        const parsedHTML = marked.parse(rawText);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = parsedHTML;

        const textContent = tempDiv.innerText;
        const finalHTML = tempDiv.innerHTML;

        let index = 0;
        let timerId = null;
        let stopped = false;

        function cleanup() {
            if (timerId) clearTimeout(timerId);
            timerId = null;
        }

        function stopNow() {
            stopped = true;
            cleanup();
            activeTypeController = null;
            updateSendButton();
        }

        function step() {
            if (stopped) return;
            if (index < textContent.length) {
                element.innerText = textContent.substring(0, index + 1);
                index++;
                scrollToBottom();
                timerId = setTimeout(step, speed);
            } else {
                cleanup();
                element.innerHTML = finalHTML;
                attachLinkHandlers(element);
                activeTypeController = null;
                updateSendButton();
                onDone();
            }
        }

        step();
        return { finishNow: stopNow };
    }

        /* ---------- Send Message ---------- */
        function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        appendMessage(message, 'user');
        userInput.value = '';

        // Show Typing Indicator
        const { messageDiv } = appendMessage('', 'bot', true);

        fetch(CHAT_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_message: message })
        })
        .then(res => res.json())
        .then(data => {
            // Remove any typing indicators safely
            const typingNodes = document.querySelectorAll('.typing-indicator');
            typingNodes.forEach(node => node.parentElement?.remove());

            // Append the bot's full message instantly (no typing animation)
            appendMessage(data.bot_reply || 'No response received.', 'bot');
        })
        .catch(err => {
            const typingNodes = document.querySelectorAll('.typing-indicator');
            typingNodes.forEach(node => node.parentElement?.remove());

            appendMessage('⚠️ Error: ' + err.message, 'bot');
        });
        }

    /* ---------- Event Listeners ---------- */
    sendButton.addEventListener('click', () => {
        if (activeTypeController) {
            activeTypeController.finishNow();
        } else {
            sendMessage();
        }
    });

    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !activeTypeController) {
            sendMessage();
        }
    });
});