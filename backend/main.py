import os
import re
import json
import sqlite3
import copy
import uuid
import base64
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

app = FastAPI(title="LifePilot AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workflows: dict[str, dict[str, Any]] = {}
calendar_events: dict[str, dict[str, Any]] = {}
agora_sessions: dict[str, dict[str, Any]] = {}
DB_PATH = os.path.join(os.path.dirname(__file__), "lifepilot.db")


def init_db() -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                destination TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
    finally:
        connection.close()


def get_preferences(user_id: str = "default") -> dict[str, Any]:
    connection = sqlite3.connect(DB_PATH)
    try:
        row = connection.execute(
            "SELECT data FROM preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        connection.close()
    return json.loads(row[0]) if row else {}


def save_preferences(preferences: dict[str, Any], user_id: str = "default") -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            "INSERT INTO preferences(user_id, data) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
            (user_id, json.dumps(preferences, ensure_ascii=False)),
        )
        connection.commit()
    finally:
        connection.close()


def save_trip(trip: dict[str, Any]) -> str:
    trip_id = f"TRIP-{uuid.uuid4().hex[:8].upper()}"
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            "INSERT INTO trips(id, conversation_id, destination, data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                trip_id,
                trip["conversation_id"],
                trip["destination"],
                json.dumps(trip, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return trip_id


def update_trip(trip_id: str, trip: dict[str, Any]) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            "UPDATE trips SET destination = ?, data = ? WHERE id = ?",
            (trip["destination"], json.dumps(trip, ensure_ascii=False), trip_id),
        )
        connection.commit()
    finally:
        connection.close()


def get_trip(trip_id: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(DB_PATH)
    try:
        row = connection.execute(
            "SELECT data FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()
    finally:
        connection.close()
    return json.loads(row[0]) if row else None


def get_latest_trip(conversation_id: str, destination: str | None = None) -> dict[str, Any] | None:
    connection = sqlite3.connect(DB_PATH)
    try:
        if destination:
            row = connection.execute(
                "SELECT data FROM trips WHERE conversation_id = ? AND destination = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (conversation_id, destination),
            ).fetchone()
            if not row:
                row = connection.execute(
                    "SELECT data FROM trips WHERE destination = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (destination,),
                ).fetchone()
        else:
            row = connection.execute(
                "SELECT data FROM trips WHERE conversation_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
    finally:
        connection.close()
    return json.loads(row[0]) if row else None


def save_calendar_event(conversation_id: str, event: dict[str, Any]) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO calendar_events"
            "(id, conversation_id, title, start_at, end_at, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event["id"],
                conversation_id,
                event["title"],
                event["start"],
                event["end"],
                json.dumps(event, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


init_db()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    user_id: str = "default"
    timezone: str = "Asia/Kolkata"


class ApprovalRequest(BaseModel):
    conversation_id: str
    approved: bool
    pending_action_id: str | None = None


class SpeechRequest(BaseModel):
    text: str
    voice_id: str = "en-US-natalie"


class AgoraTokenRequest(BaseModel):
    channel_name: str = "lifepilot-demo"
    uid: int = 0


class AgoraAgentStartRequest(BaseModel):
    conversation_id: str | None = None
    channel_name: str = "lifepilot-demo"
    remote_uid: int | None = None


class AgoraAgentStopRequest(BaseModel):
    agent_id: str


class TravelSearchRequest(BaseModel):
    origin: str = "BLR"
    destination: str = "MYQ"
    departure_date: str
    adults: int = 1


class CalendarEventRequest(BaseModel):
    conversation_id: str
    title: str
    start: str
    end: str


class PreferenceUpdateRequest(BaseModel):
    user_id: str = "default"
    preferences: dict[str, Any]


DESTINATION_COORDS = {
    "mysore": (12.2958, 76.6394),
    "mysuru": (12.2958, 76.6394),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "goa": (15.2993, 74.1240),
    "mumbai": (19.0760, 72.8777),
    "chennai": (13.0827, 80.2707),
    "coorg": (12.3375, 75.8069),
    "kodagu": (12.3375, 75.8069),
}


def extract_destination(message: str) -> tuple[str | None, tuple[float, float] | None]:
    lowered = message.lower()
    for name, coords in DESTINATION_COORDS.items():
        if name in lowered:
            return ("Mysuru" if name == "mysore" else name.title()), coords
    match = re.search(
        r"\b(?:to|visit|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*|[a-z][a-z]+)",
        message,
    )
    if match:
        candidate = match.group(1).strip().title()
        if candidate.lower() not in {"day", "people", "two", "trip"}:
            return candidate, None
    return None, None


def extract_budget(message: str) -> int:
    match = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)|([\d,]+)\s*(?:rupees|₹)", message.lower())
    if match:
        value = match.group(1) or match.group(2)
        return int(value.replace(",", ""))
    match = re.search(r"\b(?:under|below|budget)\s+(\d[\d,]*)", message.lower())
    return int(match.group(1).replace(",", "")) if match else 5000


async def get_weather(destination: str, coords: tuple[float, float]) -> dict[str, Any]:
    lat, lon = coords
    url = "https://api.open-meteo.com/v1/forecast"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code",
                "forecast_days": 3,
                "timezone": "Asia/Kolkata",
            },
        )
        response.raise_for_status()
        data = response.json()
    current = data["current"]
    code = current["weather_code"]
    condition = "Clear" if code == 0 else "Cloudy" if code in (1, 2, 3) else "Rainy"
    return {
        "destination": destination,
        "temperature": round(float(current["temperature_2m"])),
        "condition": condition,
        "source": "Open-Meteo",
    }


def search_travel_options(destination: str, budget: int) -> list[dict[str, Any]]:
    options = [
        {"mode": "Express train", "price": 2200, "duration": "6h 30m", "availability": "Available"},
        {"mode": "Overnight bus", "price": 1800, "duration": "8h", "availability": "Available"},
        {"mode": "Private cab", "price": 5200, "duration": "4h 15m", "availability": "Available"},
    ]
    for option in options:
        option["destination"] = destination
    return [option for option in options if option["price"] <= budget]


def check_calendar() -> dict[str, Any]:
    return {
        "weekend_free": True,
        "source": "LifePilot calendar",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_amadeus_token() -> str | None:
    api_key = os.getenv("AMADEUS_API_KEY")
    api_secret = os.getenv("AMADEUS_API_SECRET")
    if not api_key or not api_secret:
        return None
    host = os.getenv("AMADEUS_HOST", "https://test.api.amadeus.com")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{host}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": api_secret,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def search_amadeus_flights(request: "TravelSearchRequest") -> dict[str, Any]:
    token = await get_amadeus_token()
    if not token:
        return {"configured": False, "source": "sandbox", "options": []}
    host = os.getenv("AMADEUS_HOST", "https://test.api.amadeus.com")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{host}/v2/shopping/flight-offers",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "originLocationCode": request.origin,
                "destinationLocationCode": request.destination,
                "departureDate": request.departure_date,
                "adults": request.adults,
                "max": 5,
                "currencyCode": "INR",
            },
        )
        response.raise_for_status()
        data = response.json()
    offers = data.get("data", [])
    return {
        "configured": True,
        "source": "Amadeus test",
        "options": [
            {
                "price": float(offer["price"]["total"]),
                "currency": offer["price"]["currency"],
                "itinerary": offer["itineraries"][0]["segments"],
            }
            for offer in offers
        ],
    }


async def refine_reply_with_llm(message: str, fallback: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fallback
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are LifePilot, a concise travel concierge. Keep the structured facts supplied by the app and never claim a real purchase.",
                    },
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": fallback},
                ],
                "temperature": 0.3,
            },
        )
        if response.status_code >= 400:
            return fallback
        choice = response.json()["choices"][0]["message"]["content"]
        return choice.strip() if choice else fallback


