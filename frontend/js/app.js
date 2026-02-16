const API_BASE_URL = 'http://127.0.0.1:8000';

// Global state
let currentKpiData = null;
let currentView = 'dashboard';
let currentBorrowerId = null;
let authToken = sessionStorage.getItem('auth_token');
let refreshTokenInProgress = false;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM Content Loaded at', new Date().toLocaleTimeString());
    updateCurrentDate();
    setupEventListeners();
    checkAuth();
});

// Helper function for making authenticated API requests
async function makeAuthenticatedRequest(url, options = {}) {
    // Ensure we have the latest token
    authToken = sessionStorage.getItem('auth_token');

    if (!authToken) {
        throw new Error('Not authenticated');
    }

    // Add authorization header
    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${authToken}`
    };

    const requestOptions = {
        ...options,
        headers
    };

    try {
        const response = await fetch(url, requestOptions);

        // Handle 401 Unauthorized - token might be expired
        if (response.status === 401) {
            console.warn('⚠️ Authentication failed - token may be expired');

            // Try to refresh token
            const refreshToken = sessionStorage.getItem('refresh_token');
            if (refreshToken && !refreshTokenInProgress) {
                refreshTokenInProgress = true;
                try {
                    const refreshResponse = await fetch(`${API_BASE_URL}/auth/refresh`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ refresh_token: refreshToken })
                    });

                    if (refreshResponse.ok) {
                        const data = await refreshResponse.json();
                        authToken = data.access_token;
                        sessionStorage.setItem('auth_token', authToken);
                        refreshTokenInProgress = false;

                        // Retry the original request with new token
                        headers['Authorization'] = `Bearer ${authToken}`;
                        return await fetch(url, { ...options, headers });
                    }
                } catch (error) {
                    console.error('Token refresh failed:', error);
                }
                refreshTokenInProgress = false;
            }

            // If refresh failed or no refresh token, logout
            showNotification('Session expired. Please login again.', 'warning');
            handleLogout();
            throw new Error('Authentication failed');
        }

        return response;
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

// Authentication Check
function checkAuth() {
    const loginScreen = document.getElementById('login-screen');
    const mainApp = document.getElementById('mainApp');

    if (authToken) {
        // Authenticated
        loginScreen.style.display = 'none';
        mainApp.style.display = 'flex';

        // Update User Profile UI
        const storedUser = sessionStorage.getItem('user_name') || 'Admin';
        const displayUserName = document.getElementById('display-userName');
        const sidebarUserName = document.getElementById('sidebar-userName');
        const avatarInitial = document.getElementById('user-avatar-initial');

        if (displayUserName) displayUserName.textContent = storedUser;
        if (sidebarUserName) sidebarUserName.textContent = storedUser;
        if (avatarInitial) avatarInitial.textContent = storedUser.charAt(0).toUpperCase();

        // Recovery data from storage if it exists (Data in Local; View in Session)
        const savedData = localStorage.getItem('finance_data');
        const savedView = sessionStorage.getItem('current_view') || 'dashboard';

        // ALWAYS fetch fresh data from the server to sync state
        console.log('🔄 Syncing UI state with database...');
        fetchData();

        if (savedData) {
            console.log('🔄 Attempting to recover data from cache...');
            try {
                const data = JSON.parse(savedData);
                if (data && data.kpis) {
                    currentKpiData = data;
                    updateDashboard(data);

                    // Recover the previous view from session storage only
                    if (savedView === 'summary-details') {
                        const savedPeriod = sessionStorage.getItem('current_period_key');
                        if (savedPeriod) {
                            showSummaryDetailsListView(savedPeriod);
                        }
                    } else {
                        showView(savedView);
                    }
                }
            } catch (e) {
                console.error('❌ Failed to parse saved data', e);
            }
        }
    } else {
        // Not authenticated
        loginScreen.style.display = 'flex';
        mainApp.style.display = 'none';
    }
}

// Update current date
function updateCurrentDate() {
    const dateElement = document.getElementById('currentDate');
    const now = new Date();
    const options = { weekday: 'long', day: 'numeric', month: 'long' };
    const formattedDate = now.toLocaleDateString('en-US', options);

    // Format: "Friday, 10th February"
    const day = now.getDate();
    const suffix = getDaySuffix(day);
    const monthYear = now.toLocaleDateString('en-US', { month: 'long' });
    const weekday = now.toLocaleDateString('en-US', { weekday: 'long' });

    dateElement.textContent = `${weekday}, ${day}${suffix} ${monthYear}`;
}

function getDaySuffix(day) {
    if (day > 3 && day < 21) return 'th';
    switch (day % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
    }
}

// Setup event listeners
function setupEventListeners() {
    // File upload handler
    const fileInput = document.getElementById('fileUpload');
    if (fileInput) fileInput.addEventListener('change', handleFileUpload);

    // View details buttons
    const viewDetailsBtns = document.querySelectorAll('.view-details-btn');
    viewDetailsBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const card = e.target.closest('.period-card');
            const period = card.dataset.period;

            let periodKey = '';
            if (period === '1to7') periodKey = '1-7_days';
            else if (period === 'more7') periodKey = 'More_than_7_days';
            else if (period === 'today') periodKey = 'Today';

            showSummaryDetailsListView(periodKey);
        });
    });

    // Back button
    const backBtn = document.getElementById('backToDashboard');
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            showView('dashboard');
        });
    }

    // Make bulk call button
    const makeBulkCallBtn = document.getElementById('makeBulkCallBtn');
    if (makeBulkCallBtn) {
        makeBulkCallBtn.addEventListener('click', handleBulkCall);
    }

    // Modal close
    const closeBtn = document.querySelector('.close-btn');
    const modal = document.getElementById('detailsModal');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.classList.remove('active');
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    }

    // Sidebar navigation
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetView = item.getAttribute('data-view');
            showView(targetView);
        });
    });

    // Login Form handler
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    // Register Form handler
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
    }

    // Auth Toggles
    const showRegister = document.getElementById('show-register');
    const showLogin = document.getElementById('show-login');

    if (showRegister) {
        showRegister.addEventListener('click', (e) => {
            e.preventDefault();
            toggleAuthMode('register');
        });
    }

    if (showLogin) {
        showLogin.addEventListener('click', (e) => {
            e.preventDefault();
            toggleAuthMode('login');
        });
    }

    // Logout button handler
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }

    // Reset All Calls
    const resetAllCallsBtn = document.getElementById('resetAllCallsBtn');
    if (resetAllCallsBtn) {
        resetAllCallsBtn.addEventListener('click', handleResetCalls);
    }
}

// Reset all call statuses
async function handleResetCalls() {
    if (!confirm('Are you sure you want to reset all call records? This cannot be undone.')) return;

    showLoading(true);
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/ai_calling/reset_calls`, {
            method: 'POST'
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to reset calls');
        }

        showNotification('All call records have been reset.', 'success');

        // CLEAR LOCAL CACHE
        localStorage.removeItem('finance_data');

        // FETCH FRESH DATA
        await fetchData();

        // Refresh details view if open
        const periodKey = sessionStorage.getItem('current_period_key');
        if (currentView === 'summary-details' && periodKey) {
            showSummaryDetailsListView(periodKey);
        }
    } catch (error) {
        console.error('Reset error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification('Error resetting calls', 'error');
        }
    } finally {
        showLoading(false);
    }
}

