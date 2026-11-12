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
  payload?: {
    status?: string;
    task_id?: string;
    task_room?: string;
    hub_room_slug?: string;
    traj_mirror?: boolean;
  } | null;
};
type MessagePage = { items: Message[]; has_more: boolean };
type Task = {
  task_id: string;
  title: string;
  task_room_slug: string;
  hub_room_slug?: string;
  state: string;
  archived_at?: string | null;
};
type RosterEntry = {
  identity_handle: string;
  identity_display_name?: string;
  member_role?: string;
  presence?: string | null;
};

import { renderMarkdown } from "./markdown";

const api = "/api/v1/buzz";
const HANDLE_KEY = "buzz.handle";
const HIDE_HB_KEY = "buzz.hideHeartbeats";
const PAGE_SIZE = 20;

let currentSlug = "adh-ops";
let seen = new Set<string>();
let unread = new Map<string, number>();
let source: EventSource | null = null;
let identities: Identity[] = [];
let oldestId: string | null = null;
let hasMore = false;
let loadingOlder = false;
let activeTasks: Task[] = [];
let archivedTasks: Task[] = [];

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
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function currentHandle(): string {
  return $("identity").value || localStorage.getItem(HANDLE_KEY) || "nikd10x";
}

function hideHeartbeats(): boolean {
  return $("hide-hb").checked;
}

function nearBottom(thread: HTMLElement): boolean {
  return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
}

function updateJumpBtn() {
  const btn = document.getElementById("jump-latest");
  if (!btn) return;
  const thread = $("thread");
  btn.classList.toggle("hidden", nearBottom(thread));
}

let cachedRooms: Room[] = [];

/** E1: Dev posts on `#engg-<id>`; task home is often empty. Prefer engg when it exists. */
function enggSlugFor(taskIdOrRoom: string): string | null {
  let id = (taskIdOrRoom || "").trim();
  if (!id) return null;
  if (id.startsWith("task-")) id = id.slice("task-".length);
  if (id.startsWith("engg-")) id = id.slice("engg-".length);
  const slug = `engg-${id}`.toLowerCase();
  return cachedRooms.some((r) => r.slug === slug && r.kind === "engg") ? slug : null;
}

function collaborationSlug(taskRoom: string): string {
  return enggSlugFor(taskRoom) || taskRoom;
}

function renderRooms(rooms?: Room[]) {
  if (rooms) cachedRooms = rooms;
  const el = $("rooms");
  const hub = cachedRooms.filter((r) => r.kind === "ops" || r.kind === "general");
  // Tasks SSOT = activeTasks (do not require rooms list intersection — avoids stale sidebar).
  const liveTasks = activeTasks.filter((t) => !t.archived_at);
  const blocks: string[] = [];
  blocks.push(`<div class="side-label">Hub</div>`);
  blocks.push(
    hub
      .map((r) => {
        const n = unread.get(r.slug) || 0;
        const badge = n ? `<span class="unread">${n}</span>` : "";
        return `<div class="room ${r.slug === currentSlug ? "active" : ""}" data-slug="${esc(r.slug)}">
        <span># ${esc(r.slug)}</span>${badge}
      </div>`;
      })
      .join(""),
  );
  blocks.push(`<div class="side-label">Tasks</div>`);
  if (!liveTasks.length) {
    blocks.push(`<div class="empty-side">No active tasks</div>`);
  } else {
    blocks.push(
      liveTasks
        .map((t) => {
          const openSlug = collaborationSlug(t.task_room_slug);
          const n = unread.get(openSlug) || unread.get(t.task_room_slug) || 0;
          const badge = n ? `<span class="unread">${n}</span>` : "";
          const active =
            currentSlug === openSlug || currentSlug === t.task_room_slug ? "active" : "";
          return `<div class="room ${active}" data-slug="${esc(openSlug)}">
        <span># ${esc(t.task_id)}</span>${badge}
      </div>`;
        })
        .join(""),
    );
  }
  // E1 Dev collaboration floors — not the empty task home.
  const engg = cachedRooms.filter((r) => r.kind === "engg");
  blocks.push(`<div class="side-label">Engg</div>`);
  if (!engg.length) {
    blocks.push(`<div class="empty-side">No engg floors</div>`);
  } else {
    blocks.push(
      engg
        .map((r) => {
          const n = unread.get(r.slug) || 0;
          const badge = n ? `<span class="unread">${n}</span>` : "";
          return `<div class="room ${r.slug === currentSlug ? "active" : ""}" data-slug="${esc(r.slug)}">
        <span># ${esc(r.slug)}</span>${badge}
      </div>`;
        })
        .join(""),
    );
  }
  blocks.push(`<div class="side-label">Archived</div>`);
  if (!archivedTasks.length) {
    blocks.push(`<div class="empty-side">None</div>`);
  } else {
    blocks.push(
      archivedTasks
        .map((t) => {
          return `<div class="room archived ${t.task_room_slug === currentSlug ? "active" : ""}" data-slug="${esc(t.task_room_slug)}">
        <span># ${esc(t.task_id)}</span>
      </div>`;
        })
        .join(""),
    );
  }
  el.innerHTML = blocks.join("");
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
  const stick = nearBottom(thread);
  thread.insertAdjacentHTML("beforeend", messageHtml(m));
  if (stick) thread.scrollTop = thread.scrollHeight;
  updateJumpBtn();
  if (notify && m.identity_handle !== currentHandle() && document.hidden && "Notification" in window) {
    if (Notification.permission === "granted") {
      new Notification(`Buzz #${currentSlug}`, { body: `${m.identity_handle}: ${m.body}` });
    }
  }
}