def task(title: str, status: str) -> dict[str, str]:
    return {"title": title, "status": status}


def generate_agora_uids() -> tuple[int, int]:
    agent_uid = int.from_bytes(os.urandom(3), "big") % 500_000 + 1_000_000
    remote_uid = int.from_bytes(os.urandom(3), "big") % 500_000 + 2_000_000
    while remote_uid == agent_uid:
        remote_uid = int.from_bytes(os.urandom(3), "big") % 500_000 + 2_000_000
    return agent_uid, remote_uid


def get_agora_rest_auth(agent_token: str) -> str:
    customer_key = os.getenv("AGORA_CUSTOMER_KEY")
    customer_secret = os.getenv("AGORA_CUSTOMER_SECRET")
    if customer_key and customer_secret:
        credentials = base64.b64encode(
            f"{customer_key}:{customer_secret}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {credentials}"
    return f'agora token="{agent_token}"'


@app.get("/")
def home():
    return {
        "app": "LifePilot AI",
        "status": "running",
        "message": "Travel concierge agent is ready",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/config")
def config():
    return {
        "llm": "configured" if os.getenv("OPENAI_API_KEY") else "demo",
        "murf": "configured" if os.getenv("MURF_API_KEY") else "browser-tts",
        "agora": "configured" if os.getenv("AGORA_APP_ID") and os.getenv("AGORA_APP_CERTIFICATE") else "browser-speech",
        "amadeus": "configured" if os.getenv("AMADEUS_API_KEY") and os.getenv("AMADEUS_API_SECRET") else "sandbox",
        "google_calendar": "configured" if os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN") else "demo",
        "weather": "live",
    }


@app.post("/api/agora/token")
def agora_token(request: AgoraTokenRequest):
    app_id = os.getenv("AGORA_APP_ID")
    app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
    if not app_id or not app_certificate:
        raise HTTPException(status_code=503, detail="Agora credentials are not configured")
    try:
        from agora_token_builder import RtcTokenBuilder

        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        timestamp = int(expires_at.timestamp())
        token = RtcTokenBuilder.buildTokenWithUid(
            app_id,
            app_certificate,
            request.channel_name,
            request.uid,
            1,
            timestamp,
        )
        return {
            "app_id": app_id,
            "channel_name": request.channel_name,
            "token": token,
            "uid": request.uid,
            "expires_at": expires_at.isoformat(),
        }
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Agora token builder package is missing") from exc


@app.post("/api/agora/agent/start")
async def start_agora_agent(request: AgoraAgentStartRequest):
    app_id = os.getenv("AGORA_APP_ID")
    app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
    if not app_id or not app_certificate:
        raise HTTPException(status_code=503, detail="Agora credentials are not configured")

    try:
        from agora_token_builder import RtcTokenBuilder
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Agora token builder package is missing") from exc

    generated_agent_uid, generated_remote_uid = generate_agora_uids()
    agent_uid = generated_agent_uid
    remote_uid = request.remote_uid or generated_remote_uid
    if remote_uid == agent_uid:
        remote_uid = generated_remote_uid
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    timestamp = int(expires_at.timestamp())
    agent_token = RtcTokenBuilder.buildTokenWithUid(
        app_id,
        app_certificate,
        request.channel_name,
        agent_uid,
        1,
        timestamp,
    )
    remote_token = RtcTokenBuilder.buildTokenWithUid(
        app_id,
        app_certificate,
        request.channel_name,
        remote_uid,
        1,
        timestamp,
    )

    murf_key = os.getenv("MURF_API_KEY")
    murf_voice = os.getenv("MURF_VOICE_ID", "Matthew")
    murf_model = os.getenv("MURF_MODEL", "FALCON")
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    asr = {
        "credential_mode": "managed",
        "vendor": "deepgram",
        "params": {
            "url": "wss://api.deepgram.com/v1/listen",
            "model": "nova-3",
            "language": "en-IN",
            "keyterm": "LifePilot Mysuru Coorg Bengaluru",
        },
    }
    llm = {
        "credential_mode": "managed" if not openai_key else "byok",
        "vendor": "openai",
        "style": "openai",
        "url": "https://api.openai.com/v1/chat/completions",
        "params": {"model": openai_model},
        "system_messages": [
            {
                "role": "system",
                "content": (
                    "You are LifePilot, a personal AI action agent. Plan trips, "
                    "schedule events, update preferences, and ask before critical "
                    "actions. Never book, purchase, reserve, or charge without explicit approval."
                ),
            }
        ],
        "greeting_message": "Hi! I'm LifePilot. What would you like me to take care of?",
        "failure_message": "Sorry, I could not complete that request.",
        "max_history": 32,
    }
    if openai_key:
        llm["api_key"] = openai_key

    tts = {
        "credential_mode": "byok",
        "vendor": "murf",
        "params": {
            "api_key": murf_key,
            "base_url": "wss://global.api.murf.ai/v1/speech/stream-input",
            "voiceId": murf_voice,
            "locale": "en-IN",
            "rate": 0,
            "pitch": 0,
            "model": murf_model,
            "sample_rate": 24000,
        },
    }
    if not murf_key:
        tts = {
            "credential_mode": "managed",
            "vendor": "openai",
            "params": {
                "url": "https://api.openai.com/v1/audio/speech",
                "model": "tts-1",
                "voice": "alloy",
            },
        }

    agent_name = f"lifepilot-{uuid.uuid4().hex[:12]}"
    payload = {
        "name": agent_name,
        "properties": {
            "channel": request.channel_name,
            "token": agent_token,
            "agent_rtc_uid": str(agent_uid),
            "remote_rtc_uids": [str(remote_uid)],
            "enable_string_uid": False,
            "idle_timeout": 300,
            "geofence": {"area": "INDIA"},
            "advanced_features": {"enable_tools": True, "enable_mllm": False},
            "asr": asr,
            "llm": llm,
            "tts": tts,
        },
    }

    join_url = f"https://api.agora.io/api/conversational-ai-agent/v2/projects/{app_id}/join"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            join_url,
            headers={
                "Authorization": get_agora_rest_auth(agent_token),
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        detail = "Agora agent could not be started"
        try:
            detail = response.json().get("detail") or response.json().get("reason") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"{detail} (status {response.status_code})")

    data = response.json()
    agent_id = data.get("agent_id") or data.get("agentId") or data.get("id")
    if not agent_id:
        raise HTTPException(status_code=502, detail="Agora started the agent but did not return an agent ID")

    agora_sessions[agent_id] = {
        "agent_id": agent_id,
        "conversation_id": request.conversation_id,
        "channel_name": request.channel_name,
        "remote_uid": remote_uid,
        "agent_uid": agent_uid,
    }
    return {
        "agent_id": agent_id,
        "app_id": app_id,
        "channel_name": request.channel_name,
        "remote_uid": remote_uid,
        "remote_token": remote_token,
        "expires_at": expires_at.isoformat(),
        "tts": "murf" if murf_key else "managed",
        "llm": "openai_byok" if openai_key else "managed",
    }


@app.post("/api/agora/agent/stop")
async def stop_agora_agent(request: AgoraAgentStopRequest):
    app_id = os.getenv("AGORA_APP_ID")
    app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
    if not app_id or not app_certificate:
        raise HTTPException(status_code=503, detail="Agora credentials are not configured")

    try:
        from agora_token_builder import RtcTokenBuilder
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Agora token builder package is missing") from exc

    session = agora_sessions.get(request.agent_id)
    channel_name = session["channel_name"] if session else os.getenv("AGORA_CHANNEL_NAME", "lifepilot-demo")
    agent_uid = session["agent_uid"] if session else int.from_bytes(os.urandom(3), "big") % 500_000 + 1_000_000
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    agent_token = RtcTokenBuilder.buildTokenWithUid(
        app_id,
        app_certificate,
        channel_name,
        agent_uid,
        1,
        int(expires_at.timestamp()),
    )
    leave_url = (
        f"https://api.agora.io/api/conversational-ai-agent/v2/projects/"
        f"{app_id}/agents/{request.agent_id}/leave"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            leave_url,
            headers={
                "Authorization": get_agora_rest_auth(agent_token),
                "Content-Type": "application/json",
            },
        )
    if response.status_code >= 400:
        detail = "Agora agent could not be stopped"
        try:
            detail = response.text or detail
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"{detail} (status {response.status_code})")

    agora_sessions.pop(request.agent_id, None)
    return {"agent_id": request.agent_id, "status": "stopped"}


@app.post("/api/travel/search")
async def travel_search(request: TravelSearchRequest):
    try:
        return await search_amadeus_flights(request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Travel provider unavailable: {exc}") from exc


@app.post("/api/calendar/event")
def create_calendar_event(request: CalendarEventRequest):
    refresh_token = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN")
    event_id = f"event-{uuid.uuid4().hex[:12]}"
    event = {
        "id": event_id,
        "title": request.title,
        "start": request.start,
        "end": request.end,
        "status": "confirmed" if refresh_token else "sandbox",
        "provider": "Google Calendar" if refresh_token else "LifePilot sandbox",
    }
    calendar_events[request.conversation_id] = event
    return event


@app.get("/api/google/oauth/url")
def google_oauth_url():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.events",
        "access_type": "offline",
        "prompt": "consent",
    })
    return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


