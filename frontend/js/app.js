// API Configuration
const API_BASE_URL = (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost')
    ? 'http://127.0.0.1:8000'
    : 'https://ai-calling-live-1.onrender.com'; // Your Render URL

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
    initSidebar();
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
            showSummaryDetailsListView(period);
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

    // Sidebar Toggle
    const sidebarToggle = document.getElementById('sidebarToggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', () => {
            const sidebar = document.querySelector('.sidebar');
            const isCollapsed = sidebar.classList.toggle('collapsed');
            localStorage.setItem('sidebar_collapsed', isCollapsed);
        });
    }

    // Unified Manual Call Modal close & controls
    const manualModal = document.getElementById('manualCallModal');
    const closeManualBtn = document.getElementById('closeManualCall');
    const cancelCallBtn = document.getElementById('cancelCallBtn');
    const pauseCallBtn = document.getElementById('pauseCallBtn');

    function closeManualCallModal(isCancel = false) {
        if (isCancel && !confirm('Are you sure you want to end this manual call?')) return;

        stopManualAudioBridge();
        if (manualModal) {
            manualModal.style.display = 'none';
            manualModal.classList.remove('active');
        }
        if (isCancel) showNotification('Call ended.', 'info');
    }

    if (closeManualBtn) {
        closeManualBtn.addEventListener('click', () => closeManualCallModal(false));
    }

    if (cancelCallBtn) {
        cancelCallBtn.addEventListener('click', () => closeManualCallModal(true));
    }

    if (pauseCallBtn) {
        pauseCallBtn.addEventListener('click', () => {
            const isPaused = pauseCallBtn.classList.toggle('active');
            pauseCallBtn.style.background = isPaused ? '#fcd34d' : '#fef3c7';
            showNotification(isPaused ? 'Call paused.' : 'Call resumed.', 'info');
        });
    }

    if (manualModal) {
        manualModal.addEventListener('click', (e) => {
            if (e.target === manualModal) {
                manualModal.style.display = 'none';
                manualModal.classList.remove('active');
            }
        });
    }

    // Close email modal
    const closeEmailBtn = document.getElementById('closeEmailBtn');
    const emailModal = document.getElementById('emailPreviewModal');
    if (closeEmailBtn && emailModal) {
        closeEmailBtn.addEventListener('click', () => {
            emailModal.style.display = 'none';
        });
    }
}

