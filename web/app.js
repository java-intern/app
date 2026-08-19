// ==========================================================================
// AdaptiveTrust zero-trust Client Logic
// ==========================================================================

// ==========================================================================
// Dynamic API Base URL Config & Server Settings Modal
// ==========================================================================
function getApiBase() {
    let base = (localStorage.getItem('adaptivetrust_api_url') || window.API_BASE_URL || 'https://backend-yen7.onrender.com/api/v1').trim().replace(/\/+$/, '');
    if (base && !base.endsWith('/api/v1')) {
        base = `${base}/api/v1`;
    }
    return base;
}

function openBackendSettingsModal() {
    const modal = document.getElementById('backend-settings-modal');
    const input = document.getElementById('settings-api-url');
    const statusBox = document.getElementById('connection-status-box');
    
    if (input) {
        input.value = getApiBase();
    }
    if (statusBox) {
        statusBox.style.display = 'none';
        statusBox.innerHTML = '';
    }
    if (modal) {
        modal.classList.add('active');
    }
}

function closeBackendSettingsModal() {
    const modal = document.getElementById('backend-settings-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function setApiPreset(url) {
    const input = document.getElementById('settings-api-url');
    if (input) {
        input.value = url;
    }
}

async function testBackendConnection() {
    const input = document.getElementById('settings-api-url');
    const statusBox = document.getElementById('connection-status-box');
    if (!input || !statusBox) return;

    let targetUrl = input.value.trim().replace(/\/+$/, '');
    if (!targetUrl) {
        statusBox.style.display = 'block';
        statusBox.style.background = 'rgba(239, 68, 68, 0.15)';
        statusBox.style.border = '1px solid rgba(239, 68, 68, 0.4)';
        statusBox.style.color = '#f87171';
        statusBox.innerHTML = '❌ Please enter a valid URL.';
        return;
    }

    statusBox.style.display = 'block';
    statusBox.style.background = 'rgba(245, 158, 11, 0.15)';
    statusBox.style.border = '1px solid rgba(245, 158, 11, 0.4)';
    statusBox.style.color = '#fbbf24';
    statusBox.innerHTML = '⏳ Testing connection to server...';

    const startTime = Date.now();
    try {
        let healthUrl = targetUrl.endsWith('/api/v1') 
            ? `${targetUrl.slice(0, -7)}/health` 
            : `${targetUrl}/health`;

        let res;
        try {
            res = await fetch(healthUrl, { method: 'GET', signal: AbortSignal.timeout(4000) });
        } catch (e) {
            res = await fetch(`${targetUrl}/health`, { method: 'GET', signal: AbortSignal.timeout(4000) });
        }

        const elapsed = Date.now() - startTime;
        if (res.ok) {
            statusBox.style.background = 'rgba(16, 185, 129, 0.15)';
            statusBox.style.border = '1px solid rgba(16, 185, 129, 0.4)';
            statusBox.style.color = '#34d399';
            statusBox.innerHTML = `✅ Server Reachable & Healthy! (${elapsed}ms latency)`;
        } else {
            statusBox.style.background = 'rgba(239, 68, 68, 0.15)';
            statusBox.style.border = '1px solid rgba(239, 68, 68, 0.4)';
            statusBox.style.color = '#f87171';
            statusBox.innerHTML = `⚠️ Connection responded with HTTP ${res.status}.`;
        }
    } catch (err) {
        statusBox.style.background = 'rgba(239, 68, 68, 0.15)';
        statusBox.style.border = '1px solid rgba(239, 68, 68, 0.4)';
        statusBox.style.color = '#f87171';
        statusBox.innerHTML = `❌ Connection Failed: ${err.message}. Ensure backend server is running.`;
    }
}

function saveBackendSettings() {
    const input = document.getElementById('settings-api-url');
    if (!input) return;

    let targetUrl = input.value.trim().replace(/\/+$/, '');
    if (!targetUrl) {
        showNotification('Please enter a valid Backend API URL', 'error');
        return;
    }

    localStorage.setItem('adaptivetrust_api_url', targetUrl);
    showNotification(`Backend URL updated. Reloading...`, 'success');
    closeBackendSettingsModal();
    
    setTimeout(() => {
        location.reload();
    }, 400);
}

function resetBackendSettingsToDefault() {
    localStorage.removeItem('adaptivetrust_api_url');
    showNotification(`Reset to default URL. Reloading...`, 'info');
    closeBackendSettingsModal();

    setTimeout(() => {
        location.reload();
    }, 400);
}

// Global variables to track state
let activeStreamReader = null;
let activeStreamController = null;
let currentUserId = null;
let currentCompanyId = null;
let currentRole = null;
let selectedEmployeeId = null;

// ==========================================================================
// Initial Page Load & Routing
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    // Check if token exists
    const token = localStorage.getItem('access_token');
    if (token) {
        try {
            const claims = decodeToken(token);
            currentUserId = claims.sub;
            currentCompanyId = claims.company_id;
            currentRole = claims.role;
            
            showNotification('Session restored successfully.', 'success');
            
            if (currentRole === 'SUPER_ADMIN') {
                showView('super-admin');
                initSuperAdminDashboard(claims);
            } else if (currentRole === 'ADMIN') {
                showView('admin');
                initAdminDashboard(claims);
            } else {
                showView('employee');
                initEmployeeDashboard(claims);
            }
        } catch (e) {
            console.error('Failed to parse saved token:', e);
            logout();
        }
    } else {
        showView('auth');
    }
});