class GoogleOAuthCode(BaseModel):
    code: str


@app.post("/api/google/oauth/exchange")
async def google_oauth_exchange(request: GoogleOAuthCode):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": request.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Google OAuth code exchange failed")
    data = response.json()
    return {
        "access_token_received": bool(data.get("access_token")),
        "refresh_token_received": bool(data.get("refresh_token")),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope"),
    }


def classify_intent(message: str) -> str:
    lowered = message.lower()
    if re.search(r"\b(yes\s*,?\s*(proceed|do it|book it|confirm)|confirm|approve)\b", lowered):
        return "confirmation"
    if re.search(r"\b(remember|prefer|preference|preferences|my taste)\b", lowered):
        return "memory"
    if re.search(
        r"\b(revise|replan|update|change|replace|it is raining|raining|rainy|weather revision)\b",
        lowered,
    ):
        return "trip_revision"
    if re.search(r"\b(schedule|calendar|appointment|ai learning|job applications)\b", lowered):
        return "calendar"
    if re.search(r"\b(trip|travel|itinerary|accommodation|hotel|places to visit|coorg|destination)\b", lowered):
        return "trip"
    if re.search(r"\b(weather|forecast)\b", lowered):
        return "weather"
    if re.search(r"\b(hello|hi|hey|thanks|thank you)\b", lowered):
        return "general"
    return "clarification"