function toggleAuthMode(mode) {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const toggleAuth = document.getElementById('toggle-auth');
    const toggleLogin = document.getElementById('toggle-login');

    if (mode === 'register') {
        loginForm.style.display = 'none';
        registerForm.style.display = 'block';
        authTitle.textContent = 'Create Account';
        authSubtitle.textContent = 'Join the AI Caller platform';
        toggleAuth.style.display = 'none';
        toggleLogin.style.display = 'block';
    } else {
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
        authTitle.textContent = 'Welcome Back';
        authSubtitle.textContent = 'Please login to your account';
        toggleAuth.style.display = 'block';
        toggleLogin.style.display = 'none';
    }
}

// Handle Register
async function handleRegister(e) {
    e.preventDefault();
    const usernameInput = document.getElementById('reg-username');
    const passwordInput = document.getElementById('reg-password');
    const confirmInput = document.getElementById('reg-confirm-password');

    if (passwordInput.value !== confirmInput.value) {
        showNotification('Passwords do not match', 'error');
        return;
    }

    showLoading(true);

    try {
        const response = await fetch(`${API_BASE_URL}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: usernameInput.value,
                password: passwordInput.value
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Registration failed');
        }

        showNotification('Registration successful! Please login.', 'success');
        toggleAuthMode('login');
    } catch (error) {
        console.error('Registration error:', error);
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

// Fetch existing data from API
async function fetchData() {
    if (!authToken) return;

    showLoading(true);
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/data_ingestion/data?include_details=true`, {
            method: 'POST'
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to fetch existing data');
        }

        const data = await response.json();
        if (data && data.kpis) {
            currentKpiData = data;
            localStorage.setItem('finance_data', JSON.stringify(data));
            updateDashboard(data);
            console.log('✅ Data fetched successfully from API');
        }
    } catch (error) {
        console.error('Fetch data error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification(`Error fetching data: ${error.message}`, 'error');
        }
    } finally {
        showLoading(false);
    }
}

// Handle Login
async function handleLogin(e) {
    e.preventDefault();
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');

    if (!usernameInput || !passwordInput) return;

    const username = usernameInput.value;
    const password = passwordInput.value;

    showLoading(true);

    try {
        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
        }

        const data = await response.json();
        authToken = data.access_token;
        sessionStorage.setItem('auth_token', authToken);
        sessionStorage.setItem('refresh_token', data.refresh_token);
        sessionStorage.setItem('user_name', data.user.username);

        // CLEAR OLD STORAGE ON FRESH LOGIN
        localStorage.removeItem('finance_data');

        showNotification('Login successful!', 'success');
        checkAuth();
    } catch (error) {
        console.error('Login error:', error);
        showNotification(`Login Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

// Handle Logout
function handleLogout() {
    authToken = null;
    sessionStorage.removeItem('auth_token');
    sessionStorage.removeItem('user_name');
    sessionStorage.clear(); // Clear view state

    showNotification('Logged out successfully', 'info');
    checkAuth();
}

// Helper to switch views
function showView(viewId) {
    const sections = document.querySelectorAll('.view-section');
    const navItems = document.querySelectorAll('.nav-item');
    const headerActions = document.getElementById('headerActions');

    // Reset state
    currentView = viewId;
    sessionStorage.setItem('current_view', viewId);

    if (viewId === 'dashboard') {
        currentBorrowerId = null;
        sessionStorage.removeItem('current_borrower_id');
        sessionStorage.removeItem('current_period_key');
        if (headerActions) headerActions.style.display = 'flex';
    } else {
        if (headerActions) headerActions.style.display = 'none';
    }

    // Update Nav
    navItems.forEach(nav => {
        if (nav.getAttribute('data-view') === viewId) {
            nav.classList.add('active');
        } else {
            nav.classList.remove('active');
        }
    });

    // Update Sections
    sections.forEach(section => {
        section.classList.remove('active');
    });

    const targetElement = document.getElementById(`${viewId}-view`);
    if (targetElement) {
        targetElement.classList.add('active');
    }

    // Populate reports table when switching to reports view
    if (viewId === 'reports') {
        populateReportsTable();
    }
}

// Handle file upload
async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    console.log('File upload started:', file.name);

    // Validate file type
    const validExtensions = ['.xlsx', '.xls', '.csv'];
    const fileName = file.name.toLowerCase();
    const isValid = validExtensions.some(ext => fileName.endsWith(ext));

    if (!isValid) {
        alert('Please upload a valid Excel or CSV file (.xlsx, .xls, .csv)');
        event.target.value = '';
        return;
    }

    showLoading(true);

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/data_ingestion/data?include_details=true`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to upload file');
        }

        const data = await response.json();
        console.log('API Response received successfully');

        // Reset call states for new data
        if (data.detailed_breakdown?.by_due_date_category) {
            Object.values(data.detailed_breakdown.by_due_date_category).flat().forEach(b => {
                b.call_in_progress = false;
                b.call_completed = false;
            });
        }

        currentKpiData = data;
        // Persist data so it survives reloads
        localStorage.setItem('finance_data', JSON.stringify(data));
        console.log('✅ Data persisted to localStorage');

        updateDashboard(data);
        showNotification('File uploaded successfully!', 'success');
    } catch (error) {
        console.error('Upload error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification(`Error: ${error.message}`, 'error');
        }
    } finally {
        showLoading(false);
        event.target.value = ''; // Reset file input
    }
}