// Initialize Sidebar State
function initSidebar() {
    const isCollapsed = localStorage.getItem('sidebar_collapsed') === 'true';
    if (isCollapsed) {
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.classList.add('collapsed');
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

// Fetch existing data from API (GET - no file upload, just reads DB)
async function fetchData() {
    if (!authToken) return;

    showLoading(true);
    try {
        // Use GET endpoint so we never trigger delete+insert on page load
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/data_ingestion/borrowers?limit=2000`, {
            method: 'GET'
        });

        if (!response.ok) {
            // Fallback: use the POST endpoint without a file
            const fallback = await makeAuthenticatedRequest(`${API_BASE_URL}/data_ingestion/data?include_details=true`, {
                method: 'POST'
            });
            if (!fallback.ok) throw new Error('Failed to fetch data');
            const data = await fallback.json();
            if (data && data.kpis) {
                currentKpiData = data;
                localStorage.setItem('finance_data', JSON.stringify(data));
                updateDashboard(data);
            }
            return;
        }

        const borrowers = await response.json();
        if (borrowers && Array.isArray(borrowers)) {
            // Build structure matching the upload response
            const bySma = { SMA0: [], SMA1: [], SMA2: [], NPA: [] };
            let totalArrears = 0;
            borrowers.forEach(b => {
                const cat = b.Payment_Category || 'SMA0';
                if (bySma[cat]) bySma[cat].push(b);
                else bySma['SMA0'].push(b);
                totalArrears += parseFloat(b.amtfin || b.AMOUNT || 0);
            });
            const data = {
                status: 'success',
                kpis: { total_borrowers: borrowers.length, total_arrears: totalArrears },
                detailed_breakdown: { by_sma_category: bySma },
                uploaded: false
            };
            currentKpiData = data;
            localStorage.setItem('finance_data', JSON.stringify(data));
            updateDashboard(data);
            console.log('✅ Data fetched from borrowers endpoint', borrowers.length, 'borrowers');
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

    // Populate tables when switching views
    if (viewId === 'reports') {
        populateReportsTable();
    } else if (viewId === 'escalation') {
        populateEscalationTable();
    } else if (viewId === 'governance') {
        loadGovernanceStatus();
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
        if (data.detailed_breakdown?.by_sma_category || data.detailed_breakdown?.by_due_date_category) {
            const categories = data.detailed_breakdown.by_sma_category || data.detailed_breakdown.by_due_date_category;
            Object.values(categories).flat().forEach(b => {
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

    if (data.detailed_breakdown && data.detailed_breakdown.by_sma_category) {
        const bySma = data.detailed_breakdown.by_sma_category;
        updateCardLocal('SMA0', bySma['SMA0']);
        updateCardLocal('SMA1', bySma['SMA1']);
        updateCardLocal('SMA2', bySma['SMA2']);
        updateCardLocal('NPA', bySma['NPA']);
    }

    // Update tables if we're on those views
    if (currentView === 'reports') {
        populateReportsTable();
    } else if (currentView === 'escalation') {
        populateEscalationTable();
    }
}

// Helper to calculate counts locally and update UI
function updateCardLocal(prefix, borrowersList) {
    const container = document.getElementById(`${prefix}-count`);
    if (!container) return;
    
    const countEl = container.querySelector('.count');
    if (!countEl) return;
    
    const count = (borrowersList && Array.isArray(borrowersList)) ? borrowersList.length : 0;
    countEl.textContent = count;
    
    // Also update any badge on the card header if present
    const card = container.closest('.period-card');
    if (card) {
        const badge = card.querySelector('.period-badge');
        if (badge) badge.textContent = count;
    }
}

// Show Summary Details List View
function showSummaryDetailsListView(periodKey) {
    console.log('Showing summary details list for period:', periodKey);

    if (!currentKpiData || !currentKpiData.detailed_breakdown) {
        showNotification('No data available. Please upload a file.', 'warning');
        return;
    }

    const bySma = currentKpiData.detailed_breakdown.by_sma_category;
    const borrowers = bySma[periodKey] || [];
 
    // Map keys to labels
    const periodLabels = {
        'SMA0': 'SMA0 (0-30 Days)',
        'SMA1': 'SMA1 (31-60 Days)',
        'SMA2': 'SMA2 (61-90 Days)',
        'NPA': 'NPA (Non-Performing Asset)'
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

    const selectAllCheckbox = document.getElementById('selectAllBorrowers');
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        // Remove existing listeners if any
        const newSelectAll = selectAllCheckbox.cloneNode(true);
        selectAllCheckbox.parentNode.replaceChild(newSelectAll, selectAllCheckbox);

        newSelectAll.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            const rowCheckboxes = container.querySelectorAll('.row-checkbox');
            rowCheckboxes.forEach(cb => {
                cb.checked = isChecked;
            });
        });
    }

    if (borrowers.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">No borrowers found in this section.</div>';
        return;
    }

    borrowers.forEach(borrower => {
        const rowWrapper = createCallDataRow(borrower);
        container.appendChild(rowWrapper);

        // Add listener to the new checkbox
        const checkbox = rowWrapper.querySelector('.row-checkbox');
        if (checkbox) {
            checkbox.addEventListener('change', () => {
                const total = container.querySelectorAll('.row-checkbox').length;
                const checked = container.querySelectorAll('.row-checkbox:checked').length;
                const selectAll = document.getElementById('selectAllBorrowers');
                if (selectAll) {
                    selectAll.checked = total === checked;
                    selectAll.indeterminate = checked > 0 && checked < total;
                }
            });
        }
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

    const acstatus = borrower.acstatus || borrower.Payment_Category || 'N/A';
    const amount = (borrower.amtfin || borrower.AMOUNT || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const account = borrower.account || borrower.NO || 'N/A';
    const h_name = borrower.h_name || borrower.BORROWER || 'N/A';
    const contnr = borrower.contnr || 'N/A';

    wrapper.innerHTML = `
        <div class="call-row">
            <div class="col-check">
                <input type="checkbox" class="row-checkbox" data-id="${borrower.NO}">
            </div>
            <div class="borrower-cell">
                <img src="https://ui-avatars.com/api/?name=${encodeURIComponent(h_name)}&background=random" class="borrower-avatar" alt="${h_name}">
                <div class="borrower-meta">
                    <h4>${h_name}</h4>
                    <p>Acc: ${account} | Status: ${acstatus}</p>
                </div>
            </div>
            <div class="due-cell">₹${amount}</div>
            <div class="total-cell">${contnr}</div>
            <div class="status-cell ${statusClass}">${acstatus}</div>
            <div class="action-cell">
                <button class="status-btn ${statusBtnClass}">
                    <span>${callStatus}</span>
                    <span class="dropdown-icon">▼</span>
                </button>
            </div>
        </div>
        <div class="expanded-content">
            <div class="details-grid" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; padding: 15px; background: #f9fafb; border-radius: 12px; margin-bottom: 15px; border: 1px solid #e5e7eb;">
                <div class="detail-item">
                    <span class="detail-label" style="display: block; font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Account</span>
                    <span class="detail-value" style="font-weight: 700; color: #1f2937;">${account}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label" style="display: block; font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Holder Name</span>
                    <span class="detail-value" style="font-weight: 700; color: #1f2937;">${h_name}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label" style="display: block; font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Status</span>
                    <span class="detail-value" style="font-weight: 700; color: #1f2937;">${acstatus}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label" style="display: block; font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Container</span>
                    <span class="detail-value" style="font-weight: 700; color: #1f2937;">${contnr}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label" style="display: block; font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Amount Financed</span>
                    <span class="detail-value" style="font-weight: 700; color: #1f2937;">₹${amount}</span>
                </div>
            </div>
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
                <div class="ai-summary-preview" id="summary-preview-${borrower.NO}">
                    ${renderTruncatedSummary(borrower.ai_summary, borrower.NO, borrower.h_name || borrower.BORROWER || 'Borrower', borrower.payment_confirmation)}
                </div>
                <div class="summary-actions" style="display: flex; gap: 10px; margin-top: 15px;">
                    <button class="manual-btn" style="display: ${borrower.require_manual_process ? 'block' : 'none'}">Initiate Manual Process</button>
                    ${borrower.email_to_manager_preview ? `<button class="email-mgr-btn">Email to Area Manager</button>` : ''}
                </div>
            </div>
        </div>
    `;

    // Toggle expansion
    wrapper.querySelector('.call-row').addEventListener('click', () => {
        wrapper.classList.toggle('expanded');
    });

    // Prevent expansion when clicking checkbox
    wrapper.querySelector('.row-checkbox').addEventListener('click', (e) => {
        e.stopPropagation();
    });

    // Email Button Listener
    const emailBtn = wrapper.querySelector('.email-mgr-btn');
    if (emailBtn) {
        emailBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmailPreview(borrower.email_to_manager_preview);
        });
    }

    // Manual Process Listener
    const manualBtn = wrapper.querySelector('.manual-btn');
    if (manualBtn) {
        manualBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openManualCallModal(borrower);
        });
    }

    // View Summary Button Listener (expanded card)
    const viewSummaryBtn = wrapper.querySelector('.view-summary-btn');
    if (viewSummaryBtn) {
        viewSummaryBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openAiSummaryModal(
                borrower.ai_summary,
                borrower.h_name || borrower.BORROWER || 'Borrower',
                borrower.payment_confirmation
            );
        });
    }

    return wrapper;
}

// Function to open email preview modal
function openEmailPreview(emailData) {
    if (!emailData) return;

    const modal = document.getElementById('emailPreviewModal');
    const toEl = document.getElementById('emailTo');
    const subjectEl = document.getElementById('emailSubject');
    const bodyEl = document.getElementById('emailBody');

    if (toEl) toEl.textContent = emailData.to || 'Area Manager';
    if (subjectEl) subjectEl.textContent = emailData.subject || 'Follow-up Required';
    if (bodyEl) bodyEl.textContent = emailData.body || '';

    if (modal) modal.classList.add('active');
}

// Close listeners for email modal
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('emailPreviewModal');
    const closeBtns = document.querySelectorAll('.close-email-btn, #closeEmailBtn');

    closeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (modal) modal.classList.remove('active');
        });
    });

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    }

    const sendEmailBtn = document.getElementById('sendEmailBtn');
    if (sendEmailBtn) {
        sendEmailBtn.addEventListener('click', handleSendEmail);
    }
});

/**
 * Handle sending the escalation email
 */
async function handleSendEmail() {
    const to = document.getElementById('emailTo').textContent;
    const subject = document.getElementById('emailSubject').textContent;
    const body = document.getElementById('emailBody').textContent;

    if (!to || !subject || !body) {
        showNotification('Email data is incomplete.', 'warning');
        return;
    }

    showLoading(true);

    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/ai_calling/send_escalation_email`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ to, subject, body })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to send email');
        }

        showNotification('Email sent successfully to ' + to, 'success');

        // Close modal
        const modal = document.getElementById('emailPreviewModal');
        if (modal) modal.classList.remove('active');
    } catch (error) {
        console.error('Email send error:', error);
        if (error.message !== 'Authentication failed') {
            showNotification(`Error: ${error.message}`, 'error');
        }
    } finally {
        showLoading(false);
    }
}


// ============================================================
// AI SUMMARY TRUNCATION + VIEW MODAL
// ============================================================

/**
 * Render a truncated AI summary (first 4 words) with a "View" button
 */
function renderTruncatedSummary(summary, uniqueId, borrowerName, intent) {
    if (!summary || summary === 'No call summary yet. Initiate a call to get AI insights.') {
        return `<div class="ai-summary-short" style="color: #9ca3af; font-size: 13px; font-style: italic;">No call summary yet. Initiate a call to get AI insights.</div>`;
    }
    if (summary === 'Awaiting call...') {
        return `<div class="ai-summary-short" style="color: #9ca3af; font-size: 13px; font-style: italic;">Awaiting call...</div>`;
    }

    // Get first 4 words
    const words = summary.split(/\s+/);
    const truncated = words.slice(0, 4).join(' ');
    const hasMore = words.length > 4;

    return `
        <div class="ai-summary-truncated-container">
            <span class="ai-summary-short-text">${truncated}${hasMore ? '...' : ''}</span>
            ${hasMore ? `<button class="view-summary-btn" data-id="${uniqueId}" data-summary="${encodeURIComponent(summary)}" data-name="${encodeURIComponent(borrowerName)}" data-intent="${encodeURIComponent(intent || '')}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                View
            </button>` : ''}
        </div>
    `;
}

/**
 * Open AI Summary Modal showing full detailed summary
 */