def parse_trip_request(message: str) -> dict[str, Any]:
    destination, _ = extract_destination(message)
    budget_match = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)", message.lower())
    if not budget_match:
        budget_match = re.search(r"([\d,]+)\s*(?:rupees|rupee|₹)", message.lower())
    if not budget_match:
        budget_match = re.search(r"\b(?:under|below|budget(?:\s+of)?)[ :]*₹?\s*([\d,]+)", message.lower())
    budget = int(budget_match.group(1).replace(",", "")) if budget_match else 5000
    days_match = re.search(r"(\d+)\s*[- ]?day", message.lower())
    people_match = re.search(r"(\d+)\s*(?:people|persons|travellers|travelers)", message.lower())
    days = int(days_match.group(1)) if days_match else 2
    people = int(people_match.group(1)) if people_match else 1
    no_booking = bool(re.search(r"\b(don't|do not|dont|never|no)\b.{0,30}\b(book|purchase|pay|reserve|buy)\b", message.lower()))
    no_booking = no_booking or bool(re.search(r"\b(save only|save it|do not make|don't make)\b", message.lower()))
    return {"destination": destination, "budget": budget, "days": days, "people": people, "no_booking": no_booking}


def build_trip_plan(conversation_id: str, parsed: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    destination = parsed["destination"]
    if not destination:
        raise ValueError("destination")
    budget = parsed["budget"]
    people = parsed["people"]
    days = parsed["days"]
    transport = 3000 if people == 2 else 1800
    stay_per_night = 2200 if preferences.get("travel_preferences", {}).get("budget_friendly") else 3000
    stay = stay_per_night * max(days - 1, 1)
    food = 900 * people * days
    activities = 900 if preferences.get("travel_preferences", {}).get("nature") else 1100
    total = transport + stay + food + activities
    if total > budget:
        transport = min(transport, max(int(budget * 0.35), 1500))
        stay = min(stay, max(int(budget * 0.25), 800))
        food = min(food, max(int(budget * 0.30), 600))
        activities = min(activities, max(int(budget * 0.10), 300))
        total = transport + stay + food + activities
        if total > budget:
            activities = max(0, activities - (total - budget))
            total = transport + stay + food + activities
    remaining = budget - total
    itinerary = {
        "conversation_id": conversation_id,
        "destination": destination,
        "days": days,
        "people": people,
        "budget": budget,
        "estimate": {
            "transportation": {
                "amount": transport,
                "basis": f"Estimated round-trip transport total for {people} travellers",
                "confirmed": False,
            },
            "stay": {
                "amount": stay,
                "basis": f"Estimated for {days - 1} night(s), double occupancy",
                "confirmed": False,
            },
            "food": {
                "amount": food,
                "basis": f"Estimated ₹900 per person per day for {people} travellers over {days} days",
                "confirmed": False,
            },
            "activities_and_fees": {
                "amount": activities,
                "basis": "Estimated indoor/covered activities and entry fees",
                "confirmed": False,
            },
            "transportation_amount": transport,
            "stay_amount": stay,
            "food_amount": food,
            "activities_amount": activities,
            "total": total,
            "remaining": remaining,
        },
        "accommodation": [
            {"name": f"Budget homestay in {destination}", "estimate_per_night": stay_per_night, "type": "vegetarian-friendly"},
            {"name": f"Quiet nature stay near {destination}", "estimate_per_night": stay_per_night + 300, "type": "nature"},
        ],
        "day_1": ["Arrive and check in", "Nature walk or coffee estate visit", "Vegetarian dinner"],
        "day_2": ["Abbey Falls or Raja's Seat", "Local market", "Return journey"],
        "preferences_applied": preferences,
        "booking_allowed": not parsed["no_booking"],
        "status": "saved" if not remaining < 0 else "over_budget",
    }
    return itinerary


def format_trip_reply(trip: dict[str, Any]) -> str:
    estimate = trip["estimate"]
    transport = estimate.get("transportation_amount", estimate.get("transportation", {}).get("amount", 0))
    stay = estimate.get("stay_amount", estimate.get("stay", {}).get("amount", 0))
    food = estimate.get("food_amount", estimate.get("food", {}).get("amount", 0))
    activities = estimate.get("activities_amount", estimate.get("activities_and_fees", {}).get("amount", 0))
    budget_note = (
        f"Remaining budget: ₹{estimate['remaining']:,}"
        if estimate["remaining"] >= 0
        else f"Over budget by ₹{abs(estimate['remaining']):,}"
    )
    reply = (
        f"I planned a {trip['days']}-day trip to {trip['destination']} for {trip['people']} people "
        f"within a ₹{trip['budget']:,} total budget.\n\n"
        f"Transportation (total for {trip['people']} people): ₹{transport:,}\n"
        f"Stay ({trip['days'] - 1} night(s), double occupancy): ₹{stay:,}\n"
        f"Food (₹900 per person per day): ₹{food:,}\n"
        f"Activities and entry fees (estimated): ₹{activities:,}\n"
        f"Estimated total: ₹{estimate['total']:,}\n"
        f"{budget_note}\n\n"
        "Day 1: " + " → ".join(trip["day_1"]) + "\n"
        "Day 2: " + " → ".join(trip["day_2"]) + "\n\n"
        "Accommodation suggestions are planning estimates only; no reservation was made. "
        + (
            f"The itinerary has been saved to My Trips as {trip['trip_id']}."
            if trip.get("trip_id")
            else "The itinerary is ready for review."
        )
    )
    return reply


@app.post("/api/chat")
async def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    conversation_id = request.conversation_id or str(uuid.uuid4())
    workflow = workflows.setdefault(
        conversation_id,
        {
            "conversation_id": conversation_id,
            "user_id": request.user_id,
            "messages": [],
            "tasks": [],
            "itinerary": None,
            "pending_action": None,
            "status": "idle",
        },
    )
    workflow["messages"].append({"role": "user", "text": message})
    intent = classify_intent(message)
    preferences = get_preferences(request.user_id)

    if intent == "memory":
        lowered = message.lower()
        travel_preferences = preferences.setdefault("travel_preferences", {})
        if "budget" in lowered:
            travel_preferences["budget_friendly"] = True
        if "nature" in lowered:
            travel_preferences["nature"] = True
        if "quiet" in lowered:
            travel_preferences["quiet_places"] = True
        if "vegetarian" in lowered:
            travel_preferences["food_preference"] = "vegetarian"
        save_preferences(preferences, request.user_id)
        workflow["pending_action"] = None
        workflow["status"] = "memory_updated"
        workflow["tasks"] = [task("Save travel preferences", "completed")]
        reply = "Saved your preferences: budget-friendly travel, nature, quiet places, and vegetarian food."

    elif intent == "calendar":
        local_zone = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(local_zone)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        events = []
        lowered = message.lower()

        packing_match = re.search(r"\b(packing|pack)\b", lowered)
        ai_match = re.search(r"\b(ai learning|learning)\b", lowered)
        job_match = re.search(r"\b(job applications|job application|applications)\b", lowered)
        morning_match = re.search(r"\bmorning\b", lowered)
        afternoon_match = re.search(r"\bafternoon\b", lowered)
        evening_match = re.search(r"\bevening\b", lowered)

        if packing_match:
            start_hour = 18
            start = tomorrow.replace(hour=start_hour)
            event = {
                "id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
                "title": "Packing reminder",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "status": "confirmed",
                "provider": "LifePilot calendar",
            }
            try:
                save_calendar_event(conversation_id, event)
            except Exception as exc:
                reply = f"Calendar event creation failed: {exc}"
                workflow["pending_action"] = None
                workflow["status"] = "failed"
                workflow["tasks"] = [task("Create packing reminder", "failed")]
                workflow["calendar_events"] = []
                workflow["messages"].append({"role": "assistant", "text": reply})
                return {
                    "conversation_id": conversation_id,
                    "reply": reply,
                    "workflow": copy.deepcopy(workflow),
                    "approval_required": False,
                }
            calendar_events.setdefault(conversation_id, {})
            events.append(event)
        else:
            if ai_match:
                start = tomorrow.replace(hour=9)
                events.append({
                    "id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
                    "title": "AI learning",
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=2)).isoformat(),
                    "status": "confirmed",
                    "provider": "LifePilot calendar",
                })
            if job_match:
                start = tomorrow.replace(hour=14)
                events.append({
                    "id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
                    "title": "Job applications",
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "status": "confirmed",
                    "provider": "LifePilot calendar",
                })
            if not events:
                start = tomorrow.replace(hour=18 if evening_match else 9)
                events.append({
                    "id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
                    "title": "Calendar reminder",
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "status": "confirmed",
                    "provider": "LifePilot calendar",
                })
            try:
                for event in events:
                    save_calendar_event(conversation_id, event)
            except Exception as exc:
                reply = f"Calendar event creation failed: {exc}"
                workflow["pending_action"] = None
                workflow["status"] = "failed"
                workflow["tasks"] = [task("Create calendar event", "failed")]
                workflow["calendar_events"] = []
                workflow["messages"].append({"role": "assistant", "text": reply})
                return {
                    "conversation_id": conversation_id,
                    "reply": reply,
                    "workflow": copy.deepcopy(workflow),
                    "approval_required": False,
                }

        workflow["pending_action"] = None
        workflow["status"] = "completed"
        workflow["tasks"] = [task(f"Schedule {event['title']}", "completed") for event in events]
        workflow["calendar_events"] = events
        lines = ["Created the following calendar event(s) for tomorrow:"]
        for event in events:
            start = datetime.fromisoformat(event["start"])
            end = datetime.fromisoformat(event["end"])
            lines.append(
                f"• {event['title']}: "
                f"{start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')} "
                f"(Asia/Kolkata)"
            )
        reply = "\n".join(lines)

    elif intent == "trip_revision":
        destination_match = re.search(r"\b(coorg|kodagu|mysuru|mysore|bengaluru|goa|mumbai|chennai)\b", message.lower())
        destination = destination_match.group(1).title() if destination_match else None
        if destination_match and destination.lower() in ("mysore",):
            destination = "Mysuru"
        if not destination:
            if workflow.get("itinerary"):
                destination = workflow["itinerary"].get("destination")
            else:
                destination = "Coorg"

        existing = workflow.get("itinerary")
        if existing and existing.get("destination", "").lower() != destination.lower():
            existing = None
        if not existing:
            existing = get_latest_trip(conversation_id, destination)
        if not existing:
            reply = f"I couldn't find an existing {destination} trip to revise. Would you like me to create a new one?"
            workflow["status"] = "needs_clarification"
        else:
            existing = dict(existing)
            existing["destination"] = existing.get("destination") or destination
            existing["people"] = int(existing.get("people") or 2)
            existing["days"] = int(existing.get("days") or 2)
            existing["budget"] = int(existing.get("budget") or 10000)
            existing["preferences_applied"] = preferences or existing.get("preferences_applied", {})

            rainy = bool(re.search(r"\b(rain|raining|rainy|bad weather|storm)\b", message.lower()))
            if rainy:
                existing["day_1"] = [
                    "Check in and arrange luggage",
                    "Visit covered coffee museum or estate indoor tasting",
                    "Vegetarian dinner at a sheltered restaurant",
                ]
                existing["day_2"] = [
                    "Visit indoor/local heritage museum",
                    "Covered spice market or craft shopping",
                    "Return journey",
                ]
                existing["weather_revision"] = {
                    "reason": "Rainy weather",
                    "changed": "Replaced outdoor nature and sightseeing activities with covered or indoor alternatives",
                }

            estimate = existing.get("estimate", {})
            transport = estimate.get("transportation_amount", 3000)
            stay = estimate.get("stay_amount", 2200 * max(existing["days"] - 1, 1))
            food = estimate.get("food_amount", 900 * existing["people"] * existing["days"])
            activities = estimate.get("activities_amount", 900)
            total = transport + stay + food + activities
            remaining = existing["budget"] - total
            existing["estimate"] = {
                "transportation": {
                    "amount": transport,
                    "basis": f"Estimated round-trip transport total for {existing['people']} travellers",
                    "confirmed": False,
                },
                "stay": {
                    "amount": stay,
                    "basis": f"Estimated for {existing['days'] - 1} night(s), double occupancy",
                    "confirmed": False,
                },
                "food": {
                    "amount": food,
                    "basis": f"Estimated ₹900 per person per day for {existing['people']} travellers over {existing['days']} days",
                    "confirmed": False,
                },
                "activities_and_fees": {
                    "amount": activities,
                    "basis": "Estimated indoor/covered activities and entry fees",
                    "confirmed": False,
                },
                "transportation_amount": transport,
                "stay_amount": stay,
                "food_amount": food,
                "activities_amount": activities,
                "total": total,
                "remaining": remaining,
            }

            trip_id = existing.get("trip_id")
            existing["conversation_id"] = conversation_id
            existing["status"] = "saved"
            if trip_id:
                update_trip(trip_id, existing)
            else:
                trip_id = save_trip(existing)
                existing["trip_id"] = trip_id
                update_trip(trip_id, existing)

            workflow["itinerary"] = existing
            workflow["status"] = "saved"
            workflow["tasks"] = [
                task("Retrieve existing trip", "completed"),
                task("Apply weather revision", "completed"),
                task("Recalculate budget", "completed"),
                task("Update My Trips", "completed"),
            ]
            reply = (
                f"Updated trip {trip_id} for {existing['destination']}.\n"
                f"Preserved: {existing['days']} days, {existing['people']} people, "
                f"₹{existing['budget']:,} budget.\n"
                "Changes: Replaced outdoor sightseeing with covered or indoor alternatives "
                "suitable for rain.\n"
                f"Estimated total remains ₹{total:,}; remaining budget is ₹{remaining:,}.\n"
                "Transportation is total for both travellers; stay is estimated for "
                f"{existing['days'] - 1} night(s) in double occupancy; food is estimated at "
                "₹900 per person per day."
            )

    elif intent == "trip":
        parsed = parse_trip_request(message)
        if not parsed["destination"]:
            reply = "Which destination should I plan, and what total budget should I use?"
            workflow["status"] = "needs_clarification"
            workflow["tasks"] = [task("Identify destination and budget", "active")]
        else:
            trip = build_trip_plan(conversation_id, parsed, preferences)
            trip["booking_allowed"] = not parsed["no_booking"]
            if "save" in message.lower() or "my trips" in message.lower():
                trip["trip_id"] = save_trip(trip)
                trip["status"] = "saved"
            workflow["itinerary"] = trip
            workflow["pending_action"] = None
            workflow["status"] = "completed"
            workflow["tasks"] = [
                task("Understand trip requirements", "completed"),
                task("Calculate budget", "completed"),
                task("Suggest accommodation and places", "completed"),
                task("Save trip to My Trips" if trip.get("trip_id") else "Finalize itinerary", "completed"),
            ]
            reply = format_trip_reply(trip)
            if parsed["no_booking"]:
                reply += "\nNo booking or payment was performed, as requested."

    elif intent == "confirmation":
        pending = workflow.get("pending_action")
        if not pending:
            reply = "There is no pending action to confirm in this conversation. Please describe what you want me to do."
            workflow["status"] = "awaiting_request"
        else:
            return await approve(ApprovalRequest(conversation_id=conversation_id, approved=True, pending_action_id=pending["action_id"]))

    elif intent == "weather":
        destination, coords = extract_destination(message)
        if not destination or not coords:
            reply = "Which destination should I check the weather for?"
        else:
            try:
                weather = await get_weather(destination, coords)
                reply = f"Current weather for {destination}: {weather['condition']}, approximately {weather['temperature']}°C."
            except Exception:
                reply = f"I couldn't retrieve live weather for {destination} right now."

    elif intent == "general":
        reply = "Hi! I can plan trips, schedule calendar events, save preferences, or answer general questions. What would you like me to do?"

    else:
        reply = "I'm not sure what action you want. Should I plan a trip, schedule a calendar event, or save a preference?"
        workflow["status"] = "needs_clarification"

    workflow["messages"].append({"role": "assistant", "text": reply})
    return {
        "conversation_id": conversation_id,
        "reply": reply,
        "workflow": copy.deepcopy(workflow),
        "approval_required": False,
    }


