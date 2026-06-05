const state = {
  rooms: [],
  selectedRoomId: localStorage.getItem("reasonix-selected-room") || "",
  room: null,
  composerMode: "run",
  roomFilter: "",
  stream: null,
  streamConnected: false,
  roomsTimer: null,
  toastTimer: null,
};

const roomsList = document.getElementById("roomsList");
const roomCountLabel = document.getElementById("roomCountLabel");
const workspaceLabel = document.getElementById("workspaceLabel");
const roomFilterInput = document.getElementById("roomFilterInput");
const roomTitle = document.getElementById("roomTitle");
const roomSubtitle = document.getElementById("roomSubtitle");
const roomStatusPill = document.getElementById("roomStatusPill");
const streamPill = document.getElementById("streamPill");
const connectionLabel = document.getElementById("connectionLabel");
const roomHeroAvatar = document.getElementById("roomHeroAvatar");
const messagesPane = document.getElementById("messagesPane");
const quickFactsStrip = document.getElementById("quickFactsStrip");
const stateFacts = document.getElementById("stateFacts");
const jobsList = document.getElementById("jobsList");
const eventsList = document.getElementById("eventsList");
const transcriptsList = document.getElementById("transcriptsList");
const artifactsList = document.getElementById("artifactsList");
const toast = document.getElementById("toast");

const runForm = document.getElementById("runForm");
const reviewForm = document.getElementById("reviewForm");
const postForm = document.getElementById("postForm");

const refreshRoomsButton = document.getElementById("refreshRoomsButton");
const refreshRoomButton = document.getElementById("refreshRoomButton");
const newRoomButton = document.getElementById("newRoomButton");

const modeButtons = Array.from(document.querySelectorAll(".mode-chip"));

init().catch((error) => {
  console.error(error);
  notify(error.message || "Failed to initialize");
});

async function init() {
  bindEvents();
  renderStreamState();
  await refreshRooms();
  if (state.selectedRoomId) {
    await selectRoom(state.selectedRoomId);
  } else {
    renderRoom(null);
  }
  state.roomsTimer = window.setInterval(refreshRooms, 4000);
}

function bindEvents() {
  refreshRoomsButton.addEventListener("click", () => refreshRooms(true));
  refreshRoomButton.addEventListener("click", () => {
    if (state.selectedRoomId) {
      refreshRoom(state.selectedRoomId, true);
    }
  });
  newRoomButton.addEventListener("click", () => {
    state.selectedRoomId = "";
    localStorage.removeItem("reasonix-selected-room");
    disconnectStream();
    renderRoom(null);
    notify("Composer reset. The next run can create a new room.");
  });
  roomFilterInput.addEventListener("input", () => {
    state.roomFilter = roomFilterInput.value.trim().toLowerCase();
    renderRooms();
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => setComposerMode(button.dataset.mode || "run"));
  });

  runForm.addEventListener("submit", submitRunForm);
  reviewForm.addEventListener("submit", submitReviewForm);
  postForm.addEventListener("submit", submitPostForm);
}

async function refreshRooms(silent = false) {
  const payload = await fetchJson("/api/rooms");
  state.rooms = payload.rooms || [];
  roomCountLabel.textContent = `${state.rooms.length} rooms`;
  workspaceLabel.textContent = shortenPath(payload.config?.workspace_root || "");
  renderRooms();

  if (!state.selectedRoomId && state.rooms.length > 0) {
    await selectRoom(state.rooms[0].room_id, { preserveScroll: true, silent: true });
  }

  if (!silent && state.selectedRoomId && !state.rooms.some((room) => room.room_id === state.selectedRoomId)) {
    state.selectedRoomId = "";
    disconnectStream();
    renderRoom(null);
  }
}

async function selectRoom(roomId, options = {}) {
  if (!roomId) {
    renderRoom(null);
    return;
  }
  state.selectedRoomId = roomId;
  localStorage.setItem("reasonix-selected-room", roomId);
  renderRooms();
  await refreshRoom(roomId, false, options.preserveScroll);
  connectStream(roomId);
  if (!options.silent) {
    notify(`Switched to ${roomId}`);
  }
}

