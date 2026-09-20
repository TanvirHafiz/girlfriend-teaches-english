// ---- Config ----
const MIN_VOICE_TO_START_MS = 180;   // sustained voice before we start recording
const SILENCE_TO_STOP_MS = 900;      // sustained silence before we end the utterance
const CONTINUE_THRESHOLD_RATIO = 0.4; // once already recording, count anything above this
                                       // fraction of the start threshold as "still talking" —
                                       // sentences trail off quieter at the end, and using the
                                       // same threshold to stop as to start was cutting off the
                                       // last word or two whenever it landed softer than average
const BARGE_IN_SUSTAIN_MS = 220;     // sustained voice while she's speaking before we interrupt her
const MIN_UTTERANCE_BYTES = 2000;    // ignore tiny blips
const CALIBRATION_MS = 700;          // how long to sample ambient noise before a call starts
const NOISE_FLOOR_MULTIPLIER = 4;    // speech must be this many times louder than the noise floor
const MIN_SPEECH_THRESHOLD = 0.006;  // floor so a dead-silent room doesn't make us hair-trigger

let speechThreshold = 0.020; // replaced by calibrateNoiseFloor() once the mic is live

// ---- Setup view elements ----
const setupView = document.getElementById("setup-view");
const callView = document.getElementById("call-view");
const voiceSelect = document.getElementById("f-voice");
const modeSelect = document.getElementById("f-mode");
const detailInput = document.getElementById("f-detail");
const modelSelect = document.getElementById("f-model");
const modelHint = document.getElementById("model-hint");
const setupError = document.getElementById("setup-error");

// ---- Call view elements ----
const orb = document.getElementById("orb");
const statusEl = document.getElementById("status");
const herNameEl = document.getElementById("her-name");
const transcriptEl = document.getElementById("transcript");
const btnMute = document.getElementById("btn-mute");
const btnEnd = document.getElementById("btn-end");

let profile = null;
let ws = null;
let audioCtx = null;
let analyser = null;
let micStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let vadInterval = null;

let isRecording = false;
let isAssistantSpeaking = false;
let pendingMoreAudio = false;
let isMuted = false;

let voicedStart = null;
let lastVoiceTime = null;
let bargeInVoicedStart = null;

let nextStartTime = 0;
let activeSources = [];

// ---------------------------------------------------------------------
// Setup view
// ---------------------------------------------------------------------
async function loadVoices() {
  const res = await fetch("/api/voices");
  const voices = await res.json();
  voiceSelect.innerHTML = voices.map(v => `<option value="${v}">${v}</option>`).join("");
}

const DETAIL_LABELS = {
  general: "Topic to lean on (optional)",
  job_interview: "Job title / field (optional)",
  speaking_test: "Which test? (optional)",
  vocabulary: "Topic area (optional)",
};
const DETAIL_PLACEHOLDERS = {
  general: "e.g. small talk, daily life, travel...",
  job_interview: "e.g. software engineer, marketing manager...",
  speaking_test: "e.g. IELTS, TOEFL...",
  vocabulary: "e.g. business English, travel vocabulary...",
};
const detailLabel = document.getElementById("f-detail-label");

async function loadPracticeModes() {
  const res = await fetch("/api/practice-modes");
  const modes = await res.json();
  modeSelect.innerHTML = Object.entries(modes)
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  updateDetailPlaceholder();
}

function updateDetailPlaceholder() {
  const mode = modeSelect.value;
  detailInput.placeholder = DETAIL_PLACEHOLDERS[mode] || "";
  detailLabel.textContent = DETAIL_LABELS[mode] || "Details (optional)";
}

modeSelect.addEventListener("change", updateDetailPlaceholder);

async function loadOllamaModels() {
  try {
    const res = await fetch("/api/ollama/models");
    if (!res.ok) throw new Error(await res.text());
    const models = await res.json();
    if (models.length === 0) {
      modelSelect.innerHTML = "";
      modelHint.textContent = "No models found. Run \"ollama pull <model>\" first.";
      return;
    }
    modelSelect.innerHTML = models.map((m) => `<option value="${m}">${m}</option>`).join("");
    modelHint.textContent = "Models currently pulled in Ollama.";
  } catch (e) {
    modelSelect.innerHTML = "";
    modelHint.textContent = "Could not reach Ollama on localhost:11434 — is it running?";
  }
}

function ensureModelOption(modelName) {
  if (!modelName) return;
  const exists = Array.from(modelSelect.options).some((o) => o.value === modelName);
  if (!exists) {
    const opt = document.createElement("option");
    opt.value = modelName;
    opt.textContent = modelName + " (not currently pulled)";
    modelSelect.prepend(opt);
  }
  modelSelect.value = modelName;
}