function openAiSummaryModal(summary, borrowerName, intent) {
    let modal = document.getElementById('aiSummaryModal');
    if (!modal) {
        createAiSummaryModal();
        modal = document.getElementById('aiSummaryModal');
    }

    const nameEl = document.getElementById('aiSummaryBorrowerName');
    const intentEl = document.getElementById('aiSummaryIntentBadge');
    const textEl = document.getElementById('aiSummaryFullText');

    if (nameEl) nameEl.textContent = borrowerName || 'Borrower';

    // Style intent badge
    if (intentEl && intent) {
        intentEl.textContent = intent;
        intentEl.style.display = 'inline-block';

        // Apply intent-specific colors (case-insensitive)
        const lIntent = intent.toLowerCase().trim();
        let bg = '#f3f4f6';
        let color = '#6b7280';

        if (lIntent === 'will pay') { bg = '#dcfce7'; color = '#166534'; }
        else if (lIntent === 'paid') { bg = '#d1fae5'; color = '#065f46'; }
        else if (lIntent === 'needs extension') { bg = '#ffedd5'; color = '#9a3412'; }
        else if (lIntent === 'dispute') { bg = '#fee2e2'; color = '#991b1b'; }
        else if (lIntent === 'abusive language') { bg = '#fef2f2'; color = '#991b1b'; }
        else if (lIntent === 'threatening language') { bg = '#7f1d1d'; color = '#ffffff'; }
        else if (lIntent === 'stop calling') { bg = '#4b5563'; color = '#ffffff'; }
        else if (lIntent === 'no response') { bg = '#f3f4f6'; color = '#6b7280'; }

        intentEl.style.background = bg;
        intentEl.style.color = color;
    } else if (intentEl) {
        intentEl.style.display = 'none';
    }

    if (textEl) textEl.textContent = summary || 'No summary available.';

    modal.style.display = 'flex';
    modal.classList.add('active');
}

/**
 * Dynamically create the AI Summary Modal DOM
 */