async function refreshRoom(roomId, announce = false, preserveScroll = false) {
  const wasAtBottom = preserveScroll ? null : isNearBottom(messagesPane);
  const payload = await fetchJson(`/api/rooms/${encodeURIComponent(roomId)}`);
  state.room = payload;
  renderRoom(payload);
  if (wasAtBottom) {
    messagesPane.scrollTop = messagesPane.scrollHeight;
  }
  if (announce) {
    notify(`Synced ${roomId}`);
  }
}

function renderRooms() {
  roomsList.innerHTML = "";
  const visibleRooms = state.rooms.filter((entry) => {
    if (!state.roomFilter) return true;
    const haystack = `${entry.title || ""}\n${entry.room_id || ""}\n${entry.latest_message_excerpt || ""}`.toLowerCase();
    return haystack.includes(state.roomFilter);
  });
  if (visibleRooms.length === 0) {
    roomsList.appendChild(buildEmpty(state.roomFilter ? "No matching rooms." : "No rooms yet. Launch a run to create the first one."));
    return;
  }
  visibleRooms.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `room-card${entry.room_id === state.selectedRoomId ? " active" : ""}`;
    button.addEventListener("click", () => selectRoom(entry.room_id));
    button.innerHTML = `
      <div class="room-card-leading">
        <div class="room-avatar">${escapeHtml(buildAvatarText(entry.title || entry.room_id))}</div>
        <div class="room-card-copy">
          <div class="room-title-row">
            <span class="room-title">${escapeHtml(entry.title || entry.room_id)}</span>
            <span class="status-pill ${statusClass(entry.status)}">${escapeHtml(entry.status || "open")}</span>
          </div>
          <div class="room-preview">${escapeHtml(entry.latest_message_excerpt || "No messages yet.")}</div>
        </div>
      </div>
      <div class="meta-row">
        <span class="room-badge"><span class="room-badge-dot"></span>round ${entry.round ?? 0}</span>
        <span>${formatAgo(entry.updated_at)}</span>
      </div>
    `;
    roomsList.appendChild(button);
  });
}

function renderRoom(payload) {
  if (!payload) {
    roomTitle.textContent = "Select or start a room";
    roomSubtitle.textContent = "The timeline updates as room files and Reasonix transcripts change.";
    roomHeroAvatar.textContent = "RC";
    roomStatusPill.textContent = "idle";
    roomStatusPill.className = "status-pill neutral";
    quickFactsStrip.innerHTML = "";
    quickFactsStrip.appendChild(buildEmpty("No room selected."));
    messagesPane.innerHTML = "";
    messagesPane.appendChild(buildEmpty("No room selected."));
    stateFacts.innerHTML = "";
    jobsList.innerHTML = "";
    jobsList.appendChild(buildEmpty("No jobs yet."));
    eventsList.innerHTML = "";
    eventsList.appendChild(buildEmpty("No events yet."));
    transcriptsList.innerHTML = "";
    transcriptsList.appendChild(buildEmpty("No transcripts yet."));
    artifactsList.innerHTML = "";
    artifactsList.appendChild(buildEmpty("No artifacts yet."));
    return;
  }

  const roomInfo = payload.room || {};
  roomTitle.textContent = roomInfo.title || roomInfo.room_id || state.selectedRoomId;
  roomSubtitle.textContent = `${payload.messages?.length || 0} messages, ${payload.events?.length || 0} events, ${payload.jobs?.length || 0} jobs`;
  roomHeroAvatar.textContent = buildAvatarText(roomInfo.title || roomInfo.room_id || "RC");
  roomStatusPill.textContent = roomInfo.status || "open";
  roomStatusPill.className = `status-pill ${statusClass(roomInfo.status)}`;

  renderQuickFacts(roomInfo, payload);
  renderMessages(payload.messages || []);
  renderStateFacts(roomInfo, payload.paths || {});
  renderJobs(payload.jobs || []);
  renderEvents(payload.events || []);
  renderTranscripts(payload.transcripts || []);
  renderArtifacts(payload.artifacts || []);
}

function renderQuickFacts(roomInfo, payload) {
  const chips = [
    ["Room", roomInfo.room_id || "pending"],
    ["Round", roomInfo.round ?? 0],
    ["Artifacts", payload.artifacts?.length || 0],
    ["Transcripts", payload.transcripts?.length || 0],
  ];
  quickFactsStrip.innerHTML = "";
  chips.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "quick-chip";
    chip.innerHTML = `
      <span class="quick-chip-label">${escapeHtml(String(label))}</span>
      <span class="quick-chip-value">${escapeHtml(String(value))}</span>
    `;
    quickFactsStrip.appendChild(chip);
  });
}