// Switch active view panels
function showView(viewName) {
    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    
    const targetPanel = document.getElementById(`view-${viewName}`);
    if (targetPanel) {
        targetPanel.classList.add('active');
    }
}

// Switch authentication tabs
function switchAuthTab(tabName) {
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.classList.remove('active');
        tab.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.auth-form').forEach(form => {
        form.classList.remove('active');
    });
    
    document.getElementById(`tab-${tabName}`).classList.add('active');
    document.getElementById(`tab-${tabName}`).setAttribute('aria-selected', 'true');
    document.getElementById(`form-${tabName}`).classList.add('active');
}

// ==========================================================================
// Token Decoding Utility (Manual Base64 parse to prevent extra libraries)
// ==========================================================================
function decodeToken(token) {
    const parts = token.split('.');
    if (parts.length !== 3) {
        throw new Error('Invalid JWT Token format');
    }
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(atob(payload).split('').map(c => {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    
    return JSON.parse(jsonPayload);
}

// Helper to make authenticated requests
async function makeRequest(endpoint, options = {}) {
    const token = localStorage.getItem('access_token');
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {})
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    const baseUrl = getApiBase();
    const targetUrl = endpoint.startsWith('http') ? endpoint : `${baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
    
    let response;
    try {
        response = await fetch(targetUrl, {
            ...options,
            headers
        });
    } catch (networkErr) {
        console.error('Fetch network error:', targetUrl, networkErr);
        if (window.location.protocol === 'https:' && targetUrl.startsWith('http:')) {
            throw new Error('Mixed Content Security Block: Web is HTTPS but Backend URL is HTTP. Please update Backend URL in Settings (⚙️) to HTTPS.');
        }
        throw new Error('Could not connect to backend server. If using Render, the server may take ~30s to wake up, or check your Backend URL in Settings (⚙️).');
    }
    
    if (response.status === 401) {
        showNotification('Session expired. Please login again.', 'error');
        logout();
        throw new Error('Unauthorized');
    }
    
    if (!response.ok) {
        let errorMsg = `Request failed (${response.status})`;
        try {
            const errData = await response.json();
            if (typeof errData.detail === 'string') {
                errorMsg = errData.detail;
            } else if (Array.isArray(errData.detail)) {
                errorMsg = errData.detail.map(e => e.msg || e.detail || JSON.stringify(e)).join(', ');
            } else if (errData.message) {
                errorMsg = errData.message;
            }
        } catch (e) {
            errorMsg = `Server Error (${response.status}: ${response.statusText})`;
        }
        throw new Error(errorMsg);
    }
    
    return response.json();
}

// ==========================================================================
// Authentication Handlers & Tab Switcher
// ==========================================================================
function switchAuthTab(tabName, targetEmail = null) {
    const tabs = ['login', 'admin-signup', 'emp-signup', 'verify'];
    tabs.forEach(t => {
        const tabEl = document.getElementById(`tab-${t}`);
        const formEl = document.getElementById(`form-${t}`);
        if (tabEl) {
            tabEl.classList.toggle('active', t === tabName);
            tabEl.style.display = (t === 'verify' && tabName !== 'verify') ? 'none' : (t === 'verify' ? 'block' : '');
        }
        if (formEl) {
            formEl.classList.toggle('active', t === tabName);
        }
    });

    if (tabName === 'verify' && targetEmail) {
        document.getElementById('verify-display-email').textContent = targetEmail;
        document.getElementById('verify-email-hidden').value = targetEmail;
        const verifyOtpInput = document.getElementById('verify-otp');
        if (verifyOtpInput) verifyOtpInput.value = '';
    }
}

async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    
    try {
        const data = await makeRequest('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password })
        });

        if (data.status === 'otp_required') {
            showNotification('A 6-digit verification code has been sent to your email.', 'info');
            switchAuthTab('verify', email);
            return;
        }

        if (data.access_token) {
            localStorage.setItem('access_token', data.access_token);
            const claims = decodeToken(data.access_token);
            currentUserId = claims.sub;
            currentCompanyId = claims.company_id;
            currentRole = claims.role;
            
            showNotification('Login successful!', 'success');
            
            if (currentRole === 'SUPER_ADMIN') {
                showView('super-admin');
                initSuperAdminDashboard(claims);
            } else if (currentRole === 'ADMIN') {
                showView('admin');
                initAdminDashboard(claims);
            } else {
                showView('employee');
                initEmployeeDashboard(claims);
            }
        }
    } catch (err) {
        if (err.message && err.message.includes('email_not_verified')) {
            showNotification('Email is not verified yet. Please enter the 6-digit code sent to your email.', 'error');
            switchAuthTab('verify', email);
        } else {
            showNotification(`Login failed: ${err.message}`, 'error');
        }
    }
}

async function handleAdminSignUp(event) {
    event.preventDefault();
    const full_name = document.getElementById('admin-name').value;
    const email = document.getElementById('admin-email').value;
    const password = document.getElementById('admin-password').value;
    const company_name = document.getElementById('admin-company').value;
    
    try {
        await makeRequest('/auth/register/admin', {
            method: 'POST',
            body: JSON.stringify({ email, password, full_name, company_name })
        });
        
        showNotification('Workspace created! A 6-digit verification code was sent to your email.', 'success');
        switchAuthTab('verify', email);
    } catch (err) {
        showNotification(`Registration failed: ${err.message}`, 'error');
    }
}

async function handleEmployeeSignUp(event) {
    event.preventDefault();
    const full_name = document.getElementById('emp-name').value;
    const email = document.getElementById('emp-email').value;
    const password = document.getElementById('emp-password').value;
    const company_code = document.getElementById('emp-code').value.toUpperCase().trim();
    
    try {
        await makeRequest('/auth/register/employee', {
            method: 'POST',
            body: JSON.stringify({ email, password, full_name, company_code })
        });
        
        showNotification('Profile registered! A 6-digit verification code was sent to your email.', 'success');
        switchAuthTab('verify', email);
    } catch (err) {
        showNotification(`Registration failed: ${err.message}`, 'error');
    }
}

async function handleVerifyEmail(event) {
    event.preventDefault();
    const email = document.getElementById('verify-email-hidden').value || document.getElementById('login-email').value;
    const code = document.getElementById('verify-otp').value.trim();

    if (!code || code.length !== 6) {
        showNotification('Please enter a valid 6-digit verification code.', 'error');
        return;
    }

    try {
        const res = await makeRequest('/auth/verify-login-otp', {
            method: 'POST',
            body: JSON.stringify({ email, code })
        });

        if (res.access_token) {
            localStorage.setItem('access_token', res.access_token);
            const claims = decodeToken(res.access_token);
            currentUserId = claims.sub;
            currentCompanyId = claims.company_id;
            currentRole = claims.role;

            showNotification('Verification successful! Logging in...', 'success');

            if (currentRole === 'SUPER_ADMIN') {
                showView('super-admin');
                initSuperAdminDashboard(claims);
            } else if (currentRole === 'ADMIN') {
                showView('admin');
                initAdminDashboard(claims);
            } else {
                showView('employee');
                initEmployeeDashboard(claims);
            }
        } else {
            showNotification('Email verified successfully! You can now log in.', 'success');
            document.getElementById('login-email').value = email;
            switchAuthTab('login');
        }
    } catch (err) {
        try {
            await makeRequest('/auth/verify-email', {
                method: 'POST',
                body: JSON.stringify({ email, code })
            });
            showNotification('Email verified successfully! You can now log in.', 'success');
            document.getElementById('login-email').value = email;
            switchAuthTab('login');
        } catch (e) {
            showNotification(`Verification failed: ${err.message}`, 'error');
        }
    }
}

async function handleResendCode() {
    const email = document.getElementById('verify-email-hidden').value || document.getElementById('login-email').value;
    if (!email) {
        showNotification('No target email address specified.', 'error');
        return;
    }

    try {
        await makeRequest('/auth/resend-code', {
            method: 'POST',
            body: JSON.stringify({ email })
        });
        showNotification(`A new 6-digit code has been sent to ${email}`, 'success');
    } catch (err) {
        showNotification(`Failed to resend code: ${err.message}`, 'error');
    }
}

function logout() {
    localStorage.removeItem('access_token');
    currentUserId = null;
    currentCompanyId = null;
    currentRole = null;
    
    // Close SSE streams if open
    if (activeStreamController) {
        activeStreamController.abort();
        activeStreamController = null;
    }
    
    // Clear forms
    document.getElementById('form-login').reset();
    document.getElementById('form-admin-signup').reset();
    document.getElementById('form-emp-signup').reset();
    
    showView('auth');
    showNotification('Logged out successfully.', 'info');
}

// ==========================================================================
// Admin Dashboard Control Logic
// ==========================================================================
async function initAdminDashboard(claims) {
    document.getElementById('admin-user-display').textContent = 'Admin Console';
    document.getElementById('admin-company-display').textContent = `Workspace ID: ${claims.company_id.slice(0, 8)}...`;
    
    // Initial fetches
    await refreshAdminStats();
    await loadAdminDirectory();
    
    // Connect to real-time events via custom SSE fetch loop (supports Auth Header)
    startSseStream();
}

async function refreshAdminStats() {
    try {
        const stats = await makeRequest('/admin/dashboard');
        document.getElementById('metric-total-users').textContent = stats.total_users;
        document.getElementById('metric-active-users').textContent = stats.active_user_count;
        document.getElementById('metric-risk-alerts').textContent = stats.risk_alerts_count;
        
        // Display the 8-character Invite Code in the navbar header
        if (stats.company_code) {
            document.getElementById('admin-company-display').textContent = `Invite Code: ${stats.company_code}`;
            document.getElementById('admin-company-display').title = "Share this 8-character code with employees to register.";
        }
    } catch (err) {
        console.error('Failed to load dashboard metrics:', err);
    }
}

async function loadAdminDirectory() {
    const role = document.getElementById('admin-filter-role').value;
    const sort_by = document.getElementById('admin-sort-by').value;
    
    let endpoint = `/admin/employees/search?sort_by=${sort_by}`;
    if (role) {
        endpoint += `&role=${role}`;
    }
    
    try {
        const employees = await makeRequest(endpoint);
        const tbody = document.getElementById('directory-tbody');
        tbody.innerHTML = '';
        
        if (employees.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No employees matches selection.</td></tr>`;
            return;
        }
        
        employees.forEach(emp => {
            const tr = document.createElement('tr');
            
            // Format Last Seen
            let lastSeenStr = 'Never';
            if (emp.last_seen_at) {
                lastSeenStr = new Date(emp.last_seen_at).toLocaleTimeString();
            }
            
            // Format Coordinates
            let locStr = 'No Telemetry';
            if (typeof emp.last_lat === 'number' && typeof emp.last_lon === 'number') {
                locStr = `${emp.last_lat.toFixed(4)}, ${emp.last_lon.toFixed(4)}`;
            }
            
            const scoreClass = getScoreColorClass(emp.current_score);
            
            tr.innerHTML = `
                <td><span class="text-bold">${emp.full_name}</span><br><small class="text-muted">${emp.email}</small></td>
                <td><span class="badge ${emp.role === 'ADMIN' ? 'badge-cyan' : 'badge-purple'}">${emp.role}</span></td>
                <td><span class="score-badge ${scoreClass}">${emp.current_score}</span></td>
                <td><span class="text-bold text-${getScoreColorText(emp.current_score)}">${emp.status}</span></td>
                <td><small>${locStr}</small></td>
                <td><small>${lastSeenStr}</small></td>
            `;
            
            tr.onclick = () => openAdminModal(emp);
            tbody.appendChild(tr);
        });
    } catch (err) {
        showNotification(`Failed to load directory: ${err.message}`, 'error');
    }
}

