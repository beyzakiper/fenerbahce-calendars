// Landing page: renders one card per feed from data.json. No tracking, no third-party requests.
"use strict";

const ALARM_LABELS = { 0: "Yok", 30: "30 dk önce", 60: "1 saat önce" };
const dayFmt = new Intl.DateTimeFormat("tr-TR", { weekday: "long", day: "numeric", month: "long" });
const shortDayFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", weekday: "short" });
const timeFmt = new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit", timeZoneName: "short" });

function feedFile(feed, minutes) {
  return minutes === (feed.alarm_minutes || 0) ? `${feed.key}.ics` : `${feed.key}-alarm-${minutes}.ics`;
}

function urls(file) {
  const https = new URL(file, location.href);
  const webcal = "webcal://" + https.host + https.pathname;
  return {
    https: https.href,
    webcal,
    google: "https://calendar.google.com/calendar/render?cid=" + encodeURIComponent(webcal),
  };
}

// All-day events carry a plain date ("2026-10-11"); keep them on that calendar day in any time zone.
function parseStart(match) {
  if (match.all_day) {
    const [y, m, d] = match.start.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(match.start);
}

function describeWhen(match) {
  const start = parseStart(match);
  const day = dayFmt.format(start);
  return match.all_day ? day : `${day} · ${timeFmt.format(start)}`;
}

function countdownText(match) {
  if (match.all_day) return "";
  const ms = parseStart(match) - Date.now();
  if (ms <= 0) return "Maç başladı";
  const mins = Math.floor(ms / 60000);
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  if (d > 0) return `${d} gün ${h} saat kaldı`;
  if (h > 0) return `${h} saat ${m} dk kaldı`;
  return `${m} dk kaldı`;
}

function upcoming(feed) {
  const now = Date.now();
  return feed.upcoming.filter((m) => {
    const start = parseStart(m).getTime();
    return m.all_day ? start + 86400000 > now : start + 3 * 3600000 > now;
  });
}

// Team cards already show the sport emoji, so drop it from match titles there (the combined card keeps it).
function cardTitle(feed, match) {
  return feed.sport && match.title.startsWith(feed.emoji) ? match.title.slice(feed.emoji.length).trim() : match.title;
}

function renderCard(feed, tpl) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.id = feed.key;
  node.style.setProperty("--team", feed.color);
  node.querySelector(".emoji").textContent = feed.emoji;
  node.querySelector(".name").textContent = feed.calendar_name;
  node.querySelector(".count").textContent = `${feed.match_count} maç`;

  const list = upcoming(feed);
  const next = list[0];
  const title = node.querySelector(".next-title");
  const meta = node.querySelector(".next-meta");
  const countdown = node.querySelector(".countdown");
  if (next) {
    title.textContent = cardTitle(feed, next);
    meta.textContent = [describeWhen(next), [next.competition, next.round].filter(Boolean).join(" · ")].join(" — ");
    countdown.textContent = countdownText(next);
    countdown.dataset.start = next.all_day ? "" : next.start;
  } else {
    title.textContent = "Açıklanmış maç yok";
    meta.textContent = "Fikstür açıklanınca burada görünecek.";
  }
  const later = node.querySelector(".later");
  for (const m of list.slice(1, 4)) {
    const li = document.createElement("li");
    const a = document.createElement("span");
    const b = document.createElement("span");
    a.textContent = cardTitle(feed, m);
    b.textContent = shortDayFmt.format(parseStart(m));
    li.append(a, b);
    later.append(li);
  }

  const seg = node.querySelector(".seg");
  const apple = node.querySelector(".apple");
  const google = node.querySelector(".google");
  const ics = node.querySelector(".ics");
  const copy = node.querySelector(".copy");
  const setLinks = (minutes) => {
    const u = urls(feedFile(feed, minutes));
    apple.href = u.webcal;
    google.href = u.google;
    ics.href = u.https;
    ics.setAttribute("download", "");
    copy.dataset.url = u.https;
  };
  const current = feed.alarm_minutes || 0;
  for (const minutes of feed.alert_variants) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `alarm-${feed.key}`;
    input.value = String(minutes);
    input.checked = minutes === current;
    input.addEventListener("change", () => setLinks(minutes));
    const span = document.createElement("span");
    span.textContent = ALARM_LABELS[minutes] || `${minutes} dk önce`;
    label.append(input, span);
    seg.append(label);
  }
  setLinks(current);

  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(copy.dataset.url);
      copy.textContent = "Kopyalandı";
    } catch {
      window.prompt("Takvim bağlantısı:", copy.dataset.url);
    }
    copy.classList.add("done");
    setTimeout(() => { copy.textContent = "Bağlantıyı kopyala"; copy.classList.remove("done"); }, 2000);
  });
  return node;
}

function tickCountdowns() {
  for (const el of document.querySelectorAll(".countdown[data-start]")) {
    if (el.dataset.start) el.textContent = countdownText({ start: el.dataset.start, all_day: false });
  }
}

function highlightTarget() {
  document.querySelectorAll(".card.target").forEach((c) => c.classList.remove("target"));
  const id = decodeURIComponent(location.hash.slice(1));
  const el = id && document.getElementById(id);
  if (el && el.classList.contains("card")) {
    el.classList.add("target");
    el.scrollIntoView({ block: "center" });
  }
}

async function main() {
  const tpl = document.getElementById("card-tpl");
  const teams = document.getElementById("teams");
  try {
    const res = await fetch("data.json", { cache: "no-cache" });
    const data = await res.json();
    for (const feed of data.teams) teams.append(renderCard(feed, tpl));
    for (const feed of data.combined || []) document.getElementById("combined").append(renderCard(feed, tpl));
    const generated = new Date(data.generated);
    document.getElementById("updated").textContent =
      "Son güncelleme: " + dayFmt.format(generated) + " " + timeFmt.format(generated);
  } catch {
    teams.textContent = "Takvim bilgisi yüklenemedi. Sayfayı yenilemeyi deneyin.";
  }
  highlightTarget();
  setInterval(tickCountdowns, 30000);
}

window.addEventListener("hashchange", highlightTarget);
main();