function renderRoster(entries: RosterEntry[]) {
  const el = document.getElementById("roster");
  if (!el) return;
  if (!entries.length) {
    el.innerHTML = `<span class="roster-empty">No members yet</span>`;
    return;
  }
  el.innerHTML = entries
    .map((e) => {
      const online = !!(e.presence && e.presence !== "offline");
      const tip = online ? e.presence || "listening" : "offline / hired";
      return `<span class="roster-chip ${online ? "online" : ""}" title="${esc(tip)}">
        <span class="dot"></span>${esc(e.identity_handle)}
      </span>`;
    })
    .join("");
}

async function refreshRoster() {
  try {
    const entries = await j<RosterEntry[]>(`/rooms/${encodeURIComponent(currentSlug)}/roster`);
    renderRoster(entries);
  } catch {
    renderRoster([]);
  }
}

function maybeAutoSwitchToTask(payload: Message["payload"]) {
  const taskRoom = (payload?.task_room || "").trim();
  if (!taskRoom.startsWith("task-")) return;
  const openSlug = collaborationSlug(taskRoom);
  // F.15: never steal focus from another active task/engg floor.
  const onOtherTask =
    (currentSlug.startsWith("task-") || currentSlug.startsWith("engg-")) &&
    currentSlug !== taskRoom &&
    currentSlug !== openSlug;
  if (onOtherTask) {
    unread.set(openSlug, (unread.get(openSlug) || 0) + 1);
    refreshSidebar().catch(() => undefined);
    return;
  }
  // Auto-switch only when Lead is on a tenant hub (or already this task/engg).
  const hub =
    payload?.hub_room_slug ||
    activeTasks.find((t) => t.task_room_slug === taskRoom)?.hub_room_slug;
  if (
    currentSlug.endsWith("-ops") ||
    (hub && currentSlug === hub) ||
    currentSlug === taskRoom ||
    currentSlug === openSlug
  ) {
    if (currentSlug !== openSlug) {
      openRoom(openSlug).catch((err) => console.error(err));
    }
    return;
  }
  unread.set(openSlug, (unread.get(openSlug) || 0) + 1);
  refreshSidebar().catch(() => undefined);
}

async function loadMessages() {
  const room = await j<Room>(`/rooms/${encodeURIComponent(currentSlug)}`);
  $("title").textContent = room.title;
  $("subtitle").textContent = `#${room.slug}`;
  $("body").setAttribute("placeholder", `Message #${room.slug}`);
  await refreshRoster();
  const page = await j<MessagePage>(
    `/rooms/${encodeURIComponent(currentSlug)}/messages?limit=${PAGE_SIZE}`,
  );
  seen = new Set();
  const thread = $("thread");
  const visible = hideHeartbeats() ? page.items.filter((m) => m.kind !== "heartbeat") : page.items;
  hasMore = page.has_more;
  oldestId = visible.length ? visible[0].id : null;
  thread.innerHTML = visible.length
    ? `${hasMore ? `<div id="load-earlier" class="load-earlier">Scroll up for earlier</div>` : ""}${visible.map(messageHtml).join("")}`
    : `<div class="empty">No messages yet.</div>`;
  visible.forEach((m) => seen.add(m.id));
  thread.scrollTop = thread.scrollHeight;
  updateJumpBtn();
}

