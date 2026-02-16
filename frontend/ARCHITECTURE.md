# Frontend Architecture - AI Finance Platform

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER BROWSER                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Frontend (HTML/CSS/JS)                     │    │
│  │                                                          │    │
│  │  ├─ index.html (Main Dashboard)                        │    │
│  │  ├─ test.html (Connection Test)                        │    │
│  │  ├─ style.css (Styling)                                │    │
│  │  └─ js/app.js (Application Logic)                      │    │
│  │                                                          │    │
│  │     ┌──────────────────────────────────────┐           │    │
│  │     │   makeAuthenticatedRequest()         │           │    │
│  │     │   - Adds auth headers                │           │    │
│  │     │   - Handles 401 errors               │           │    │
│  │     │   - Auto token refresh               │           │    │
│  │     └──────────────────────────────────────┘           │    │
│  │                      │                                   │    │
│  └──────────────────────┼───────────────────────────────────┘    │
│                         │                                        │
│                         │ HTTP/HTTPS                             │
│                         ▼                                        │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │
┌─────────────────────────┼─────────────────────────────────────┐
│                         │         BACKEND                      │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────┐     │
│  │           FastAPI Server (Port 8000)                  │     │
│  │                                                        │     │
│  │  ┌─────────────────────────────────────────────┐     │     │
│  │  │  Authentication Middleware                   │     │     │
│  │  │  - Verify JWT tokens                        │     │     │
│  │  │  - Extract user_id                          │     │     │
│  │  └─────────────────────────────────────────────┘     │     │
│  │                                                        │     │
│  │  ┌─────────────────────────────────────────────┐     │     │
│  │  │  API Endpoints                              │     │     │
│  │  │                                              │     │     │
│  │  │  /auth/*                                     │     │     │
│  │  │  ├─ POST /register                          │     │     │
│  │  │  ├─ POST /login                             │     │     │
│  │  │  ├─ POST /refresh                           │     │     │
│  │  │  └─ POST /logout                            │     │     │
│  │  │                                              │     │     │
│  │  │  /data_ingestion/*                          │     │     │
│  │  │  ├─ POST /data (upload + fetch)             │     │     │
│  │  │  ├─ GET /borrowers                          │     │     │
│  │  │  └─ DELETE /delete_all                      │     │     │
│  │  │                                              │     │     │
│  │  │  /ai_calling/*                              │     │     │
│  │  │  ├─ POST /trigger_calls                     │     │     │
│  │  │  ├─ POST /reset_calls                       │     │     │
│  │  │  └─ GET /sessions                           │     │     │
│  │  └─────────────────────────────────────────────┘     │     │
│  │                      │                                 │     │
│  └──────────────────────┼─────────────────────────────────┘     │
│                         │                                       │
│                         ▼                                       │
│  ┌──────────────────────────────────────────────────────┐     │
│  │              MongoDB Database                         │     │
│  │                                                        │     │
│  │  Collections:                                         │     │
│  │  ├─ users (user_id, username, password, tokens)      │     │
│  │  ├─ borrowers (user_id, borrower data)               │     │
│  │  └─ call_sessions (user_id, call data)               │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Authentication Flow

```
┌──────────┐                                    ┌──────────┐
│ Frontend │                                    │ Backend  │
└────┬─────┘                                    └────┬─────┘
     │                                                │
     │  1. POST /auth/login                          │
     │  { username, password }                       │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  2. Verify credentials                        │
     │     Generate access_token                     │
     │     Generate refresh_token                    │
     │◄──────────────────────────────────────────────┤
     │  { access_token, refresh_token, user }        │
     │                                                │
     │  3. Store tokens in sessionStorage            │
     │                                                │
     │  4. Make authenticated request                │
     │  Authorization: Bearer <access_token>         │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  5. Verify token & extract user_id            │
     │     Return user-specific data                 │
     │◄──────────────────────────────────────────────┤
     │  { data filtered by user_id }                 │
     │                                                │
     │  6. Token expires (401 error)                 │
     │◄──────────────────────────────────────────────┤
     │                                                │
     │  7. POST /auth/refresh                        │
     │  { refresh_token }                            │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  8. Verify refresh_token                      │
     │     Generate new access_token                 │
     │◄──────────────────────────────────────────────┤
     │  { access_token }                             │
     │                                                │
     │  9. Retry original request                    │
     │  Authorization: Bearer <new_access_token>     │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  10. Success                                  │
     │◄──────────────────────────────────────────────┤
     │                                                │
```

## Data Flow - File Upload

```
┌──────────┐                                    ┌──────────┐
│ Frontend │                                    │ Backend  │
└────┬─────┘                                    └────┬─────┘
     │                                                │
     │  1. User selects file                         │
     │     (Excel/CSV)                                │
     │                                                │
     │  2. POST /data_ingestion/data                 │
     │  Authorization: Bearer <token>                │
     │  FormData: file                               │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  3. Verify authentication                     │
     │     Extract user_id from token                │
     │     Parse file (pandas)                       │
     │     Categorize borrowers                      │
     │     Save to MongoDB with user_id              │
     │                                                │
     │  4. Return aggregated data                    │
     │◄──────────────────────────────────────────────┤
     │  {                                             │
     │    kpis: { total_borrowers, total_arrears },  │
     │    detailed_breakdown: {                      │
     │      by_due_date_category: {                  │
     │        "Today": [...],                        │
     │        "1-7_days": [...],                     │
     │        "More_than_7_days": [...]              │
     │      }                                         │
     │    }                                           │
     │  }                                             │
     │                                                │
     │  5. Update UI with data                       │
     │     Store in localStorage                     │
     │                                                │
```

## Data Flow - AI Calling

```
┌──────────┐                                    ┌──────────┐
│ Frontend │                                    │ Backend  │
└────┬─────┘                                    └────┬─────┘
     │                                                │
     │  1. User clicks "Make call"                   │
     │                                                │
     │  2. POST /ai_calling/trigger_calls            │
     │  Authorization: Bearer <token>                │
     │  {                                             │
     │    borrowers: [                               │
     │      { NO, cell1, preferred_language }        │
     │    ],                                          │
     │    use_dummy_data: true                       │
     │  }                                             │
     ├──────────────────────────────────────────────►│
     │                                                │
     │  3. Verify authentication                     │
     │     Extract user_id from token                │
     │     Process calls in parallel                 │
     │     Generate AI conversations                 │
     │     Save to call_sessions with user_id        │
     │     Update borrowers with user_id filter      │
     │                                                │
     │  4. Return results                            │
     │◄──────────────────────────────────────────────┤
     │  {                                             │
     │    total_requests: 10,                        │
     │    successful_calls: 10,                      │
     │    results: [                                 │
     │      {                                         │
     │        success: true,                         │
     │        call_uuid: "...",                      │
     │        conversation: [...],                   │
     │        ai_analysis: { summary, ... }          │
     │      }                                         │
     │    ]                                           │
     │  }                                             │
     │                                                │
     │  5. Update UI                                 │
     │     - Change status to "Call Success"         │
     │     - Display transcripts                     │
     │     - Show AI summaries                       │
     │     - Update localStorage                     │
     │                                                │
```

## User Isolation

```
┌─────────────────────────────────────────────────────────┐
│                    MongoDB Database                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Users Collection:                                       │
│  ┌────────────────────────────────────────────────┐    │
│  │ { _id: "user1", username: "alice", ... }       │    │
│  │ { _id: "user2", username: "bob", ... }         │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  Borrowers Collection:                                  │
│  ┌────────────────────────────────────────────────┐    │
│  │ { user_id: "user1", NO: "001", ... }  ◄─ Alice │    │
│  │ { user_id: "user1", NO: "002", ... }  ◄─ Alice │    │
│  │ { user_id: "user2", NO: "001", ... }  ◄─ Bob   │    │
│  │ { user_id: "user2", NO: "002", ... }  ◄─ Bob   │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  Call Sessions Collection:                              │
│  ┌────────────────────────────────────────────────┐    │
│  │ { user_id: "user1", call_uuid: "...", ... }    │    │
│  │ { user_id: "user2", call_uuid: "...", ... }    │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  Query Pattern:                                         │
│  db.borrowers.find({ user_id: current_user_id })       │
│                                                          │
│  Result: Each user sees ONLY their own data             │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Frontend File Structure

```
frontend/
├── index.html              # Main dashboard UI
├── test.html               # Connection testing page
├── style.css               # All styling and animations
├── js/
│   └── app.js             # Application logic
│       ├── Authentication
│       │   ├── checkAuth()
│       │   ├── handleLogin()
│       │   ├── handleRegister()
│       │   ├── handleLogout()
│       │   └── makeAuthenticatedRequest() ★
│       ├── Data Management
│       │   ├── fetchData()
│       │   ├── handleFileUpload()
│       │   └── updateDashboard()
│       ├── AI Calling
│       │   ├── handleBulkCall()
│       │   ├── handleResetCalls()
│       │   └── createCallDataRow()
│       └── UI Helpers
│           ├── showView()
│           ├── showLoading()
│           └── showNotification()
├── start.sh               # Quick start script
├── README.md              # User documentation
├── UPDATES.md             # Technical changes
└── CHECKLIST.md           # Quick reference
```

## Key Components

### makeAuthenticatedRequest() ★
The central function that handles all API communication:

```javascript
async function makeAuthenticatedRequest(url, options = {}) {
    // 1. Add Authorization header
    // 2. Make request
    // 3. Check for 401 (token expired)
    // 4. If 401, try to refresh token
    // 5. Retry request with new token
    // 6. If refresh fails, logout user
    // 7. Return response
}
```

### Token Management
```
sessionStorage:
├── auth_token (access token)
├── refresh_token (refresh token)
└── user_name (username)

localStorage:
└── finance_data (cached borrower data)
```

## Security Features

1. **JWT Authentication**
   - Access tokens for API calls
   - Refresh tokens for session renewal
   - Automatic token rotation

2. **User Isolation**
   - All data filtered by user_id
   - No cross-user data access
   - Backend enforces isolation

3. **Session Management**
   - Tokens in sessionStorage (cleared on close)
   - Data cache in localStorage (persists)
   - Automatic cleanup on logout

4. **Error Handling**
   - Graceful authentication failures
   - User-friendly error messages
   - Automatic retry on token refresh

## Performance Optimizations

1. **Data Caching**
   - localStorage for offline access
   - Reduces API calls
   - Faster page loads

2. **Parallel Processing**
   - Bulk calls processed concurrently
   - Async/await for non-blocking UI
   - Real-time status updates

3. **Lazy Loading**
   - Views loaded on demand
   - Reduced initial load time
   - Better user experience

---

**Architecture Version**: 2.0.0  
**Last Updated**: February 16, 2026