function createAiSummaryModal() {
    const modal = document.createElement('div');
    modal.id = 'aiSummaryModal';
    modal.className = 'ai-summary-modal-overlay';
    modal.innerHTML = `
        <div class="ai-summary-modal-container">
            <div class="ai-summary-modal-header">
                <div class="ai-summary-modal-title">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #4f46e5;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    <span>AI Summary Report</span>
                </div>
                <button class="ai-summary-modal-close" id="closeAiSummaryBtn">&times;</button>
            </div>
            <div class="ai-summary-modal-body">
                <div class="ai-summary-meta-row">
                    <div class="ai-summary-borrower-label">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #6b7280;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                        <span id="aiSummaryBorrowerName">Borrower</span>
                    </div>
                    <span class="ai-summary-intent-badge" id="aiSummaryIntentBadge">Will Pay</span>
                </div>
                <div class="ai-summary-divider"></div>
                <div class="ai-summary-full-text" id="aiSummaryFullText">
                    No summary available.
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Close listeners
    const closeBtn = document.getElementById('closeAiSummaryBtn');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
            modal.classList.remove('active');
        });
    }
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
            modal.classList.remove('active');
        }
    });
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

    const borrowersList = (currentKpiData.detailed_breakdown.by_sma_category || currentKpiData.detailed_breakdown.by_due_date_category || {})[periodKey] || [];

    // Filter selected borrowers
    const selectedIds = Array.from(document.querySelectorAll('.row-checkbox:checked')).map(cb => cb.dataset.id);
    const borrowers = borrowersList.filter(b => selectedIds.includes(String(b.NO || b.contnr)));

    if (borrowers.length === 0) {
        showNotification('Please select at least one borrower to make a call.', 'warning');
        return;
    }

    showNotification(`Triggering parallel calls for ${borrowers.length} selected borrowers...`, 'info');

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

    const selectedIntent = document.getElementById('testIntentSelector')?.value || 'normal';
    console.log(`Starting bulk call with intent mode: ${selectedIntent}`);

    try {
        // Borrower IDs that should use REAL Vonage calls instead of dummy data
        const REAL_CALL_BORROWER_IDS = ["12150"];

        const payload = {
            borrowers: borrowers.map(b => {
                let intent = selectedIntent;
                if (selectedIntent === 'random') {
                    const intents = ['normal', 'paid', 'needs_extension', 'dispute', 'abusive', 'threatening', 'stop_calling', 'no_response', 'mid_call', 'failed_pickup'];
                    intent = intents[Math.floor(Math.random() * intents.length)];
                }

                return {
                    contnr: String(b.contnr || b.NO || ''),
                    cell1: String(b.cell1 || ''),
                    preferred_language: String(b.preferred_language || 'en-IN'),
                    acstatus: String(b.acstatus || b.Payment_Category || 'SMA0'),
                    intent_for_testing: intent
                };
            }),
            use_dummy_data: true,
            real_call_borrower_ids: REAL_CALL_BORROWER_IDS
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
            // ── RBI CALLING HOURS 403 HANDLER ──
            if (response.status === 403) {
                showNotification(
                    errorData.detail || '⛔ Cannot initiate call: Outside allowed calling window',
                    'error'
                );
                // Reset all "calling" spinners
                borrowers.forEach(b => {
                    b.call_in_progress = false;
                    updateBorrowerRowUI(b);
                });
                return;
            }
            throw new Error(errorData.detail || 'Bulk call request failed');
        }

        const result = await response.json();
        console.log('Bulk Call Results:', result);

        // Track real call borrowers that need polling
        const realCallBorrowerIds = [];

        // Update local state and UI
        result.results.forEach(res => {
            // Use loose equality (==) to handle string vs number comparison
            const borrower = borrowers.find(b => (b.NO == res.borrower_id) || (b.contnr == res.borrower_id));
            if (borrower) {
                console.log(`Updating UI for borrower ${res.borrower_id}`);
                borrower.call_in_progress = false;
                borrower.call_completed = res.success;
                borrower.ai_summary = res.next_step_summary || (res.ai_analysis ? res.ai_analysis.summary : (res.success ? 'Call completed.' : 'Call failed: ' + res.error));
                borrower.transcript = res.conversation || [];
                borrower.payment_confirmation = (res.payment_confirmation != null) ? res.payment_confirmation : borrower.payment_confirmation;
                borrower.follow_up_date = (res.follow_up_date != null) ? res.follow_up_date : borrower.follow_up_date;
                borrower.call_frequency = (res.call_frequency != null) ? res.call_frequency : borrower.call_frequency;
                borrower.email_to_manager_preview = res.email_to_manager_preview;
                borrower.require_manual_process = res.require_manual_process;

                // If this is a real call (not dummy) with no conversation yet, poll for results
                if (!res.is_dummy && (!res.conversation || res.conversation.length === 0)) {
                    realCallBorrowerIds.push(borrower.NO);
                    // Show "Call in progress" for real calls
                    borrower.call_in_progress = true;
                    borrower.call_completed = false;
                    borrower.ai_summary = '📞 Real call initiated. Waiting for call to complete...';
                }

                updateBorrowerRowUI(borrower, res);
            } else {
                console.warn(`Could not find borrower ${res.borrower_id} in current list to update UI.`);
            }
        });

        // Save state
        localStorage.setItem('finance_data', JSON.stringify(currentKpiData));
        showNotification(`Bulk call completed! ${result.successful_calls} successful.`, 'success');

        // Start polling for real call borrowers
        if (realCallBorrowerIds.length > 0) {
            console.log(`📞 Starting poll for ${realCallBorrowerIds.length} real call borrower(s):`, realCallBorrowerIds);
            showNotification(`📞 ${realCallBorrowerIds.length} real call(s) in progress. Will update automatically when completed.`, 'info');
            pollRealCallResults(borrowers, realCallBorrowerIds);
        }

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

// ============================================================
// REAL CALL POLLING
// ============================================================

/**
 * Update the borrower's row UI with call result data
 */
function updateBorrowerRowUI(borrower, data = {}) {
    // 1. Update DASHBOARD Summary Details Row
    const row = document.getElementById(`row-${borrower.NO}`);
    if (row) {
        const btn = row.querySelector('.status-btn');
        if (btn) {
            const span = btn.querySelector('span');
            if (borrower.call_in_progress) {
                btn.className = 'status-btn in-progress';
                if (span) span.textContent = 'In progress';
            } else if (borrower.call_completed) {
                btn.className = 'status-btn success';
                if (span) span.textContent = 'Call Success';
            } else {
                btn.className = 'status-btn yet-to-call';
                if (span) span.textContent = 'Yet To Call';
            }
        }

        // Dashboard Transcript
        const transcriptEl = document.getElementById(`transcript-${borrower.NO}`);
        if (transcriptEl) {
            transcriptEl.innerHTML = renderTranscript(borrower.transcript);
        }

        // Dashboard Summary (truncated with View button)
        const summaryPreviewEl = document.getElementById(`summary-preview-${borrower.NO}`);
        if (summaryPreviewEl) {
            summaryPreviewEl.innerHTML = renderTruncatedSummary(
                borrower.ai_summary, borrower.NO,
                borrower.h_name || borrower.BORROWER || 'Borrower',
                borrower.payment_confirmation
            );
            // Re-attach view button listener
            const viewBtn = summaryPreviewEl.querySelector('.view-summary-btn');
            if (viewBtn) {
                viewBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openAiSummaryModal(borrower.ai_summary, borrower.h_name || borrower.BORROWER || 'Borrower', borrower.payment_confirmation);
                });
            }
        }

        // Dashboard Actions
        const summaryCard = document.getElementById(`summary-card-${borrower.NO}`);
        if (summaryCard) {
            const manualBtn = summaryCard.querySelector('.manual-btn');
            if (manualBtn) manualBtn.style.display = (data.require_manual_process || borrower.require_manual_process) ? 'block' : 'none';

            const actionsDiv = summaryCard.querySelector('.summary-actions');
            if (actionsDiv) {
                const existingEmailBtn = actionsDiv.querySelector('.email-mgr-btn');
                const emailPreview = data.email_to_manager_preview || borrower.email_to_manager_preview;
                const hasEmailDraft = emailPreview && Object.keys(emailPreview).length > 0;
                if (hasEmailDraft) {
                    if (!existingEmailBtn) {
                        const emailBtn = document.createElement('button');
                        emailBtn.className = 'email-mgr-btn';
                        emailBtn.textContent = 'Email to Area Manager';
                        emailBtn.addEventListener('click', (e) => {
                            e.stopPropagation();
                            openEmailPreview(emailPreview);
                        });
                        actionsDiv.appendChild(emailBtn);
                    }
                } else if (existingEmailBtn) {
                    existingEmailBtn.remove();
                }
            }
        }
    }

    // 2. Update REPORTS and ESCALATION Tables
    updateTableRowUI('report', borrower, data);
    updateTableRowUI('esc', borrower, data);
}

/**
 * Helper to update a specific table row (report or escalation)
 */
function updateTableRowUI(prefix, borrower, data) {
    const tableBodyId = prefix === 'esc' ? 'escalationTableBody' : 'reportsTableBody';
    const tableBody = document.getElementById(tableBodyId);
    if (!tableBody) return;

    let row = document.querySelector(`#${tableBodyId} tr[data-no="${borrower.NO}"]`);

    // Special logic for escalation table: add row if it doesn't exist but should
    if (prefix === 'esc' && !row) {
        const escInfo = getEscalationInfo(borrower);
        if (escInfo.isEscalated) {
            // Remove the "No escalations" placeholder if it's there
            if (tableBody.querySelectorAll('tr').length === 1 && tableBody.innerText.includes('No escalations')) {
                tableBody.innerHTML = '';
            }
            row = createReportRow(borrower, 'escalation');
            tableBody.appendChild(row);
        }
    }

    if (!row) return;

    // Payment Status
    const paymentStatusEl = document.getElementById(`${prefix}-payment-status-${borrower.NO}`);
    if (paymentStatusEl) {
        const paymentConf = borrower.payment_confirmation || '-';
        let paymentConfStyle = 'padding: 6px 16px; border-radius: 20px; font-weight: 600; font-size: 13px; white-space: nowrap; display: inline-block;';
        switch (paymentConf) {
            case 'Paid': paymentConfStyle += 'background: #d1fae5; color: #065f46;'; break;
            case 'Will Pay': paymentConfStyle += 'background: #dcfce7; color: #166534;'; break;
            case 'Needs Extension': paymentConfStyle += 'background: #ffedd5; color: #9a3412;'; break;
            case 'Dispute': paymentConfStyle += 'background: #fee2e2; color: #991b1b;'; break;
            case 'No Response': paymentConfStyle += 'background: #f3f4f6; color: #6b7280;'; break;
            default: paymentConfStyle += 'background: #f9fafb; color: #9ca3af; border: 1px solid #e5e7eb;';
        }
        paymentStatusEl.innerHTML = `<span style="${paymentConfStyle}">${paymentConf}</span>`;
    }

    // Follow Up
    const followUpEl = document.getElementById(`${prefix}-follow-up-${borrower.NO}`);
    if (followUpEl) {
        followUpEl.innerHTML = renderFollowUpBadges(data.follow_up_date || borrower.follow_up_date);
    }

    // AI Summary Text (truncated with View button)
    const summaryCellEl = document.getElementById(`${prefix}-summary-cell-${borrower.NO}`);
    if (summaryCellEl) {
        const summary = data.ai_summary || borrower.ai_summary || 'No summary available.';
        summaryCellEl.innerHTML = renderTruncatedSummary(
            summary, `${prefix}-${borrower.NO}`,
            borrower.h_name || borrower.BORROWER || 'Borrower',
            borrower.payment_confirmation
        );
        // Re-attach view button listener
        const viewBtn = summaryCellEl.querySelector('.view-summary-btn');
        if (viewBtn) {
            viewBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                openAiSummaryModal(summary, borrower.h_name || borrower.BORROWER || 'Borrower', borrower.payment_confirmation);
            });
        }
    }

    // Category (only for escalation table)
    if (prefix === 'esc') {
        const categoryEl = document.getElementById(`esc-category-${borrower.NO}`);
        if (categoryEl) {
            categoryEl.textContent = borrower.Payment_Category || '-';
        }
    }

    // Action Required (Buttons)
    const actionsEl = document.getElementById(`${prefix}-actions-${borrower.NO}`);
    if (actionsEl) {
        const manualBtn = actionsEl.querySelector('.report-manual-btn');
        if (manualBtn) manualBtn.style.display = (data.require_manual_process || borrower.require_manual_process) ? 'inline-flex' : 'none';

        const existingEmailBtn = actionsEl.querySelector('.report-email-btn');
        const emailPreview = data.email_to_manager_preview || borrower.email_to_manager_preview;
        const hasEmailDraft = emailPreview && Object.keys(emailPreview).length > 0;

        if (hasEmailDraft) {
            if (!existingEmailBtn) {
                const emailBtn = document.createElement('button');
                emailBtn.className = 'email-mgr-btn report-email-btn';
                emailBtn.textContent = 'Email Manager';
                emailBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openEmailPreview(emailPreview);
                });
                actionsEl.appendChild(emailBtn);
            } else {
                existingEmailBtn.style.display = 'inline-flex';
            }
        } else if (existingEmailBtn) {
            existingEmailBtn.style.display = 'none';
        }
    }

    // Action/Freq
    const actionFreqEl = document.getElementById(`${prefix}-action-freq-${borrower.NO}`);
    if (actionFreqEl) {
        actionFreqEl.textContent = borrower.call_frequency || '-';
    }
}

/**
 * Poll the backend for real call results until all calls complete or timeout (3 minutes)
 */
