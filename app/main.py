import os
import secrets
import datetime
import json
import hashlib
import keyring
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware


session_secret = keyring.get_password("clipp_com_job_app_secret", ""username"")
if not session_secret:
    raise RuntimeError(""username" not found in keyring")


jwt_signing_secret = keyring.get_password("clipp_com_job_app_jwt_secret", "JWT_SIGNING_SECRET")
if not jwt_signing_secret:
	raise RuntimeError("JWT_SIGNING_SECRET not found in keyring")


app = FastAPI(title="Diandra's OAuth2 Callback Demo")
app.add_middleware(
	SessionMiddleware,
	secret_key=session_secret,
)
    

# Configure these with your OAuth provider values.
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "Ov23li6MrOJeoBMQLAGu")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", session_secret)
AUTHORIZATION_URL = os.getenv("OAUTH_AUTHORIZATION_URL", "https://github.com/login/oauth/authorize")
TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "https://github.com/login/oauth/access_token")
SCOPE = os.getenv("OAUTH_SCOPE", "read:user,user:email")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"}
JOB_APPLICATION_URL = os.getenv("JOB_APPLICATION_URL", "https://kibjbsigxbqpfhqqarbo.supabase.co/functions/v1/apply")
JOB_APPLICATION_COMMENT = os.getenv("JOB_APPLICATION_COMMENT", "Job application submitted via OAuth flow")
MAX_RESUME_BYTES = 5 * 1024 * 1024

# Must exactly match what you registered at your OAuth provider.
REDIRECT_PATH = "/auth/callback"


@app.get("/")
def home() -> dict[str, str]:
	return {
		"message": "Visit /login to begin OAuth2 flow.",
	}


@app.post("/apply")
async def submit_job_application(
	request: Request,
	name: str | None = Form(None, description="your full name"),
	email: str | None = Form(None, description="your email address"),
	github_username: str | None = Form(None, description="your github username"),
	resume: UploadFile = File(..., description="PDF, max 5mb"),
):
	if not JOB_APPLICATION_URL:
		raise HTTPException(status_code=500, detail="JOB_APPLICATION_URL is not configured")

	resolved_name = (name or "").strip()
	resolved_email = (email or "").strip()
	resolved_github_username = (github_username or "").strip()

	if not (resolved_name and resolved_email and resolved_github_username):
		app_token = request.cookies.get("app_token")
		if app_token:
			try:
				claims = jwt.decode(app_token, jwt_signing_secret, algorithms=["HS256"])
			except jwt.PyJWTError as exc:
				raise HTTPException(status_code=401, detail=f"Invalid app_token cookie: {exc}") from exc

			if not resolved_name:
				resolved_name = (claims.get("name") or "").strip()
			if not resolved_email:
				resolved_email = (claims.get("email") or "").strip()
			if not resolved_github_username:
				resolved_github_username = (claims.get("sub") or "").strip()

	if not (resolved_name and resolved_email and resolved_github_username):
		raise HTTPException(
			status_code=400,
			detail="Missing required applicant fields. Provide form fields or a valid app_token cookie.",
		)

	resume_content = await resume.read()
	if len(resume_content) > MAX_RESUME_BYTES:
		raise HTTPException(status_code=400, detail="Resume exceeds 5 MB limit")

	if resume.content_type != "application/pdf":
		raise HTTPException(status_code=400, detail="Resume must be a PDF")

	data = {
		"name": resolved_name,
		"email": resolved_email,
		"github_username": resolved_github_username,
	}
    
	files = {
		"resume": (
			resume.filename or "resume.pdf",
			resume_content,
			"application/pdf",
		),
	}

	headers = {
        "x-applicant-name": resolved_name,
        "x-applicant-email": resolved_email,
        "x-applicant-github": resolved_github_username,
        "x-application-comment": "Add custom comment here, e.g. source of applicant referral",
        "x-application-source": "Diandra's OAuth2 Demo App",
        "x-application-timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "x-application-id": secrets.token_hex(8)
	}
	email_sha256 = hashlib.sha256(resolved_email.encode("utf-8")).hexdigest()
	headers["authorization"] = f"Bearer {email_sha256}"

	async with httpx.AsyncClient(timeout=20) as client:
		upstream_response = await client.post(
			JOB_APPLICATION_URL,
			data=data,
			files=files,
			headers=headers,
		)

	if upstream_response.status_code >= 400:
		raise HTTPException(
			status_code=upstream_response.status_code,
			detail=f"Job application submit failed: {upstream_response.text}",
		)

	resume_metadata = {
		"filename": resume.filename or "resume.pdf",
		"content_type": resume.content_type,
		"size_bytes": len(resume_content),
	}
	confirmation_payload = {
		"method": request.method,
		"path": request.url.path,
		"headers_sent": headers,
		"upstream_request_body": {
			"size_bytes": len(resume_content) + sum(len(v.encode("utf-8")) for v in data.values()),
			"form_fields": data,
			"files": {"resume": resume_metadata},
			"http_method": "POST",
			"http_url": JOB_APPLICATION_URL,
			"http_response_status": upstream_response.status_code,
			"http_response_body": upstream_response.text
		},
	}
	pretty = json.dumps(confirmation_payload, indent=2, sort_keys=True)
	print(pretty, flush=True)

	return PlainTextResponse(pretty, media_type="application/json")
    

