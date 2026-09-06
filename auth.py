import httpx
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request

CSS_JWKS_URL = "http://127.0.0.1:5900/.well-known/jwks.json"
jwks_client = PyJWKClient(CSS_JWKS_URL)

def verify_token(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    elif "token" in request.query_params:
        token = request.query_params["token"]
    elif "auth_token" in request.cookies:
        token = request.cookies["auth_token"]

    if not token:
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
