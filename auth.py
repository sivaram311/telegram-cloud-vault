import httpx
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

CSS_JWKS_URL = "http://127.0.0.1:5900/.well-known/jwks.json"
security_bearer = HTTPBearer(auto_error=False)
jwks_client = PyJWKClient(CSS_JWKS_URL)

def verify_token(request: Request, creds: HTTPAuthorizationCredentials = Security(security_bearer)):
    # 1. Allow internal localhost requests or check query param ?token= (for video streaming tags)
    token = None
    if creds:
        token = creds.credentials
    elif "token" in request.query_params:
        token = request.query_params["token"]
    elif "auth_token" in request.cookies:
        token = request.cookies["auth_token"]

    if not token:
        # Check if local internal request from 127.0.0.1
        client_host = request.client.host if request.client else ""
        if client_host in ["127.0.0.1", "localhost", "::1"]:
            return {"sub": "internal", "roles": ["ROLE_ADMIN"]}
        raise HTTPException(status_code=401, detail="Authentication required (CSS JWT token)")

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired CSS security token: {str(e)}")