// Score Color mappings
function getScoreColorClass(score) {
    if (score >= 70) return 'score-green';
    if (score >= 40) return 'score-yellow';
    return 'score-red';
}
function getScoreColorText(score) {
    if (score >= 70) return 'green';
    if (score >= 40) return 'warn';
    return 'red';
}

// SSE Custom stream reader with Auth Header support
async function startSseStream() {
    if (activeStreamController) {
        activeStreamController.abort();
    }
    
    activeStreamController = new AbortController();
    const token = localStorage.getItem('access_token');
    
    try {
        const response = await fetch(`${getApiBase()}/sync/stream`, {
            headers: { 'Authorization': `Bearer ${token}` },
            signal: activeStreamController.signal
        });
        
        if (!response.ok) {
            throw new Error(`SSE stream failed: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // save remainder
            
            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data: ')) {
                    const dataStr = trimmed.slice(6);
                    try {
                        const data = JSON.parse(dataStr);
                        addLiveTelemetryEvent(data);
                        // Refresh metrics and directory listing
                        refreshAdminStats();
                        loadAdminDirectory();
                    } catch (e) {
                        console.error('Failed to parse SSE JSON:', e);
                    }
                }
            }
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error('SSE Stream Connection Error:', err);
            // Retry after 5s
            setTimeout(startSseStream, 5000);
        }
    }
}

function addLiveTelemetryEvent(event) {
    const feed = document.getElementById('live-stream-feed');
    const entry = document.createElement('div');
    
    const scoreTextClass = getScoreColorText(event.current_score);
    entry.className = `stream-log-entry log-${scoreTextClass}`;
    
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `
        <span class="log-time">[${time}]</span> 
        <strong>${event.name}</strong> (${event.role}): score updated to 
        <span class="text-bold text-${scoreTextClass}">${event.current_score}</span> (${event.status}). <br>
        <small class="text-muted">Loc: ${event.location.lat.toFixed(4)}, ${event.location.lon.toFixed(4)} | Reason: ${event.cause_of_change}</small>
    `;
    
    feed.insertBefore(entry, feed.firstChild);
    
    // Cap log entries at 50 to prevent DOM slowdowns
    if (feed.childNodes.length > 50) {
        feed.removeChild(feed.lastChild);
    }
}

function clearLiveFeed() {
    const feed = document.getElementById('live-stream-feed');
    feed.innerHTML = `
        <div class="stream-log-entry system-msg">
            <span class="log-time">[System]</span> Live stream cleared. Waiting for telemetry check-ins...
        </div>
    `;
}

// Modal management for admin overrides
function openAdminModal(employee) {
    selectedEmployeeId = employee.id;
    document.getElementById('modal-employee-name').textContent = `Manage: ${employee.full_name}`;
    document.getElementById('modal-employee-email').textContent = employee.email;
    document.getElementById('modal-employee-status').textContent = employee.status;
    document.getElementById('modal-employee-score').textContent = employee.current_score;
    document.getElementById('modal-employee-score').className = `text-bold text-${getScoreColorText(employee.current_score)}`;
    
    document.getElementById('admin-modal').classList.add('active');
}

function closeAdminModal() {
    document.getElementById('admin-modal').classList.remove('active');
    selectedEmployeeId = null;
}

// Override Requests
async function triggerBoostOverride() {
    if (!selectedEmployeeId) return;
    try {
        const res = await makeRequest('/admin/override/boost', {
            method: 'POST',
            body: JSON.stringify({ user_id: selectedEmployeeId })
        });
        showNotification(res.message, 'success');
        closeAdminModal();
        await refreshAdminStats();
        await loadAdminDirectory();
    } catch (err) {
        showNotification(`Failed to boost: ${err.message}`, 'error');
    }
}

async function triggerMfaOverride() {
    if (!selectedEmployeeId) return;
    try {
        const res = await makeRequest('/admin/override/mfa', {
            method: 'POST',
            body: JSON.stringify({ user_id: selectedEmployeeId })
        });
        showNotification(res.message, 'success');
        closeAdminModal();
    } catch (err) {
        showNotification(`Failed to trigger MFA: ${err.message}`, 'error');
    }
}

async function triggerLockOverride() {
    if (!selectedEmployeeId) return;
    try {
        const res = await makeRequest('/admin/override/lock', {
            method: 'POST',
            body: JSON.stringify({ user_id: selectedEmployeeId })
        });
        showNotification(res.message, 'success');
        closeAdminModal();
        await refreshAdminStats();
        await loadAdminDirectory();
    } catch (err) {
        showNotification(`Failed to suspend user: ${err.message}`, 'error');
    }
}

// ==========================================================================
// Employee Self-Service Dashboard Logic
// ==========================================================================
async function initEmployeeDashboard(claims) {
    document.getElementById('employee-user-display').textContent = 'My Secure Device Portal';
    document.getElementById('employee-company-display').textContent = `Workspace ID: ${claims.company_id.slice(0, 8)}...`;
    
    await refreshEmployeeDashboard();
}

async function refreshEmployeeDashboard() {
    try {
        // Fetch current score & status
        const dashData = await makeRequest('/employee/dashboard');
        
        // Update Gauge Dial
        document.getElementById('gauge-score-value').textContent = dashData.current_score;
        
        const badge = document.getElementById('gauge-status-value');
        badge.textContent = dashData.status;
        badge.className = 'badge'; // Reset class
        
        const scoreClass = getScoreColorText(dashData.current_score);
        if (scoreClass === 'green') badge.classList.add('badge-cyan');
        else if (scoreClass === 'warn') badge.classList.add('badge-cyan'); // Yellow badge or customizable
        else badge.classList.add('badge-purple'); // Red / Inactive
        
        // Update SVG arc length
        const circle = document.getElementById('gauge-arc-filled');
        circle.style.stroke = `var(--color-${scoreClass === 'green' ? 'active' : (scoreClass === 'warn' ? 'warn' : 'suspended')})`;
        
        // Calculate offset (r=85 -> C ≈ 534)
        const offset = 534 - (dashData.current_score / 100) * 534;
        circle.style.strokeDashoffset = offset;
        
        // Fetch timeline logs
        const logs = await makeRequest('/employee/history');
        const timelineList = document.getElementById('timeline-list');
        timelineList.innerHTML = '';
        
        if (logs.length === 0) {
            timelineList.innerHTML = `<div class="text-center text-muted py-4">No events logged.</div>`;
            return;
        }
        
        logs.forEach(log => {
            const time = new Date(log.timestamp).toLocaleString();
            const logItem = document.createElement('div');
            logItem.className = 'timeline-item';
            logItem.onclick = () => openEmployeeModal(log.log_id);
            
            const logScoreClass = getScoreColorText(log.score_after);
            
            logItem.innerHTML = `
                <div class="timeline-meta">
                    <h4>Trust Score: ${log.score_before} &rarr; <span class="text-${logScoreClass}">${log.score_after}</span></h4>
                    <p>${time}</p>
                </div>
                <div class="timeline-arrow">DETAILS &gt;</div>
            `;
            timelineList.appendChild(logItem);
        });
    } catch (err) {
        showNotification(`Failed to load employee metrics: ${err.message}`, 'error');
    }
}

// Employee Log Detail Modal management
async function openEmployeeModal(logId) {
    try {
        const detail = await makeRequest(`/employee/history/${logId}`);
        document.getElementById('log-detail-id').textContent = detail.log_id;
        document.getElementById('log-detail-time').textContent = new Date(detail.timestamp).toLocaleString();
        
        const scoreClass = getScoreColorText(detail.score_after);
        document.getElementById('log-detail-transition').innerHTML = `
            ${detail.score_before} &rarr; <span class="text-${scoreClass}">${detail.score_after}</span>
        `;
        document.getElementById('log-detail-cause').textContent = detail.cause_of_change;
        
        document.getElementById('employee-modal').classList.add('active');
    } catch (err) {
        showNotification(`Failed to fetch log details: ${err.message}`, 'error');
    }
}

function closeEmployeeModal() {
    document.getElementById('employee-modal').classList.remove('active');
}

// Telemetry Ingestion Simulator Submission
async function submitSimulatedTelemetry(event) {
    event.preventDefault();
    const lat = parseFloat(document.getElementById('sim-lat').value);
    const lon = parseFloat(document.getElementById('sim-lon').value);
    const device_status = document.getElementById('sim-device').value;
    const activity_type = document.getElementById('sim-activity').value;
    
    try {
        const res = await makeRequest('/telemetry/submit', {
            method: 'POST',
            body: JSON.stringify({ lat, lon, device_status, activity_type })
        });
        
        showNotification('Telemetry submitted successfully!', 'success');
        // Refresh local dashboard metrics
        await refreshEmployeeDashboard();
    } catch (err) {
        showNotification(`Telemetry ingestion failed: ${err.message}`, 'error');
    }
}

// Telemetry presets loading
function loadSimPreset(presetName) {
    const latInput = document.getElementById('sim-lat');
    const lonInput = document.getElementById('sim-lon');
    
    if (presetName === 'sf') {
        latInput.value = '37.7749';
        lonInput.value = '-122.4194';
        showNotification('San Francisco presets loaded.', 'info');
    } else if (presetName === 'nyc') {
        latInput.value = '40.7128';
        lonInput.value = '-74.0060';
        showNotification('New York presets loaded.', 'info');
    } else if (presetName === 'london') {
        latInput.value = '51.5074';
        lonInput.value = '-0.1278';
        showNotification('London coordinates loaded. (Warning: Impossible travel if run consecutively!)', 'info');
    }
}

// ==========================================================================
// Notification Toast Banner
// ==========================================================================
function showNotification(message, type = 'info') {
    const toast = document.getElementById('toast');
    const msgSpan = document.getElementById('toast-message');
    
    msgSpan.textContent = message;
    toast.className = 'toast'; // Reset
    
    if (type === 'success') toast.classList.add('success-toast');
    else if (type === 'error') toast.classList.add('error-toast');
    else toast.classList.add('info-toast');
    
    toast.classList.add('show');
    
    // Dismiss after 4s
    setTimeout(() => {
        toast.classList.remove('show');
    }, 4000);
}

// ==========================================================================
// Platform Super Admin System Portal Controller
// ==========================================================================
async function initSuperAdminDashboard(claims) {
    document.getElementById('super-admin-user-display').textContent = 'yogaroh16@gmail.com (Super Admin)';
    await loadSuperAdminData();
}

async function loadSuperAdminData() {
    try {
        const summary = await makeRequest('/super-admin/summary');
        document.getElementById('super-metric-companies').textContent = summary.total_companies;
        document.getElementById('super-metric-users').textContent = summary.total_users;
        document.getElementById('super-metric-users-breakdown').textContent = `${summary.total_admins} Admins, ${summary.total_employees} Employees`;
        document.getElementById('super-metric-verified').textContent = summary.verified_users_count;
        document.getElementById('super-metric-score').textContent = summary.average_trust_score;

        // Load Companies Table
        const companies = await makeRequest('/super-admin/companies');
        const compTbody = document.getElementById('super-companies-tbody');
        compTbody.innerHTML = '';
        if (companies.length === 0) {
            compTbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No corporate workspaces provisioned yet.</td></tr>`;
        } else {
            companies.forEach(c => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><span class="text-bold">${c.name}</span><br><small class="text-muted">ID: ${c.id.slice(0, 8)}...</small></td>
                    <td><span class="badge badge-cyan">${c.company_code}</span></td>
                    <td><small class="text-muted">${c.admin_email || 'None'}</small></td>
                    <td><span class="text-bold">${c.total_employees}</span></td>
                    <td><span class="badge ${c.is_active ? 'badge-green' : 'badge-red'}">${c.is_active ? 'ACTIVE' : 'SUSPENDED'}</span></td>
                    <td>
                        <button class="btn btn-sm ${c.is_active ? 'btn-outline-danger' : 'btn-outline-success'}" onclick="toggleCompanyStatus('${c.id}')">
                            ${c.is_active ? 'Suspend Workspace' : 'Activate Workspace'}
                        </button>
                    </td>
                `;
                compTbody.appendChild(tr);
            });
        }

        // Load Users Directory Table
        const users = await makeRequest('/super-admin/users');
        const usersTbody = document.getElementById('super-users-tbody');
        usersTbody.innerHTML = '';
        if (users.length === 0) {
            usersTbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No user accounts found.</td></tr>`;
        } else {
            users.forEach(u => {
                const tr = document.createElement('tr');
                let lastSeenStr = 'Never';
                if (u.last_seen_at) {
                    lastSeenStr = new Date(u.last_seen_at).toLocaleTimeString();
                }
                const scoreClass = getScoreColorClass(u.current_score);

                tr.innerHTML = `
                    <td><span class="text-bold">${u.full_name || 'User'}</span><br><small class="text-muted">${u.email}</small></td>
                    <td><span class="text-bold">${u.company_name}</span></td>
                    <td><span class="badge ${u.role === 'SUPER_ADMIN' ? 'badge-purple' : u.role === 'ADMIN' ? 'badge-cyan' : 'badge-green'}">${u.role}</span></td>
                    <td><span class="score-badge ${scoreClass}">${u.current_score}</span></td>
                    <td><span class="text-bold text-${getScoreColorText(u.current_score)}">${u.status}</span></td>
                    <td><span class="badge ${u.is_email_verified ? 'badge-green' : 'badge-yellow'}">${u.is_email_verified ? 'VERIFIED' : 'PENDING'}</span></td>
                    <td><small>${lastSeenStr}</small></td>
                    <td>
                        <button class="btn btn-sm btn-outline-warning" onclick="triggerSuperAdminForceOtp('${u.id}')">
                            🔒 Force OTP
                        </button>
                    </td>
                `;
                usersTbody.appendChild(tr);
            });
        }
    } catch (err) {
        showNotification(`Failed to load Super Admin portal data: ${err.message}`, 'error');
    }
}

async function toggleCompanyStatus(companyId) {
    try {
        const res = await makeRequest(`/super-admin/company/${companyId}/toggle`, { method: 'POST' });
        showNotification(res.message, 'success');
        await loadSuperAdminData();
    } catch (err) {
        showNotification(`Action failed: ${err.message}`, 'error');
    }
}

async function triggerSuperAdminForceOtp(userId) {
    try {
        const res = await makeRequest(`/super-admin/user/${userId}/force-otp`, { method: 'POST' });
        showNotification(res.message, 'success');
        await loadSuperAdminData();
    } catch (err) {
        showNotification(`Action failed: ${err.message}`, 'error');
    }
}