async function loadOlder() {
  if (!hasMore || !oldestId || loadingOlder) return;
  loadingOlder = true;
  const thread = $("thread");
  const prevHeight = thread.scrollHeight;
  try {
    const page = await j<MessagePage>(
      `/rooms/${encodeURIComponent(currentSlug)}/messages?limit=${PAGE_SIZE}&before_id=${encodeURIComponent(oldestId)}`,
    );
    const visible = hideHeartbeats() ? page.items.filter((m) => m.kind !== "heartbeat") : page.items;
    hasMore = page.has_more;
    if (visible.length) {
      oldestId = visible[0].id;
      const html = visible
        .filter((m) => !seen.has(m.id))
        .map((m) => {
          seen.add(m.id);
          return messageHtml(m);
        })
        .join("");
      const marker = document.getElementById("load-earlier");
      if (marker) marker.insertAdjacentHTML("afterend", html);
      else thread.insertAdjacentHTML("afterbegin", html);
      if (!hasMore) document.getElementById("load-earlier")?.remove();
      thread.scrollTop = thread.scrollHeight - prevHeight;
    } else {
      hasMore = false;
      document.getElementById("load-earlier")?.remove();
    }
  } finally {
    loadingOlder = false;
  }
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
      const data = JSON.parse(ev.data) as Message & {
        type?: string;
        payload?: { status?: string };
      };
      if (data.type === "ping" || data.type === "subscribed") return;
      if (data.id) appendMessage(data, true);
      const status = data.payload?.status || "";
      if (status === "task_opened") {
        refreshSidebar()
          .then(() => maybeAutoSwitchToTask(data.payload || null))
          .catch(() => undefined);
      } else if (status === "task_archived" || status === "task_deleted") {
        refreshSidebar().catch(() => undefined);
      } else if (status === "traj_mirror") {
        refreshSidebar().catch(() => undefined);
      }
    } catch {
      /* ignore keepalives */
    }
  };
}

async function refreshTasks() {
  try {
    // RealWorld guinea pig default; empty list is fine for adh-ops-only.
    activeTasks = await j<Task[]>("/tenants/realworld/tasks");
    const all = await j<Task[]>("/tenants/realworld/tasks?include_archived=true");
    archivedTasks = all.filter((t) => !!t.archived_at);
  } catch {
    activeTasks = [];
    archivedTasks = [];
  }
  renderRooms();
}

async function refreshSidebar() {
  await refreshTasks();
  try {
    const rooms = (await j<Room[]>("/rooms")).filter((r) => r.kind !== "memory");
    renderRooms(rooms);
  } catch {
    /* keep cached rooms */
  }
}

async function openRoom(slug: string) {
  if (!slug) return;
  currentSlug = slug;
  unread.set(slug, 0);
  await refreshTasks();
  const rooms = (await j<Room[]>("/rooms")).filter((r) => r.kind !== "memory");
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
  await refreshSidebar();
  await openRoom(currentSlug);
  // Keep Tasks list + listening strip fresh while army works.
  window.setInterval(() => {
    refreshSidebar().catch(() => undefined);
    refreshRoster().catch(() => undefined);
  }, 8000);
}

$("identity").addEventListener("change", () => {
  localStorage.setItem(HANDLE_KEY, currentHandle());
});
$("hide-hb").addEventListener("change", () => {
  localStorage.setItem(HIDE_HB_KEY, hideHeartbeats() ? "1" : "0");
  loadMessages().catch((err) => console.error(err));
});
$("thread").addEventListener("scroll", () => {
  const thread = $("thread");
  updateJumpBtn();
  if (thread.scrollTop < 40) loadOlder().catch((err) => console.error(err));
});
document.getElementById("jump-latest")?.addEventListener("click", () => {
  const thread = $("thread");
  thread.scrollTop = thread.scrollHeight;
  updateJumpBtn();
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