@app.get("/login")
def login(request: Request):
	# Build absolute callback URL, e.g. http://localhost:8000/auth/callback
	redirect_uri = str(request.url_for("oauth_callback"))

	state = secrets.token_urlsafe(32)
	request.session["oauth_state"] = state

	params = {
		"client_id": CLIENT_ID,
		"redirect_uri": redirect_uri,
		"scope": SCOPE,
		"state": state,
	}
	auth_url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
	return RedirectResponse(url=auth_url)


@app.get(REDIRECT_PATH, name="oauth_callback")
async def oauth_callback(
	request: Request,
	code: str = Query(..., description="Authorization code returned by provider"),
	state: str | None = Query(None),
):
	expected_state = request.session.get("oauth_state")
	if expected_state and state != expected_state:
		raise HTTPException(status_code=400, detail="Invalid state parameter")

	redirect_uri = str(request.url_for("oauth_callback"))

	token_payload = {
		"code": code,
		"redirect_uri": redirect_uri,
		"client_id": CLIENT_ID,
		"client_secret": CLIENT_SECRET,
		"state": state,
	}

	async with httpx.AsyncClient(timeout=10) as client:
		token_response = await client.post(
			TOKEN_URL,
			data=token_payload,
			headers={"Accept": "application/json"},
		)

	if token_response.status_code >= 400:
		raise HTTPException(
			status_code=token_response.status_code,
			detail=f"Token exchange failed: {token_response.text}",
		)

	tokens = token_response.json()
	access_token = tokens.get("access_token")
	if not access_token:
		raise HTTPException(status_code=400, detail="GitHub token response missing access_token")

	headers = {
		"Authorization": f"Bearer {access_token}",
		"Accept": "application/vnd.github+json",
	}

	async with httpx.AsyncClient(timeout=10) as client:
		user_response = await client.get("https://api.github.com/user", headers=headers)
		emails_response = await client.get("https://api.github.com/user/emails", headers=headers)

	if user_response.status_code >= 400:
		raise HTTPException(
			status_code=user_response.status_code,
			detail=f"Failed to fetch GitHub profile: {user_response.text}",
		)

	if emails_response.status_code >= 400:
		raise HTTPException(
			status_code=emails_response.status_code,
			detail=f"Failed to fetch GitHub emails: {emails_response.text}",
		)

	user_data = user_response.json()
	emails_data = emails_response.json()

	primary_email = None
	for entry in emails_data:
		if entry.get("primary"):
			primary_email = entry.get("email")
			break
	if not primary_email and emails_data:
		primary_email = emails_data[0].get("email")

	full_name = user_data.get("name") or ""
	github_username = user_data.get("login") or ""
	email = primary_email or ""

	now = datetime.datetime.utcnow()
	jwt_payload = {
		"sub": github_username,
		"name": full_name,
		"email": email,
		"iat": now,
		"exp": now + datetime.timedelta(hours=1),
	}
	app_token = jwt.encode(jwt_payload, jwt_signing_secret, algorithm="HS256")

	response = JSONResponse(
		{
			"message": "OAuth callback succeeded",
			"full_name": full_name,
			"email": email,
			"github_username": github_username,
			"token": app_token,
		}
	)
	response.headers["x-full-name"] = full_name
	response.headers["x-email"] = email
	response.headers["x-github-username"] = github_username
	response.headers["x-app-token"] = app_token
	response.set_cookie(
		key="app_token",
		value=app_token,
		httponly=True,
		secure=COOKIE_SECURE,
		samesite="lax",
		max_age=3600,
		path="/",
	)
	return response


@app.post("/test_submit_application")
async def echo_application(
	request: Request,
	name: str | None = Form(None),
	email: str | None = Form(None),
	github_username: str | None = Form(None),
	resume: UploadFile = File(...),
):
	"""Demo echo endpoint for testing multipart form submission."""
	resume_content = await resume.read()
	
	headers_dict = {key: value for key, value in request.headers.items()}
	
	resume_metadata = {
		"filename": resume.filename or "resume.pdf",
		"content_type": resume.content_type,
		"size_bytes": len(resume_content),
	}
	
	form_fields = {
		"name": name,
		"email": email,
		"github_username": github_username,
	}
	
	response_payload = {
		"method": request.method,
		"path": request.url.path,
		"headers": headers_dict,
		"body": {
			"content_type": request.headers.get("content-type", "unknown"),
			"size_bytes": len(resume_content) + sum(len(str(v or "").encode("utf-8")) for v in form_fields.values()),
			"preview": "omitted (resume file preview disabled)",
			"form_fields": form_fields,
			"files": {"resume": resume_metadata},
		},
	}
	
	pretty = json.dumps(response_payload, indent=2, sort_keys=True)
	print(pretty, flush=True)
	
	return PlainTextResponse(pretty, media_type="application/json")
