type Room = { slug: string; title: string; kind: string };
type Identity = { handle: string; display_name: string; kind: string; role: string };
type Message = {
  id: string;
  identity_handle: string;
  identity_display_name: string;
  body: string;
  kind: string;
  event_type?: string | null;
  created_at?: string | null;
};

import { renderMarkdown } from "./markdown";

const api = "/api/v1/buzz";
const HANDLE_KEY = "buzz.handle";
const HIDE_HB_KEY = "buzz.hideHeartbeats";

let currentSlug = "adh-ops";
let seen = new Set<string>();
let unread = new Map<string, number>();
let source: EventSource | null = null;
let identities: Identity[] = [];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function esc(s: string): string {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] || c);
}

function setStatus(text: string, live: boolean) {
  const el = $("status");
  el.textContent = text;
  el.className = `status ${live ? "live" : "off"}`;
}

async function j<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(api + path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

function currentHandle(): string {
  return $("identity").value || localStorage.getItem(HANDLE_KEY) || "nikd10x";
}

function hideHeartbeats(): boolean {
  return $("hide-hb").checked;
}

function renderRooms(rooms: Room[]) {
  const el = $("rooms");
  el.innerHTML = rooms
    .map((r) => {
      const n = unread.get(r.slug) || 0;
      const badge = n ? `<span class="unread">${n}</span>` : "";
      return `<div class="room ${r.slug === currentSlug ? "active" : ""}" data-slug="${esc(r.slug)}">
        <span># ${esc(r.slug)}</span>${badge}
      </div>`;
    })
    .join("");
  el.querySelectorAll<HTMLElement>(".room").forEach((n) =>
    n.addEventListener("click", () => openRoom(n.dataset.slug || "")),
  );
}

function renderIdentities() {
  const sel = $("identity");
  const keep = currentHandle();
  sel.innerHTML = identities
    .map((i) => `<option value="${esc(i.handle)}">${esc(i.handle)}</option>`)
    .join("");
  if (identities.some((i) => i.handle === keep)) sel.value = keep;
  else if (identities.some((i) => i.handle === "nikd10x")) sel.value = "nikd10x";
}

function messageHtml(m: Message): string {
  const when = m.created_at ? new Date(m.created_at).toLocaleTimeString() : "";
  const human = identities.find((i) => i.handle === m.identity_handle)?.kind === "human";
  const cls = ["msg", m.kind === "heartbeat" ? "heartbeat" : "", human ? "human" : ""].filter(Boolean).join(" ");
  const extra = m.event_type ? ` · ${esc(m.event_type)}` : "";
  return `<div class="${cls}" data-id="${esc(m.id)}">
    <div class="meta">${esc(m.identity_handle)} <span class="kind">${esc(m.kind)}${extra}</span> · ${esc(when)}</div>
    <div class="body">${renderMarkdown(m.body)}</div>
  </div>`;
}

function appendMessage(m: Message, notify: boolean) {
  if (!m.id || seen.has(m.id)) return;
  if (m.kind === "heartbeat" && hideHeartbeats()) {
    seen.add(m.id);
    return;
  }
  seen.add(m.id);
  const thread = $("thread");
  const stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  thread.insertAdjacentHTML("beforeend", messageHtml(m));
  if (stick) thread.scrollTop = thread.scrollHeight;
  if (notify && m.identity_handle !== currentHandle() && document.hidden && "Notification" in window) {
    if (Notification.permission === "granted") {
      new Notification(`Buzz #${currentSlug}`, { body: `${m.identity_handle}: ${m.body}` });
    }
  }
}

async function loadMessages() {
  const room = await j<Room>(`/rooms/${encodeURIComponent(currentSlug)}`);
  $("title").textContent = room.title;
  $("subtitle").textContent = `#${room.slug}`;
  $("body").setAttribute("placeholder", `Message #${room.slug}`);
  const msgs = await j<Message[]>(`/rooms/${encodeURIComponent(currentSlug)}/messages`);
  seen = new Set();
  const thread = $("thread");
  const visible = hideHeartbeats() ? msgs.filter((m) => m.kind !== "heartbeat") : msgs;
  thread.innerHTML = visible.length ? visible.map(messageHtml).join("") : `<div class="empty">No messages yet.</div>`;
  visible.forEach((m) => seen.add(m.id));
  thread.scrollTop = thread.scrollHeight;
}

let reconnectTimer: number | null = null;
let reconnectDelay = 1500;
const MAX_RECONNECT_DELAY = 15000;

function connectStream() {
  source?.close();
  source = null;
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  source = new EventSource(`${api}/rooms/${encodeURIComponent(currentSlug)}/stream`);
  source.onopen = () => {
    setStatus("live", true);
    reconnectDelay = 1500;
  };
  source.onerror = () => {
    if (reconnectTimer !== null) return;
    setStatus("reconnecting", false);
    source?.close();
    source = null;
    const delay = reconnectDelay;
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connectStream();
    }, delay);
  };
  source.onmessage = (ev) => {
    setStatus("live", true);
    reconnectDelay = 1500;
    try {
      const data = JSON.parse(ev.data) as Message & { type?: string };
      if (data.type === "ping" || data.type === "subscribed") return;
      if (data.id) appendMessage(data, true);
    } catch {
      /* ignore keepalives */
    }
  };
}

async function openRoom(slug: string) {
  if (!slug) return;
  currentSlug = slug;
  unread.set(slug, 0);
  const rooms = await j<Room[]>("/rooms");
  renderRooms(rooms);
  await loadMessages();
  connectStream();
}

async function boot() {
  $("hide-hb").checked = localStorage.getItem(HIDE_HB_KEY) === "1";
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => undefined);
  }
  identities = await j<Identity[]>("/identities");
  renderIdentities();
  const rooms = await j<Room[]>("/rooms");
  renderRooms(rooms);
  await openRoom(currentSlug);
}

$("identity").addEventListener("change", () => {
  localStorage.setItem(HANDLE_KEY, currentHandle());
});
$("hide-hb").addEventListener("change", () => {
  localStorage.setItem(HIDE_HB_KEY, hideHeartbeats() ? "1" : "0");
  loadMessages().catch((err) => console.error(err));
});
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = $("body").value.trim();
  if (!body) return;
  $("body").value = "";
  const posted = await j<Message>(`/rooms/${encodeURIComponent(currentSlug)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identity_handle: currentHandle(), body }),
  });
  appendMessage(posted, false);
});
$("new-room").addEventListener("submit", async (e) => {
  e.preventDefault();
  const slug = $("new-slug").value.trim().toLowerCase().replace(/\s+/g, "-");
  if (!slug) return;
  await j<Room>("/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug, title: slug, kind: "general" }),
  });
  $("new-slug").value = "";
  await openRoom(slug);
});

boot().catch((err) => {
  setStatus("offline", false);
  $("thread").innerHTML = `<div class="empty">Buzz backend is offline. From adh-iac-local run <code>make buzz-up</code>.<br/><br/>${esc(String(err))}</div>`;
});