async function loadExistingProfile() {
  try {
    const res = await fetch("/api/profile/default");
    const p = await res.json();
    document.getElementById("f-name").value = p.name;
    document.getElementById("f-level").value = p.proficiency_level;
    modeSelect.value = p.practice_mode || "general";
    updateDetailPlaceholder();
    detailInput.value = p.focus_detail || "";
    ensureModelOption(p.ollama_model);
    if (p.voice) voiceSelect.value = p.voice;
  } catch (e) { /* no existing profile yet, fine */ }
}

async function saveProfileAndStart() {
  setupError.textContent = "";
  profile = {
    id: "default",
    name: document.getElementById("f-name").value.trim() || "Ms. Claire",
    proficiency_level: document.getElementById("f-level").value,
    practice_mode: modeSelect.value,
    focus_detail: detailInput.value.trim(),
    voice: voiceSelect.value,
    ollama_model: modelSelect.value,
  };
  if (!profile.ollama_model) {
    setupError.textContent = "No Ollama model selected. Make sure Ollama is running and a model is pulled.";
    return;
  }
  try {
    const res = await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) throw new Error(await res.text());
  } catch (e) {
    setupError.textContent = "Could not save profile: " + e.message;
    return;
  }
  herNameEl.textContent = profile.name;
  setupView.classList.add("hidden");
  callView.classList.remove("hidden");
  startCall();
}

document.getElementById("btn-save").addEventListener("click", saveProfileAndStart);

