document.addEventListener('DOMContentLoaded', () => {
    // ---------------------------------------------------------
    // System Clock
    // ---------------------------------------------------------
    const clockElement = document.getElementById('system-clock');
    function updateClock() {
        const now = new Date();
        const yyyy = now.getFullYear();
        const mm = String(now.getMonth() + 1).padStart(2, '0');
        const dd = String(now.getDate()).padStart(2, '0');
        const hh = String(now.getHours()).padStart(2, '0');
        const min = String(now.getMinutes()).padStart(2, '0');
        const sec = String(now.getSeconds()).padStart(2, '0');
        clockElement.textContent = `${yyyy}.${mm}.${dd} ${hh}:${min}:${sec}`;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // ---------------------------------------------------------
    // System Status Log
    // ---------------------------------------------------------
    const statusLog = document.getElementById('status-log');
    function logMessage(level, message) {
        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');
        
        const entry = document.createElement('div');
        let colorClass = 'text-cyan-500';
        if (level === 'ERROR') colorClass = 'text-red-500';
        if (level === 'WARN') colorClass = 'text-amber-500';

        entry.innerHTML = `<span class="text-gray-500">[${timeStr}]</span> <span class="font-bold ${colorClass}">[${level}]</span> <span class="text-gray-300">${message}</span>`;
        
        statusLog.appendChild(entry);
        statusLog.scrollTop = statusLog.scrollHeight;
    }

    logMessage('INFO', 'NODE-774A INITIALIZED AND AWAITING SECURE INGESTION.');

    // ---------------------------------------------------------
    // Industrial Asset Tags
    // ---------------------------------------------------------
    const tagInput = document.getElementById('tag-input');
    const tagsContainer = document.getElementById('tags-container');
    let tags = [];

    function renderTags() {
        tagsContainer.innerHTML = '';
        tags.forEach((tag, index) => {
            const tagEl = document.createElement('div');
            tagEl.className = 'flex items-center gap-1 bg-cyan-900/40 border border-cyan-700 text-cyan-300 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider';
            
            const textSpan = document.createElement('span');
            textSpan.textContent = tag;
            
            const removeBtn = document.createElement('button');
            removeBtn.innerHTML = '&times;';
            removeBtn.className = 'text-cyan-500 hover:text-cyan-300 font-bold ml-1 text-xs outline-none';
            removeBtn.onclick = () => {
                tags.splice(index, 1);
                renderTags();
                logMessage('INFO', `TAG REMOVED: ${tag}`);
            };

            tagEl.appendChild(textSpan);
            tagEl.appendChild(removeBtn);
            tagsContainer.appendChild(tagEl);
        });
    }

    tagInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = tagInput.value.trim().toUpperCase();
            if (val && !tags.includes(val)) {
                tags.push(val);
                tagInput.value = '';
                renderTags();
                logMessage('INFO', `TAG ADDED: ${val}`);
            }
        }
    });

    // ---------------------------------------------------------
    // File Upload & Drag-and-Drop (Pane 01)
    // ---------------------------------------------------------
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-upload');
    const resultContainer = document.getElementById('result-container');
    const resultImage = document.getElementById('result-image');
    const downloadBtn = document.getElementById('download-btn');
    const resetBtn = document.getElementById('reset-btn');

    let currentBase64 = null;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.add('border-cyan-500', 'bg-[#0b101c]');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.remove('border-cyan-500', 'bg-[#0b101c]');
        }, false);
    });

    dropZone.addEventListener('drop', (e) => handleFiles(e.dataTransfer.files), false);
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', function() { handleFiles(this.files); });

    function handleFiles(files) {
        if (files.length === 0) return;
        const file = files[0];
        
        if (!['image/jpeg', 'image/png'].includes(file.type)) {
            logMessage('ERROR', 'INVALID FILE TYPE. ONLY JPEG/PNG ALLOWED.');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            logMessage('ERROR', 'FILE SIZE EXCEEDS MAXIMUM SECURE LIMIT (10MB).');
            return;
        }

        uploadFile(file);
    }

    function uploadFile(file) {
        logMessage('INFO', `INITIATING INGESTION: ${file.name} (${(file.size/1024).toFixed(1)} KB)`);
        
        // Visual loading state inside drop zone
        dropZone.innerHTML = `<div class="text-cyan-500 animate-pulse font-bold tracking-widest text-sm">PROCESSING ARTIFACT...</div>`;
        dropZone.style.pointerEvents = 'none';

        const formData = new FormData();
        formData.append('file', file);

        fetch('/api/process', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.detail || "SERVER FAULT DURING INGESTION.");
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.image_base64) {
                logMessage('INFO', 'PIPELINE COMPLETE: GRAYSCALE -> ADAPTIVE BINARIZE -> DESKEW.');
                
                // Show result in Pane 01
                currentBase64 = data.image_base64;
                resultImage.src = `data:image/jpeg;base64,${currentBase64}`;
                
                dropZone.classList.add('hidden');
                resultContainer.classList.remove('hidden');
            } else {
                throw new Error(data.error || "UNKNOWN FAULT.");
            }
        })
        .catch(error => {
            logMessage('ERROR', error.message);
            resetDropZone();
        });
    }

    function resetDropZone() {
        dropZone.style.pointerEvents = 'auto';
        dropZone.innerHTML = `
            <svg class="h-16 w-16 text-gray-600 mb-4 group-hover:text-cyan-500 drop-shadow-[0_0_5px_rgba(6,182,212,0)] group-hover:drop-shadow-[0_0_10px_rgba(6,182,212,0.5)] transition-all" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
            </svg>
            <div class="text-sm font-semibold text-gray-400 group-hover:text-cyan-400">SECURE FILE UPLOAD</div>
            <div class="text-xs text-gray-600 mt-2">DRAG & DROP OR CLICK TO INGEST (JPEG/PNG)</div>
            <input id="file-upload" type="file" class="hidden" accept=".jpg,.jpeg,.png">
        `;
        // Re-bind the file input listener since we replaced innerHTML
        const newFileInput = document.getElementById('file-upload');
        newFileInput.addEventListener('change', function() { handleFiles(this.files); });
    }

    // Download action
    downloadBtn.addEventListener('click', () => {
        if (currentBase64) {
            logMessage('INFO', 'ARTIFACT DOWNLOAD INITIATED.');
            const a = document.createElement('a');
            a.href = `data:image/jpeg;base64,${currentBase64}`;
            a.download = `SECURE_ARTIFACT_${Date.now()}.jpg`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }
    });

    // Reset action
    resetBtn.addEventListener('click', () => {
        logMessage('WARN', 'NODE RESET INITIATED BY OPERATOR.');
        currentBase64 = null;
        resultContainer.classList.add('hidden');
        dropZone.classList.remove('hidden');
        resetDropZone();
        
        // Clear forms
        document.querySelectorAll('input[type="text"], input[type="date"], textarea').forEach(el => el.value = '');
        tags = [];
        renderTags();
        logMessage('INFO', 'NODE RESET COMPLETE.');
    });

    document.getElementById('submit-btn').addEventListener('click', () => {
        if (!currentBase64) {
            logMessage('ERROR', 'SUBMISSION BLOCKED: NO ARTIFACT DIGITIZED.');
            return;
        }
        logMessage('INFO', 'SUBMITTING CLASSIFIED RECORD TO LOCAL VAULT...');
        setTimeout(() => {
            logMessage('INFO', 'RECORD SECURELY COMMITTED.');
            resetBtn.click();
        }, 800);
    });
});