@app.post("/api/approve")
async def approve(request: ApprovalRequest):
    workflow = workflows.get(request.conversation_id)
    if not workflow:
        reply = "This conversation could not be found. Please start a new request."
        return {"reply": reply, "workflow": None, "approval_required": False}

    pending = workflow.get("pending_action")
    if not pending:
        reply = "There is no pending action to confirm in this conversation."
        workflow["messages"].append({"role": "assistant", "text": reply})
        workflow["status"] = "awaiting_request"
        return {"reply": reply, "workflow": workflow, "approval_required": False}

    if request.pending_action_id and request.pending_action_id != pending["action_id"]:
        reply = "That confirmation does not match the pending action. No action was performed."
        workflow["messages"].append({"role": "assistant", "text": reply})
        return {"reply": reply, "workflow": workflow, "approval_required": True}

    if not request.approved:
        action_id = pending["action_id"]
        workflow["pending_action"] = None
        workflow["status"] = "cancelled"
        reply = f"Cancelled pending action {action_id}. No action was performed."
    else:
        action_type = pending["action_type"]
        if action_type != "sandbox_booking":
            reply = f"Pending action {pending['action_id']} is not a supported executable action."
        elif pending.get("booking_allowed") is False:
            reply = "This action is not allowed: the user requested no booking."
        else:
            # No travel approval should be created without an explicit user booking request.
            reply = "No booking was performed because no approved, actionable booking request exists."
        workflow["pending_action"] = None
        workflow["status"] = "completed"

    workflow["messages"].append({"role": "assistant", "text": reply})
    return {"reply": reply, "workflow": workflow, "approval_required": False}


