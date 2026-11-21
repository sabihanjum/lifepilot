import { useCallback, useEffect, useRef, useState } from "react";
import AgoraRTC from "agora-rtc-sdk-ng";
import {
  Plane,
  LayoutDashboard,
  Compass,
  CalendarDays,
  Settings,
  Bell,
  Mic,
  MicOff,
  Sparkles,
  MapPin,
  CloudSun,
  Wallet,
  Clock3,
  ArrowUpRight,
  CheckCircle2,
  Circle,
  Send,
  Menu,
  Bot,
  Activity,
  ShieldCheck,
} from "lucide-react";

const initialTasks = [
  { title: "Understand trip requirements", status: "completed" },
  { title: "Search travel options", status: "completed" },
  { title: "Check destination weather", status: "completed" },
  { title: "Optimize itinerary & budget", status: "active" },
  { title: "Await user approval", status: "pending" },
];

const suggestions = [
  "Plan a weekend trip to Mysore",
  "Find a trip under ₹5,000",
  "Check weather before planning",
];

export default function App() {
  const [activeTab, setActiveTab] = useState("Overview");
  const [message, setMessage] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [providerConfig, setProviderConfig] = useState(null);
  const [voiceStatus, setVoiceStatus] = useState("Tap to start a voice conversation");
  const [savedTrips, setSavedTrips] = useState([]);
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [preferences, setPreferences] = useState({
    travel_preferences: {
      budget_friendly: false,
      nature: false,
      quiet_places: false,
      food_preference: "vegetarian",
    },
  });
  const [preferenceSaved, setPreferenceSaved] = useState(false);
  const [tripOverview, setTripOverview] = useState({
    destination: "No trip planned",
    budget: null,
    duration: null,
    status: "Ready",
  });
  const [tasks, setTasks] = useState(initialTasks);
  const [conversation, setConversation] = useState([
    {
      role: "assistant",
      text: "Hi! I'm LifePilot, your personal AI action agent. Tell me what you want to accomplish, and I'll plan it, research options, and take action with your approval.",
    },
  ]);

  const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
  const recognitionRef = useRef(null);
  const agoraClientRef = useRef(null);
  const microphoneTrackRef = useRef(null);
  const agoraAgentIdRef = useRef(null);

  useEffect(() => {
    fetch(`${import.meta.env.VITE_API_URL || "http://localhost:8000"}/api/config`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => data && setProviderConfig(data))
      .catch(() => setProviderConfig(null));
  }, []);

  useEffect(() => {
    const baseUrl = apiUrl;
    Promise.all([
      fetch(`${baseUrl}/api/trips`).then((response) =>
        response.ok ? response.json() : [],
      ),
      fetch(`${baseUrl}/api/calendar/events`).then((response) =>
        response.ok ? response.json() : [],
      ),
      fetch(`${baseUrl}/api/preferences?user_id=default`).then((response) =>
        response.ok ? response.json() : {},
      ),
    ])
      .then(([trips, events, savedPreferences]) => {
        setSavedTrips(trips);
        setCalendarEvents(events);
        if (savedPreferences?.travel_preferences) {
          setPreferences(savedPreferences);
        }
      })
      .catch(() => {});
  }, [apiUrl, conversationId, activeTab]);

  const speak = useCallback(async (text) => {
    if (providerConfig?.murf === "configured") {
      try {
        const response = await fetch(`${apiUrl}/api/voice/synthesize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            voice_id: import.meta.env.VITE_MURF_VOICE_ID || "en-US-natalie",
          }),
        });
        if (response.ok) {
          const data = await response.json();
          const audioUrl =
            data.audioFile ||
            data.audioUrl ||
            data.url ||
            data.audio_url ||
            data.output?.url;
          if (audioUrl) {
            const audio = new Audio(audioUrl);
            await audio.play();
            return;
          }
        }
      } catch {
        // Fall back to browser speech if the Murf service is unavailable.
      }
    }

    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.95;
    utterance.lang = "en-IN";
    window.speechSynthesis.speak(utterance);
  }, [apiUrl, providerConfig?.murf]);

  const sendMessage = useCallback(async (text = message) => {
    const value = text.trim();
    if (!value || isSending) return;

    setConversation((prev) => [...prev, { role: "user", text: value }]);
    setMessage("");
    setIsSending(true);
    setTasks([
      { title: "Understand user request", status: "completed" },
      { title: "Create execution plan", status: "active" },
      { title: "Gather information using tools", status: "pending" },
      { title: "Evaluate available options", status: "pending" },
      { title: "Request approval & execute", status: "pending" },
    ]);

    try {
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: value, conversation_id: conversationId }),
      });
      if (!response.ok) throw new Error(`Agent request failed (${response.status})`);
      const data = await response.json();
      setConversationId(data.conversation_id);
      setApprovalRequired(data.approval_required);
      setTasks(data.workflow.tasks);
      if (data.workflow.itinerary) {
        setTripOverview({
          destination: data.workflow.itinerary.destination,
          budget: data.workflow.itinerary.budget,
          duration: `${data.workflow.itinerary.days} day${data.workflow.itinerary.days === 1 ? "" : "s"}`,
          status: data.workflow.itinerary.status === "saved" ? "Saved" : "Draft",
        });
      }
      setConversation((prev) => [
        ...prev,
        { role: "assistant", text: data.reply },
      ]);
      speak(data.reply);
    } catch {
      const reply =
        "I couldn't reach the agent service. Please verify the API is running and try again.";
      setConversation((prev) => [...prev, { role: "assistant", text: reply }]);
      setTasks((current) =>
        current.map((item, index) => ({
          ...item,
          status: index === 2 ? "pending" : item.status,
        })),
      );
    } finally {
      setIsSending(false);
    }
  }, [apiUrl, conversationId, isSending, message, speak]);

  useEffect(() => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-IN";
    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setMessage(transcript);
      sendMessage(transcript);
    };
    recognitionRef.current = recognition;
  }, [sendMessage]);

  const handleApproval = async (approved) => {
    if (!conversationId) return;
    setIsSending(true);
    try {
      const response = await fetch(`${apiUrl}/api/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, approved }),
      });
      if (!response.ok) throw new Error("Approval request failed");
      const data = await response.json();
      setApprovalRequired(false);
      setTasks(data.workflow.tasks);
      setConversation((prev) => [
        ...prev,
        { role: "user", text: approved ? "Yes, proceed." : "No, don't book it." },
        { role: "assistant", text: data.reply },
      ]);
      speak(data.reply);
    } finally {
      setIsSending(false);
    }
  };

  const startAgoraVoice = async () => {
    try {
      if (agoraClientRef.current) {
        await stopAgoraVoice();
      }
      if (!window.isSecureContext) {
        throw new Error("Microphone access requires HTTPS or localhost.");
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("This browser does not support microphone capture.");
      }
      setVoiceStatus("Requesting microphone permission...");
      const permissionStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      permissionStream.getTracks().forEach((track) => track.stop());

      setVoiceStatus("Joining the LifePilot voice channel...");
      const remoteUid = 2_000_000 + crypto.getRandomValues(new Uint32Array(1))[0] % 500_000;
      const randomSuffix = Array.from(crypto.getRandomValues(new Uint32Array(4)))
        .map((value) => value.toString(16))
        .join("");
      const channelName = `lifepilot-${conversationId || randomSuffix}`
        .replace(/[^a-zA-Z0-9_-]/g, "")
        .slice(0, 64);
      const response = await fetch(`${apiUrl}/api/agora/agent/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          channel_name: channelName,
          remote_uid: remoteUid,
        }),
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Could not start Agora voice agent");
      }

      const session = await response.json();
      agoraAgentIdRef.current = session.agent_id;
      const client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
      agoraClientRef.current = client;
      client.on("user-published", async (user, mediaType) => {
        await client.subscribe(user, mediaType);
        if (mediaType === "audio") {
          user.audioTrack?.play();
        }
      });

      await client.join(
        session.app_id,
        session.channel_name,
        session.remote_token,
        session.remote_uid,
      );
      setVoiceStatus("Publishing microphone audio...");
      const microphoneTrack = await AgoraRTC.createMicrophoneAudioTrack({
        encoderConfig: "music_standard",
      });
      microphoneTrackRef.current = microphoneTrack;
      await client.publish([microphoneTrack]);
      setVoiceStatus("Voice connected — speak now");
      agoraAgentIdRef.current = session.agent_id;
      setIsListening(true);
    } catch (error) {
      await stopAgoraVoice();
      setConversation((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `Agora voice could not start: ${error.message}`,
        },
      ]);
    }
  };

  const stopAgoraVoice = async () => {
    const agentId = agoraAgentIdRef.current;
    const client = agoraClientRef.current;
    const microphoneTrack = microphoneTrackRef.current;

    microphoneTrack?.stop();
    microphoneTrack?.close();
    microphoneTrackRef.current = null;

    if (client) {
      await client.leave().catch(() => {});
      agoraClientRef.current = null;
    }

    if (agentId) {
      await fetch(`${apiUrl}/api/agora/agent/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId }),
      }).catch(() => {});
      agoraAgentIdRef.current = null;
    }
    setVoiceStatus("Tap to start a voice conversation");
    setIsListening(false);
  };

  useEffect(() => {
    return () => {
      const microphoneTrack = microphoneTrackRef.current;
      microphoneTrack?.stop();
      microphoneTrack?.close();
      agoraClientRef.current?.leave().catch(() => {});
    };
  }, []);

  const toggleMic = () => {
    if (providerConfig?.agora === "configured") {
      if (isListening) {
        stopAgoraVoice();
      } else {
        startAgoraVoice();
      }
      return;
    }

    if (!recognitionRef.current) {
      setConversation((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Browser voice recognition is not supported here. You can continue by typing.",
        },
      ]);
      return;
    }
    if (isListening) {
      recognitionRef.current.stop();
    } else {
      recognitionRef.current.start();
    }
  };

  const navItems = [
    { name: "Overview", icon: LayoutDashboard },
    { name: "My Trips", icon: Plane },
    { name: "Explore", icon: Compass },
    { name: "Calendar", icon: CalendarDays },
  ];

  return (
    <div className="min-h-screen bg-[#080b11] text-[#e7eaf2]">
      {/* SIDEBAR */}
      <aside className="fixed left-0 top-0 z-20 hidden h-screen w-[245px] border-r border-white/[0.07] bg-[#0b0e15] p-6 lg:flex lg:flex-col">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/20">
            <Sparkles size={21} />
          </div>
          <div>
            <h1 className="text-[17px] font-bold tracking-tight">LifePilot</h1>
            <p className="text-[10px] tracking-[2px] text-slate-500">AI ACTION AGENT</p>
          </div>
        </div>

        <div className="mt-10">
          <p className="mb-3 text-[10px] font-semibold tracking-[1.8px] text-slate-500">
            WORKSPACE
          </p>

          <div className="space-y-1">
            {navItems.map(({ name, icon: Icon }) => (
              <button
                key={name}
                onClick={() => setActiveTab(name)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm transition ${
                  activeTab === name
                    ? "bg-indigo-500/10 text-indigo-300 ring-1 ring-indigo-500/20"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-white"
                }`}
              >
                <Icon size={18} />
                {name}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-9">
          <p className="mb-3 text-[10px] font-semibold tracking-[1.8px] text-slate-500">
            PREFERENCES
          </p>
          <button
            onClick={() => setActiveTab("Settings")}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm transition ${
              activeTab === "Settings"
                ? "bg-indigo-500/10 text-indigo-300 ring-1 ring-indigo-500/20"
                : "text-slate-400 hover:bg-white/[0.04]"
            }`}
          >
            <Settings size={18} />
            Settings
          </button>
        </div>

        <div className="mt-auto rounded-2xl border border-indigo-500/15 bg-gradient-to-br from-indigo-500/10 to-violet-500/5 p-4">
          <div className="flex items-center gap-2 text-indigo-300">
            <Sparkles size={16} />
            <span className="text-xs font-semibold">Your AI companion</span>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            From conversations to real-world actions. Your day, simplified.
          </p>
        </div>

        <div className="mt-5 flex items-center gap-3 border-t border-white/[0.07] pt-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-800 text-xs font-bold text-indigo-300">
            S
          </div>
          <div>
            <p className="text-sm font-medium">Sabiha</p>
            <p className="text-xs text-slate-500">Personal workspace</p>
          </div>
        </div>
      </aside>

      <nav className="fixed bottom-3 left-3 right-3 z-30 grid grid-cols-5 rounded-2xl border border-white/[0.08] bg-[#0b0e15]/95 p-1.5 backdrop-blur-xl lg:hidden">
        {[...navItems, { name: "Settings", icon: Settings }].map(({ name, icon: Icon }) => (
          <button
            key={name}
            onClick={() => setActiveTab(name)}
            className={`flex min-w-0 flex-col items-center gap-1 rounded-xl py-2 text-[9px] transition ${
              activeTab === name
                ? "bg-indigo-500/15 text-indigo-300"
                : "text-slate-500"
            }`}
          >
            <Icon size={16} />
            <span className="truncate">{name === "My Trips" ? "Trips" : name}</span>
          </button>
        ))}
      </nav>

      {/* MAIN */}
      <main className="lg:ml-[245px]">
        {/* TOPBAR */}
        <header className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-white/[0.07] bg-[#080b11]/90 px-5 backdrop-blur-xl md:px-9">
          <div className="flex items-center gap-3">
            <button className="text-slate-400 lg:hidden">
              <Menu size={21} />
            </button>
            <div>
              <p className="text-sm font-semibold">{activeTab}</p>
              <p className="text-[11px] text-slate-500">Your intelligent workspace</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.07] text-slate-400 hover:bg-white/5">
              <Bell size={17} />
              <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-indigo-400" />
            </button>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/15 text-sm font-bold text-indigo-300">
              S
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-[1500px] p-5 md:p-9">
          {activeTab !== "Overview" ? (
            <div>
              {activeTab === "My Trips" && (
                <section>
                  <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold tracking-[1.8px] text-indigo-400">YOUR TRAVEL JOURNAL</p>
                      <h2 className="mt-2 text-2xl font-semibold md:text-3xl">My Trips</h2>
                      <p className="mt-2 text-sm text-slate-500">Saved itineraries and planning records.</p>
                    </div>
                    <button
                      onClick={() => setActiveTab("Overview")}
                      className="rounded-xl bg-indigo-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-indigo-400"
                    >
                      Plan a new trip
                    </button>
                  </div>
                  {savedTrips.length === 0 ? (
                    <div className="rounded-3xl border border-dashed border-white/[0.09] bg-[#10141d] px-6 py-16 text-center">
                      <Plane size={28} className="mx-auto text-indigo-400" />
                      <h3 className="mt-4 text-lg font-semibold">No trips saved yet</h3>
                      <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
                        Ask LifePilot to plan a trip and explicitly save it to My Trips.
                      </p>
                    </div>
                  ) : (
                    <div className="grid gap-5 lg:grid-cols-2">
                      {savedTrips.map((trip) => (
                        <article key={trip.id} className="rounded-2xl border border-white/[0.07] bg-[#10141d] p-5">
                          <div className="flex items-start justify-between">
                            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300">
                              <MapPin size={20} />
                            </div>
                            <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] text-emerald-300">
                              Saved
                            </span>
                          </div>
                          <h3 className="mt-5 text-xl font-semibold">{trip.destination}</h3>
                          <p className="mt-1 text-xs text-slate-500">{trip.days} days · {trip.people} travellers</p>
                          <div className="mt-5 grid grid-cols-3 gap-3">
                            <div className="rounded-xl bg-black/20 p-3 text-xs text-slate-500">Budget<span className="mt-1 block text-sm font-semibold text-slate-200">₹{trip.budget?.toLocaleString("en-IN")}</span></div>
                            <div className="rounded-xl bg-black/20 p-3 text-xs text-slate-500">Estimated<span className="mt-1 block text-sm font-semibold text-slate-200">₹{trip.estimate?.total?.toLocaleString("en-IN")}</span></div>
                            <div className="rounded-xl bg-black/20 p-3 text-xs text-slate-500">Remaining<span className="mt-1 block text-sm font-semibold text-emerald-300">₹{trip.estimate?.remaining?.toLocaleString("en-IN")}</span></div>
                          </div>
                          <div className="mt-4 border-t border-white/[0.06] pt-4 text-xs text-slate-500">
                            Trip ID: {trip.id}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              )}

              {activeTab === "Explore" && (
                <section>
                  <div className="mb-7">
                    <p className="text-xs font-semibold tracking-[1.8px] text-violet-400">DISCOVER PLACES</p>
                    <h2 className="mt-2 text-2xl font-semibold md:text-3xl">Explore</h2>
                    <p className="mt-2 text-sm text-slate-500">Start a trip plan from curated Indian destinations.</p>
                  </div>
                  <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                    {[
                      ["Coorg", "Nature & coffee estates", "₹8,000"],
                      ["Mysuru", "Palaces & quiet getaways", "₹5,000"],
                      ["Goa", "Beaches & coastal food", "₹12,000"],
                      ["Bengaluru", "City breaks & gardens", "₹6,000"],
                      ["Chennai", "Culture & coastal trips", "₹7,000"],
                      ["Mumbai", "Food, culture & nightlife", "₹10,000"],
                    ].map(([name, description, budget]) => (
                      <button
                        key={name}
                        onClick={() => {
                          setActiveTab("Overview");
                          sendMessage(`Plan a 2-day trip to ${name} under ${budget}`);
                        }}
                        className="group rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 text-left transition hover:-translate-y-1 hover:border-indigo-500/30"
                      >
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/20 to-violet-500/10 text-indigo-300">
                          <Compass size={22} />
                        </div>
                        <h3 className="mt-5 text-lg font-semibold">{name}</h3>
                        <p className="mt-1 text-xs text-slate-500">{description}</p>
                        <div className="mt-5 flex items-center justify-between border-t border-white/[0.06] pt-4">
                          <span className="text-xs text-slate-500">Typical budget</span>
                          <span className="text-sm font-semibold text-emerald-300">{budget}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {activeTab === "Calendar" && (
                <section>
                  <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold tracking-[1.8px] text-emerald-400">YOUR SCHEDULE</p>
                      <h2 className="mt-2 text-2xl font-semibold md:text-3xl">Calendar</h2>
                      <p className="mt-2 text-sm text-slate-500">Events created and managed by LifePilot.</p>
                    </div>
                    <button
                      onClick={() => {
                        setActiveTab("Overview");
                        setMessage("Schedule ");
                      }}
                      className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-2.5 text-xs font-semibold hover:bg-white/[0.06]"
                    >
                      Add event
                    </button>
                  </div>
                  {calendarEvents.length === 0 ? (
                    <div className="rounded-3xl border border-dashed border-white/[0.09] bg-[#10141d] px-6 py-16 text-center">
                      <CalendarDays size={28} className="mx-auto text-emerald-400" />
                      <h3 className="mt-4 text-lg font-semibold">No events scheduled</h3>
                      <p className="mt-2 text-sm text-slate-500">Ask LifePilot to schedule learning, work, or appointments.</p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {calendarEvents.map((event) => (
                        <article key={event.id} className="flex flex-col gap-4 rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 md:flex-row md:items-center">
                          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-300">
                            <CalendarDays size={20} />
                          </div>
                          <div className="flex-1">
                            <h3 className="font-semibold">{event.title}</h3>
                            <p className="mt-1 text-xs text-slate-500">
                              {new Date(event.start).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                              {" – "}
                              {new Date(event.end).toLocaleTimeString("en-IN", { timeStyle: "short" })}
                            </p>
                          </div>
                          <span className="rounded-full border border-emerald-500/15 bg-emerald-500/[0.06] px-3 py-1 text-[10px] text-emerald-300">
                            {event.status || "sandbox"}
                          </span>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              )}

              {activeTab === "Settings" && (
                <section>
                  <div className="mb-7">
                    <p className="text-xs font-semibold tracking-[1.8px] text-slate-400">PERSONALIZE LIFE PILOT</p>
                    <h2 className="mt-2 text-2xl font-semibold md:text-3xl">Settings</h2>
                    <p className="mt-2 text-sm text-slate-500">Manage saved preferences and connected capabilities.</p>
                  </div>
                  <div className="grid gap-5 lg:grid-cols-[1fr_0.7fr]">
                    <div className="rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 md:p-6">
                      <h3 className="font-semibold">Travel preferences</h3>
                      <p className="mt-1 text-xs text-slate-500">LifePilot uses these preferences in future trip plans.</p>
                      <div className="mt-5 grid gap-3 sm:grid-cols-2">
                        {[
                          ["budget_friendly", "Budget-friendly"],
                          ["nature", "Nature-focused"],
                          ["quiet_places", "Quiet places"],
                        ].map(([key, label]) => (
                          <label key={key} className="flex items-center justify-between rounded-xl border border-white/[0.06] p-4 text-sm">
                            {label}
                            <input
                              type="checkbox"
                              checked={Boolean(preferences.travel_preferences?.[key])}
                              onChange={(event) => setPreferences((current) => ({
                                ...current,
                                travel_preferences: {
                                  ...current.travel_preferences,
                                  [key]: event.target.checked,
                                },
                              }))}
                              className="h-4 w-4 accent-indigo-500"
                            />
                          </label>
                        ))}
                        <label className="rounded-xl border border-white/[0.06] p-4 text-sm">
                          Food preference
                          <select
                            value={preferences.travel_preferences?.food_preference || "vegetarian"}
                            onChange={(event) => setPreferences((current) => ({
                              ...current,
                              travel_preferences: {
                                ...current.travel_preferences,
                                food_preference: event.target.value,
                              },
                            }))}
                            className="mt-3 w-full rounded-lg border border-white/[0.07] bg-[#080b11] px-3 py-2 text-sm outline-none"
                          >
                            <option value="vegetarian">Vegetarian</option>
                            <option value="vegan">Vegan</option>
                            <option value="non_vegetarian">Non-vegetarian</option>
                            <option value="no_preference">No preference</option>
                          </select>
                        </label>
                      </div>
                      <button
                        onClick={async () => {
                          const response = await fetch(`${apiUrl}/api/preferences`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ user_id: "default", preferences }),
                          }).catch(() => {});
                          if (response?.ok) {
                            setPreferenceSaved(true);
                            window.setTimeout(() => setPreferenceSaved(false), 2500);
                          }
                        }}
                        className="mt-5 rounded-xl bg-indigo-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-indigo-400"
                      >
                        {preferenceSaved ? "Preferences saved" : "Save preferences"}
                      </button>
                    </div>
                    <div className="space-y-4">
                      {[
                        ["Agora voice", providerConfig?.agora === "configured" ? "Connected" : "RTC fallback"],
                        ["Murf Falcon", providerConfig?.murf === "configured" ? "Connected" : "Browser voice"],
                        ["Travel provider", providerConfig?.amadeus === "configured" ? "Connected" : "Sandbox"],
                        ["Calendar", providerConfig?.google_calendar === "configured" ? "Connected" : "Sandbox"],
                      ].map(([name, status]) => (
                        <div key={name} className="flex items-center justify-between rounded-2xl border border-white/[0.07] bg-[#10141d] p-4">
                          <span className="text-sm">{name}</span>
                          <span className="text-xs text-emerald-300">{status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              )}
            </div>
          ) : (
          <>
          {/* GREETING */}
          <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm text-slate-400">THURSDAY, NOVEMBER 19</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
                Let's make things happen<span className="text-indigo-400">.</span>
              </h2>
              <p className="mt-2 text-sm text-slate-500">
                Tell LifePilot what you need. We'll figure out the rest.
              </p>
            </div>

            <div className="flex items-center gap-2 rounded-full border border-emerald-500/15 bg-emerald-500/[0.06] px-3 py-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-xs text-emerald-300">
                {providerConfig
                  ? `${providerConfig.agora === "configured" ? "Agora voice" : "Voice"} · ${providerConfig.amadeus === "configured" ? "Live travel" : "Sandbox travel"}`
                  : "Agent ready"}
              </span>
            </div>
          </div>

          {/* HERO / VOICE AGENT */}
          <section className="relative overflow-hidden rounded-3xl border border-white/[0.08] bg-[#10141e]">
            <div className="absolute -right-20 -top-24 h-80 w-80 rounded-full bg-indigo-600/10 blur-[100px]" />
            <div className="absolute -bottom-28 left-20 h-60 w-60 rounded-full bg-violet-600/10 blur-[100px]" />

            <div className="relative grid lg:grid-cols-[1.2fr_0.8fr]">
              <div className="p-6 md:p-9">
                <div className="flex items-center gap-2">
                  <div className="rounded-lg bg-indigo-500/10 p-2 text-indigo-300">
                    <Bot size={17} />
                  </div>
                  <span className="text-xs font-medium text-indigo-300">
                    PERSONAL AI AGENT
                  </span>
                </div>

                <h3 className="mt-5 text-2xl font-semibold leading-tight md:text-3xl">
                  What can I take care
                  <br className="hidden md:block" /> of for you today?
                </h3>

                <p className="mt-3 max-w-md text-sm leading-6 text-slate-400">
                  Speak naturally. I'll plan, research, coordinate and take action
                  on your behalf.
                </p>

                {/* VOICE BUTTON */}
                <div className="my-8 flex items-center gap-5">
                  <button
                    onClick={toggleMic}
                    className={`relative flex h-[76px] w-[76px] items-center justify-center rounded-full transition-all ${
                      isListening
                        ? "bg-rose-500 shadow-[0_0_45px_rgba(244,63,94,0.35)]"
                        : "bg-gradient-to-br from-indigo-500 to-violet-600 shadow-[0_0_40px_rgba(99,102,241,0.25)] hover:scale-105"
                    }`}
                  >
                    {isListening ? <MicOff size={26} /> : <Mic size={26} />}
                    {isListening && (
                      <span className="absolute -inset-2 animate-ping rounded-full border border-rose-400/30" />
                    )}
                  </button>

                  <div>
                    <p className="text-sm font-medium">
                      {isListening ? "Listening..." : "Start a conversation"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {isListening
                        ? voiceStatus
                        : providerConfig?.agora === "configured"
                          ? "Tap to join the Agora voice channel"
                          : "Tap to use browser voice or type below"}
                    </p>
                  </div>
                </div>

                {/* INPUT */}
                <div className="flex max-w-xl items-center gap-2 rounded-2xl border border-white/[0.08] bg-[#080b11] p-2 focus-within:border-indigo-500/40">
                  <input
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                    placeholder="Tell me what you want to accomplish..."
                    className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-slate-600"
                  />
                  <button
                    onClick={() => sendMessage()}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-500 text-white transition hover:bg-indigo-400"
                  >
                    <Send size={17} />
                  </button>
                </div>

                <p className="mt-3 text-[11px] text-slate-600">
                  AI actions will always require your approval when necessary.
                </p>
              </div>

              {/* AGENT VISUAL */}
              <div className="flex min-h-[300px] items-center justify-center border-t border-white/[0.05] bg-[#0c1019]/60 p-8 lg:border-l lg:border-t-0">
                <div className="relative flex flex-col items-center">
                  <div className="absolute h-52 w-52 rounded-full border border-indigo-500/10" />
                  <div className="absolute h-40 w-40 rounded-full border border-violet-500/10" />
                  <div
                    className={`relative flex h-32 w-32 items-center justify-center rounded-full border border-indigo-400/20 bg-gradient-to-br from-indigo-500/20 via-[#15182b] to-violet-600/20 shadow-[0_0_80px_rgba(99,102,241,0.15)] ${
                      isListening ? "animate-pulse" : ""
                    }`}
                  >
                    <div className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 shadow-xl shadow-indigo-500/20">
                      <Sparkles size={34} />
                    </div>
                  </div>

                  <div className="mt-7 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    <span className="text-sm font-medium">LifePilot AI</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {isListening ? "Listening to your voice" : "Ready for your next task"}
                  </p>

                  <div className="mt-6 flex items-center gap-1.5">
                    {[12, 22, 35, 18, 28, 42, 24, 15, 32, 20, 38, 14, 26].map(
                      (height, i) => (
                        <div
                          key={i}
                          className={`w-1 rounded-full bg-gradient-to-t from-indigo-500 to-violet-400 transition-all ${
                            isListening ? "animate-pulse" : ""
                          }`}
                          style={{ height: isListening ? height : 5 }}
                        />
                      )
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* QUICK SUGGESTIONS */}
          <section className="mt-6">
            <p className="mb-3 text-xs font-medium text-slate-500">
              TRY ASKING
            </p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => sendMessage(suggestion)}
                  className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-2.5 text-xs text-slate-400 transition hover:border-indigo-500/30 hover:bg-indigo-500/[0.06] hover:text-indigo-300"
                >
                  <span className="mr-2 text-indigo-400">✦</span>
                  {suggestion}
                </button>
              ))}
            </div>
          </section>

          {/* GRID */}
          <div className="mt-8 grid gap-5 xl:grid-cols-2">
            {/* TASK PANEL */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 md:p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity size={17} className="text-indigo-400" />
                  <h3 className="text-sm font-semibold">Agent execution</h3>
                </div>
                <span className="rounded-full bg-indigo-500/10 px-2.5 py-1 text-[10px] text-indigo-300">
                  LIVE WORKFLOW
                </span>
              </div>

              <div className="mt-6 space-y-5">
                {tasks.map((task, index) => (
                  <div key={index} className="flex items-start gap-3">
                    <div className="mt-0.5">
                      {task.status === "completed" ? (
                        <CheckCircle2 size={18} className="text-emerald-400" />
                      ) : task.status === "active" ? (
                        <div className="h-[18px] w-[18px] animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
                      ) : (
                        <Circle size={18} className="text-slate-600" />
                      )}
                    </div>
                    <div className="flex-1">
                      <p
                        className={`text-sm ${
                          task.status === "completed"
                            ? "text-slate-300"
                            : task.status === "active"
                            ? "font-medium text-indigo-300"
                            : "text-slate-500"
                        }`}
                      >
                        {task.title}
                      </p>
                      {task.status === "active" && (
                        <p className="mt-1 text-[11px] text-indigo-400/70">
                          In progress
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-7 rounded-xl border border-white/[0.05] bg-[#080b11] p-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={15} className="text-emerald-400" />
                  <p className="text-xs text-slate-400">
                    Actions are verified before being marked complete.
                  </p>
                </div>
              </div>
            </section>

            {/* TRIP OVERVIEW */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 md:p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Compass size={17} className="text-violet-400" />
                  <h3 className="text-sm font-semibold">Trip overview</h3>
                </div>
                <button className="rounded-lg p-2 text-slate-500 transition hover:bg-white/5 hover:text-white">
                  <ArrowUpRight size={17} />
                </button>
              </div>

              <div className="mt-5 overflow-hidden rounded-xl bg-gradient-to-br from-indigo-500/15 via-[#171b2b] to-violet-500/10 p-5">
                <div className="flex items-center gap-2 text-xs text-indigo-300">
                  <MapPin size={14} />
                  DESTINATION
                </div>
                <h3 className="mt-2 text-2xl font-semibold">{tripOverview.destination}</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Your next adventure awaits
                </p>

                <div className="mt-5 grid grid-cols-3 gap-3">
                  <div className="rounded-xl border border-white/[0.05] bg-black/20 p-3">
                    <Wallet size={15} className="text-emerald-400" />
                    <p className="mt-2 text-[10px] text-slate-500">Budget</p>
                    <p className="mt-1 text-sm font-semibold">
                      {tripOverview.budget ? `₹${tripOverview.budget.toLocaleString("en-IN")}` : "Not set"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/[0.05] bg-black/20 p-3">
                    <CloudSun size={15} className="text-amber-400" />
                    <p className="mt-2 text-[10px] text-slate-500">Weather</p>
                    <p className="mt-1 text-sm font-semibold">Check live</p>
                  </div>
                  <div className="rounded-xl border border-white/[0.05] bg-black/20 p-3">
                    <Clock3 size={15} className="text-violet-400" />
                    <p className="mt-2 text-[10px] text-slate-500">Duration</p>
                    <p className="mt-1 text-sm font-semibold">{tripOverview.duration || "Not set"}</p>
                  </div>
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between rounded-xl border border-white/[0.05] p-3">
                <div>
                  <p className="text-xs font-medium">Planning status</p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {tripOverview.status === "Ready" ? "Waiting for your travel request" : tripOverview.status}
                  </p>
                </div>
                <span className="rounded-full border border-amber-500/10 bg-amber-500/[0.06] px-2 py-1 text-[10px] text-amber-300">
                  Draft
                </span>
              </div>
            </section>
          </div>

          {/* CHAT */}
          <section className="mt-5 rounded-2xl border border-white/[0.07] bg-[#10141d] p-5 md:p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Bot size={17} className="text-indigo-400" />
                <h3 className="text-sm font-semibold">Conversation</h3>
              </div>
              <span className="text-xs text-slate-600">
                {conversation.length} messages
              </span>
            </div>

            <div className="mt-5 max-h-[360px] space-y-4 overflow-y-auto pr-2">
              {conversation.map((item, index) => (
                <div
                  key={index}
                  className={`flex gap-3 ${
                    item.role === "user" ? "flex-row-reverse" : ""
                  }`}
                >
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${
                      item.role === "assistant"
                        ? "bg-indigo-500/15 text-indigo-300"
                        : "bg-slate-700 text-slate-300"
                    }`}
                  >
                    {item.role === "assistant" ? (
                      <Sparkles size={15} />
                    ) : (
                      <span className="text-xs font-semibold">S</span>
                    )}
                  </div>

                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                      item.role === "assistant"
                        ? "rounded-tl-sm border border-white/[0.04] bg-[#171c28]"
                        : "rounded-tr-sm bg-indigo-500/15"
                    }`}
                  >
                    <p className="text-[10px] font-medium text-slate-500">
                      {item.role === "assistant" ? "LIFEPILOT" : "YOU"}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-300">
                      {item.text}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            {approvalRequired && (
              <div className="mt-5 flex flex-wrap gap-2 rounded-xl border border-amber-500/15 bg-amber-500/[0.04] p-3">
                <p className="w-full text-xs text-amber-200">
                  Approval required before this sandbox booking
                </p>
                <button
                  onClick={() => handleApproval(true)}
                  disabled={isSending}
                  className="rounded-lg bg-emerald-500 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-400 disabled:opacity-50"
                >
                  Approve & book
                </button>
                <button
                  onClick={() => handleApproval(false)}
                  disabled={isSending}
                  className="rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
                >
                  Not now
                </button>
              </div>
            )}

            <div className="mt-5 flex items-center gap-2 rounded-xl border border-white/[0.07] bg-[#080b11] p-2">
              <input
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                placeholder="Continue your conversation..."
                className="flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-slate-600"
              />
              <button
                onClick={() => sendMessage()}
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500 text-white hover:bg-indigo-400"
              >
                <Send size={16} />
              </button>
            </div>
          </section>

          </>
          )}

          {/* FOOTER */}
          <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] py-5">
            <p className="text-xs text-slate-600">
              LifePilot AI · Your personal action agent
            </p>
            <div className="flex items-center gap-2 text-xs text-slate-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Built for Build with Agora · Bengaluru 2026
            </div>
          </footer>
        </div>
      </main>
    </div>
  );
}