async function pollRealCallResults(borrowersList, realCallIds) {
    const POLL_INTERVAL_MS = 5000;  // Poll every 5 seconds
    const MAX_POLL_TIME_MS = 180000; // Max 3 minutes
    const startTime = Date.now();
    let pendingIds = [...realCallIds];

    const poll = async () => {
        if (pendingIds.length === 0) {
            console.log('✅ All real calls completed.');
            return;
        }

        if (Date.now() - startTime > MAX_POLL_TIME_MS) {
            console.warn('⏱️ Polling timeout reached. Some calls may not have completed.');
            showNotification(`⏱️ Polling timeout. ${pendingIds.length} call(s) may still be in progress. Refresh to check.`, 'warning');
            // Mark remaining as completed with timeout message
            pendingIds.forEach(id => {
                const borrower = borrowersList.find(b => b.NO == id);
                if (borrower) {
                    borrower.call_in_progress = false;
                    borrower.call_completed = true;
                    borrower.ai_summary = borrower.ai_summary || 'Call may still be in progress. Please refresh to check.';
                    updateBorrowerRowUI(borrower, {});
                }
            });
            localStorage.setItem('finance_data', JSON.stringify(currentKpiData));
            return;
        }

        const completedThisRound = [];

        for (const borrowerNo of pendingIds) {
            try {
                const response = await makeAuthenticatedRequest(
                    `${API_BASE_URL}/ai_calling/borrower_call_status/${borrowerNo}`
                );

                if (response.ok) {
                    const data = await response.json();

                    // Check if the call is complete (has transcript data)
                    if (data.transcript && data.transcript.length > 0) {
                        console.log(`✅ Real call data received for borrower ${borrowerNo}`);

                        // Update local borrower state
                        const borrower = borrowersList.find(b => b.NO == borrowerNo);
                        if (borrower) {
                            borrower.call_in_progress = false;
                            borrower.call_completed = true;
                            borrower.transcript = data.transcript;
                            borrower.ai_summary = data.ai_summary || 'Call completed.';
                            borrower.payment_confirmation = data.payment_confirmation || borrower.payment_confirmation;
                            borrower.follow_up_date = data.follow_up_date || borrower.follow_up_date;
                            borrower.call_frequency = data.call_frequency || borrower.call_frequency;
                            borrower.require_manual_process = data.require_manual_process;
                            borrower.email_to_manager_preview = data.email_to_manager_preview;

                            updateBorrowerRowUI(borrower, data);
                            showNotification(`📞 Call for ${borrowerNo} completed! ${data.ai_summary}`, 'success');
                        }

                        completedThisRound.push(borrowerNo);
                    }
                }
            } catch (err) {
                console.warn(`Poll error for borrower ${borrowerNo}:`, err);
            }
        }

        // Remove completed borrowers from pending list
        pendingIds = pendingIds.filter(id => !completedThisRound.includes(id));

        // Save state
        if (completedThisRound.length > 0) {
            localStorage.setItem('finance_data', JSON.stringify(currentKpiData));
        }

        // Continue polling if there are still pending calls
        if (pendingIds.length > 0) {
            setTimeout(poll, POLL_INTERVAL_MS);
        } else {
            console.log('✅ All real calls completed and UI updated.');
        }
    };

    // Start polling
    setTimeout(poll, POLL_INTERVAL_MS);
}

// Show/hide loading spinner
function showLoading(show) {
    const spinner = document.getElementById('loadingSpinner');
    spinner.style.display = show ? 'flex' : 'none';
}

// Show notification (toast)
function showNotification(message, type = 'info') {
    const styles = {
        success: 'background: #10b981; color: white;',
        error: 'background: #dc2626; color: white;',
        warning: 'background: #f59e0b; color: white;',
        info: 'background: #3b82f6; color: white;'
    };

    const icons = {
        success: '✅',
        error: '⛔',
        warning: '⚠️',
        info: 'ℹ️'
    };

    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        max-width: 420px;
        padding: 16px 20px;
        border-radius: 14px;
        font-weight: 600;
        font-size: 14px;
        line-height: 1.5;
        word-wrap: break-word;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
        z-index: 3000;
        animation: slideInRight 0.3s ease;
        ${styles[type] || styles.info}
    `;
    notification.textContent = message;

    document.body.appendChild(notification);

    const duration = type === 'error' ? 5000 : 3000;
    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, duration);
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
                <td colspan="11" style="padding: 60px; text-align: center; color: #9ca3af;">
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
    const byDate = currentKpiData.detailed_breakdown.by_sma_category || currentKpiData.detailed_breakdown.by_due_date_category;

    Object.values(byDate).forEach(borrowersList => {
        if (Array.isArray(borrowersList)) {
            allBorrowers.push(...borrowersList);
        }
    });

    if (allBorrowers.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="11" style="padding: 60px; text-align: center; color: #9ca3af;">
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
    allBorrowers.forEach(borrower => {
        const row = createReportRow(borrower, 'report');
        tableBody.appendChild(row);
    });
}

/**
 * Populate the Escalation Report table with Inconsistent and Overdue borrowers
 */
function populateEscalationTable() {
    const tableBody = document.getElementById('escalationTableBody');

    if (!currentKpiData || !currentKpiData.detailed_breakdown) {
        // Default empty state is already in HTML or set here
        return;
    }

    // Collect all borrowers and filter for escalations
    const allBorrowers = [];
    const byDate = currentKpiData.detailed_breakdown.by_sma_category || currentKpiData.detailed_breakdown.by_due_date_category;

    Object.values(byDate).forEach(borrowersList => {
        if (Array.isArray(borrowersList)) {
            allBorrowers.push(...borrowersList);
        }
    });

    // Filter escalated borrowers
    const escalatedBorrowers = allBorrowers.filter(isEscalation);

    if (escalatedBorrowers.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="11" style="padding: 60px; text-align: center; color: #9ca3af;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🚩</div>
                    <div style="font-size: 18px; font-weight: 500; margin-bottom: 8px;">No escalations currently</div>
                    <div style="font-size: 14px;">Great! All borrowers are either on track or still awaiting call.</div>
                </td>
            </tr>
        `;
        return;
    }

    // Populate table rows
    tableBody.innerHTML = '';
    escalatedBorrowers.forEach(borrower => {
        const row = createReportRow(borrower, 'escalation');
        tableBody.appendChild(row);
    });
}

/**
 * Helper to create a report row for either Reports or Escalation table
 */
