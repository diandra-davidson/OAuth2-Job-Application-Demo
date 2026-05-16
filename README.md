# Diandra's OAuth2 Job Application Demo

A FastAPI application that implements GitHub OAuth2 authorization with a secure multipart job application submission flow. Users authenticate with GitHub, and their credentials are exchanged for a short-lived JWT token used to submit a job application with resume upload.

## Features

- **GitHub OAuth2 Authorization Code Flow** — Redirect users to GitHub login, exchange code for access token
- **User Profile Extraction** — Automatically fetch name, email, and GitHub username from GitHub API
- **JWT Token Issuance** — Generate HS256-signed short-lived JWT tokens (1 hour expiry)
- **Secure Cookies** — HttpOnly, Secure, SameSite cookie storage for app tokens (configurable for local dev)
- **Multipart Job Application** — Submit PDF resume + form fields (name, email, github_username)
- **SHA-256 Bearer Authorization** — Upstream endpoint authentication using email hash
- **Pretty Print Logging** — Debug output showing all headers and form fields sent upstream

## Prerequisites

- Python 3.9+
- Linux (uses `keyring` for secret storage)
- `pip` with system package installation support

## Installation

1. Clone/navigate to the project:
```bash
cd /path/to/project/oauth_job_app
```

2. Create a Python virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:
```bash
python3 -m pip install -r requirements.txt
```

4. Store secrets in your system keyring:
```bash
# Session middleware secret (random 32+ character string)
python3 -c "import keyring; keyring.set_password('service_name', 'username', 'your-random-session-secret-here')"

# JWT signing secret (random 32+ character string, separate from session secret)
python3 -c "import keyring; keyring.set_password('jwt_service_name', 'username', 'your-random-jwt-signing-secret-here')"
```

## Configuration

Set environment variables before running:

```bash
# GitHub OAuth credentials (required)
export OAUTH_CLIENT_ID="your-github-oauth-app-client-id"
export OAUTH_CLIENT_SECRET="your-github-oauth-app-client-secret"

# GitHub OAuth endpoints (defaults work for standard GitHub)
export OAUTH_AUTHORIZATION_URL="https://github.com/login/oauth/authorize"
export OAUTH_TOKEN_URL="https://github.com/login/oauth/access_token"
export OAUTH_SCOPE="read:user,user:email"

# Job application endpoint (required for /apply to work)
export JOB_APPLICATION_URL="https://your-backend.example.com/apply"

# Custom message sent in x-application-comment header (optional)
export JOB_APPLICATION_COMMENT="Your custom comment here"

# Cookie security (set to 'false' for local HTTP dev, 'true' for production HTTPS)
export COOKIE_SECURE="false"
```

## Running the Application

```bash
cd /path/to/project/oauth_job_app
# Running with the --reload flag will start in debug mode
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The app will start on `http://localhost:8000`.

## API Endpoints

### `GET /`
Home page with instructions.

**Response:**
```json
{
  "message": "Visit /login to begin OAuth2 flow."
}
```

---

### `GET /login`
Initiates GitHub OAuth2 authorization flow.

Redirects to GitHub's authorization endpoint with your client ID, requested scopes, and a state parameter for CSRF protection.

---

### `GET /auth/callback`
OAuth2 callback endpoint (called by GitHub after user authorization).

**Query Parameters:**
- `code` (string, required) — Authorization code from GitHub
- `state` (string, required) — State parameter for CSRF validation

**On Success:**
- Exchanges code for GitHub access token
- Fetches user profile and emails from GitHub API
- Generates HS256 JWT token (1 hour expiry)
- Sets HttpOnly cookie `app_token`

**Response (200 OK):**
```json
{
  "message": "OAuth callback succeeded",
  "full_name": "Diandra Davidson",
  "email": "diandra@example.com",
  "github_username": "diandra-davidson",
  "token": "eyBz..."
}
```

**Response Headers:**
- `x-full-name` — User's full name
- `x-email` — User's primary email
- `x-github-username` — GitHub username
- `x-app-token` — The JWT token
- `Set-Cookie` — `app_token` (HttpOnly, Secure)

---

### `POST /apply`
Submit job application with resume upload.

Accepts form fields and multipart resume file. Identity fields are optional if `app_token` cookie is valid; otherwise they must be provided.

**Form Parameters:**
- `name` (string, optional) — Applicant full name (auto-filled from JWT if not provided)
- `email` (string, optional) — Applicant email (auto-filled from JWT if not provided)
- `github_username` (string, optional) — GitHub username (auto-filled from JWT if not provided)
- `resume` (file, required) — PDF resume (max 5 MB)

