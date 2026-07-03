document.addEventListener('DOMContentLoaded', () => {

    // ── Login Gate ────────────────────────────────────────────────────────────
    const loginOverlay  = document.getElementById('login-overlay');
    const loginBtn      = document.getElementById('login-btn');
    const loginUsername = document.getElementById('login-username');
    const loginPassword = document.getElementById('login-password');
    const loginError    = document.getElementById('login-error');

    function grantAccess() {
        loginOverlay.style.opacity = '0';
        setTimeout(() => { loginOverlay.style.display = 'none'; }, 500);
        sessionStorage.setItem('ld_authenticated', 'true');
    }

    // Skip login if already authenticated this session
    if (sessionStorage.getItem('ld_authenticated') === 'true') {
        loginOverlay.style.display = 'none';
    } else {
        if (loginUsername) loginUsername.focus();
    }

    async function attemptLogin() {
        const username = loginUsername.value.trim();
        const password = loginPassword.value;

        if (!username || !password) {
            loginError.textContent = 'OPERATOR ID AND ACCESS CODE REQUIRED';
            loginError.style.display = 'block';
            return;
        }

        // Visual feedback — disable button while request is in flight
        loginBtn.textContent = 'AUTHENTICATING...';
        loginBtn.disabled = true;
        loginError.style.display = 'none';

        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await res.json();

            if (data.success) {
                loginBtn.textContent = 'ACCESS GRANTED ✓';
                loginBtn.style.background = '#166534';
                loginBtn.style.color = '#fff';
                setTimeout(() => grantAccess(), 400);
            } else {
                // Shake the card and show the error
                loginError.textContent = 'ACCESS DENIED - INVALID CREDENTIALS';
                loginError.style.display = 'block';
                loginPassword.value = '';
                loginPassword.focus();
                loginBtn.textContent = 'SYSTEM LOGIN';
                loginBtn.disabled = false;
            }
        } catch (err) {
            loginError.textContent = 'SYSTEM ERROR - COULD NOT REACH SERVER';
            loginError.style.display = 'block';
            loginBtn.textContent = 'SYSTEM LOGIN';
            loginBtn.disabled = false;
        }
    }

    // Button click
    if (loginBtn) {
        loginBtn.addEventListener('click', attemptLogin);
    }

    // Enter key on either field submits the form
    [loginUsername, loginPassword].forEach(el => {
        if (el) {
            el.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') attemptLogin();
            });
        }
    });
    // ── End Login Gate ────────────────────────────────────────────────────────


    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const queueList = document.getElementById('upload-queue');
    const documentContainer = document.getElementById('document-container');
    const emptyState = document.getElementById('empty-state');
    const docBlockTemplate = document.getElementById('doc-block-template');
    
    // Export Data
    const exportBtn = document.getElementById('export-btn');
    const exportDocType = document.getElementById('export-doc-type');
    if (exportBtn && exportDocType) {
        exportBtn.addEventListener('click', () => {
            const docType = encodeURIComponent(exportDocType.value);
            window.location.href = `/api/export-data?doc_type=${docType}`;
        });
    }

    // Click to open file dialog
    dropZone.addEventListener('click', () => fileInput.click());

    // File input change
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
        fileInput.value = ''; // Reset
    });

    // Drag and Drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('border-green-400', 'bg-gray-800');
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-green-400', 'bg-gray-800');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-green-400', 'bg-gray-800');
        if (e.dataTransfer.files.length) {
            handleFiles(e.dataTransfer.files);
        }
    });

    function handleFiles(files) {
        if (files.length > 0) {
            emptyState.style.display = 'none';
        }
        
        Array.from(files).forEach(file => {
            // Add to queue UI
            const queueItemId = 'queue-' + Math.random().toString(36).substr(2, 9);
            addQueueItem(file.name, queueItemId);
            
            // Upload file
            uploadFile(file, queueItemId);
        });
    }

    function addQueueItem(filename, id) {
        const li = document.createElement('li');
        li.id = id;
        li.className = 'flex justify-between items-center text-gray-400 p-2 bg-gray-800 rounded border border-gray-700';
        li.innerHTML = `
            <span class="truncate w-3/4" title="${filename}">${filename}</span>
            <span class="status text-yellow-500 animate-pulse">Uploading...</span>
        `;
        queueList.appendChild(li);
    }

    function updateQueueItem(id, status, isError = false) {
        const li = document.getElementById(id);
        if (li) {
            const statusSpan = li.querySelector('.status');
            statusSpan.textContent = status;
            statusSpan.className = `status text-${isError ? 'red' : 'green'}-500`;
            setTimeout(() => { li.remove(); }, 3000); // Remove from queue after 3s
        }
    }

    async function uploadFile(file, queueItemId) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            
            const result = await response.json();
            
            if (result.status === 'processed') {
                updateQueueItem(queueItemId, 'Done');
                renderDocumentBlock(result, file);
            } else {
                updateQueueItem(queueItemId, 'Failed', true);
                console.error("Processing failed:", result.message);
            }
        } catch (error) {
            console.error('Upload error:', error);
            updateQueueItem(queueItemId, 'Error', true);
        }
    }

    function renderDocumentBlock(data, file) {
        // Clone template
        const templateNode = docBlockTemplate.content.cloneNode(true);
        const block = templateNode.querySelector('.document-block');
        
        // Populate static data
        block.querySelector('.doc-filename').textContent = data.filename;
        
        // Render actual image preview
        if (file) {
            const previewContainer = block.children[0]; // The left panel div
            const placeholder = previewContainer.querySelector('.text-gray-600');
            
            if (file.type.startsWith('image/')) {
                if (placeholder) placeholder.style.display = 'none';
                const imgUrl = URL.createObjectURL(file);
                
                // Wrapper for scroll and zoom
                const wrapper = document.createElement('div');
                wrapper.className = 'absolute inset-0 pt-10 pb-2 px-2 overflow-auto bg-black z-0 flex items-start justify-center';
                
                const img = document.createElement('img');
                img.src = imgUrl;
                let zoomLevel = 100;
                img.style.width = zoomLevel + '%';
                img.className = 'transition-all opacity-80';
                wrapper.appendChild(img);
                
                // Zoom Controls
                const controls = document.createElement('div');
                controls.className = 'absolute bottom-2 right-2 flex space-x-1 z-10 opacity-70 hover:opacity-100 transition-opacity';
                controls.innerHTML = `
                    <button type="button" class="zoom-out bg-gray-800 hover:bg-gray-700 text-white w-6 h-6 flex items-center justify-center rounded text-xs border border-gray-600">-</button>
                    <button type="button" class="zoom-reset bg-gray-800 hover:bg-gray-700 text-white w-6 h-6 flex items-center justify-center rounded text-[10px] border border-gray-600 font-bold">R</button>
                    <button type="button" class="zoom-in bg-gray-800 hover:bg-gray-700 text-white w-6 h-6 flex items-center justify-center rounded text-xs border border-gray-600">+</button>
                `;
                
                controls.querySelector('.zoom-in').addEventListener('click', () => {
                    zoomLevel += 30;
                    img.style.width = zoomLevel + '%';
                });
                controls.querySelector('.zoom-out').addEventListener('click', () => {
                    zoomLevel = Math.max(30, zoomLevel - 30);
                    img.style.width = zoomLevel + '%';
                });
                controls.querySelector('.zoom-reset').addEventListener('click', () => {
                    zoomLevel = 100;
                    img.style.width = zoomLevel + '%';
                });
                
                previewContainer.appendChild(wrapper);
                previewContainer.appendChild(controls);
                
                // Clean up object URL when block is removed to free memory
                block.querySelector('.remove-block-btn').addEventListener('click', () => {
                    setTimeout(() => URL.revokeObjectURL(imgUrl), 500);
                });
            } else if (file.name.endsWith('.pdf') || file.name.endsWith('.docx') || file.name.endsWith('.doc')) {
                if (placeholder) placeholder.style.display = 'none';
                
                // Document Icon/Preview
                const docPreview = document.createElement('div');
                docPreview.className = 'absolute inset-0 w-full h-full flex flex-col items-center justify-center bg-green-900 bg-opacity-20 p-4';
                docPreview.innerHTML = `
                    <svg class="w-16 h-16 text-green-500 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                    </svg>
                    <span class="text-green-400 font-bold text-sm tracking-widest uppercase">DOCUMENT RECORD</span>
                `;
                docPreview.style.zIndex = '0';
                previewContainer.appendChild(docPreview);
            }
        }
        
        block.querySelector('.doc-type').textContent = data.parsed_schema.document_type || "Unknown Document";
        
        const confPercent = Math.round((data.parsed_schema.confidence || 0) * 100);
        const confBadge = block.querySelector('.doc-confidence');
        confBadge.textContent = `CONF: ${confPercent}%`;
        
        if (confPercent < 80) {
            confBadge.classList.replace('bg-green-900', 'bg-yellow-900');
            confBadge.classList.replace('text-green-400', 'text-yellow-400');
            confBadge.classList.replace('border-green-700', 'border-yellow-700');
        }

        // Schema-Driven Form Generation
        const formContainer = block.querySelector('.dynamic-form');
        const fields = data.parsed_schema.fields || [];
        
        fields.forEach(field => {
            const wrapper = document.createElement('div');
            wrapper.className = 'flex flex-col mb-3';
            
            // Full width for textareas
            if (field.type === 'textarea') {
                wrapper.classList.add('col-span-2');
            }

            const label = document.createElement('label');
            label.className = 'text-xs text-gray-400 mb-1 tracking-wide uppercase';
            label.textContent = field.label + (field.required ? ' *' : '');
            label.setAttribute('for', `${field.id}-${data.filename}`); // pseudo-unique

            let inputElement;

            if (field.type === 'select' && field.options) {
                inputElement = document.createElement('select');
                field.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt;
                    option.textContent = opt;
                    if (field.value === opt) option.selected = true;
                    inputElement.appendChild(option);
                });
                inputElement.className = 'bg-gray-800 text-white border border-gray-600 rounded px-3 py-2 text-sm cyber-glow transition-all w-full';
            } else if (field.type === 'textarea') {
                inputElement = document.createElement('textarea');
                inputElement.rows = 3;
                if (field.value) inputElement.value = field.value;
                inputElement.className = 'bg-gray-800 text-white border border-gray-600 rounded px-3 py-2 text-sm cyber-glow transition-all w-full';
            } else if (field.type === 'table' && Array.isArray(field.value)) {
                wrapper.classList.add('col-span-2');
                const tableContainer = document.createElement('div');
                tableContainer.className = 'overflow-x-auto border border-gray-700 rounded cyber-glow bg-gray-900 shadow-inner mt-1';
                
                const table = document.createElement('table');
                table.className = 'w-full text-xs text-left text-gray-300';
                
                const headers = Object.keys(field.value[0] || {});
                
                const thead = document.createElement('thead');
                thead.className = 'bg-gray-800 text-green-400 font-bold uppercase tracking-wider border-b border-gray-700';
                const trHead = document.createElement('tr');
                headers.forEach(h => {
                    const th = document.createElement('th');
                    th.className = 'px-3 py-2 whitespace-nowrap border-r border-gray-700 last:border-r-0';
                    th.textContent = h;
                    trHead.appendChild(th);
                });
                thead.appendChild(trHead);
                table.appendChild(thead);
                
                const tbody = document.createElement('tbody');
                tbody.className = 'divide-y divide-gray-800';
                field.value.forEach(row => {
                    const tr = document.createElement('tr');
                    tr.className = 'hover:bg-gray-800 transition-colors';
                    headers.forEach(h => {
                        const td = document.createElement('td');
                        td.className = 'px-3 py-2 border-r border-gray-800 last:border-r-0 whitespace-pre-wrap';
                        td.textContent = row[h] || '';
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
                table.appendChild(tbody);
                tableContainer.appendChild(table);
                
                // Add a hidden input so the form serializer picks up the table data
                const hiddenInput = document.createElement('input');
                hiddenInput.type = 'hidden';
                hiddenInput.name = field.id;
                hiddenInput.value = JSON.stringify(field.value);
                wrapper.appendChild(hiddenInput);
                
                // Keep inputElement reference so we can set ID/Name
                inputElement = tableContainer;
            } else {
                inputElement = document.createElement('input');
                inputElement.type = field.type === 'number' ? 'number' : 'text';
                if (field.value) inputElement.value = field.value;
                inputElement.className = 'bg-gray-800 text-white border border-gray-600 rounded px-3 py-2 text-sm cyber-glow transition-all w-full';
            }

            // Apply standard attributes
            inputElement.id = `${field.id}-${data.filename}`;
            if (field.type !== 'table') {
                inputElement.name = field.id;
                if (field.required) inputElement.required = true;
            }

            wrapper.appendChild(label);
            wrapper.appendChild(inputElement);
            formContainer.appendChild(wrapper);
        });
        
        // Inject an extra static "Operator's Notes" field that is always available
        const operatorWrapper = document.createElement('div');
        operatorWrapper.className = 'flex flex-col mb-3 col-span-2 mt-2';
        
        const operatorLabel = document.createElement('label');
        operatorLabel.className = 'text-xs text-gray-400 mb-1 tracking-wide uppercase';
        operatorLabel.textContent = "Operator's Notes";
        operatorLabel.setAttribute('for', `operator-notes-${data.filename}`);
        
        const operatorInput = document.createElement('textarea');
        operatorInput.rows = 2;
        operatorInput.id = `operator-notes-${data.filename}`;
        operatorInput.name = 'operators_notes';
        operatorInput.className = 'bg-gray-800 text-white border border-gray-600 rounded px-3 py-2 text-sm cyber-glow transition-all w-full placeholder-gray-600';
        operatorInput.placeholder = "Enter manual observations or overrides here...";
        
        operatorWrapper.appendChild(operatorLabel);
        operatorWrapper.appendChild(operatorInput);
        formContainer.appendChild(operatorWrapper);

        // Event listener for removal
        block.querySelector('.remove-block-btn').addEventListener('click', () => {
            block.style.opacity = '0';
            setTimeout(() => {
                block.remove();
                if (documentContainer.querySelectorAll('.document-block').length === 0) {
                    emptyState.style.display = 'flex';
                }
            }, 300);
        });
        
        // Event listener for Database Commit
        const commitBtn = block.querySelector('.bg-green-700');
        if (commitBtn) {
            commitBtn.addEventListener('click', async () => {
                const docType = data.parsed_schema.document_type || "Unknown Document";
                const fieldsData = {};
                
                // Gather all input values
                const inputs = formContainer.querySelectorAll('input, select, textarea');
                inputs.forEach(input => {
                    fieldsData[input.name] = input.value;
                });
                
                try {
                    commitBtn.textContent = 'SAVING...';
                    commitBtn.disabled = true;
                    
                    const saveFormData = new FormData();
                    saveFormData.append("filename", data.filename);
                    saveFormData.append("document_type", docType);
                    saveFormData.append("fields_data", JSON.stringify(fieldsData));
                    if (file) saveFormData.append("file", file);
                    
                    const res = await fetch('/api/save-record', {
                        method: 'POST',
                        body: saveFormData
                    });
                    
                    if (res.ok) {
                        commitBtn.textContent = 'SAVED';
                        commitBtn.classList.replace('bg-green-700', 'bg-gray-700');
                        // Animate and remove
                        setTimeout(() => {
                            block.style.opacity = '0';
                            setTimeout(() => {
                                block.remove();
                                if (documentContainer.querySelectorAll('.document-block').length === 0) {
                                    emptyState.style.display = 'flex';
                                }
                            }, 300);
                        }, 500);
                    } else {
                        commitBtn.textContent = 'ERROR';
                        commitBtn.disabled = false;
                    }
                } catch (err) {
                    console.error(err);
                    commitBtn.textContent = 'ERROR';
                    commitBtn.disabled = false;
                }
            });
        }

        // Prepend to top of container
        documentContainer.insertBefore(block, documentContainer.children[1]); 
    }

    // Chat Terminal Logic
    const chatTerminal = document.getElementById('chat-terminal');
    const chatHeader = document.getElementById('chat-header');
    const chatToggleIcon = document.getElementById('chat-toggle-icon');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    if (chatHeader) {
        let isChatOpen = false;
        chatHeader.addEventListener('click', () => {
            isChatOpen = !isChatOpen;
            if (isChatOpen) {
                chatTerminal.style.transform = 'translateY(0)';
                chatToggleIcon.textContent = '▼';
                chatInput.focus();
            } else {
                chatTerminal.style.transform = 'translateY(calc(100% - 40px))';
                chatToggleIcon.textContent = '▲';
            }
        });

        // Expose function globally so the sidebar button can use it
        window.submitChatQuery = async function(queryStr) {
            // Force chat window open if it's closed
            if (!isChatOpen) {
                isChatOpen = true;
                chatTerminal.style.transform = 'translateY(0)';
                chatToggleIcon.textContent = '▼';
            }
            
            chatInput.value = '';
            appendChatMessage(`> ${queryStr}`, 'text-white');
            
            const loadingId = 'loading-' + Date.now();
            appendChatMessage(`> Analyzing Database...`, 'text-yellow-500 animate-pulse', loadingId);
            
            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: queryStr })
                });
                
                const data = await res.json();
                document.getElementById(loadingId)?.remove();
                
                appendChatMessage(`> ${data.response}`, 'text-green-400');
                if (data.data && data.data.length > 0) {
                    appendChatTable(data.data);
                }
            } catch (err) {
                document.getElementById(loadingId)?.remove();
                appendChatMessage(`> Error connecting to NLP engine.`, 'text-red-500');
            }
        };

        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && chatInput.value.trim() !== '') {
                window.submitChatQuery(chatInput.value.trim());
            }
        });
        
        function appendChatMessage(text, className, id = null) {
            const div = document.createElement('div');
            if (id) div.id = id;
            div.className = className;
            div.textContent = text;
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        
        function appendChatTable(dataArray) {
            if (!dataArray || dataArray.length === 0) return;
            
            const table = document.createElement('table');
            table.className = 'w-full text-left mt-2 mb-4 border-collapse border border-gray-700 text-[10px] text-gray-300';
            
            // Header
            const thead = document.createElement('thead');
            const trHead = document.createElement('tr');
            trHead.className = 'bg-gray-800 text-gray-400';
            Object.keys(dataArray[0]).forEach(key => {
                const th = document.createElement('th');
                th.className = 'border border-gray-700 p-1 font-bold';
                th.textContent = key;
                trHead.appendChild(th);
            });
            thead.appendChild(trHead);
            table.appendChild(thead);
            
            // Body
            const tbody = document.createElement('tbody');
            dataArray.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-800 hover:bg-gray-800 transition-colors';
                Object.values(row).forEach(val => {
                    const td = document.createElement('td');
                    td.className = 'border border-gray-800 p-1 truncate max-w-[100px]';
                    td.textContent = val;
                    td.title = val;
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            
            chatMessages.appendChild(table);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
});