function createReportRow(borrower, context = 'report') {
    const row = document.createElement('tr');
    row.style.cssText = 'border-bottom: 1px solid #e5e7eb; transition: background 0.2s;';
    row.dataset.no = borrower.NO;
    row.className = context === 'escalation' ? 'escalation-row' : 'report-row';
    row.onmouseenter = () => row.style.background = '#f9fafb';
    row.onmouseleave = () => row.style.background = 'transparent';

    const isCalled = borrower.call_completed === true;
    const paymentConf = isCalled ? (borrower.payment_confirmation || '-') : '-';
    const followUpHTML = isCalled ? renderFollowUpBadges(borrower.follow_up_date) : '-';
    const callFreq = isCalled ? (borrower.call_frequency || '-') : '-';
    const amount = (borrower.amtfin || borrower.AMOUNT || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const emi = (borrower.emi || borrower.EMI || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

    // Style payment confirmation based on intent
    let paymentConfStyle = 'padding: 6px 16px; border-radius: 20px; font-weight: 600; font-size: 13px; white-space: nowrap; display: inline-block;';

    switch (paymentConf) {
        case 'Paid': paymentConfStyle += 'background: #d1fae5; color: #065f46;'; break;
        case 'Will Pay': paymentConfStyle += 'background: #dcfce7; color: #166534;'; break;
        case 'Needs Extension': paymentConfStyle += 'background: #ffedd5; color: #9a3412;'; break;
        case 'Dispute': paymentConfStyle += 'background: #fee2e2; color: #991b1b;'; break;
        case 'No Response': paymentConfStyle += 'background: #f3f4f6; color: #6b7280;'; break;
        default: paymentConfStyle += 'background: #f9fafb; color: #9ca3af; border: 1px solid #e5e7eb;';
    }

    const summaryText = isCalled ? (borrower.ai_summary || 'No summary available.') : 'Awaiting call...';
    const emailPreview = borrower.email_to_manager_preview;
    const hasEmailBtn = emailPreview && Object.keys(emailPreview).length > 0;
    const prefix = context === 'escalation' ? 'esc' : 'report';
    const borrowerDisplayName = borrower.h_name || borrower.BORROWER || 'Borrower';

    row.innerHTML = `
        ${context !== 'escalation' ? `
        <td style="padding: 16px; font-weight: 500; color: #9ca3af; font-size: 12px;">${borrower.NO || '-'}</td>
        ` : ''}
        <td style="padding: 16px;">
            <div class="borrower-info-cell">
                <div class="borrower-avatar-mini">${(borrower.h_name || borrower.BORROWER || 'B').charAt(0)}</div>
                <div style="font-weight: 700; color: #1f2937; letter-spacing: 0.3px;">${borrower.h_name || borrower.BORROWER || '-'}</div>
            </div>
        </td>
        <td style="padding: 16px;">
            <span class="pill-badge amount">₹${amount}</span>
        </td>
        <td style="padding: 16px; color: #64748b; font-weight: 500;">${borrower.cell1 || borrower.MOBILE || '-'}</td>
        <td style="padding: 16px; color: #475569; font-weight: 600;">₹${emi}</td>
        ${context !== 'escalation' ? `
        <td style="padding: 16px;">
            <span class="pill-badge lang">${borrower.preferred_language || borrower.LANGUAGE || 'English'}</span>
        </td>
        ` : ''}
        <td style="padding: 16px; text-align: center;" id="${prefix}-payment-status-${borrower.NO}">
            <span style="${paymentConfStyle}">${paymentConf}</span>
        </td>
        ${context === 'escalation' ? `
        <td style="padding: 16px; font-weight: 700; color: #1f2937;" id="esc-category-${borrower.NO}">
            ${borrower.Payment_Category || '-'}
        </td>
        ` : ''}
        <td style="padding: 16px; font-weight: 600; color: #4b5563; line-height: 1.4; font-size: 13px;" id="${prefix}-follow-up-${borrower.NO}">${followUpHTML}</td>
        <td class="report-summary-cell" style="padding: 16px;" id="${prefix}-summary-cell-${borrower.NO}">
            ${renderTruncatedSummary(summaryText, `${prefix}-${borrower.NO}`, borrowerDisplayName, paymentConf)}
        </td>
        <td style="padding: 16px; min-width: 150px;">
            <div class="report-actions" id="${prefix}-actions-${borrower.NO}">
                <button class="report-action-btn report-manual-btn" style="display: ${isCalled && borrower.require_manual_process ? 'inline-flex' : 'none'}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                    Manual Call
                </button>
                <button class="report-action-btn report-email-btn" style="display: ${isCalled && hasEmailBtn ? 'inline-flex' : 'none'}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                    Email Manager
                </button>
            </div>
        </td>
        ${context !== 'escalation' ? `
        <td style="padding: 16px; font-weight: 500; color: #4b5563; font-size: 13px;" id="${prefix}-action-freq-${borrower.NO}">${callFreq}</td>
        ` : ''}
    `;

    // Always attach event listeners so they work when shown dynamically later
    const manualBtn = row.querySelector('.report-manual-btn');
    const emailBtn = row.querySelector('.report-email-btn');

    if (manualBtn) {
        manualBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openManualCallModal(borrower);
        });
    }

    if (emailBtn) {
        emailBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const currentEmailPreview = borrower.email_to_manager_preview;
            if (currentEmailPreview && Object.keys(currentEmailPreview).length > 0) {
                openEmailPreview(currentEmailPreview);
            } else {
                showNotification('No email draft available for this borrower.', 'warning');
            }
        });
    }

    // View Summary Button Listener
    const viewSummaryBtn = row.querySelector('.view-summary-btn');
    if (viewSummaryBtn) {
        viewSummaryBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const borrowerDisplayName = borrower.h_name || borrower.BORROWER || 'Borrower';
            const summary = isCalled ? (borrower.ai_summary || 'No summary available.') : 'Awaiting call...';
            openAiSummaryModal(summary, borrowerDisplayName, borrower.payment_confirmation);
        });
    }

    return row;
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
            updateDashboard(currentKpiData);
            showNotification('Data refreshed successfully!', 'success');
        });
    }
});

// Helper functions for intent styling (Case-insensitive)
function getIntentBg(intent) {
    if (!intent) return '#f3f4f6';
    const lIntent = intent.toLowerCase().trim();
    switch (lIntent) {
        case 'paid': return '#d1fae5';
        case 'will pay': return '#dcfce7';
        case 'needs extension': return '#fed7aa';
        case 'dispute': return '#fee2e2';
        case 'no response': return '#e5e7eb';
        case 'abusive language': return '#fef2f2';
        case 'threatening language': return '#7f1d1d';
        case 'stop calling': return '#4b5563';
        default: return '#f3f4f6';
    }
}

function getIntentColor(intent) {
    if (!intent) return '#9ca3af';
    const lIntent = intent.toLowerCase().trim();
    switch (lIntent) {
        case 'paid': return '#065f46';
        case 'will pay': return '#166534';
        case 'needs_extension': return '#9a3412';
        case 'dispute': return '#991b1b';
        case 'no response': return '#6b7280';
        case 'abusive language': return '#991b1b';
        case 'threatening language': return '#ffffff';
        case 'stop calling': return '#ffffff';
        default: return '#9ca3af';
    }
}
/**
 * Helper to render follow up dates as styled badges
 */