function renderMessages(messages) {
  messagesPane.innerHTML = "";
  if (messages.length === 0) {
    messagesPane.appendChild(buildEmpty("No messages yet."));
    return;
  }
  messages.forEach((message) => {
    const article = document.createElement("article");
    article.className = `message-card role-${message.role || "user"}`;
    article.innerHTML = `
      <div class="message-row role-${escapeHtml(message.role || "user")}">
        <div class="message-avatar">${escapeHtml(buildRoleAvatar(message))}</div>
        <div class="message-body">
          <div class="message-header">
            <div>
              <div class="message-role">${escapeHtml(message.role || "message")} · ${escapeHtml(message.agent_id || "agent")}</div>
              <div class="timeline-meta">${escapeHtml(message.type || "note")} · ${formatAgo(message.timestamp)}</div>
            </div>
            <span class="status-pill neutral">${escapeHtml(message.id || "")}</span>
          </div>
          <div class="message-bubble">
            <div class="message-content">${escapeHtml(formatMessageContent(message))}</div>
          </div>
        </div>
      </div>
    `;
    messagesPane.appendChild(article);
  });
}

function renderStateFacts(roomInfo, paths) {
  const facts = [
    ["room_id", roomInfo.room_id],
    ["status", roomInfo.status],
    ["round", roomInfo.round],
    ["updated", roomInfo.updated_at],
    ["artifact", roomInfo.latest_artifact_path],
    ["root", paths.root],
  ];
  stateFacts.innerHTML = "";
  facts.forEach(([label, value]) => {
    if (!value && value !== 0) return;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = label === "root" || label === "artifact" ? shortenPath(String(value)) : String(value);
    stateFacts.append(dt, dd);
  });
}

function renderJobs(jobs) {
  jobsList.innerHTML = "";
  if (jobs.length === 0) {
    jobsList.appendChild(buildEmpty("No jobs yet."));
    return;
  }
  jobs.forEach((job) => {
    const section = document.createElement("section");
    section.className = "job-card";
    section.innerHTML = `
      <div class="job-header">
        <strong>${escapeHtml(job.title || job.job_id)}</strong>
        <span class="status-pill ${statusClass(job.status)}">${escapeHtml(job.status || "queued")}</span>
      </div>
      <div class="timeline-meta">${escapeHtml(job.job_id || "")} · ${formatAgo(job.updated_at)}</div>
      <div class="job-output">${escapeHtml(truncateForUi((job.stderr || job.stdout || job.prompt || "").trim() || "Waiting for output.", 1000))}</div>
    `;
    jobsList.appendChild(section);
  });
}

function renderEvents(events) {
  eventsList.innerHTML = "";
  if (events.length === 0) {
    eventsList.appendChild(buildEmpty("No events yet."));
    return;
  }
  events.slice().reverse().forEach((event) => {
    const section = document.createElement("section");
    section.className = "event-card";
    section.innerHTML = `
      <div class="event-header">
        <strong>${escapeHtml(event.event || "event")}</strong>
        <span class="timeline-meta">${formatAgo(event.timestamp)}</span>
      </div>
      <div class="event-content">${escapeHtml(summarizeEvent(event))}</div>
    `;
    eventsList.appendChild(section);
  });
}

function renderTranscripts(transcripts) {
  transcriptsList.innerHTML = "";
  if (transcripts.length === 0) {
    transcriptsList.appendChild(buildEmpty("No transcripts yet."));
    return;
  }
  transcripts.forEach((transcript) => {
    const section = document.createElement("section");
    section.className = "transcript-card";
    const entries = (transcript.entries || [])
      .map((entry) => {
        if (entry.kind === "json") {
          return `<div class="transcript-entry"><strong>${escapeHtml(entry.label || "entry")}</strong><br />${escapeHtml(summarizeTranscriptData(entry.data))}</div>`;
        }
        return `<div class="transcript-entry">${escapeHtml(truncateForUi(entry.text || "", 360))}</div>`;
      })
      .join("");
    section.innerHTML = `
      <div class="transcript-header">
        <strong>${escapeHtml(transcript.name)}</strong>
        <span class="timeline-meta">${formatAgo(transcript.modified_at)}</span>
      </div>
      ${entries || `<div class="transcript-entry">No transcript entries yet.</div>`}
    `;
    transcriptsList.appendChild(section);
  });
}

