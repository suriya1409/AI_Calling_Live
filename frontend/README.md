# AI Finance Platform - Frontend

## Overview
This is the frontend interface for the AI Finance Platform, providing a modern, user-friendly dashboard for managing borrower data and AI-powered calling features.

## Features

### 🔐 Authentication
- **User Registration**: Create new user accounts
- **Login/Logout**: Secure authentication with JWT tokens
- **Auto Token Refresh**: Automatic token refresh for seamless user experience
- **Session Management**: Persistent sessions across page reloads

### 📊 Dashboard
- **KPI Overview**: View total borrowers, total arrears, and call statistics
- **Due Date Categories**: Organize borrowers by due date (Today, 1-7 Days, More than 7 Days)
- **Payment Categories**: Track Consistent, Inconsistent, and Overdue payers
- **Real-time Updates**: Live data synchronization with backend

### 📤 Data Management
- **File Upload**: Upload Excel (.xlsx, .xls) or CSV files
- **Data Validation**: Automatic file type and size validation
- **Data Persistence**: Local storage for offline access
- **User Isolation**: Each user sees only their own data

### 📞 AI Calling Features
- **Bulk Calls**: Trigger calls for multiple borrowers simultaneously
- **Call Status Tracking**: Monitor call progress (Yet To Call, In Progress, Call Success)
- **AI Transcripts**: View conversation transcripts for each call
- **AI Summaries**: Get AI-generated summaries and next steps
- **Multi-language Support**: English, Hindi, and Tamil

### 🎨 UI/UX Features
- **Modern Design**: Glassmorphism effects and smooth animations
- **Responsive Layout**: Works on desktop and mobile devices
- **Dark Theme**: Eye-friendly dark color scheme
- **Toast Notifications**: Real-time feedback for user actions
- **Loading States**: Visual feedback during API operations

## Getting Started

### Prerequisites
- Modern web browser (Chrome, Firefox, Safari, Edge)
- Backend server running on `http://127.0.0.1:8000`

### Running the Frontend

1. **Using a Simple HTTP Server (Python)**:
   ```bash
   cd frontend
   python3 -m http.server 8080
   ```
   Then open `http://localhost:8080` in your browser

2. **Using Live Server (VS Code Extension)**:
   - Install the "Live Server" extension in VS Code
   - Right-click on `index.html` and select "Open with Live Server"

3. **Using Node.js http-server**:
   ```bash
   cd frontend
   npx http-server -p 8080
   ```

### First Time Setup

1. **Register a New Account**:
   - Click "Register here" on the login screen
   - Enter a username and password
   - Click "Register"

2. **Login**:
   - Enter your credentials
   - Click "Login"

3. **Upload Data**:
   - Click the "Upload" button in the header
   - Select an Excel or CSV file with borrower data
   - Wait for the upload to complete

4. **Make Calls**:
   - Click "View Details" on any due date category
   - Click "Make call" to trigger AI calls for all borrowers in that category
   - Expand individual rows to view transcripts and summaries

## File Structure

```
frontend/
├── index.html          # Main HTML file
├── style.css           # Styling and animations
├── js/
│   └── app.js         # Application logic and API integration
└── README.md          # This file
```

## API Integration

The frontend communicates with the backend using the following endpoints:

### Authentication
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get tokens
- `POST /auth/refresh` - Refresh access token
- `POST /auth/logout` - Logout and revoke tokens

### Data Ingestion
- `POST /data_ingestion/data` - Upload file and fetch borrower data
- `GET /data_ingestion/borrowers` - List borrowers

### AI Calling
- `POST /ai_calling/trigger_calls` - Trigger bulk calls
- `POST /ai_calling/reset_calls` - Reset all call statuses
- `GET /ai_calling/sessions` - Get call sessions

## Configuration

The API base URL is configured in `js/app.js`:

```javascript
const API_BASE_URL = 'http://127.0.0.1:8000';
```

If your backend is running on a different port or host, update this constant.

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Troubleshooting

### "Authentication failed" errors
- Check if the backend server is running
- Try logging out and logging back in
- Clear browser cache and session storage

### Data not loading
- Ensure you're logged in
- Check browser console for errors
- Verify backend API is accessible

### File upload fails
- Check file format (must be .xlsx, .xls, or .csv)
- Ensure file size is reasonable
- Check backend logs for errors

### Calls not triggering
- Ensure borrower data has valid phone numbers
- Check that `preferred_language` field is set
- Verify backend AI calling service is configured

## Security Notes

- Tokens are stored in `sessionStorage` (cleared on browser close)
- Data is cached in `localStorage` (persists across sessions)
- All API requests include authentication headers
- Automatic token refresh prevents session expiration

## Development

### Making Changes

1. Edit the relevant files (`index.html`, `style.css`, `js/app.js`)
2. Refresh the browser to see changes
3. Use browser DevTools for debugging

### Adding New Features

1. Add UI elements in `index.html`
2. Style them in `style.css`
3. Add logic in `js/app.js`
4. Use `makeAuthenticatedRequest()` for API calls

## Support

For issues or questions, please check:
- Backend logs for API errors
- Browser console for frontend errors
- Network tab in DevTools for failed requests
