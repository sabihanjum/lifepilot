# LifePilot

LifePilot is a voice-first travel concierge built for the Build with Agora hackathon.

## Local development

Start the FastAPI agent:

```powershell
cd backend
py -m pip install -r requirements.txt
py -m uvicorn main:app --reload --port 8000
```

Start the React application in another terminal:

```powershell
cd frontend
npm install
$env:VITE_API_URL="http://localhost:8000"
npm run dev
```

The chat workflow uses live Open-Meteo weather data and deterministic demo travel options.
Browser speech recognition and synthesis provide a zero-credential voice demo.

Production integrations are enabled through environment variables:

- **Agora:** `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`
- **Murf Falcon:** `MURF_API_KEY`, `MURF_VOICE_ID`, `MURF_MODEL`
- **LLM:** `OPENAI_API_KEY`, `OPENAI_MODEL`, optional `LLM_BASE_URL`
- **Amadeus:** `AMADEUS_API_KEY`, `AMADEUS_API_SECRET`, optional `AMADEUS_HOST`
- **Google Calendar:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI`, `GOOGLE_CALENDAR_REFRESH_TOKEN`

## Render deployment

1. Push the project to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Approve the `lifepilot-api` Python web service and `lifepilot` static site.
4. Set `VITE_API_URL` on the static site to the public URL of `lifepilot-api`.
5. Optionally set `MURF_API_KEY`, `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`, and `OPENAI_API_KEY`.

The included `render.yaml` configures both services.