function renderArtifacts(artifacts) {
  artifactsList.innerHTML = "";
  if (artifacts.length === 0) {
    artifactsList.appendChild(buildEmpty("No artifacts yet."));
    return;
  }
  artifacts.forEach((artifact) => {
    const section = document.createElement("section");
    section.className = "artifact-card";
    section.innerHTML = `
      <div class="artifact-header">
        <strong>${escapeHtml(artifact.name)}</strong>
        <span class="timeline-meta">${formatAgo(artifact.modified_at)}</span>
      </div>
      <div class="artifact-excerpt">${escapeHtml(truncateForUi(artifact.excerpt || artifact.path || "", 900))}</div>
    `;
    artifactsList.appendChild(section);
  });
}

function setComposerMode(mode) {
  state.composerMode = mode;
  modeButtons.forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
  runForm.classList.toggle("hidden", mode !== "run");
  reviewForm.classList.toggle("hidden", mode !== "review");
  postForm.classList.toggle("hidden", mode !== "post");
}

async function submitRunForm(event) {
  event.preventDefault();
  const roomId = state.selectedRoomId || slugify(document.getElementById("runTitle").value || document.getElementById("runPrompt").value || "reasonix-room");
  const body = {
    prompt: document.getElementById("runPrompt").value.trim(),
    title: document.getElementById("runTitle").value.trim(),
    reasonix_model: document.getElementById("runReasonixModel").value.trim(),
    subagent_model: document.getElementById("runSubagentModel").value.trim(),
    effort: document.getElementById("runEffort").value.trim(),
    skill_names: splitList(document.getElementById("runSkillNames").value),
    skill_brief: document.getElementById("runSkillBrief").value.trim(),
    image_brief: document.getElementById("runImageBrief").value.trim(),
    skip_self_review: document.getElementById("runSkipReview").checked,
  };
  if (!body.prompt) {
    notify("Prompt is required.");
    return;
  }
  if (!state.selectedRoomId) {
    state.selectedRoomId = roomId;
    localStorage.setItem("reasonix-selected-room", roomId);
  }
  await postJson(`/api/rooms/${encodeURIComponent(state.selectedRoomId)}/reasonix`, body);
  await refreshRooms(true);
  await selectRoom(state.selectedRoomId, { preserveScroll: true, silent: true });
  notify(`Launched room run for ${state.selectedRoomId}`);
}

async function submitReviewForm(event) {
  event.preventDefault();
  if (!state.selectedRoomId) {
    notify("Select a room first.");
    return;
  }
  const body = {
    status: document.getElementById("reviewStatus").value,
    reviewer_id: document.getElementById("reviewerId").value.trim(),
    feedback: document.getElementById("reviewFeedback").value.trim(),
  };
  if (!body.feedback) {
    notify("Feedback is required.");
    return;
  }
  await postJson(`/api/rooms/${encodeURIComponent(state.selectedRoomId)}/review`, body);
  await refreshRoom(state.selectedRoomId, true, true);
  notify("Review recorded.");
}

async function submitPostForm(event) {
  event.preventDefault();
  if (!state.selectedRoomId) {
    notify("Select a room first.");
    return;
  }
  const body = {
    role: document.getElementById("postRole").value,
    agent_id: document.getElementById("postAgentId").value.trim(),
    message_type: document.getElementById("postMessageType").value.trim(),
    content: document.getElementById("postContent").value.trim(),
  };
  if (!body.content) {
    notify("Content is required.");
    return;
  }
  await postJson(`/api/rooms/${encodeURIComponent(state.selectedRoomId)}/post`, body);
  await refreshRoom(state.selectedRoomId, true, true);
  notify("Message posted.");
}

function connectStream(roomId) {
  disconnectStream();
  const source = new EventSource(`/api/rooms/${encodeURIComponent(roomId)}/stream`);
  state.streamConnected = true;
  renderStreamState();
  source.addEventListener("sync", async () => {
    if (!state.selectedRoomId || state.selectedRoomId !== roomId) return;
    await refreshRoom(roomId, false, false);
    await refreshRooms(true);
  });
  source.onerror = () => {
    source.close();
    state.streamConnected = false;
    renderStreamState();
    if (state.selectedRoomId === roomId) {
      window.setTimeout(() => connectStream(roomId), 1500);
    }
  };
  state.stream = source;
}

