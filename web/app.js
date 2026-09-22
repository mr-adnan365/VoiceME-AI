// VoiceMe front end.
//
//   Talk -> record the microphone -> stop when you pause -> POST the audio to /api/talk
//   -> the server streams back one JSON line per sentence (text + WAV audio)
//   -> sentences are queued on the Web Audio clock so they play back to back.
//
// A single string on the canvas vibrates with your voice (blue) and with VoiceMe's (magenta).

const $ = (selector) => document.querySelector(selector);
const els = {
  status: $('#status'),
  statusText: $('#status-text'),
  notice: $('#notice'),
  canvas: $('#string'),
  caption: $('#caption'),
  talk: $('#talk'),
  continuous: $('#continuous'),
  history: $('#history'),
  log: $('#log'),
  reset: $('#reset'),
};

// Tuning -----------------------------------------------------------------
const SILENCE_MS = 1300; // a pause this long ends your turn
const NO_SPEECH_MS = 8000; // give up if nothing is said
const MAX_RECORD_MS = 30000; // hard cap on one recording
const MIN_VOICE_MS = 200; // less voiced audio than this counts as silence
const CALIBRATE_MS = 300; // measure background noise before listening for speech

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

const BUTTON_LABEL = { idle: 'Talk', listening: 'Done', thinking: 'Cancel', speaking: 'Interrupt' };
const STATUS_LABEL = { idle: 'Ready', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking' };

// State --------------------------------------------------------------------
let mode = 'idle'; // idle | listening | thinking | speaking
let audioCtx = null;
let outAnalyser = null; // taps VoiceMe's voice for the string
let mic = null; // the active recording, if any
let turn = null; // the active request/playback, if any
let starting = false;
let llmReady = true;
let hasMessages = false;

const sessionId = (crypto.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`);

// Small helpers ----------------------------------------------------------
function setMode(next) {
  mode = next;
  els.talk.textContent = BUTTON_LABEL[next];
  els.talk.dataset.mode = next;
  els.status.dataset.state = next;
  els.statusText.textContent = next === 'idle' && !llmReady ? 'Setup needed' : STATUS_LABEL[next];
}

function setCaption(text) {
  els.caption.textContent = text;
}

function idleHint() {
  return hasMessages ? 'Press Talk to continue.' : 'Press Talk and ask me anything.';
}

function showNotice(message, command) {
  els.notice.replaceChildren();
  const strong = document.createElement('strong');
  strong.textContent = message;
  els.notice.append(strong);
  if (command) {
    const code = document.createElement('code');
    code.textContent = command;
    els.notice.append(' ', code, '. Then press Talk again.');
  }
  els.notice.hidden = false;
}

function hideNotice() {
  els.notice.hidden = true;
}

function addMessage(who, text) {
  const item = document.createElement('li');
  item.className = 'message';
  item.dataset.who = who;
  const name = document.createElement('span');
  name.className = 'who';
  name.textContent = who === 'you' ? 'You' : 'VoiceMe';
  const body = document.createElement('p');
  body.textContent = text;
  item.append(name, body);
  els.log.append(item);
  els.history.hidden = false;
  hasMessages = true;
  item.scrollIntoView({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' });
  return body;
}

function base64ToBuffer(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function pickMime() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? '';
}

function extensionFor(type) {
  if (type.includes('mp4')) return 'm4a';
  if (type.includes('ogg')) return 'ogg';
  return 'webm';
}

function ensureAudio() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    outAnalyser = audioCtx.createAnalyser();
    outAnalyser.fftSize = 1024;
    outAnalyser.connect(audioCtx.destination);
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
}

// Server health ----------------------------------------------------------
async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    llmReady = health.llm.ready;
    if (llmReady) hideNotice();
    else showNotice(health.llm.message, health.llm.fix);
  } catch {
    llmReady = false;
    showNotice("Can't reach the VoiceMe server. Is it still running?");
  }
  setMode(mode);
}

// Listening ----------------------------------------------------------------
async function startListening() {
  if (starting || mode === 'listening') return;
  starting = true;
  try {
    ensureAudio(); // must happen inside the click so the browser allows sound
    if (!llmReady) await checkHealth();
    if (!llmReady) return;

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);

    const mimeType = pickMime();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const now = performance.now();
    const rec = {
      stream, source, analyser, recorder,
      chunks: [], send: true, reason: '',
      startedAt: now, lastTick: now, lastVoiceAt: 0, voicedMs: 0, noiseFloor: 0,
      timer: null, samples: new Float32Array(analyser.fftSize),
    };
    recorder.ondataavailable = (event) => { if (event.data.size) rec.chunks.push(event.data); };
    recorder.onstop = () => onRecorded(rec);
    recorder.start();
    rec.timer = setInterval(() => listenTick(rec), 50);

    mic = rec;
    hideNotice();
    setMode('listening');
    setCaption('Listening…');
  } catch (error) {
    micError(error);
  } finally {
    starting = false;
  }
}

// Runs every 50 ms while recording: decides when you have finished talking.
function listenTick(rec) {
  const now = performance.now();
  const dt = now - rec.lastTick;
  rec.lastTick = now;

  rec.analyser.getFloatTimeDomainData(rec.samples);
  let sum = 0;
  for (const value of rec.samples) sum += value * value;
  const level = Math.sqrt(sum / rec.samples.length);

  const elapsed = now - rec.startedAt;
  if (elapsed < CALIBRATE_MS) {
    rec.noiseFloor = Math.max(rec.noiseFloor, level);
    return;
  }
  const threshold = Math.max(0.02, Math.min(rec.noiseFloor * 2.5, 0.05));
  if (level > threshold) {
    rec.voicedMs += dt;
    rec.lastVoiceAt = now;
  }
  const spoke = rec.voicedMs > MIN_VOICE_MS;
  if (spoke && now - rec.lastVoiceAt > SILENCE_MS) finishRecording(true);
  else if (!spoke && elapsed > NO_SPEECH_MS) finishRecording(false, 'no_speech');
  else if (elapsed > MAX_RECORD_MS) finishRecording(spoke, 'no_speech');
}

function finishRecording(send, reason = '') {
  const rec = mic;
  if (!rec) return;
  rec.send = send;
  rec.reason = reason;
  clearInterval(rec.timer);
  if (rec.recorder.state !== 'inactive') rec.recorder.stop();
  else onRecorded(rec);
}

function onRecorded(rec) {
  clearInterval(rec.timer);
  rec.source.disconnect();
  rec.stream.getTracks().forEach((track) => track.stop()); // turns off the browser's mic indicator
  if (mic === rec) mic = null;

  if (!rec.send || rec.chunks.length === 0) {
    setMode('idle');
    setCaption(idleHint());
    if (rec.reason === 'no_speech') {
      showNotice("Didn't hear anything. Check that the right microphone is selected, then try again.");
    }
    return;
  }
  const type = rec.recorder.mimeType || 'audio/webm';
  sendTurn(new Blob(rec.chunks, { type }));
}

function micError(error) {
  let message = "Couldn't start the microphone.";
  switch (error?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      message = 'Microphone access is blocked. Allow it in your browser’s site settings, then press Talk again.';
      break;
    case 'NotFoundError':
      message = 'No microphone found. Plug one in, then press Talk again.';
      break;
    case 'NotReadableError':
      message = 'Another app is using the microphone. Close it, then press Talk again.';
      break;
  }
  els.continuous.checked = false;
  showNotice(message);
  setMode('idle');
  setCaption(idleHint());
}

// One conversational turn -----------------------------------------------------
async function sendTurn(blob) {
  const t = {
    controller: new AbortController(),
    cancelled: false, finished: false, streamDone: false, failed: false,
    playhead: 0, pending: 0, chain: Promise.resolve(),
    sources: new Set(), timers: new Set(),
    replyBody: null,
  };
  turn = t;
  setMode('thinking');
  setCaption('Thinking…');

  try {
    const form = new FormData();
    form.append('audio', blob, `speech.${extensionFor(blob.type)}`);
    form.append('session_id', sessionId);
    const response = await fetch('/api/talk', { method: 'POST', body: form, signal: t.controller.signal });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `The server returned an error (${response.status}).`);
    }
    await readEvents(response.body, (event) => handleEvent(t, event));
  } catch (error) {
    if (t.cancelled) return;
    fail(t, error instanceof TypeError ? "Lost the connection to the VoiceMe server. Is it still running?" : error.message);
  }
  t.streamDone = true;
  maybeFinish(t);
}

// The server sends newline-delimited JSON; this reads it as it arrives.
async function readEvents(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffered += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffered.indexOf('\n')) >= 0) {
      const line = buffered.slice(0, newline).trim();
      buffered = buffered.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

function handleEvent(t, event) {
  if (t.cancelled) return;
  switch (event.type) {
    case 'transcript':
      if (event.text) {
        addMessage('you', event.text);
        setCaption(`“${event.text}”`);
      }
      break;
    case 'sentence':
      queueSentence(t, event);
      break;
    case 'error':
      fail(t, event.message);
      break;
  }
}

function fail(t, message) {
  t.failed = true;
  showNotice(message);
}

// Playback ---------------------------------------------------------------------
function queueSentence(t, event) {
  t.pending++;
  t.chain = t.chain
    .then(() => playSentence(t, event))
    .catch(() => {})
    .finally(() => {
      t.pending--;
      maybeFinish(t);
    });
}

async function playSentence(t, event) {
  let buffer = null;
  try {
    buffer = await audioCtx.decodeAudioData(base64ToBuffer(event.audio));
  } catch {
    // Show the text even if this clip can't be decoded.
  }
  if (t.cancelled) return;

  const now = audioCtx.currentTime;
  const startAt = Math.max(now + 0.03, t.playhead);
  if (buffer) {
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(outAnalyser);
    source.onended = () => {
      t.sources.delete(source);
      maybeFinish(t);
    };
    t.sources.add(source);
    source.start(startAt);
    t.playhead = startAt + buffer.duration;
  }
  // Update the caption and the log at the moment this sentence is actually heard.
  const timer = setTimeout(() => {
    t.timers.delete(timer);
    onSentenceStart(t, event.text);
    maybeFinish(t);
  }, Math.max(0, (startAt - now) * 1000));
  t.timers.add(timer);
}

function onSentenceStart(t, text) {
  if (t.cancelled) return;
  if (mode !== 'speaking') setMode('speaking');
  setCaption(text);
  if (t.replyBody) {
    t.replyBody.textContent += ` ${text}`;
  } else {
    t.replyBody = addMessage('voiceme', text);
  }
}

function maybeFinish(t) {
  if (t.finished || t.cancelled) return;
  if (!t.streamDone || t.pending > 0 || t.sources.size > 0 || t.timers.size > 0) return;
  t.finished = true;
  turn = null;
  setMode('idle');
  setCaption(t.failed ? 'Press Talk to try again.' : idleHint());
  if (els.continuous.checked && !t.failed) startListening();
}

// Stops the request and any audio that is playing.
function interrupt() {
  const t = turn;
  if (!t) return;
  t.cancelled = true;
  t.controller.abort();
  t.sources.forEach((source) => {
    source.onended = null;
    try { source.stop(); } catch { /* already stopped */ }
  });
  t.timers.forEach((timer) => clearTimeout(timer));
  turn = null;
  setMode('idle');
  setCaption(idleHint());
}

function stopEverything() {
  if (mic) finishRecording(false, 'cancel');
  interrupt();
}

// Controls -----------------------------------------------------------------------
function onTalk() {
  switch (mode) {
    case 'idle':
      startListening();
      break;
    case 'listening':
      if (mic) finishRecording(mic.voicedMs > MIN_VOICE_MS, 'no_speech');
      break;
    case 'thinking':
      interrupt();
      break;
    case 'speaking':
      interrupt();
      startListening(); // talking over VoiceMe is a normal way to interrupt
      break;
  }
}

els.talk.addEventListener('click', onTalk);

document.addEventListener('keydown', (event) => {
  if (event.repeat) return;
  const tag = document.activeElement?.tagName;
  const onControl = tag === 'BUTTON' || tag === 'INPUT' || tag === 'A';
  if (event.code === 'Space' && !onControl) {
    event.preventDefault();
    onTalk();
  } else if (event.key === 'Escape') {
    stopEverything();
  }
});

els.reset.addEventListener('click', () => {
  stopEverything();
  els.log.replaceChildren();
  els.history.hidden = true;
  hasMessages = false;
  hideNotice();
  setCaption(idleHint());
  fetch('/api/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {});
});

try {
  els.continuous.checked = localStorage.getItem('voiceme.continuous') === '1';
} catch { /* storage can be unavailable in private windows */ }
els.continuous.addEventListener('change', () => {
  try { localStorage.setItem('voiceme.continuous', els.continuous.checked ? '1' : '0'); } catch { /* ignore */ }
});

addEventListener('pagehide', () => mic?.stream.getTracks().forEach((track) => track.stop()));

// The string ---------------------------------------------------------------------
const g = els.canvas.getContext('2d');
const drawSamples = new Float32Array(1024);
let width = 0;
let height = 0;

function resizeCanvas() {
  const rect = els.canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  width = rect.width;
  height = rect.height;
  els.canvas.width = Math.round(width * ratio);
  els.canvas.height = Math.round(height * ratio);
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
}
new ResizeObserver(resizeCanvas).observe(els.canvas);

function readColors() {
  const styles = getComputedStyle(document.documentElement);
  const get = (name) => styles.getPropertyValue(name).trim();
  return { ink: get('--ink'), soft: get('--ink-soft'), you: get('--you'), reply: get('--reply') };
}
let colors = readColors();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { colors = readColors(); });

function drawString(time) {
  requestAnimationFrame(drawString);
  g.clearRect(0, 0, width, height);

  const pad = 14;
  const span = width - pad * 2;
  const mid = height / 2;

  // Which voice is the string carrying right now?
  let analyser = null;
  let color = colors.ink;
  let gain = 0;
  if (mode === 'listening' && mic) {
    analyser = mic.analyser; color = colors.you; gain = 5;
  } else if (mode === 'speaking') {
    analyser = outAnalyser; color = colors.reply; gain = 2.4;
  } else if (mode === 'thinking') {
    color = colors.soft;
  }

  g.lineWidth = 3.5;
  g.lineCap = 'round';
  g.lineJoin = 'round';
  g.strokeStyle = color;
  g.beginPath();
  if (analyser) {
    analyser.getFloatTimeDomainData(drawSamples);
    const points = Math.max(60, Math.floor(span / 5));
    const last = drawSamples.length - 1;
    for (let i = 0; i <= points; i++) {
      const x = i / points;
      const j = Math.min(last, Math.floor(x * drawSamples.length));
      const sample = (drawSamples[Math.max(0, j - 1)] + drawSamples[j] + drawSamples[Math.min(last, j + 1)]) / 3;
      const pinned = Math.pow(Math.sin(Math.PI * x), 0.9); // both ends of the string stay fixed
      const y = mid + Math.tanh(sample * gain) * height * 0.42 * pinned;
      if (i === 0) g.moveTo(pad + x * span, y);
      else g.lineTo(pad + x * span, y);
    }
  } else {
    g.moveTo(pad, mid);
    g.lineTo(width - pad, mid);
  }
  g.stroke();

  // The two posts the string is tied to.
  g.fillStyle = colors.ink;
  for (const x of [pad, width - pad]) {
    g.beginPath();
    g.arc(x, mid, 5, 0, Math.PI * 2);
    g.fill();
  }

  // While thinking, a bead travels along the string.
  if (mode === 'thinking') {
    const x = 0.5 + (reducedMotion ? 0 : 0.45 * Math.sin(time / 450));
    g.fillStyle = colors.ink;
    g.beginPath();
    g.arc(pad + x * span, mid, 7, 0, Math.PI * 2);
    g.fill();
  }
}

// Start-up -----------------------------------------------------------------------
if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
  els.talk.disabled = true;
  showNotice(
    "This browser can't record audio here. Open VoiceMe at http://localhost:8000 in a current version of Chrome, Edge, Firefox or Safari.",
  );
} else {
  checkHealth();
}
setMode('idle');
resizeCanvas();
requestAnimationFrame(drawString);