// ---------------------------------------------------------------------
// Call lifecycle
// ---------------------------------------------------------------------
async function startCall() {
  setStatus("Connecting...");
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (e) {
    setStatus("Microphone access denied.");
    return;
  }

  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const micSource = audioCtx.createMediaStreamSource(micStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  micSource.connect(analyser);

  await calibrateNoiseFloor();
  connectWebSocket();
  vadInterval = setInterval(vadTick, 80);
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/chat`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "set_profile", profile_id: "default" }));
  };

  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      handleServerEvent(JSON.parse(event.data));
    } else {
      playSentenceAudio(event.data);
    }
  };

  ws.onclose = () => setStatus("Disconnected.");
  ws.onerror = () => setStatus("Connection error.");
}

function endCall() {
  clearInterval(vadInterval);
  stopAssistantAudio();
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (ws) ws.close();
  if (audioCtx) audioCtx.close();
  callView.classList.add("hidden");
  setupView.classList.remove("hidden");
  transcriptEl.innerHTML = "";
  targetWordsList.innerHTML = "";
  learnedWordsList.innerHTML = "";
  learnedWords.clear();
  learnedEmptyHint.hidden = false;
}

btnEnd.addEventListener("click", endCall);

btnMute.addEventListener("click", () => {
  isMuted = !isMuted;
  micStream.getAudioTracks().forEach((t) => (t.enabled = !isMuted));
  btnMute.classList.toggle("active", isMuted);
  btnMute.textContent = isMuted ? "Unmute" : "Mute";
});

// ---------------------------------------------------------------------
// Voice activity detection / turn taking
// ---------------------------------------------------------------------
function currentRms() {
  const data = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(data);
  let sumSq = 0;
  for (let i = 0; i < data.length; i++) sumSq += data[i] * data[i];
  return Math.sqrt(sumSq / data.length);
}

async function calibrateNoiseFloor() {
  setStatus("Calibrating mic...");
  const samples = [];
  const start = performance.now();
  while (performance.now() - start < CALIBRATION_MS) {
    samples.push(currentRms());
    await new Promise((r) => setTimeout(r, 30));
  }
  const avgNoise = samples.reduce((a, b) => a + b, 0) / samples.length;
  speechThreshold = Math.max(MIN_SPEECH_THRESHOLD, avgNoise * NOISE_FLOOR_MULTIPLIER);
}

function vadTick() {
  if (isMuted || !analyser) return;
  const rms = currentRms();
  const voiced = rms > speechThreshold;
  const now = performance.now();

  if (isAssistantSpeaking) {
    if (voiced) {
      bargeInVoicedStart = bargeInVoicedStart || now;
      if (now - bargeInVoicedStart > BARGE_IN_SUSTAIN_MS) {
        bargeInVoicedStart = null;
        triggerBargeIn();
      }
    } else {
      bargeInVoicedStart = null;
    }
    return;
  }

  if (!isRecording) {
    if (voiced) {
      voicedStart = voicedStart || now;
      if (now - voicedStart > MIN_VOICE_TO_START_MS) {
        voicedStart = null;
        startRecording();
      }
    } else {
      voicedStart = null;
    }
  } else {
    const stillTalking = voiced || rms > speechThreshold * CONTINUE_THRESHOLD_RATIO;
    if (stillTalking) {
      lastVoiceTime = now;
    } else if (now - lastVoiceTime > SILENCE_TO_STOP_MS) {
      stopRecording();
    }
  }
}

function triggerBargeIn() {
  stopAssistantAudio();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "barge_in" }));
  }
  setStatus("Listening...");
  setOrb("idle");
}

function startRecording() {
  isRecording = true;
  recordedChunks = [];
  lastVoiceTime = performance.now();
  try {
    mediaRecorder = new MediaRecorder(micStream, { mimeType: "audio/webm;codecs=opus" });
  } catch (e) {
    mediaRecorder = new MediaRecorder(micStream);
  }
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.onstop = onRecordingStopped;
  mediaRecorder.start();
  setOrb("listening");
  setStatus("Listening...");
}

function stopRecording() {
  isRecording = false;
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
}

async function onRecordingStopped() {
  const blob = new Blob(recordedChunks, { type: "audio/webm" });
  recordedChunks = [];
  if (blob.size < MIN_UTTERANCE_BYTES) {
    setOrb("idle");
    setStatus("Listening...");
    return;
  }
  setOrb("thinking");
  setStatus("Thinking...");
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "utterance", mime: "audio/webm" }));
    const buf = await blob.arrayBuffer();
    ws.send(buf);
  }
}

// ---------------------------------------------------------------------
// Server events + transcript
// ---------------------------------------------------------------------
function handleServerEvent(msg) {
  switch (msg.type) {
    case "ready":
      setStatus("Say hello...");
      setOrb("idle");
      break;
    case "transcript":
      addLine("user", msg.text);
      setStatus("Thinking...");
      setOrb("thinking");
      break;
    case "assistant_sentence":
      pendingMoreAudio = true;
      addLine("her", msg.text);
      setStatus("Speaking...");
      break;
    case "turn_end":
      pendingMoreAudio = false;
      if (activeSources.length === 0) {
        setAssistantSpeaking(false);
        setStatus("Listening...");
      }
      break;
    case "error":
      addLine("her", "(" + msg.message + ")");
      setStatus("Listening...");
      setOrb("idle");
      break;
    case "lesson_words":
      renderTargetWords(msg.words);
      break;
    case "vocab_update":
      markUsedTargetWords(msg.used_target_words);
      addLearnedWords(msg.difficult_words);
      break;
  }
}

function addLine(who, text) {
  const div = document.createElement("div");
  div.className = "line " + who;
  div.textContent = text;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

// ---------------------------------------------------------------------
// Vocabulary panels
// ---------------------------------------------------------------------
const targetWordsList = document.getElementById("target-words-list");
const learnedWordsList = document.getElementById("learned-words-list");
const learnedEmptyHint = document.getElementById("learned-empty-hint");
const learnedWords = new Set();

function renderTargetWords(words) {
  targetWordsList.innerHTML = "";
  for (const w of words || []) {
    const li = document.createElement("li");
    li.dataset.word = w.word.toLowerCase();
    li.innerHTML = `<span>${w.word}</span><span class="bangla">&ndash; ${w.bangla}</span>`;
    targetWordsList.appendChild(li);
  }
}

function markUsedTargetWords(words) {
  for (const word of words || []) {
    const li = targetWordsList.querySelector(`li[data-word="${word.toLowerCase()}"]`);
    if (li) li.classList.add("used");
  }
}

function addLearnedWords(items) {
  for (const item of items || []) {
    const key = item.word.toLowerCase();
    if (learnedWords.has(key)) continue;
    learnedWords.add(key);
    const li = document.createElement("li");
    li.innerHTML = `<span>${item.word}</span><span class="bangla">&ndash; ${item.bangla}</span>`;
    learnedWordsList.appendChild(li);
  }
  learnedEmptyHint.hidden = learnedWords.size > 0;
}

// ---------------------------------------------------------------------
// Gapless playback
// ---------------------------------------------------------------------
async function playSentenceAudio(arrayBuffer) {
  let buffer;
  try {
    buffer = await audioCtx.decodeAudioData(arrayBuffer.slice(0));
  } catch (e) {
    console.error("audio decode failed", e);
    return;
  }
  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(audioCtx.destination);
  const startAt = Math.max(audioCtx.currentTime, nextStartTime);
  source.start(startAt);
  nextStartTime = startAt + buffer.duration;
  activeSources.push(source);
  setAssistantSpeaking(true);
  source.onended = () => {
    activeSources = activeSources.filter((s) => s !== source);
    if (activeSources.length === 0 && !pendingMoreAudio) {
      setAssistantSpeaking(false);
      setStatus("Listening...");
    }
  };
}

function stopAssistantAudio() {
  activeSources.forEach((s) => {
    try {
      s.stop();
    } catch (e) {}
  });
  activeSources = [];
  nextStartTime = 0;
  pendingMoreAudio = false;
  setAssistantSpeaking(false);
}

function setAssistantSpeaking(speaking) {
  isAssistantSpeaking = speaking;
  setOrb(speaking ? "speaking" : "idle");
}

function setOrb(state) {
  orb.className = "orb " + state;
}

function setStatus(text) {
  statusEl.textContent = text;
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
Promise.all([loadVoices(), loadOllamaModels(), loadPracticeModes()]).then(loadExistingProfile);