function disconnectStream() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  state.streamConnected = false;
  renderStreamState();
}

function renderStreamState() {
  if (!state.selectedRoomId) {
    streamPill.textContent = "idle";
    streamPill.className = "status-pill neutral";
    connectionLabel.textContent = "Realtime Room Feed";
    return;
  }
  streamPill.textContent = state.streamConnected ? "live" : "reconnecting";
  streamPill.className = `status-pill ${state.streamConnected ? "success" : "warning"}`;
  connectionLabel.textContent = state.streamConnected ? "Realtime Room Feed" : "Reconnecting Room Feed";
}

function buildEmpty(text) {
  const div = document.createElement("div");
  div.className = "room-preview";
  div.textContent = text;
  return div;
}

function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (["succeeded", "accepted", "needs-codex-review", "reasonix-ready"].includes(value)) return "success";
  if (["running", "queued", "reasonix-running", "needs-review", "needs-rework"].includes(value)) return "info";
  if (["failed", "reasonix-failed", "reasonix-self-review-failed", "rejected"].includes(value)) return "danger";
  if (["warning"].includes(value)) return "warning";
  return "neutral";
}

function splitList(value) {
  return value
    .split(/[,\\n]/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function slugify(value) {
  return `reasonix-${String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "")}` || "reasonix-room";
}

function isNearBottom(element) {
  return element.scrollHeight - element.scrollTop - element.clientHeight < 80;
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function notify(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 3200);
}

function formatAgo(value) {
  if (!value) return "just now";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return String(value);
  const delta = Math.round((Date.now() - timestamp) / 1000);
  if (delta < 8) return "just now";
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h ago`;
  return `${Math.round(delta / 86400)}d ago`;
}

function compactObject(value) {
  if (!value) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatMessageContent(message) {
  const base = String(message.content || "");
  if (message.role === "system") return truncateForUi(base, 2400);
  if (message.role === "writer") return truncateForUi(base, 2200);
  return truncateForUi(base, 900);
}

function truncateForUi(text, limit) {
  if (!text || text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 42)).trimEnd()}\n\n[truncated in UI]`;
}

function summarizeEvent(event) {
  const keys = ["phase", "model", "returncode", "transcript_path", "artifact_path", "prompt_path"];
  const lines = [];
  keys.forEach((key) => {
    if (event[key] !== undefined && event[key] !== null && event[key] !== "") {
      const value = key.endsWith("_path") ? shortenPath(String(event[key])) : String(event[key]);
      lines.push(`${key}: ${value}`);
    }
  });
  if (lines.length === 0) {
    return truncateForUi(compactObject(event), 500);
  }
  return lines.join("\n");
}

function summarizeTranscriptData(data) {
  const pieces = [];
  if (data.role) pieces.push(`role: ${data.role}`);
  if (data.type) pieces.push(`type: ${data.type}`);
  if (data.event) pieces.push(`event: ${data.event}`);
  if (data.tool) pieces.push(`tool: ${data.tool}`);
  if (data.turn !== undefined) pieces.push(`turn: ${data.turn}`);
  if (data.content) pieces.push(`content: ${truncateForUi(String(data.content), 260)}`);
  if (data.meta?.model) pieces.push(`model: ${data.meta.model}`);
  if (pieces.length === 0) {
    return truncateForUi(compactObject(data), 320);
  }
  return pieces.join("\n");
}

function shortenPath(path) {
  if (!path) return "Workspace";
  return path.length > 42 ? `...${path.slice(-39)}` : path;
}

function buildAvatarText(value) {
  const words = String(value || "")
    .split(/[^A-Za-z0-9]+/g)
    .filter(Boolean);
  if (words.length === 0) return "RC";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

function buildRoleAvatar(message) {
  const role = String(message.role || "").toLowerCase();
  if (role === "writer") return "RX";
  if (role === "reviewer") return "CR";
  if (role === "system") return "SYS";
  if (role === "user") return "YOU";
  return buildAvatarText(message.agent_id || role || "AG");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
