# Render deployment

Create a Python web service from this repository. Build command: `pip install -r requirements.txt`. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set secrets in Render Environment Variables, including Supabase and provider keys. Do not rely on the local filesystem for production data; the local adapter is for development/tests while production persistence should use Supabase.

`/health` is liveness. `/ready` reports configuration readiness and returns 503 when required settings are missing. `/metrics` requires admin authentication. Render's injected `PORT` takes precedence over the local example value.