// Update dashboard with KPI data
function updateDashboard(data) {
    if (!data || !data.kpis) return;

    // Update overview KPIs
    const borrowersEl = document.getElementById('totalBorrowers');
    const arrearsEl = document.getElementById('totalArrears');

    if (borrowersEl) borrowersEl.textContent = data.kpis.total_borrowers || 0;
    if (arrearsEl) arrearsEl.textContent =
        `₹${(data.kpis.total_arrears || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    if (data.detailed_breakdown && data.detailed_breakdown.by_due_date_category) {
        const byDate = data.detailed_breakdown.by_due_date_category;
        updateCardLocal('more7', byDate['More_than_7_days']);
        updateCardLocal('oneToSeven', byDate['1-7_days']);
        updateCardLocal('today', byDate['Today']);
    }

    // Update reports table if we're on the reports view
    if (currentView === 'reports') {
        populateReportsTable();
    }
}

// Helper to calculate counts locally and update UI
function updateCardLocal(prefix, borrowersList) {
    if (!borrowersList || !Array.isArray(borrowersList)) {
        document.querySelector(`#${prefix}-consistent .count`).textContent = 0;
        document.querySelector(`#${prefix}-inconsistent .count`).textContent = 0;
        document.querySelector(`#${prefix}-overdue .count`).textContent = 0;
        return;
    }

    let consistent = 0, inconsistent = 0, overdue = 0;

    borrowersList.forEach(b => {
        const category = b.Payment_Category;
        if (category === 'Consistent') consistent++;
        else if (category === 'Inconsistent') inconsistent++;
        else if (category === 'Overdue') overdue++;
    });

    document.querySelector(`#${prefix}-consistent .count`).textContent = consistent;
    document.querySelector(`#${prefix}-inconsistent .count`).textContent = inconsistent;
    document.querySelector(`#${prefix}-overdue .count`).textContent = overdue;
}