function renderFollowUpBadges(dateString) {
    if (!dateString || dateString === '-') return '-';

    const todayStr = new Date().toISOString().split('T')[0];
    const dates = dateString.split(',').map(d => d.trim()).filter(d => d);

    if (dates.length === 0) return '-';

    let html = '<div class="follow-up-badge-container">';
    dates.forEach(date => {
        const isToday = date === todayStr;
        const priorityClass = isToday ? 'priority-today' : '';

        // Use a simple SVG calendar icon for premium feel
        const calendarIcon = `<svg class="calendar-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px; vertical-align: middle;"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;

        html += `<span class="follow-up-badge ${priorityClass}">${calendarIcon}${date}</span>`;
    });
    html += '</div>';

    return html;
}

/**
 * Common logic to check if a borrower should be in the escalation report
 */
/**
 * Detects if a borrower should be escalated and returns info object
 */
function getEscalationInfo(borrower) {
    if (!borrower) return { isEscalated: false, reason: '' };

    // 1. Always escalate Inconsistent and Overdue (Case-insensitive)
    const category = (borrower.Payment_Category || '').trim();
    const lCategory = category.toLowerCase();

    if (lCategory === 'inconsistent' || lCategory === 'overdue') {
        return { isEscalated: true, reason: `Category: ${category}` };
    }

    // 2. High priority confirmations for ANY category (Case-insensitive)
    const conf = (borrower.payment_confirmation || '').trim();
    const lConf = conf.toLowerCase();

    if (lConf === 'abusive language') return { isEscalated: true, reason: 'AI: Abusive Language' };
    if (lConf === 'threatening language') return { isEscalated: true, reason: 'AI: Threatening Language' };
    if (lConf === 'dispute') return { isEscalated: true, reason: 'AI: Dispute' };
    if (lConf === 'stop calling') return { isEscalated: true, reason: 'AI: Stop Calling' };

    // 3. Any manual action required (Action Required column buttons)
    if (borrower.require_manual_process === true) {
        return { isEscalated: true, reason: 'Manual Action required' };
    }

    return { isEscalated: false, reason: '' };
}

/**
 * Returns true if the borrower should be in the escalation pool
 */
/**
 * Returns true if the borrower should be in the escalation pool
 */
function isEscalation(borrower) {
    return getEscalationInfo(borrower).isEscalated;
}

/**
 * Open the Manual Call Modal with borrower details
 */
function openManualCallModal(borrower) {
    console.log('Opening Manual Call Modal for:', borrower.h_name || borrower.BORROWER);
    currentBorrowerId = borrower.NO;

    const modal = document.getElementById('manualCallModal');
    const detailsContainer = document.getElementById('manualCallDetails');
    const statusZone = document.getElementById('manualCallStatus');
    const callBtn = document.getElementById('startManualCallBtn');
    const callBtnText = document.getElementById('callBtnText');
    const pauseBtn = document.getElementById('pauseCallBtn');
    const cancelBtn = document.getElementById('cancelCallBtn');

    if (!modal || !detailsContainer) return;

    // 1. Populate details
    const amount = (borrower.amtfin || borrower.AMOUNT || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const emi = (borrower.emi || borrower.EMI || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const phone = borrower.cell1 || borrower.MOBILE || 'N/A';
    const loanId = borrower.contnr || borrower.NO || 'N/A';
    const category = borrower.acstatus || borrower.Payment_Category || 'Normal';

    detailsContainer.innerHTML = `
        <div class="detail-item">
            <span class="detail-label">Borrower Name</span>
            <span class="detail-value">${borrower.h_name || borrower.BORROWER}</span>
        </div>
        <div class="detail-item">
            <span class="detail-label">Phone Number</span>
            <span class="detail-value">${phone}</span>
        </div>
        <div class="detail-item">
            <span class="detail-label">Loan Amount</span>
            <span class="detail-value">₹${amount}</span>
        </div>
        <div class="detail-item">
            <span class="detail-label">EMI Amount</span>
            <span class="detail-value">₹${emi}</span>
        </div>
        <div class="detail-item">
            <span class="detail-label">Loan ID</span>
            <span class="detail-value">#${loanId}</span>
        </div>
        <div class="detail-item">
            <span class="detail-label">Payment Category</span>
            <span class="detail-value">${category}</span>
        </div>
    `;

    // 2. Reset Status
    statusZone.className = 'status-indicator yet-to-call';
    statusZone.querySelector('.status-text').textContent = 'Yet To Call';

    // 3. Reset Buttons
    callBtn.disabled = false;
    callBtnText.textContent = 'MAKE CALL';
    callBtn.style.opacity = '1';
    pauseBtn.disabled = true;
    cancelBtn.disabled = false;

    // 4. Show Modal
    modal.style.display = 'flex';
    modal.classList.add('active');

    // 5. Setup Start Button (Clone to clear old listeners)
    const oldBtn = document.getElementById('startManualCallBtn');
    if (oldBtn) {
        const newBtn = oldBtn.cloneNode(true);
        oldBtn.parentNode.replaceChild(newBtn, oldBtn);
        newBtn.addEventListener('click', () => {
            initiateManualCallSimulation(borrower);
        });
    }
}

/**
 * Handle the manual call initiation and simulation
 */
// ── ACTUAL MANUAL CALL AUDIO HANDLER ──
let manualAudioContext = null;
let manualWs = null;
let manualMicStream = null;
let manualScriptProcessor = null;

async function initiateManualCallSimulation(borrower) {
    const statusContainer = document.getElementById('manualCallStatus');
    const statusText = statusContainer.querySelector('.status-text');
    const makeCallBtn = document.getElementById('startManualCallBtn');

    statusText.innerText = 'Connecting...';
    statusContainer.className = 'status-indicator status-connecting';
    makeCallBtn.disabled = true;

    console.log(`☎️ Starting Manual Audio Bridge to ${borrower.h_name || borrower.BORROWER}...`);

    try {
        const phone = String(borrower.cell1 || borrower.MOBILE || '');
        const borrowerId = String(borrower.NO || '');


        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/ai_calling/make_call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                to_number: phone,
                borrower_id: borrowerId,
                is_manual: true,
                use_dummy_data: false
            })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Failed to initiate call');
        }

        const data = await response.json();
        const callUuid = data.call_uuid;

        statusText.innerText = 'Call in Progress (Real-time Audio)';
        statusText.className = 'manual-call-status status-in-progress';

        // Start Audio Bridge
        await startManualAudioBridge(callUuid);

    } catch (error) {
        console.error('Manual call error:', error);
        statusText.innerText = 'Call Failed';
        statusText.className = 'manual-call-status status-completed';
        makeCallBtn.disabled = false;
        showNotification('Error starting manual call: ' + error.message, 'error');
    }
}

async function startManualAudioBridge(callUuid) {
    try {
        // 1. Get Microphone
        manualMicStream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // 2. Initialize Audio Context
        manualAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });

        // 3. Setup WebSocket - MUST hit port 5000 (Flask)
        let wsHost = API_BASE_URL.replace(/http:\/\/|https:\/\//, '');
        // If we're hitting local FastAPI (8000), switch to local Flask (5000) for WebSockets
        if (wsHost.includes('127.0.0.1:8000') || wsHost.includes('localhost:8000')) {
            wsHost = wsHost.replace(':8000', ':5000');
        }

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        console.log(`[WS] Connecting to Manual Bridge: ${wsProtocol}//${wsHost}/agent-socket/${callUuid}`);
        manualWs = new WebSocket(`${wsProtocol}//${wsHost}/agent-socket/${callUuid}`);
        manualWs.binaryType = 'arraybuffer';

        manualWs.onopen = () => {
            console.log('[WS] Manual session connected');

            // Start streaming mic
            const source = manualAudioContext.createMediaStreamSource(manualMicStream);
            manualScriptProcessor = manualAudioContext.createScriptProcessor(4096, 1, 1);

            manualScriptProcessor.onaudioprocess = (e) => {
                const inputData = e.inputBuffer.getChannelData(0);
                const pcmBuffer = new ArrayBuffer(inputData.length * 2);
                const view = new DataView(pcmBuffer);

                for (let i = 0; i < inputData.length; i++) {
                    let s = Math.max(-1, Math.min(1, inputData[i]));
                    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                }

                if (manualWs.readyState === WebSocket.OPEN) {
                    manualWs.send(pcmBuffer);
                }
            };

            source.connect(manualScriptProcessor);
            manualScriptProcessor.connect(manualAudioContext.destination);
        };

        manualWs.onmessage = (e) => {
            if (typeof e.data === 'string') return;

            // Play received audio
            const pcm16 = new Int16Array(e.data);
            const float32 = new Float32Array(pcm16.length);
            for (let i = 0; i < pcm16.length; i++) {
                float32[i] = pcm16[i] / 32768.0;
            }

            const buffer = manualAudioContext.createBuffer(1, float32.length, 16000);
            buffer.getChannelData(0).set(float32);

            const source = manualAudioContext.createBufferSource();
            source.buffer = buffer;
            source.connect(manualAudioContext.destination);
            source.start();
        };

        manualWs.onclose = () => {
            console.log('[WS] Manual session closed');
            stopManualAudioBridge();
        };

    } catch (err) {
        console.error('Audio Bridge Error:', err);
        showNotification('Microphone access required for manual call.', 'error');
        stopManualAudioBridge();
    }
}

function stopManualAudioBridge() {
    console.log('[AUDIO] Stopping bridge and cleanup...');
    if (manualWs) {
        manualWs.close();
        manualWs = null;
    }
    if (manualMicStream) {
        manualMicStream.getTracks().forEach(track => track.stop());
        manualMicStream = null;
    }
    if (manualScriptProcessor) {
        manualScriptProcessor.disconnect();
        manualScriptProcessor = null;
    }
    if (manualAudioContext) {
        if (manualAudioContext.state !== 'closed') {
            manualAudioContext.close();
        }
        manualAudioContext = null;
    }

    const statusContainer = document.getElementById('manualCallStatus');
    if (statusContainer) {
        const statusText = statusContainer.querySelector('.status-text');
        if (statusText) statusText.innerText = 'Call Ended';
        statusContainer.className = 'status-indicator completed';
    }

    const makeCallBtn = document.getElementById('startManualCallBtn');
    if (makeCallBtn) {
        makeCallBtn.disabled = false;
        const btnText = document.getElementById('callBtnText');
        if (btnText) btnText.textContent = 'MAKE CALL';
    }
}

// Remove the redundant listener at the bottom

// ================================================================
// GOVERNANCE — RBI Calling Hours & Slot Management
// ================================================================

let selectedSlotId = null;

async function loadGovernanceStatus() {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/governance/calling_hours_status`);
        if (!response.ok) throw new Error('Failed to load governance status');
        const status = await response.json();

        // Update status indicator
        const indicator = document.getElementById('rbiStatusIndicator');
        const badge = document.getElementById('rbiStatusBadge');
        if (status.is_within_calling_hours) {
            indicator.style.background = '#22c55e';
            indicator.style.boxShadow = '0 0 8px rgba(34,197,94,0.5)';
            badge.textContent = 'Window Open';
            badge.style.background = '#dcfce7';
            badge.style.color = '#166534';
        } else {
            indicator.style.background = '#ef4444';
            indicator.style.boxShadow = '0 0 8px rgba(239,68,68,0.5)';
            badge.textContent = 'Window Closed';
            badge.style.background = '#fee2e2';
            badge.style.color = '#991b1b';
        }

        // Update info cards
        document.getElementById('govCurrentTime').textContent = status.current_time_ist;
        document.getElementById('govWindowLabel').textContent = status.calling_window.label;
        document.getElementById('govRemainingMin').textContent =
            status.is_within_calling_hours ? `${status.remaining_minutes} min` : 'Closed';

        // Update dropdowns to reflect current config
        const startSelect = document.getElementById('govStartHour');
        const endSelect = document.getElementById('govEndHour');
        if (startSelect) startSelect.value = status.calling_window.start.split(':')[0];
        if (endSelect) endSelect.value = status.calling_window.end.split(':')[0];

        // Restore selected slot from backend
        if (status.selected_slot) {
            selectedSlotId = status.selected_slot.slot_id;
            const infoBox = document.getElementById('selectedSlotInfo');
            const labelSpan = document.getElementById('selectedSlotLabel');
            if (infoBox) infoBox.style.display = 'block';
            if (labelSpan) labelSpan.textContent = status.selected_slot.label;
        } else {
            selectedSlotId = null;
            const infoBox = document.getElementById('selectedSlotInfo');
            if (infoBox) infoBox.style.display = 'none';
        }

        // Load slots
        await loadTimeSlots();
    } catch (err) {
        console.error('Governance status error:', err);
    }
}

async function loadTimeSlots() {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE_URL}/governance/time_slots`);
        if (!response.ok) throw new Error('Failed to load time slots');
        const data = await response.json();

        const grid = document.getElementById('slotGrid');
        if (!grid) return;

        // Use backend's selected_slot as source of truth
        if (data.selected_slot) {
            selectedSlotId = data.selected_slot.slot_id;
        }

        grid.innerHTML = data.slots.map(slot => {
            let bgColor, textColor, border, cursor, opacity;
            if (slot.status === 'past') {
                bgColor = '#f1f5f9'; textColor = '#94a3b8'; border = '1px solid #e2e8f0';
                cursor = 'not-allowed'; opacity = '0.6';
            } else if (slot.status === 'current') {
                bgColor = 'linear-gradient(135deg, #bbf7d0, #86efac)'; textColor = '#166534';
                border = '2px solid #22c55e'; cursor = 'pointer'; opacity = '1';
            } else {
                bgColor = '#ffffff'; textColor = '#1e293b';
                border = '1px solid #e2e8f0'; cursor = 'pointer'; opacity = '1';
            }

            // Highlight selected slot with purple gradient
            if (slot.is_selected) {
                bgColor = 'linear-gradient(135deg, #667eea, #764ba2)';
                textColor = '#ffffff';
                border = '2px solid #667eea';
            }

            return `
                <div class="slot-card" data-slot-id="${slot.id}" data-slot-label="${slot.label}"
                     data-slot-status="${slot.status}" data-start-hour="${slot.start_hour}" data-end-hour="${slot.end_hour}"
                     style="background: ${bgColor}; color: ${textColor}; border: ${border};
                            border-radius: 12px; padding: 16px; text-align: center;
                            cursor: ${cursor}; opacity: ${opacity}; transition: all 0.2s ease;
                            ${slot.status !== 'past' ? 'box-shadow: 0 2px 8px rgba(0,0,0,0.06);' : ''}">
                    <div style="font-size: 14px; font-weight: 700; margin-bottom: 4px;">${slot.label}</div>
                    <div style="font-size: 11px; font-weight: 500; opacity: 0.8; text-transform: uppercase;">
                        ${slot.is_selected ? '🔒 Selected' : slot.status === 'current' ? '🟢 Active Now' : slot.status === 'past' ? '⏰ Passed' : '📅 Available'}
                    </div>
                </div>
            `;
        }).join('');

        // Slot click handlers
        grid.querySelectorAll('.slot-card').forEach(card => {
            card.addEventListener('click', async () => {
                const slotStatus = card.dataset.slotStatus;
                if (slotStatus === 'past') return;

                const slotId = card.dataset.slotId;
                const label = card.dataset.slotLabel;
                const startHour = parseInt(card.dataset.startHour);
                const endHour = parseInt(card.dataset.endHour);

                // POST slot selection to backend for enforcement
                try {
                    const resp = await makeAuthenticatedRequest(`${API_BASE_URL}/governance/select_slot`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            slot_id: slotId,
                            start_hour: startHour,
                            end_hour: endHour,
                            label: label
                        })
                    });

                    if (!resp.ok) {
                        const errData = await resp.json().catch(() => ({}));
                        throw new Error(errData.detail || 'Failed to select slot');
                    }

                    const result = await resp.json();
                    selectedSlotId = slotId;

                    // Update selection info bar
                    const infoBox = document.getElementById('selectedSlotInfo');
                    const labelSpan = document.getElementById('selectedSlotLabel');
                    if (infoBox) infoBox.style.display = 'block';
                    if (labelSpan) labelSpan.textContent = label;

                    showNotification(result.message, 'success');

                    // Re-render slots to update visual state
                    await loadTimeSlots();
                } catch (err) {
                    showNotification('Failed to select slot: ' + err.message, 'error');
                }
            });

            // Hover effects for non-past slots
            if (card.dataset.slotStatus !== 'past') {
                card.addEventListener('mouseenter', () => {
                    if (card.dataset.slotId !== selectedSlotId) {
                        card.style.transform = 'translateY(-2px)';
                        card.style.boxShadow = '0 4px 12px rgba(0,0,0,0.12)';
                    }
                });
                card.addEventListener('mouseleave', () => {
                    card.style.transform = '';
                    card.style.boxShadow = '';
                });
            }
        });
    } catch (err) {
        console.error('Time slots error:', err);
    }
}