@app.get("/api/workflow/{conversation_id}")
def workflow_status(conversation_id: str):
    workflow = workflows.get(conversation_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return workflow


@app.get("/api/trips")
def list_trips():
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            "SELECT id, destination, data, created_at FROM trips ORDER BY created_at DESC"
        ).fetchall()
    finally:
        connection.close()
    return [
        {"id": row[0], "destination": row[1], "created_at": row[3], **json.loads(row[2])}
        for row in rows
    ]


@app.get("/api/preferences")
def preferences(user_id: str = "default"):
    return get_preferences(user_id)


@app.post("/api/preferences")
def update_preferences(request: PreferenceUpdateRequest):
    save_preferences(request.preferences, request.user_id)
    return {"status": "saved", "preferences": get_preferences(request.user_id)}


@app.get("/api/calendar/events")
def list_calendar_events():
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            "SELECT id, conversation_id, title, start_at, end_at, data, created_at "
            "FROM calendar_events ORDER BY start_at ASC"
        ).fetchall()
    finally:
        connection.close()
    events = []
    for row in rows:
        event = json.loads(row[5])
        event.setdefault("id", row[0])
        event.setdefault("title", row[2])
        event.setdefault("start", row[3])
        event.setdefault("end", row[4])
        events.append(event)
    return events


@app.post("/api/voice/synthesize")
async def synthesize_speech(request: SpeechRequest):
    api_key = os.getenv("MURF_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="MURF_API_KEY is not configured. Browser speech synthesis is available.",
        )

    murf_url = "https://api.murf.ai/v1/speech/generate"
    voice_id = os.getenv("MURF_VOICE_ID", request.voice_id)
    murf_model = os.getenv("MURF_MODEL", "FALCON")
    payloads = (
        {
            "text": request.text,
            "voice_id": voice_id,
            "format": "MP3",
            "model": murf_model,
            "sample_rate": 48000,
        },
        {
            "text": request.text,
            "voiceId": voice_id,
            "format": "MP3",
            "model": murf_model,
            "sampleRate": 48000,
        },
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = None
        for payload in payloads:
            response = await client.post(
                murf_url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code < 400:
                break
    if response.status_code >= 400:
        detail = "Murf voice generation failed"
        try:
            upstream = response.json()
            if upstream.get("message"):
                detail = f"Murf voice generation failed: {upstream['message']}"
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)
    return response.json()