// Show Summary Details List View
function showSummaryDetailsListView(periodKey) {
    console.log('Showing summary details list for period:', periodKey);

    if (!currentKpiData || !currentKpiData.detailed_breakdown) {
        showNotification('No data available. Please upload a file.', 'warning');
        return;
    }

    const byDate = currentKpiData.detailed_breakdown.by_due_date_category;
    const borrowers = byDate[periodKey] || [];

    // Map keys to labels
    const periodLabels = {
        'More_than_7_days': 'More than 7 Days',
        '1-7_days': '1-7 Days',
        'Today': '6th Feb (Today Data)'
    };

    const labelEl = document.getElementById('selectedPeriodLabel');
    if (labelEl) labelEl.textContent = periodLabels[periodKey] || periodKey;

    // Reset any stale call states for these borrowers when opening the view fresh
    borrowers.forEach(b => {
        if (!b.call_completed) { // Only reset if not already successful
            b.call_in_progress = false;
        }
    });

    // Save state
    currentView = 'summary-details';
    sessionStorage.setItem('current_view', currentView);
    sessionStorage.setItem('current_period_key', periodKey);

    // Switch view
    showView('summary-details');

    // Populate rows
    const container = document.getElementById('callRowsContainer');
    container.innerHTML = '';

    if (borrowers.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">No borrowers found in this section.</div>';
        return;
    }

    borrowers.forEach(borrower => {
        const rowWrapper = createCallDataRow(borrower);
        container.appendChild(rowWrapper);
    });

    window.scrollTo(0, 0);
}