function setupGovernanceListeners() {
    // Update calling hours button
    const updateBtn = document.getElementById('updateCallingHoursBtn');
    if (updateBtn) {
        updateBtn.addEventListener('click', async () => {
            const startHour = parseInt(document.getElementById('govStartHour').value);
            const endHour = parseInt(document.getElementById('govEndHour').value);

            if (startHour >= endHour) {
                showNotification('Start time must be before end time', 'error');
                return;
            }

            try {
                const response = await makeAuthenticatedRequest(`${API_BASE_URL}/governance/update_calling_hours`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ start_hour: startHour, end_hour: endHour })
                });

                if (!response.ok) {
                    const errData = await response.json().catch(() => ({}));
                    throw new Error(errData.detail || 'Failed to update');
                }

                const result = await response.json();
                showNotification(result.message, 'success');
                await loadGovernanceStatus();
            } catch (err) {
                showNotification('Failed to update calling hours: ' + err.message, 'error');
            }
        });
    }

    // Clear slot button
    const clearBtn = document.getElementById('clearSlotBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', async () => {
            try {
                const response = await makeAuthenticatedRequest(`${API_BASE_URL}/governance/clear_slot`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (!response.ok) throw new Error('Failed to clear slot');

                const result = await response.json();
                selectedSlotId = null;

                const infoBox = document.getElementById('selectedSlotInfo');
                if (infoBox) infoBox.style.display = 'none';

                showNotification(result.message, 'success');
                await loadTimeSlots();
            } catch (err) {
                showNotification('Failed to clear slot: ' + err.message, 'error');
            }
        });
    }
}

// Initialize governance listeners after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    setupGovernanceListeners();
});