**Custom Headers Sent Upstream:**
- `authorization: Bearer <sha256(email)>` — Upstream endpoint auth
- `x-applicant-name` — Applicant name
- `x-applicant-email` — Applicant email
- `x-applicant-github` — GitHub username
- `x-application-comment` — Custom comment/message
- `x-application-source` — Source identifier
- `x-application-timestamp` — ISO 8601 timestamp
- `x-application-id` — Unique request ID

**Response (200 OK):**
```
{
  "method": "POST",
  "path": "/apply",
  "headers_sent": { ... },
  "upstream_request_body": { ... }
}
```

Pretty-printed to stdout and returned as plain text JSON.

---

### `POST /test_submit_application`
Demo echo endpoint (for local testing only).

Receives multipart form data and returns a pretty-printed JSON dump of all received headers, form fields, and file metadata.

**Response (200 OK):**
```json
{
  "method": "POST",
  "path": "/test_submit_application",
  "headers": { ... },
  "body": {
    "content_type": "multipart/form-data; boundary=...",
    "size_bytes": 12345,
    "preview": "omitted (resume file preview disabled)",
    "form_fields": { ... },
    "files": { ... }
  }
}
```

## Example Usage

### 1. Start OAuth2 Flow
```bash
# Open browser or visit:
curl -v http://localhost:8000/login
```
This redirects to GitHub. After authorization, GitHub redirects back to `/auth/callback` with a `code`.

### 2. GitHub Automatically Redirects to Callback
GitHub sends browser to:
```
http://localhost:8000/auth/callback?code=...&state=...
```

Your app exchanges the code for a token and sets `app_token` cookie.

### 3. Submit Job Application
```bash
curl -X POST "http://localhost:8000/apply" \
  -H "Cookie: app_token=<your-jwt-from-callback>" \
  -F "resume=@/path/to/resume.pdf;type=application/pdf"
```

Or with explicit fields:
```bash
curl -X POST "http://localhost:8000/apply" \
  -F "name=Diandra Davidson" \
  -F "email=diandra@example.com" \
  -F "github_username=diandra-davidson" \
  -F "resume=@/path/to/resume.pdf;type=application/pdf"
```

## Security Notes

1. **Secrets in Keyring** — Session and JWT signing secrets are stored in your system keyring, not source code.
2. **HttpOnly Cookies** — JWT tokens are stored in HttpOnly cookies, preventing JavaScript theft.
3. **CSRF Protection** — State parameter validated on callback to prevent CSRF attacks.
4. **Short-Lived Tokens** — JWT tokens expire in 1 hour.
5. **Email Hashing** — Email is hashed (SHA-256) for upstream bearer token, not sent in plain form.
6. **Secure Flag** — Cookies marked Secure for HTTPS (disable only for local dev with `COOKIE_SECURE=false`).
7. **SameSite** — Cookies set with `SameSite=Lax` to prevent cross-site submission.

## Production Deployment

Before deploying:

1. **Set HTTPS** — Ensure `COOKIE_SECURE=true` for production
2. **Use Strong Secrets** — Generate cryptographically strong secrets for keyring
3. **Store Tokens** — Optionally store GitHub access tokens server-side in a database (encrypted) for future API calls
4. **Remove Debug Output** — Consider removing or redirecting `print()` statements
5. **Add Logging** — Integrate structured logging (e.g., Python logging module)
6. **Rate Limiting** — Add rate limiting to `/apply` endpoint
7. **Input Validation** — Add additional email/name validation as needed

## Troubleshooting

### `keyring.get_password()` returns None
- Ensure you've run the `keyring.set_password()` commands for both secrets
- Verify the keyring service is running (e.g., `gnome-keyring-daemon` on Linux)

### Resume upload fails with "Resume must be a PDF"
- Ensure the file is actually a PDF and the `Content-Type` is set to `application/pdf` in the curl `-F` flag

### `COOKIE_SECURE=false` not working
- Restart the uvicorn server after changing the environment variable
- Verify the env var is set in the shell before running: `echo $COOKIE_SECURE`

### Upstream endpoint returns "Invalid authorization"
- Check that the upstream expects `Authorization: Bearer <sha256(email)>` format
- Verify email is being correctly extracted from GitHub
- Try base64-encoding instead by modifying the hashlib line if needed

## License

MIT