// Create a call data row
function createCallDataRow(borrower) {
    const wrapper = document.createElement('div');
    wrapper.className = 'call-row-wrapper';
    wrapper.id = `row-${borrower.NO}`;

    const interactionType = borrower.Payment_Category || 'Normal';
    const statusClass = interactionType.toLowerCase();

    // Call Status Logic
    let callStatus = "Yet To Call";
    let statusBtnClass = "yet-to-call";

    if (borrower.call_in_progress) {
        callStatus = "In progress";
        statusBtnClass = "in-progress";
    } else if (borrower.call_completed) {
        callStatus = "Call Success";
        statusBtnClass = "success";
    }

    const lastPaid = borrower['LAST DUE REVD DATE'] || borrower['LAST DUE/REVD DATE'] || borrower.LAST_PAID_DATE || borrower.DUE_DATE || 'N/A';
    const amount = (borrower.AMOUNT || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const totalAmount = (borrower.TOTAL_LOAN || (borrower.AMOUNT * 1.5) || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

    wrapper.innerHTML = `
        <div class="call-row">
            <div class="borrower-cell">
                <img src="https://ui-avatars.com/api/?name=${encodeURIComponent(borrower.BORROWER)}&background=random" class="borrower-avatar" alt="${borrower.BORROWER}">
                <div class="borrower-meta">
                    <h4>${borrower.BORROWER}</h4>
                    <p>Last paid: ${lastPaid}</p>
                </div>
            </div>
            <div class="due-cell">$${amount}</div>
            <div class="total-cell">$${totalAmount}</div>
            <div class="status-cell ${statusClass}">${interactionType}</div>
            <div class="action-cell">
                <button class="status-btn ${statusBtnClass}">
                    <span>${callStatus}</span>
                    <span class="dropdown-icon">▼</span>
                </button>
            </div>
        </div>
        <div class="expanded-content">
            <div class="conversation-card">
                <div class="card-header">
                    <span class="icon">✨</span> AI Conversation
                </div>
                <div class="chat-bubbles" id="transcript-${borrower.NO}">
                    ${renderTranscript(borrower.transcript)}
                </div>
            </div>
            <div class="summary-card" id="summary-card-${borrower.NO}">
                <div class="card-header">
                    <span class="icon">✨</span> AI Summary
                </div>
                <div class="next-steps-title">Next Steps</div>
                <div class="next-steps-text" id="summary-text-${borrower.NO}">
                    ${borrower.ai_summary || 'No call summary yet. Initiate a call to get AI insights.'}
                </div>
                <button class="manual-btn">Initiate Manual Process</button>
            </div>
        </div>
    `;

    // Toggle expansion
    wrapper.querySelector('.call-row').addEventListener('click', () => {
        wrapper.classList.toggle('expanded');
    });

    return wrapper;
}

// Render transcript bubbles
function renderTranscript(transcript) {
    if (!transcript || transcript.length === 0) {
        return '<div class="chat-bubble ai">No conversation recorded yet.</div>';
    }

    return transcript.map(t => `
        <div class="chat-bubble ${t.speaker.toLowerCase() === 'ai' ? 'ai' : 'person'}">
            ${t.text}
        </div>
    `).join('');
}

// Handle bulk call
async function handleBulkCall() {
    const periodKey = sessionStorage.getItem('current_period_key');
    if (!periodKey || !currentKpiData) return;

    const borrowers = currentKpiData.detailed_breakdown.by_due_date_category[periodKey] || [];
    if (borrowers.length === 0) {
        showNotification('No borrowers to call.', 'warning');
        return;
    }

    showNotification(`Triggering parallel calls for ${borrowers.length} borrowers...`, 'info');

    const makeBulkCallBtn = document.getElementById('makeBulkCallBtn');
    if (makeBulkCallBtn) makeBulkCallBtn.disabled = true;

    // Update UI to "In progress"
    borrowers.forEach(b => {
        // Skip if already completed
        if (b.call_completed) return;

        b.call_in_progress = true;
        b.call_completed = false;

        const row = document.getElementById(`row-${b.NO}`);
        if (row) {
            const btn = row.querySelector('.status-btn');
            if (btn) {
                btn.className = 'status-btn in-progress';
                const span = btn.querySelector('span');
                if (span) span.textContent = 'In progress';
            }
        }
    });

    try {
        const payload = {
            borrowers: borrowers.map(b => ({
                NO: String(b.NO || ''),
                cell1: String(b.cell1 || ''),
                preferred_language: String(b.preferred_language || 'en-IN')
            })),
            use_dummy_data: true
        };

        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/ai_calling/trigger_calls`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Bulk call request failed');
        }

        const result = await response.json();
        console.log('Bulk Call Results:', result);

        // Update local state and UI
        result.results.forEach(res => {
            // Use loose equality (==) to handle string vs number comparison
            const borrower = borrowers.find(b => b.NO == res.borrower_id);
            if (borrower) {
                console.log(`Updating UI for borrower ${res.borrower_id}`);
                borrower.call_in_progress = false;
                borrower.call_completed = res.success;
                borrower.ai_summary = res.ai_analysis ? res.ai_analysis.summary : (res.success ? 'Call completed.' : 'Call failed: ' + res.error);
                borrower.transcript = res.conversation || [];

                // Update Row UI
                const row = document.getElementById(`row-${borrower.NO}`);
                if (row) {
                    const btn = row.querySelector('.status-btn');
                    if (btn) {
                        const span = btn.querySelector('span');
                        if (res.success) {
                            btn.className = 'status-btn success';
                            if (span) span.textContent = 'Call Success';
                        } else {
                            btn.className = 'status-btn yet-to-call';
                            if (span) span.textContent = 'Yet To Call';
                        }
                    }

                    // Update Transcript in expanded content
                    const transcriptEl = document.getElementById(`transcript-${borrower.NO}`);
                    if (transcriptEl) {
                        transcriptEl.innerHTML = renderTranscript(borrower.transcript);
                    }

                    // Update Summary in expanded content
                    const summaryEl = document.getElementById(`summary-text-${borrower.NO}`);
                    if (summaryEl) {
                        summaryEl.textContent = borrower.ai_summary;
                    }
                }
            } else {
                console.warn(`Could not find borrower ${res.borrower_id} in current list to update UI.`);
            }
        });

        // Save state
        localStorage.setItem('finance_data', JSON.stringify(currentKpiData));
        showNotification(`Bulk call completed! ${result.successful_calls} successful.`, 'success');

    } catch (error) {
        console.error('Bulk call error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification(`Error: ${error.message}`, 'error');
        }

        // Reset progress status on error
        borrowers.forEach(b => {
            b.call_in_progress = false;
            const row = document.getElementById(`row-${b.NO}`);
            if (row) {
                const btn = row.querySelector('.status-btn');
                if (btn) {
                    btn.className = 'status-btn yet-to-call';
                    btn.querySelector('span').textContent = 'Yet To Call';
                }
            }
        });
    } finally {
        if (makeBulkCallBtn) makeBulkCallBtn.disabled = false;
    }
}

// Show/hide loading spinner
function showLoading(show) {
    const spinner = document.getElementById('loadingSpinner');
    spinner.style.display = show ? 'flex' : 'none';
}

// Show notification (basic version)
function showNotification(message, type = 'info') {
    // You can enhance this with a proper toast notification library
    const styles = {
        success: 'background: #10b981; color: white;',
        error: 'background: #ef4444; color: white;',
        warning: 'background: #f59e0b; color: white;',
        info: 'background: #3b82f6; color: white;'
    };

    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 24px;
        border-radius: 12px;
        font-weight: 600;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        z-index: 3000;
        animation: slideInRight 0.3s ease;
        ${styles[type] || styles.info}
    `;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Add animation styles
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// ============================================================
// REPORTS SECTION FUNCTIONALITY
// ============================================================

function populateReportsTable() {
    const tableBody = document.getElementById('reportsTableBody');

    if (!currentKpiData || !currentKpiData.detailed_breakdown) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="9" style="padding: 60px; text-align: center; color: #9ca3af;">
                    <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                    <div style="font-size: 18px; font-weight: 500; margin-bottom: 8px;">No data available</div>
                    <div style="font-size: 14px;">Upload a file or refresh to load borrower data</div>
                </td>
            </tr>
        `;
        return;
    }

    // Collect all borrowers from all categories
    const allBorrowers = [];
    const byDate = currentKpiData.detailed_breakdown.by_due_date_category;

    Object.values(byDate).forEach(borrowersList => {
        if (Array.isArray(borrowersList)) {
            allBorrowers.push(...borrowersList);
        }
    });

    if (allBorrowers.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="9" style="padding: 60px; text-align: center; color: #9ca3af;">
                    <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                    <div style="font-size: 18px; font-weight: 500; margin-bottom: 8px;">No borrowers found</div>
                    <div style="font-size: 14px;">Upload a file to get started</div>
                </td>
            </tr>
        `;
        return;
    }

    // Populate table rows
    tableBody.innerHTML = '';
    allBorrowers.forEach((borrower, index) => {
        const row = document.createElement('tr');
        row.style.cssText = 'border-bottom: 1px solid #e5e7eb; transition: background 0.2s;';
        row.onmouseenter = () => row.style.background = '#f9fafb';
        row.onmouseleave = () => row.style.background = 'transparent';

        const paymentConf = borrower.payment_confirmation || '-';
        const followUpDate = borrower.follow_up_date || '-';
        const lastDate = borrower['LAST DUE REVD DATE'] || borrower['LAST DUE/REVD DATE'] || borrower.LAST_PAID_DATE || borrower.DUE_DATE || '-';
        const amount = (borrower.AMOUNT || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
        const emi = (borrower.EMI || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

        // Style payment confirmation based on intent
        let paymentConfStyle = 'padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 12px; white-space: nowrap;';

        switch (paymentConf) {
            case 'Paid':
                // Dark green - payment completed
                paymentConfStyle += 'background: #d1fae5; color: #065f46;';
                break;
            case 'Will Pay':
                // Light green - positive commitment
                paymentConfStyle += 'background: #dcfce7; color: #166534;';
                break;
            case 'Needs Extension':
                // Orange - needs attention
                paymentConfStyle += 'background: #fed7aa; color: #9a3412;';
                break;
            case 'Dispute':
                // Red - requires immediate action
                paymentConfStyle += 'background: #fee2e2; color: #991b1b;';
                break;
            case 'No Response':
                // Gray - no engagement
                paymentConfStyle += 'background: #e5e7eb; color: #6b7280;';
                break;
            default:
                // Default gray for pending/unknown
                paymentConfStyle += 'background: #f3f4f6; color: #9ca3af;';
        }

        row.innerHTML = `
            <td style="padding: 16px; font-weight: 500;">${borrower.NO || '-'}</td>
            <td style="padding: 16px; font-weight: 600; color: #1f2937;">${borrower.BORROWER || '-'}</td>
            <td style="padding: 16px; color: #059669; font-weight: 600;">₹${amount}</td>
            <td style="padding: 16px;">${borrower.cell1 || borrower.MOBILE || '-'}</td>
            <td style="padding: 16px;">₹${emi}</td>
            <td style="padding: 16px; text-transform: capitalize;">${borrower.preferred_language || borrower.LANGUAGE || 'English'}</td>
            <td style="padding: 16px;">
                <span style="${paymentConfStyle}">${paymentConf}</span>
            </td>
            <td style="padding: 16px; font-weight: 500; color: #4b5563;">${followUpDate}</td>
            <td style="padding: 16px; color: #6b7280;">${lastDate}</td>
        `;

        tableBody.appendChild(row);
    });
}

// Export CSV functionality
async function handleExportCSV() {
    showLoading(true);
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/data_ingestion/export/csv`, {
            method: 'GET'
        });

        if (!response.ok) {
            throw new Error('Failed to export CSV');
        }

        // Get the CSV content
        const blob = await response.blob();

        // Create download link
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `borrowers_report_${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();

        // Cleanup
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showNotification('CSV exported successfully!', 'success');
    } catch (error) {
        console.error('Export error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification('Error exporting CSV', 'error');
        }
    } finally {
        showLoading(false);
    }
}

// Add event listeners for reports functionality
document.addEventListener('DOMContentLoaded', () => {
    // Export CSV button
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', handleExportCSV);
    }

    // Refresh data button
    const refreshDataBtn = document.getElementById('refreshDataBtn');
    if (refreshDataBtn) {
        refreshDataBtn.addEventListener('click', async () => {
            await fetchData();
            populateReportsTable();
            showNotification('Data refreshed successfully!', 'success');
        });
    }
});
