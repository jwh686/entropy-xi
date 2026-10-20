/* 熵锋奕 · Entropy XI — single-page app (no build step). */
(() => {
  "use strict";

  // ------------------------------------------------------------------ state & utils
  const S = { lang: "zh", meta: null, pred: null, results: null, perf: null, teams: {}, charts: [], teamCache: {} };
  try { S.lang = localStorage.getItem("exi-lang") || "zh"; } catch (e) { /* storage unavailable */ }
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const t = (k, vars) => {
    let s = (I18N[S.lang] && I18N[S.lang][k]) || I18N.zh[k] || k;
    if (vars) Object.entries(vars).forEach(([a, b]) => (s = s.replace(`{${a}}`, b)));
    return s;
  };
  const pct = (x, d = 1) => (x == null || isNaN(x) ? "—" : (x * 100).toFixed(d) + "%");
  const num = (x, d = 2) => (x == null || isNaN(x) ? "—" : Number(x).toFixed(d));
  const signed = (x, d = 2) => (x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + Number(x).toFixed(d));
  const cls = (x) => (x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");
  const ZH_LOCALE = () => (S.lang === "zh" ? "zh-CN" : "en-GB");
  const fmtTime = (iso, opts) => new Intl.DateTimeFormat(ZH_LOCALE(), Object.assign({ timeZone: "Asia/Shanghai" }, opts)).format(new Date(iso));
  const kickoff = (iso) => fmtTime(iso, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  const hhmm = (iso) => fmtTime(iso, { hour: "2-digit", minute: "2-digit", hour12: false });

  async function getJSON(path) {
    const r = await fetch(path + "?v=" + Date.now().toString(36).slice(0, -3), { cache: "no-cache" });
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }

  // ------------------------------------------------------------------ naming helpers
  const comp = (slug) => {
    const c = S.meta && S.meta.competitions[slug];
    if (!c) return slug;
    return S.lang === "zh" ? c.zh : c.en;
  };
  const team = (key, fallback) => {
    const tm = S.teams[key];
    if (!tm) return fallback || key;
    return (S.lang === "zh" && tm.zh) || tm.name || fallback || key;
  };
  function lum(hex) {
    if (!hex || hex.length < 6) return 0;
    const n = parseInt(hex.slice(0, 6), 16);
    return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  }
  function badge(key, name) {
    const tm = S.teams[key] || {};
    let ab = (tm.abbr || (name || key).replace(/[^A-Za-z]/g, "").slice(0, 3) || "?").toUpperCase().slice(0, 4);
    if (S.lang === "zh" && tm.zh) ab = tm.zh.slice(0, 2);
    const col = tm.color && lum(tm.color) > 0.12 ? "#" + tm.color.slice(0, 6) : "#2f6bff";
    return `<span class="badge" style="--c:${col}">${esc(ab)}</span>`;
  }
  const stars = (n) => `<span class="stars">${"★".repeat(n)}<span class="off">${"★".repeat(Math.max(0, 5 - n))}</span></span>`;

  function pickText(rec, p) {
    if (!p) return "";
    if (p.market === "AH") {
      const line = p.sel === "home" ? p.line : -p.line;
      const nm = p.sel === "home" ? team(rec.home, rec.home_name) : team(rec.away, rec.away_name);
      return `${nm} ${FB.fmtSigned(line)}`;
    }
    if (p.market === "OU") return `${t("sel." + p.sel)} ${FB.ouWord(p.line)}`;
    return t("sel." + p.sel);
  }
  const srcLabel = (s) => t("src." + s);

  // ------------------------------------------------------------------ charts
  const C = { blue: "#3d8bff", cyan: "#5ee7ff", violet: "#8a7dff", gold: "#ffd166", win: "#2fe6a6", loss: "#ff5d7a", grid: "rgba(80,150,255,0.12)", text: "#9fb6dd" };
  function chart(el, option) {
    if (!el || !window.echarts) return null;
    const c = echarts.init(el, null, { renderer: "canvas" });
    const base = {
      backgroundColor: "transparent", textStyle: { color: C.text, fontFamily: "Noto Sans SC, Microsoft YaHei, sans-serif" },
      tooltip: { trigger: "axis", backgroundColor: "rgba(6,23,54,.95)", borderColor: "rgba(94,231,255,.35)", textStyle: { color: "#e6f0ff" } },
      grid: { left: 48, right: 24, top: 36, bottom: 36, containLabel: true },
      animationDuration: 1200, animationEasing: "cubicOut",
    };
    c.setOption(Object.assign(base, option));
    S.charts.push(c);
    return c;
  }
  const axis = (extra) => Object.assign({ axisLine: { lineStyle: { color: C.grid } }, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.text } }, extra || {});
  window.addEventListener("resize", () => S.charts.forEach((c) => c.resize()));
  function disposeCharts() { S.charts.forEach((c) => c.dispose()); S.charts = []; }

  function countUp(root) {
    $$("[data-count]", root).forEach((el) => {
      const target = parseFloat(el.dataset.count);
      if (isNaN(target)) return;
      const dec = parseInt(el.dataset.dec || "0", 10), suf = el.dataset.suf || "", pre = el.dataset.pre || "";
      const t0 = performance.now(), dur = 1400;
      const step = (now) => {
        const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        const v = target * e;
        el.textContent = pre + (pre === "" && target > 0 && el.dataset.sign ? "+" : "") + v.toFixed(dec) + suf;
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  // ------------------------------------------------------------------ components
  function probBar(p) {
    const [h, d, a] = p.map((x) => (x || 0) * 100);
    return `<div class="probbar"><span class="h" style="width:${h}%"></span><span class="d" style="width:${d}%"></span><span class="a" style="width:${a}%"></span></div>
      <div class="problbl"><span>${t("p.home")} ${h.toFixed(0)}%</span><span>${t("p.draw")} ${d.toFixed(0)}%</span><span>${t("p.away")} ${a.toFixed(0)}%</span></div>`;
  }
  function pickCell(rec, key) {
    const p = rec.picks && rec.picks[key];
    if (!p) {
      const why = key === "1X2" && rec.x_skipped ? t("m.below") : t("m.noLine");
      return `<div class="pick none"><div class="k"><span>${t("m." + key)}</span></div><div class="v">${why}</div></div>`;
    }
    const rec3 = p.stars >= 3;
    return `<div class="pick ${rec3 ? "rec" : ""}">
      <div class="k"><span>${t("m." + key)}</span>${stars(p.stars)}</div>
      <div class="v" title="${esc(pickText(rec, p))}">${esc(pickText(rec, p))}</div>
      <div class="o">@${num(p.odds)} · ${pct(p.p, 0)} · <span class="${cls(p.ev)}">${signed(p.ev * 100, 1)}%</span></div></div>`;
  }
  const alertChips = (rec) => (rec.alerts || []).length
    ? `<div class="alerts">${rec.alerts.map((a) => `<span class="alert ${["goal_fest", "tight", "second_leg", "line_move"].includes(a) ? "info" : ""}">${t("alert." + a)}</span>`).join("")}</div>` : "";

  /* Entropy index 0–100: normalised 1X2 Shannon entropy rescaled over the range real matches occupy
     (≈0.55 for a heavy favourite … 1.0 for a coin-flip), so the meter actually discriminates. */
  const entIdx = (h) => Math.max(0, Math.min(100, Math.round(((h || 0) - 0.55) / 0.45 * 100)));

  function matchCard(rec) {
    const best = rec.best_stars || 0;
    const ent = entIdx(rec.model.entropy) / 100;
    return `<article class="mcard panel ${best >= 3 ? "hot" : ""}" data-mid="${esc(rec.mid)}" tabindex="0">
      ${best >= 4 ? `<div class="ribbon">${stars(best).replace(/class="stars"/, 'class="stars" style="color:#2a1a00"')}</div>` : ""}
      <div class="meta"><span class="comp-tag">${esc(comp(rec.comp))}</span><span class="kick">${rec.mode === "preview" ? `<span class="mode-tag replay" title="${esc(t("pv.tip"))}">${t("pv.tag")}</span> ` : `<span class="mode-tag" title="${esc(t("lk.tip"))}">${t("lk.tag")}</span> `}${kickoff(rec.kickoff)}</span></div>
      <div class="teams">
        <div class="team">${badge(rec.home, rec.home_name)}<div><div class="nm">${esc(team(rec.home, rec.home_name))}</div><div class="sub">Elo ${rec.elo[0] ?? "—"}</div></div></div>
        <div class="vs"><b>VS</b>xG ${num(rec.model.lh, 1)}:${num(rec.model.la, 1)}</div>
        <div class="team away">${badge(rec.away, rec.away_name)}<div><div class="nm">${esc(team(rec.away, rec.away_name))}</div><div class="sub">Elo ${rec.elo[1] ?? "—"}</div></div></div>
      </div>
      ${probBar(rec.model.p)}
      <div class="picks">${pickCell(rec, "AH")}${pickCell(rec, "OU")}${pickCell(rec, "1X2")}</div>
      <div class="entropy"><span>${t("entropy")}</span><div class="meter"><i style="width:${(ent * 100).toFixed(0)}%"></i></div><span class="mono">${(ent * 100).toFixed(0)}</span></div>
      ${alertChips(rec)}
    </article>`;
  }
  function bindCards(root) {
    $$(".mcard", root).forEach((el) => {
      const open = () => openMatch(el.dataset.mid);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  }

  // ------------------------------------------------------------------ views
  const views = {};

  views.home = (app) => {
    const perf = S.perf || {};
    const live = perf.live || {};
    const bt = perf.backtest || { pools: {} };
    const club = bt.pools.club || {}, intl = bt.pools.intl || {};
    const hold = (club.final && club.final.holdout) || {};
    const useLive = live.AH && live.AH.rec && live.AH.rec.n >= 30;
    const ahRec = useLive ? live.AH.rec : hold.AH && hold.AH.rec;
    const xRec = useLive ? live["1X2"].rec : hold["1X2"] && hold["1X2"].rec;
    const srcName = useLive ? t("kpi.liveFoot") : t("kpi.holdFoot");
    const top = (S.pred.matches || []).filter((r) => r.best_stars >= 3).sort((a, b) => b.best_stars - a.best_stars || a.kickoff.localeCompare(b.kickoff)).slice(0, 6);
    const recent = (S.results.matches || []).slice(0, 8);
    const db = S.meta.db || {};
    const k = (label, v, dec, suf, foot, sign) => `<div class="panel kpi"><div class="label">${label}</div>
      <div class="value ${sign ? cls(v) : ""}" data-count="${v == null ? "" : v}" data-dec="${dec}" data-suf="${suf}" ${sign ? 'data-sign="1"' : ""}>${v == null ? "—" : v}</div><div class="foot">${foot}</div></div>`;
    app.innerHTML = `<div class="view">
      <section class="hero">
        <div>
          <div class="eyebrow">${t("hero.eyebrow")}</div>
          <h1>${t("hero.title")}</h1>
          <p class="lead">${t("hero.lead")}</p>
          <div class="hero-cta"><a class="btn primary" href="#/predict">${t("hero.cta1")} →</a><a class="btn" href="#/stats">${t("hero.cta2")}</a></div>
        </div>
        <div class="hero-visual">${heroSVG()}<div class="scan"></div></div>
      </section>
      <section class="grid g5" style="margin-top:18px">
        ${k(t("kpi.ahHit"), ahRec && ahRec.hit != null ? +(ahRec.hit * 100).toFixed(1) : null, 1, "%", `★★★+ · ${srcName} · ${ahRec ? ahRec.n : 0} ${t("kpi.picks")} · ${t("s.roi")} ${ahRec && ahRec.roi != null ? signed(ahRec.roi * 100, 1) + "%" : "—"}`)}
        ${k(t("kpi.xRoi"), xRec && xRec.roi != null ? +(xRec.roi * 100).toFixed(1) : null, 1, "%", `★★★+ · ${srcName} · ${xRec ? xRec.n : 0} ${t("kpi.picks")} · ${t("s.hit")} ${pct(xRec && xRec.hit)}`, true)}
        ${k(t("kpi.xAcc"), club.prob ? +(club.prob.acc * 100).toFixed(1) : null, 1, "%", `${t("kpi.clubs")} ${club.prob ? club.prob.n : 0} · ${t("kpi.nations")} ${pct(intl.prob && intl.prob.acc)}`)}
        ${k(t("kpi.ouAcc"), club.prob ? +(club.prob.ou25_acc * 100).toFixed(1) : null, 1, "%", `${t("kpi.clubs")} · ${t("kpi.nations")} ${pct(intl.prob && intl.prob.ou25_acc)}`)}
        ${k(t("kpi.db"), db.matches || 0, 0, "", `${db.first || ""} → ${db.last || ""}`)}
      </section>
      <div class="section-head"><h2>${t("home.top")}</h2><span class="sub">${t("home.topSub")} · <a href="#/predict">${t("home.all")}</a></span></div>
      ${top.length ? `<div class="cards">${top.map(matchCard).join("")}</div>` : `<div class="panel empty"><b>${t("home.noTop")}</b><a href="#/predict">${t("home.all")}</a></div>`}
      <div class="section-head"><h2>${t("home.recent")}</h2><span class="sub"><a href="#/results">${t("nav.results")} →</a></span></div>
      <div class="panel">${recent.length ? recent.map(resultRow).join("") : `<div class="empty">${t("r.none")}</div>`}</div>
    </div>`;
    bindCards(app);
    countUp(app);
  };

  function heroSVG() {
    const ticks = Array.from({ length: 60 }, (_, i) => {
      const a = (i / 60) * Math.PI * 2, r1 = 170, r2 = i % 5 === 0 ? 156 : 163;
      return `<line x1="${200 + r1 * Math.cos(a)}" y1="${200 + r1 * Math.sin(a)}" x2="${200 + r2 * Math.cos(a)}" y2="${200 + r2 * Math.sin(a)}" stroke="rgba(94,231,255,${i % 5 === 0 ? 0.7 : 0.25})" stroke-width="${i % 5 === 0 ? 2 : 1}"/>`;
    }).join("");
    const hexes = [0, 1, 2, 3, 4, 5].map((i) => {
      const a = (i / 6) * Math.PI * 2 - Math.PI / 2;
      return `<circle cx="${200 + 112 * Math.cos(a)}" cy="${200 + 112 * Math.sin(a)}" r="5" fill="#5ee7ff"><animate attributeName="r" values="4;7;4" dur="${2 + i * 0.4}s" repeatCount="indefinite"/></circle>`;
    }).join("");
    return `<svg viewBox="0 0 400 400" aria-hidden="true">
      <defs>
        <radialGradient id="core" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#5ee7ff" stop-opacity=".55"/><stop offset="1" stop-color="#2f6bff" stop-opacity="0"/></radialGradient>
        <linearGradient id="arc" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5ee7ff"/><stop offset="1" stop-color="#2f6bff" stop-opacity=".1"/></linearGradient>
      </defs>
      <circle cx="200" cy="200" r="190" fill="url(#core)" opacity=".35"/>
      <g class="ring-rot">${ticks}</g>
      <g class="ring-rot-r"><circle cx="200" cy="200" r="140" fill="none" stroke="url(#arc)" stroke-width="3" stroke-dasharray="260 620"/>
        <circle cx="200" cy="200" r="126" fill="none" stroke="rgba(138,125,255,.55)" stroke-width="1.5" stroke-dasharray="4 10"/></g>
      <polygon points="200,88 297,144 297,256 200,312 103,256 103,144" fill="rgba(10,30,70,.55)" stroke="rgba(94,231,255,.55)" stroke-width="1.5"/>
      ${hexes}
      <path d="M140 236 L176 186 L212 218 L262 150" fill="none" stroke="#5ee7ff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="240" stroke-dashoffset="240">
        <animate attributeName="stroke-dashoffset" from="240" to="0" dur="2.2s" fill="freeze"/></path>
      <circle cx="262" cy="150" r="7" fill="#fff"><animate attributeName="opacity" values="1;.3;1" dur="1.6s" repeatCount="indefinite"/></circle>
      <text x="200" y="272" text-anchor="middle" fill="#e6f0ff" font-family="Orbitron, sans-serif" font-size="15" letter-spacing="4">ENTROPY XI</text>
      <text x="200" y="128" text-anchor="middle" fill="#9fb6dd" font-family="JetBrains Mono, monospace" font-size="11">H = −Σ p·log p</text>
    </svg>`;
  }

  // ---- predictions
  views.predict = (app) => {
    const all = S.pred.matches || [];
    const comps = Array.from(new Set(all.map((r) => r.comp)));
    const st = (S.predState = S.predState || { comp: "all", rec: false, sort: "time" });
    const render = () => {
      let list = all.filter((r) => (st.comp === "all" || r.comp === st.comp) && (!st.rec || r.best_stars >= 3));
      list = list.slice().sort((a, b) => (st.sort === "star" ? b.best_stars - a.best_stars : 0) || a.kickoff.localeCompare(b.kickoff));
      $("#cards").innerHTML = list.length ? list.map(matchCard).join("")
        : `<div class="panel empty" style="grid-column:1/-1"><b>${t("predict.none")}</b>${t("predict.noneSub")}</div>`;
      bindCards($("#cards"));
      $$("#comp-chips .chip").forEach((c) => c.classList.toggle("on", c.dataset.c === st.comp));
      $("#rec-chip").classList.toggle("on", st.rec);
      $$("#sort-seg button").forEach((b) => b.classList.toggle("on", b.dataset.s === st.sort));
    };
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("predict.title")}</h2><span class="sub">${t("predict.sub")} · ${all.length}</span></div>
      <div class="toolbar" id="comp-chips"><button class="chip" data-c="all">${t("predict.all")}</button>
        ${comps.map((c) => `<button class="chip" data-c="${esc(c)}">${esc(comp(c))}</button>`).join("")}</div>
      <div class="toolbar"><button class="chip" id="rec-chip">${t("predict.recOnly")}</button>
        <div class="seg" id="sort-seg"><button data-s="time">${t("predict.sortTime")}</button><button data-s="star">${t("predict.sortStar")}</button></div></div>
      <div class="cards" id="cards"></div></div>`;
    $$("#comp-chips .chip").forEach((c) => c.addEventListener("click", () => { st.comp = c.dataset.c; render(); }));
    $("#rec-chip").addEventListener("click", () => { st.rec = !st.rec; render(); });
    $$("#sort-seg button").forEach((b) => b.addEventListener("click", () => { st.sort = b.dataset.s; render(); }));
    render();
  };

  // ---- results
  function resultRow(r) {
    const sc = r.result ? `${r.result[0]} : ${r.result[1]}` : t("o.void");
    const picks = Object.entries(r.picks || {}).map(([k, p]) => {
      const o = r.settled && r.settled[k] ? r.settled[k].outcome : r.status === "void" ? "void" : "";
      return `<span class="rpick">${t("m." + k)} ${esc(pickText(r, p))} @${num(p.odds)} ${stars(p.stars)} ${o ? `<span class="res ${o}">${t("o." + o)}</span>` : ""}</span>`;
    }).join("");
    const lean = r.p ? ["H", "D", "A"][r.p.indexOf(Math.max(...r.p))] : null;
    return `<div class="rrow">
      <div class="rt"><div class="mono">${hhmm(r.kickoff)}</div><div class="muted" style="font-size:12px">${esc(comp(r.comp))}<span class="mode-tag ${r.mode}">${t("r." + r.mode)}</span></div></div>
      <div class="mt">${esc(team(r.home, r.home_name))} <span class="muted">vs</span> ${esc(team(r.away, r.away_name))}
        <small>${t("r.lean")}: ${lean ? t("sel." + lean) : "—"} ${r.lean_hit != null ? `<span class="res ${r.lean_hit ? "win" : "loss"}">${r.lean_hit ? "✓" : "✗"}</span>` : ""} · xG ${num(r.lhla[0], 1)}:${num(r.lhla[1], 1)}</small></div>
      <div class="score">${sc}</div>
      <div class="rpicks">${picks || `<span class="muted" style="font-size:12px">${t("m.noLine")}</span>`}</div></div>`;
  }

  views.results = (app) => {
    const all = S.results.matches || [];
    const days = Array.from(new Set(all.map((r) => r.bj_date))).sort().reverse();
    const st = (S.resState = S.resState || { day: days[0] });
    if (!days.includes(st.day)) st.day = days[0];
    const daySummary = (d) => {
      let n = 0, won = 0, dec = 0, u = 0;
      all.filter((r) => r.bj_date === d).forEach((r) => Object.entries(r.picks || {}).forEach(([k, p]) => {
        if (p.stars < 3 || !r.settled || !r.settled[k]) return;
        const s = r.settled[k]; n++; u += s.profit;
        const map = { win: [1, 1], half_win: [0.5, 0.5], push: [0, 0], half_loss: [0, 0.5], loss: [0, 1] }[s.outcome] || [0, 0];
        won += map[0]; dec += map[1];
      }));
      return { n, hit: dec ? won / dec : null, u };
    };
    const render = () => {
      const rows = all.filter((r) => r.bj_date === st.day).sort((a, b) => a.kickoff.localeCompare(b.kickoff));
      const s = daySummary(st.day);
      $("#day-sum").innerHTML = st.day ? t("r.daySum", { n: s.n, hit: pct(s.hit), u: `<span class="${cls(s.u)}">${signed(s.u)}</span>` }) : "";
      $("#res-list").innerHTML = rows.length ? rows.map(resultRow).join("") : `<div class="empty">${t("r.none")}</div>`;
      $$(".day").forEach((d) => d.classList.toggle("on", d.dataset.d === st.day));
    };
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("r.title")}</h2><span class="sub">${t("r.sub")}</span></div>
      <div class="daystrip">${days.slice(0, 60).map((d) => {
        const s = daySummary(d);
        const wd = new Intl.DateTimeFormat(ZH_LOCALE(), { weekday: "short", timeZone: "UTC" }).format(new Date(d + "T00:00:00Z"));
        return `<div class="day" data-d="${d}"><div class="d1">${d.slice(5)}</div><div class="d2">${wd}</div><div class="d3 ${cls(s.u)}">${s.n ? signed(s.u, 1) : "·"}</div></div>`;
      }).join("")}</div>
      <p class="muted" id="day-sum" style="margin:14px 2px"></p>
      <div class="panel" id="res-list"></div></div>`;
    $$(".day").forEach((d) => d.addEventListener("click", () => { st.day = d.dataset.d; render(); }));
    render();
  };

  // ---- stats
  views.stats = (app) => {
    const P = S.perf || {};
    const st = (S.statState = S.statState || { tab: (P.live && P.live.rec && P.live.rec.n >= 30) ? "live" : "replay" });
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("s.title")}</h2>
        <div class="seg" id="stat-seg"><button data-t="live">${t("s.live")}</button><button data-t="replay">${t("s.replay")}</button><button data-t="backtest">${t("s.backtest")}</button></div></div>
      <div id="stat-body"></div></div>`;
    const render = () => {
      disposeCharts();
      $$("#stat-seg button").forEach((b) => b.classList.toggle("on", b.dataset.t === st.tab));
      const body = $("#stat-body");
      if (st.tab === "backtest") return renderBacktest(body, P.backtest);
      const blk = P[st.tab] || {};
      const note = st.tab === "live" ? t("s.liveNote", { d: P.live_start || "" }) : t("s.replayNote");
      if (!blk.rec || !blk.matches) {
        body.innerHTML = `<p class="note">${note}</p><div class="panel empty" style="margin-top:16px"><b>${t("s.empty", { d: P.live_start || "" })}</b></div>`;
        return;
      }
      const tile = (lbl, v, foot, c) => `<div class="panel kpi"><div class="label">${lbl}</div><div class="value ${c || ""}">${v}</div><div class="foot">${foot}</div></div>`;
      const MINN = 20;
      const recOk = blk.rec.n >= MINN;
      const allTile = (m, lbl) => {
        const a = blk[m] && blk[m].all;
        return tile(lbl, a && a.n ? pct(a.hit) : "—", a && a.n ? `${a.n} ${t("kpi.picks")} · ${t("s.roi")} <span class="${cls(a.roi)}">${signed(a.roi * 100, 1)}%</span>` : t("s.small"));
      };
      body.innerHTML = `<p class="note">${note}</p>
        <section class="grid g4" style="margin-top:16px">
          ${tile("★★★+ " + t("s.hit"), recOk ? pct(blk.rec.hit) : "—", recOk ? `${blk.rec.n} ${t("kpi.picks")} · ${t("s.roi")} <span class="${cls(blk.rec.roi)}">${signed(blk.rec.roi * 100, 1)}%</span>` : `${t("s.small")} (n=${blk.rec.n})`)}
          ${allTile("AH", t("s.ahAll"))}
          ${allTile("OU", t("s.ouAll"))}
          ${tile(t("s.xAcc"), pct(blk.lean.x_acc), `${blk.matches} ${t("s.matches")} · ${t("s.ouAcc")} ${pct(blk.lean.ou_acc)}`)}
        </section>
        <div class="grid g2" style="margin-top:16px">
          <div class="panel panel-pad"><div class="eyebrow">${t("s.cum")}</div><div class="chart" id="ch-cum"></div></div>
          <div class="panel panel-pad"><div class="eyebrow">${t("s.byStar")}</div><div class="chart" id="ch-star"></div></div>
        </div>
        <div class="grid g2" style="margin-top:16px">
          <div class="panel panel-pad"><div class="eyebrow">${t("s.byMarket")}</div>${marketTable(blk)}</div>
          <div class="panel panel-pad"><div class="eyebrow">${t("s.byComp")}</div>${compTable(blk.by_comp)}</div>
        </div>`;
      const sa = blk.series_all || {}, ser = blk.series || [];
      const days = Array.from(new Set([].concat(...["AH", "OU", "1X2"].map((m) => (sa[m] || []).map((x) => x[0])), ser.map((x) => x[0])))).sort();
      const fill = (arr, vi) => { const mp = new Map(arr.map((x) => [x[0], x[vi]])); let last = null; return days.map((d) => (mp.has(d) ? (last = mp.get(d)) : last)); };
      const colors = { AH: C.blue, OU: C.cyan, "1X2": C.violet };
      chart($("#ch-cum"), {
        legend: { textStyle: { color: C.text }, top: 0 },
        xAxis: axis({ type: "category", data: days }),
        yAxis: axis({ type: "value", name: t("s.profit") }),
        series: ["AH", "OU", "1X2"].map((m) => ({ name: t("m." + m) + " · " + t("s.allLeans"), type: "line", smooth: true, showSymbol: false,
          data: fill(sa[m] || [], 1), lineStyle: { color: colors[m], width: 2 } }))
          .concat([{ name: "★★★+", type: "line", smooth: true, showSymbol: false, data: fill(ser, 3), lineStyle: { color: C.gold, width: 2.5 },
            areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(255,209,102,.25)" }, { offset: 1, color: "rgba(255,209,102,0)" }]) } }]),
      });
      const mk = ["AH", "OU", "1X2"], starsX = [1, 2, 3, 4, 5];
      chart($("#ch-star"), {
        legend: { textStyle: { color: C.text }, top: 0 },
        tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%") },
        xAxis: axis({ type: "category", data: starsX.map((s) => "≥" + "★".repeat(s)) }),
        yAxis: axis({ type: "value", min: 0, max: 1, axisLabel: { formatter: (v) => (v * 100).toFixed(0) + "%", color: C.text } }),
        series: mk.map((m, i) => ({ name: t("m." + m), type: "bar", barMaxWidth: 18, itemStyle: { borderRadius: [4, 4, 0, 0], color: [C.blue, C.cyan, C.violet][i] },
          data: starsX.map((s) => { const r = blk[m] && blk[m].by_star[s]; return r && r.n >= 5 ? r.hit : null; }) })),
      });
    };
    $$("#stat-seg button").forEach((b) => b.addEventListener("click", () => { st.tab = b.dataset.t; render(); }));
    render();
  };

  function marketTable(blk) {
    const cells = (r) => `<td class="mono">${r ? r.n : 0}</td><td class="mono">${pct(r && r.hit)}</td><td class="mono ${cls(r && r.roi)}">${r && r.roi != null ? signed(r.roi * 100, 1) + "%" : "—"}</td>`;
    const row = (m) => `<tr><td>${t("m." + m)}</td>${cells(blk[m] && blk[m].rec)}${cells(blk[m] && blk[m].all)}</tr>`;
    const lean = S.lang === "zh" ? "全部方向" : "All leans";
    return `<div class="table-wrap"><table class="t"><thead><tr><th></th><th colspan="3">★★★+</th><th colspan="3">${lean}</th></tr>
      <tr><th></th><th>${t("s.n")}</th><th>${t("s.hit")}</th><th>${t("s.roi")}</th><th>${t("s.n")}</th><th>${t("s.hit")}</th><th>${t("s.roi")}</th></tr></thead>
      <tbody>${["AH", "OU", "1X2"].map(row).join("")}</tbody></table></div>`;
  }
  function compTable(byComp) {
    const rows = Object.entries(byComp || {}).sort((a, b) => (b[1].lean.n || 0) - (a[1].lean.n || 0));
    return `<div class="table-wrap"><table class="t"><thead><tr><th>${t("h.comp")}</th><th>${t("s.matches")}</th><th>${t("s.xAcc")}</th><th>★★★+ ${t("s.n")}</th><th>${t("s.hit")}</th><th>${t("s.roi")}</th></tr></thead>
      <tbody>${rows.map(([c, v]) => `<tr><td>${esc(comp(c))}</td><td class="mono">${v.lean.n || 0}</td><td class="mono">${pct(v.lean.x_acc)}</td><td class="mono">${v.n}</td><td class="mono">${pct(v.hit)}</td><td class="mono ${cls(v.roi)}">${v.roi != null ? signed(v.roi * 100, 1) + "%" : "—"}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderBacktest(body, bt) {
    if (!bt) { body.innerHTML = `<div class="panel empty">—</div>`; return; }
    const club = bt.pools.club || {}, intl = bt.pools.intl || {};
    const hold = (club.final && club.final.holdout) || {};
    const stratRows = ["model", "market", "final"].map((s) => {
      const h = (club[s] && club[s].holdout) || {};
      const c = (m) => { const r = h[m] && h[m].all; return r ? `<td class="mono">${pct(r.hit)}</td><td class="mono ${cls(r.roi)}">${signed(r.roi * 100, 1)}%</td>` : "<td>—</td><td>—</td>"; };
      return `<tr><td>${t("strat." + s)}</td>${c("AH")}${c("OU")}${c("1X2")}</tr>`;
    }).join("");
    const rules = bt.star_rules || {};
    const ruleRows = ["AH", "OU", "1X2"].map((m) => `<tr><td>${t("m." + m)}</td>${(rules[m] || []).map((x, i) => `<td class="mono">${x >= 9 ? "—" : (i === 0 ? "≥0" : "≥" + (x * 100).toFixed(1) + "%")}</td>`).join("")}</tr>`).join("");
    const starRows = ["AH", "OU", "1X2"].map((m) => {
      const h = hold[m] || {};
      return [3, 4, 5].map((s) => {
        const r = h[s] || h[String(s)];
        return r ? `<tr><td>${t("m." + m)}</td><td>${stars(s)}</td><td class="mono">${r.n}</td><td class="mono">${pct(r.hit)}</td><td class="mono ${cls(r.roi)}">${signed(r.roi * 100, 1)}%</td><td class="mono">${num(r.avg_odds)}</td></tr>` : "";
      }).join("") + (h.rec ? `<tr style="background:rgba(47,107,255,.08)"><td>${t("m." + m)}</td><td>★★★+</td><td class="mono">${h.rec.n}</td><td class="mono">${pct(h.rec.hit)}</td><td class="mono ${cls(h.rec.roi)}">${signed(h.rec.roi * 100, 1)}%</td><td class="mono">${num(h.rec.avg_odds)}</td></tr>` : "");
    }).join("");
    const pm = (p) => p ? `<div class="kv"><span>${t("s.matches")}</span><b>${p.n}</b></div><div class="kv"><span>${t("s.xAcc")}</span><b>${pct(p.acc)}</b></div>
      <div class="kv"><span>${t("s.ouAcc")}</span><b>${pct(p.ou25_acc)}</b></div><div class="kv"><span>${t("s.logloss")}</span><b>${num(p.logloss, 4)}</b></div>
      ${p.with_market ? `<div class="kv"><span>${t("s.logloss")} · ${t("d.final")} / ${t("d.model")} / ${t("d.market")}</span><b>${num(p.with_market.final_logloss, 4)} / ${num(p.with_market.model_only_logloss, 4)} / ${num(p.with_market.market_logloss, 4)}</b></div>` : ""}` : "—";
    body.innerHTML = `<p class="note">${t("s.btNote")}</p>
      <div class="grid g2" style="margin-top:16px">
        <div class="panel panel-pad"><div class="eyebrow">${t("s.byStar")} · 2022–</div><div class="table-wrap"><table class="t"><thead><tr><th></th><th></th><th>${t("s.n")}</th><th>${t("s.hit")}</th><th>${t("s.roi")}</th><th>${t("s.odds")}</th></tr></thead><tbody>${starRows}</tbody></table></div></div>
        <div class="panel panel-pad"><div class="eyebrow">${t("s.bySeason")}</div><div class="chart" id="ch-season"></div></div>
      </div>
      <div class="grid g3" style="margin-top:16px">
        <div class="panel panel-pad"><div class="eyebrow">${t("s.prob")} · Club</div>${pm(club.prob)}</div>
        <div class="panel panel-pad"><div class="eyebrow">${t("s.prob")} · International</div>${pm(intl.prob)}</div>
        <div class="panel panel-pad"><div class="eyebrow">${t("s.calib")}</div><div class="chart s" id="ch-cal"></div></div>
      </div>
      <div class="grid g2" style="margin-top:16px">
        <div class="panel panel-pad"><div class="eyebrow">${t("s.strat")}</div><div class="table-wrap"><table class="t"><thead><tr><th></th>${["AH", "OU", "1X2"].map((m) => `<th>${t("m." + m)} ${t("s.hit")}</th><th>${t("s.roi")}</th>`).join("")}</tr></thead><tbody>${stratRows}</tbody></table></div></div>
        <div class="panel panel-pad"><div class="eyebrow">${t("s.rules")}</div><div class="table-wrap"><table class="t"><thead><tr><th></th>${[1, 2, 3, 4, 5].map((s) => `<th>${stars(s)}</th>`).join("")}</tr></thead><tbody>${ruleRows}</tbody></table></div><p class="muted" style="font-size:12px;margin:10px 0 0">${t("s.ruleNote")}</p></div>
      </div>
      <div class="panel panel-pad" style="margin-top:16px"><div class="eyebrow">${t("s.byComp")} · 2022–</div>${btCompTable(bt.by_comp)}</div>`;
    const seasons = Array.from(new Set((bt.by_season || []).map((r) => r.season))).sort();
    chart($("#ch-season"), {
      legend: { textStyle: { color: C.text }, top: 0 },
      tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%") },
      xAxis: axis({ type: "category", data: seasons.map((s) => `${s}/${String(s + 1).slice(2)}`) }),
      yAxis: axis({ type: "value", axisLabel: { formatter: (v) => (v * 100).toFixed(0) + "%", color: C.text } }),
      series: ["AH", "OU", "1X2"].map((m, i) => ({ name: t("m." + m) + " " + t("s.roi"), type: "line", smooth: true, symbolSize: 6,
        lineStyle: { color: [C.blue, C.cyan, C.violet][i] }, itemStyle: { color: [C.blue, C.cyan, C.violet][i] },
        data: seasons.map((s) => { const r = (bt.by_season || []).find((x) => x.season === s && x.market === m); return r ? r.roi : null; }),
        markLine: i === 0 ? { silent: true, symbol: "none", lineStyle: { color: "rgba(255,255,255,.3)" }, data: [{ yAxis: 0 }] } : undefined })),
    });
    const cal = bt.calibration || [];
    chart($("#ch-cal"), {
      grid: { left: 40, right: 16, top: 16, bottom: 30, containLabel: true },
      tooltip: { trigger: "item" },
      xAxis: axis({ type: "value", min: 0, max: 1 }), yAxis: axis({ type: "value", min: 0, max: 1 }),
      series: [{ type: "line", data: [[0, 0], [1, 1]], showSymbol: false, lineStyle: { color: "rgba(255,255,255,.25)", type: "dashed" } },
        { type: "scatter", data: cal.map((c) => [c[0], c[1], c[2]]), symbolSize: (v) => Math.max(5, Math.min(18, Math.sqrt(v[2]) / 4)), itemStyle: { color: C.cyan, shadowBlur: 10, shadowColor: C.cyan } }],
    });
  }
  function btCompTable(rows) {
    const by = {};
    (rows || []).forEach((r) => { (by[r.comp] = by[r.comp] || {})[r.market] = r; });
    const cell = (r) => r ? `<td class="mono">${r.n}</td><td class="mono">${pct(r.hit)}</td><td class="mono ${cls(r.roi)}">${signed(r.roi * 100, 1)}%</td>` : `<td>—</td><td>—</td><td>—</td>`;
    return `<div class="table-wrap"><table class="t"><thead><tr><th>${t("h.comp")}</th>${["AH", "OU", "1X2"].map((m) => `<th>${t("m." + m)} ${t("s.n")}</th><th>${t("s.hit")}</th><th>${t("s.roi")}</th>`).join("")}</tr></thead>
      <tbody>${Object.entries(by).map(([c, v]) => `<tr><td>${esc(comp(c))}</td>${cell(v.AH)}${cell(v.OU)}${cell(v["1X2"])}</tr>`).join("")}</tbody></table></div>`;
  }

  // ---- teams
  views.teams = (app) => {
    const entries = Object.entries(S.teams);
    const groups = {};
    entries.forEach(([k, v]) => {
      const g = v.pool === "intl" ? "intl" : (v.league && S.meta.competitions[v.league] ? v.league : "other");
      (groups[g] = groups[g] || []).push([k, v]);
    });
    const order = Object.keys(S.meta.competitions).filter((c) => groups[c]).concat(groups.other ? ["other"] : [], groups.intl ? ["intl"] : []);
    const gname = (g) => (g === "intl" ? (S.lang === "zh" ? "国家队" : "National teams") : g === "other" ? (S.lang === "zh" ? "其他（杯赛参赛队）" : "Other (cup sides)") : comp(g));
    const st = (S.teamState = S.teamState || { q: "", a: "", b: "" });
    const opts = entries.slice().sort((x, y) => team(x[0]).localeCompare(team(y[0]), ZH_LOCALE())).map(([k]) => `<option value="${esc(k)}">${esc(team(k))}</option>`).join("");
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("t.title")}</h2><span class="sub">${t("t.sub")}</span></div>
      <div class="panel panel-pad">
        <div class="eyebrow">${t("t.compare")}</div>
        <div class="calc-grid" style="margin-top:10px;grid-template-columns:1fr 1fr auto">
          <div class="field"><label>${t("t.pickA")}</label><select id="cmp-a"><option value=""></option>${opts}</select></div>
          <div class="field"><label>${t("t.pickB")}</label><select id="cmp-b"><option value=""></option>${opts}</select></div>
          <div class="field"><label>&nbsp;</label><button class="btn primary" id="cmp-go">${t("t.compare")}</button></div>
        </div>
        <div id="cmp-out"></div>
      </div>
      <div class="toolbar" style="margin-top:20px"><input class="search" id="team-q" placeholder="${t("t.search")}" value="${esc(st.q)}"></div>
      <div id="team-groups"></div></div>`;
    const renderList = () => {
      const q = st.q.trim().toLowerCase();
      $("#team-groups").innerHTML = order.map((g) => {
        const items = groups[g].filter(([k, v]) => !q || (v.name || "").toLowerCase().includes(q) || (v.zh || "").includes(q))
          .sort((x, y) => (y[1].elo || 0) - (x[1].elo || 0));
        if (!items.length) return "";
        return `<div class="section-head"><h2 style="font-size:17px">${esc(gname(g))}</h2><span class="sub">${items.length}</span></div>
          <div class="toolbar">${items.map(([k, v]) => `<a class="chip" href="#/team/${encodeURIComponent(k)}" style="display:inline-flex;align-items:center;gap:8px">${esc(team(k))}<span class="mono muted">${v.elo ? Math.round(v.elo) : ""}</span></a>`).join("")}</div>`;
      }).join("");
    };
    $("#team-q").addEventListener("input", (e) => { st.q = e.target.value; renderList(); });
    $("#cmp-a").value = st.a; $("#cmp-b").value = st.b;
    $("#cmp-go").addEventListener("click", async () => {
      st.a = $("#cmp-a").value; st.b = $("#cmp-b").value;
      if (!st.a || !st.b || st.a === st.b) return;
      const [A, B] = await Promise.all([loadTeam(st.a), loadTeam(st.b)]);
      $("#cmp-out").innerHTML = compareHTML(A, B);
    });
    renderList();
  };

  async function loadTeam(key) {
    if (S.teamCache[key]) return S.teamCache[key];
    const d = await getJSON(`data/teams/${key.replace(":", "_")}.json`);
    S.teamCache[key] = d;
    return d;
  }

  function statLines(sa, sb) {
    if (!sa || !sb) return "";
    const L = [["st.ppg", "ppg", 3], ["st.gf", "gfp", 4], ["st.ga", "gap", 4], ["st.o25", "o25", 1], ["st.btts", "btts", 1], ["st.cs", "cs", 1], ["st.sot", "sotf", 10]];
    const val = (s, k) => (k === "gfp" ? s.gf / s.n : k === "gap" ? s.ga / s.n : s[k]);
    return L.map(([lbl, k, max]) => {
      const a = val(sa, k), b = val(sb, k);
      if (a == null || b == null) return "";
      const fmt = (v) => (max === 1 ? pct(v, 0) : num(v, 2));
      return `<div class="statline"><span class="vl">${fmt(a)}</span><div class="bar l"><i style="width:${Math.min(100, (a / max) * 100)}%"></i></div>
        <span class="lbl">${t(lbl)}</span><div class="bar r"><i style="width:${Math.min(100, (b / max) * 100)}%"></i></div><span class="vr">${fmt(b)}</span></div>`;
    }).join("");
  }
  function formDots(rows, n = 6) { return `<span class="form-dots">${(rows || []).slice(0, n).map((r) => `<i class="${r[7]}">${r[7]}</i>`).join("")}</span>`; }
  function matchTable(rows, n = 20) {
    return `<div class="table-wrap"><table class="t"><thead><tr><th>${t("h.date")}</th><th>${t("h.comp")}</th><th>${t("h.venue")}</th><th>${t("h.opp")}</th><th>${t("h.score")}</th><th>${t("h.res")}</th></tr></thead><tbody>
      ${(rows || []).slice(0, n).map((r) => `<tr><td class="mono">${r[0]}</td><td>${esc(comp(r[1]))}</td><td>${r[4]}</td><td>${esc(team(r[2], r[3]))}</td><td class="mono">${r[5]}-${r[6]}</td><td><span class="res ${r[7]}">${r[7]}</span></td></tr>`).join("")}</tbody></table></div>`;
  }
  function compareHTML(A, B) {
    const h2h = (A.matches || []).filter((r) => r[2] === B.key);
    const w = h2h.filter((r) => r[7] === "W").length, d = h2h.filter((r) => r[7] === "D").length, l = h2h.filter((r) => r[7] === "L").length;
    return `<div class="teams" style="margin-top:18px">
        <div class="team">${badge(A.key, A.name)}<div><div class="nm">${esc(team(A.key, A.name))}</div><div class="sub">Elo ${A.elo ? Math.round(A.elo) : "—"} ${formDots(A.matches)}</div></div></div>
        <div class="vs"><b>${w}-${d}-${l}</b>H2H</div>
        <div class="team away">${badge(B.key, B.name)}<div><div class="nm">${esc(team(B.key, B.name))}</div><div class="sub">Elo ${B.elo ? Math.round(B.elo) : "—"} ${formDots(B.matches)}</div></div></div></div>
      <div class="eyebrow" style="margin:14px 0 6px">${t("d.last10")} / 20</div>${statLines(A.last20, B.last20)}
      <div class="eyebrow" style="margin:16px 0 6px">${t("tab.h2h")}</div>${h2h.length ? matchTable(h2h, 10) : `<p class="muted">${t("d.noH2H")}</p>`}`;
  }

  views.team = async (app, key) => {
    key = decodeURIComponent(key || "");
    let d;
    try { d = await loadTeam(key); } catch (e) { app.innerHTML = `<div class="panel empty">${esc(key)} —</div>`; return; }
    const s = (x) => x ? `${x.w}-${x.d}-${x.l}` : "—";
    const tile = (lbl, x) => `<div class="panel kpi"><div class="label">${lbl}</div><div class="value" style="font-size:22px">${s(x)}</div><div class="foot">${x ? `${t("t.goals")} ${x.gf}:${x.ga} · ${t("st.ppg")} ${x.ppg}` : ""}</div></div>`;
    app.innerHTML = `<div class="view">
      <div class="panel panel-pad" style="margin-top:6px">
        <div class="teams" style="grid-template-columns:auto 1fr;margin:0">
          <div class="team">${badge(d.key, d.name).replace('class="badge"', 'class="badge" style="width:64px;height:64px;font-size:15px"')}</div>
          <div><div style="font-size:26px;font-weight:700">${esc(team(d.key, d.name))}</div>
            <div class="muted">${esc(d.name)} · ${d.league ? esc(comp(d.league)) : ""} · Elo <b class="mono" style="color:#fff">${d.elo ? Math.round(d.elo) : "—"}</b> · ${formDots(d.matches, 10)}</div></div>
        </div></div>
      <section class="grid g4" style="margin-top:16px">${tile(t("t.all"), d.all)}${tile(S.lang === "zh" ? "近20场" : "Last 20", d.last20)}${tile(S.lang === "zh" ? "主场近20" : "Home (20)", d.home)}${tile(S.lang === "zh" ? "客场近20" : "Away (20)", d.away)}</section>
      <div class="panel panel-pad" style="margin-top:16px"><div class="eyebrow">${t("t.eloTrend")}</div><div class="chart" id="ch-elo"></div></div>
      <div class="panel panel-pad" style="margin-top:16px"><div class="eyebrow">${t("t.recent")}</div>${matchTable(d.matches, 40)}</div></div>`;
    const tr = d.elo_track || [];
    chart($("#ch-elo"), {
      xAxis: axis({ type: "category", data: tr.map((x) => x[0]), boundaryGap: false }),
      yAxis: axis({ type: "value", scale: true }),
      series: [{ type: "line", data: tr.map((x) => x[1]), showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 2.4 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(61,139,255,.4)" }, { offset: 1, color: "rgba(61,139,255,0)" }]) } }],
    });
  };

  // ---- calculator
  function calcHTML(id) {
    return `<div class="calc-grid">
      <div class="field"><label>${t("c.ahLine")}</label><input id="${id}-ahl" type="number" step="0.25" value="-0.5"></div>
      <div class="field"><label>${t("c.ahH")}</label><input id="${id}-ahh" type="number" step="0.01" value="1.90"></div>
      <div class="field"><label>${t("c.ahA")}</label><input id="${id}-aha" type="number" step="0.01" value="1.90"></div>
      <div class="field"><label>&nbsp;</label><div class="mono muted" id="${id}-ahw" style="padding:10px 0"></div></div>
      <div class="field"><label>${t("c.ouLine")}</label><input id="${id}-oul" type="number" step="0.25" value="2.5"></div>
      <div class="field"><label>${t("c.ouO")}</label><input id="${id}-ouo" type="number" step="0.01" value="1.90"></div>
      <div class="field"><label>${t("c.ouU")}</label><input id="${id}-ouu" type="number" step="0.01" value="1.90"></div>
      <div class="field"><label>&nbsp;</label><div class="mono muted" id="${id}-ouw" style="padding:10px 0"></div></div>
    </div><div class="grid g2"><div id="${id}-vah"></div><div id="${id}-vou"></div></div>`;
  }
  function bindCalc(id, rec) {
    const run = () => {
      const m = FB.matrix(rec.model.lh, rec.model.la, rec.model.rho);
      const v = (s) => parseFloat($(`#${id}-${s}`).value);
      const ahl = v("ahl"), oul = v("oul");
      $(`#${id}-ahw`).textContent = isNaN(ahl) ? "" : (ahl < 0 ? (S.lang === "zh" ? "主让 " : "Home gives ") : ahl > 0 ? (S.lang === "zh" ? "主受让 " : "Home receives ") : "") + FB.ahWord(ahl);
      $(`#${id}-ouw`).textContent = isNaN(oul) ? "" : FB.ouWord(oul);
      const verdict = (title, opts) => {
        const best = opts.reduce((a, b) => (b.ev > a.ev ? b : a));
        const outs = ["win", "half_win", "push", "half_loss", "loss"].map((k) => `<div>${t("o." + k)}<b>${pct(best.pr[k], 1)}</b></div>`).join("");
        return `<div class="verdict"><div class="eyebrow">${title}</div>
          <div class="big ${cls(best.ev)}">${best.ev > 0 ? esc(best.label) : t("c.pass")}</div>
          <div class="kv"><span>${opts.map((o) => esc(o.label)).join(" / ")} · ${t("c.ev")}</span><b>${opts.map((o) => `<span class="${cls(o.ev)}">${signed(o.ev * 100, 1)}%</span>`).join(" / ")}</b></div>
          <div class="kv"><span>${t("c.p")}</span><b>${opts.map((o) => pct(o.p, 1)).join(" / ")}</b></div>
          <div class="kv"><span>${t("c.fair")}</span><b>${opts.map((o) => num(o.fair)).join(" / ")}</b></div>
          <div class="outcomes">${outs}</div></div>`;
      };
      if (!isNaN(ahl)) {
        const ph = FB.handicap(m, ahl, "home"), pa = FB.handicap(m, ahl, "away");
        $(`#${id}-vah`).innerHTML = verdict(t("c.verdictAH"), [
          { label: `${team(rec.home, rec.home_name)} ${FB.fmtSigned(ahl)}`, pr: ph, ev: FB.ev(ph, v("ahh")), p: FB.effP(ph), fair: FB.fair(ph) },
          { label: `${team(rec.away, rec.away_name)} ${FB.fmtSigned(-ahl)}`, pr: pa, ev: FB.ev(pa, v("aha")), p: FB.effP(pa), fair: FB.fair(pa) }]);
      }
      if (!isNaN(oul)) {
        const po = FB.totals(m, oul, "over"), pu = FB.totals(m, oul, "under");
        $(`#${id}-vou`).innerHTML = verdict(t("c.verdictOU"), [
          { label: `${t("sel.over")} ${FB.ouWord(oul)}`, pr: po, ev: FB.ev(po, v("ouo")), p: FB.effP(po), fair: FB.fair(po) },
          { label: `${t("sel.under")} ${FB.ouWord(oul)}`, pr: pu, ev: FB.ev(pu, v("ouu")), p: FB.effP(pu), fair: FB.fair(pu) }]);
      }
    };
    const L = rec.lines || {}, ah = rec.picks && rec.picks.AH;
    const set = (s, v) => { if (v != null && !isNaN(v)) $(`#${id}-${s}`).value = v; };
    if (L.ah) { set("ahl", L.ah[0]); set("ahh", L.ah[1]); set("aha", L.ah[2]); }
    else if (ah) set("ahl", ah.line);
    else set("ahl", rec.model.fair_ah);
    if (L.ou) { set("oul", L.ou[0]); set("ouo", L.ou[1]); set("ouu", L.ou[2]); }
    else set("oul", rec.model.fair_ou);
    ["ahl", "ahh", "aha", "oul", "ouo", "ouu"].forEach((s) => $(`#${id}-${s}`).addEventListener("input", run));
    run();
  }

  views.calc = (app) => {
    const list = S.pred.matches || [];
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("c.title")}</h2><span class="sub">${t("c.sub")}</span></div>
      <div class="panel panel-pad">
        ${list.length ? `<div class="field" style="max-width:560px;margin-bottom:16px"><label>${t("c.match")}</label><select id="calc-m">${list.map((r) => `<option value="${esc(r.mid)}">${kickoff(r.kickoff)} · ${esc(comp(r.comp))} · ${esc(team(r.home, r.home_name))} vs ${esc(team(r.away, r.away_name))}</option>`).join("")}</select></div>
        <div id="calc-box"></div>` : `<div class="empty"><b>${t("predict.none")}</b></div>`}
      </div></div>`;
    if (!list.length) return;
    const draw = () => {
      const rec = list.find((r) => r.mid === $("#calc-m").value);
      $("#calc-box").innerHTML = `<p class="muted" style="margin-top:0">xG ${num(rec.model.lh)} : ${num(rec.model.la)} · ${t("d.fairAH")} ${FB.fmtSigned(rec.model.fair_ah)} · ${t("d.fairOU")} ${FB.ouWord(rec.model.fair_ou)}</p>` + calcHTML("cv");
      bindCalc("cv", rec);
    };
    $("#calc-m").addEventListener("change", draw);
    draw();
  };

  // ---- methodology
  views.method = (app) => {
    const zh = S.lang === "zh";
    const flow = zh
      ? [["01", "数据采集", "ESPN 全球赛程/赛果/技术统计，football-data 的 Bet365 亚盘与大小球历史及实时盘口，1872 年至今国际A级赛事"],
         ["02", "动态评级", "Elo（净胜球加权、赛事权重）、Pi-Rating（主客分离）、在线泊松攻防评级，单次时间顺序计算，无未来信息"],
         ["03", "特征工程", "参考 ProphitBet 的近况窗口（胜负、进失球、大胜）并扩展：跨赛季、对手强度修正、射正、休息天数、交锋、次回合比分"],
         ["04", "多算法集成", "泊松 GLM、LightGBM 泊松、逻辑回归、随机森林、XGBoost、神经网络、Dixon–Coles；权重仅由历史样本外预测学习"],
         ["05", "盘口决策", "以市场共识为锚做模型修正，对 Bet365 报价计算每个方向的有效胜率与期望收益，按星级分级，并生成冷门/体能/盘口异动预警"]]
      : [["01", "Data", "ESPN fixtures, results and match stats; football-data Bet365 Asian-handicap and goal-line prices (historical + current); every A-level international since 1872"],
         ["02", "Ratings", "Elo (goal-margin and competition weighted), Pi-ratings (home/away), online Poisson attack/defence — one chronological pass, no look-ahead"],
         ["03", "Features", "ProphitBet-style form windows (wins, losses, goals, big wins) extended across seasons, opponent-adjusted, shots on target, rest days, H2H, 2nd-leg context"],
         ["04", "Ensemble", "Poisson GLM, LightGBM-Poisson, logistic regression, random forest, XGBoost, neural net, Dixon–Coles; weights learned only from out-of-sample predictions"],
         ["05", "Decision", "Anchor on market consensus with model corrections, compute effective win probability and EV against the Bet365 price, assign stars and raise early warnings"]];
    const algos = zh
      ? [["Elo", "评级", "World Football Elo 思路：净胜球乘数、赛事 K 值、主场优势；俱乐部跨联赛/欧冠/亚冠统一尺度。"],
         ["Pi-Rating", "评级", "Constantinou & Fenton (2013)：分别刻画主场与客场实力，以净胜球误差的对数更新。"],
         ["OPR 在线泊松", "进球", "指数遗忘的 Dixon–Coles/Maher 攻防模型，每场赛后按泊松似然梯度更新，直接给出双方预期进球。"],
         ["GLM / LightGBM", "进球", "以全部特征回归主客队进球数（泊松损失），与 OPR 几何加权融合。"],
         ["LR · RF · XGB · MLP", "胜平负", "ProphitBet 的分类器族，输出概率；由样本外对数损失学习集成权重。"],
         ["Dixon–Coles 比分矩阵", "盘口", "带低比分相关修正的双泊松，推导任意让球（含四分之一盘）与大小球的赢/赢半/走/输半/输概率。"],
         ["一致化 (Reconcile)", "盘口", "保持总进球不变，重新分配双方预期进球，使比分矩阵的胜负差与集成胜平负一致。"],
         ["市场锚定修正 MAC", "价值", "回测显示纯模型不及市场共识价，因此以市场均价反推的预期进球为锚，用强正则 LightGBM 只学习小幅系统性修正（±15%以内）；再与 Bet365 实际报价比较得到期望收益。"]]
      : [["Elo", "rating", "World Football Elo style: goal-margin multiplier, competition K, home edge; one scale across leagues, UCL and ACL."],
         ["Pi-rating", "rating", "Constantinou & Fenton (2013): separate home and away strength, updated on log goal-difference error."],
         ["OPR online Poisson", "goals", "Exponentially-forgetting Dixon–Coles/Maher attack/defence, updated by the Poisson likelihood gradient after each game."],
         ["GLM / LightGBM", "goals", "Regress home and away goals on all features (Poisson loss), blended geometrically with OPR."],
         ["LR · RF · XGB · MLP", "1X2", "ProphitBet's classifier family with probability outputs; ensemble weights from out-of-sample log loss."],
         ["Dixon–Coles matrix", "lines", "Bivariate Poisson with low-score correction → win/half-win/push/half-loss/loss for any (quarter) handicap or goal line."],
         ["Reconcile", "lines", "Keep total goals, re-split the expected goals so the score matrix matches the ensemble's 1X2."],
         ["Market-anchored correction", "value", "The backtest shows the pure model is weaker than consensus prices, so the market-implied expected goals are the anchor and a heavily regularised LightGBM learns only small systematic corrections (within ±15%); EV is then measured against the actual Bet365 price."]];
    const rules = zh
      ? `<ul style="line-height:2;color:var(--text-2);font-size:14px;margin:0;padding-left:18px">
          <li><b>亚盘方向</b>：在 Bet365 当前主盘口（无则由市场价推算的亚洲主盘）上，选择期望收益更高的一方。</li>
          <li><b>大小球</b>：在可用盘口（Bet365 2.5 或 DraftKings 主盘）上选择大或小。</li>
          <li><b>胜平负</b>：只在赔率 ≥ 1.40 的选项中挑选，绝不为命中率牺牲利润空间；全部低于 1.40 时显示“不选”。</li>
          <li><b>星级</b>：按扣除算法分歧与数据不足惩罚后的期望收益分级，★★★ 及以上为推荐；门槛在 2013–2021 验证期选定，2022 年后为保留样本检验。</li>
          <li><b>不可篡改</b>：实盘预测在开赛前发布并冻结，赛后以90分钟比分自动结算（含加时的比赛按常规时间结算）。</li></ul>`
      : `<ul style="line-height:2;color:var(--text-2);font-size:14px;margin:0;padding-left:18px">
          <li><b>Asian handicap</b>: on Bet365's current main line (or the Asian main line implied by market prices), take the side with the higher expected value.</li>
          <li><b>Goal line</b>: over or under on the available line (Bet365 2.5 or the DraftKings main total).</li>
          <li><b>Full-time result</b>: only outcomes priced ≥ 1.40 are eligible — accuracy is never bought with margin; if all are below, no pick.</li>
          <li><b>Stars</b>: graded on expected value after penalties for algorithm disagreement and thin data; ★★★+ = recommended. Thresholds chosen on 2013–2021, tested on the 2022+ hold-out.</li>
          <li><b>Tamper-proof</b>: live picks are published and frozen before kick-off and settled on the 90-minute score.</li></ul>`;
    const honest = zh
      ? "坦诚声明：足球博彩市场（尤其收盘价）效率很高。熵锋奕的历史回测显示，模型在概率准确度上可以接近乃至略优于市场均价，但扣除庄家抽水后长期稳定盈利并未得到证明——请以“战绩统计”中的保留样本与实盘数据为准，并理性看待任何推荐。中国体育彩票的让球与赔率属公益性质，不纳入模型的预测与推荐依据。"
      : "Honest note: football betting markets — closing prices especially — are highly efficient. Entropy XI's backtest shows probability accuracy close to (or slightly better than) the market average, but sustained profit after the bookmaker margin is not proven. Judge it by the hold-out and live record on the Track-record page. China Sports Lottery handicaps and odds are a public-welfare product and are not used as model inputs or recommendations.";
    app.innerHTML = `<div class="view">
      <div class="section-head" style="margin-top:6px"><h2>${t("method.title")}</h2><span class="sub">${t("method.sub")}</span></div>
      <div class="flow">${flow.map((f) => `<div class="panel node"><div class="ic">${f[0]}</div><h4>${f[1]}</h4><p>${f[2]}</p></div>`).join("")}</div>
      <div class="section-head"><h2>${zh ? "算法矩阵" : "Algorithms"}</h2></div>
      <div class="grid g4">${algos.map((a) => `<div class="panel algo"><h4>${a[0]} <em>${a[1]}</em></h4><p>${a[2]}</p></div>`).join("")}</div>
      <div class="section-head"><h2>${zh ? "决策规则" : "Decision rules"}</h2></div>
      <div class="panel panel-pad">${rules}</div>
      <div class="section-head"><h2>${zh ? "风险与诚信" : "Risk & integrity"}</h2></div>
      <p class="note">${honest}</p></div>`;
  };

  // ------------------------------------------------------------------ match modal
  function openMatch(mid) {
    const rec = (S.pred.matches || []).find((r) => r.mid === mid);
    if (!rec) return;
    const modal = $("#modal");
    const tabs = ["overview", "h2h", "form", "stats", "calc"];
    $("#modal-body").innerHTML = `
      <div class="mhead">
        <div class="meta" style="display:flex;justify-content:space-between;color:var(--text-2);font-size:13px"><span class="comp-tag">${esc(comp(rec.comp))}</span><span class="mono">${kickoff(rec.kickoff)} (UTC+8)</span></div>
        <div class="teams">
          <div class="team">${badge(rec.home, rec.home_name)}<div><div class="nm" id="modal-title">${esc(team(rec.home, rec.home_name))}</div><div class="sub">Elo ${rec.elo[0] ?? "—"} ${formDots(rec.ctx.home.form)}</div></div></div>
          <div class="vs"><b>${num(rec.model.lh, 2)} : ${num(rec.model.la, 2)}</b>${t("d.xg")}</div>
          <div class="team away">${badge(rec.away, rec.away_name)}<div><div class="nm">${esc(team(rec.away, rec.away_name))}</div><div class="sub">Elo ${rec.elo[1] ?? "—"} ${formDots(rec.ctx.away.form)}</div></div></div>
        </div>
        ${probBar(rec.model.p)}
        <div class="picks">${pickCell(rec, "AH")}${pickCell(rec, "OU")}${pickCell(rec, "1X2")}</div>
        ${alertChips(rec)}
      </div>
      <div class="tabs">${tabs.map((k, i) => `<button data-tab="${k}" class="${i === 0 ? "on" : ""}">${t("tab." + k)}</button>`).join("")}</div>
      <div class="mbody" id="mbody"></div>`;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    const show = (k) => {
      $$(".tabs button", modal).forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
      S.charts.filter((c) => c.__modal).forEach((c) => c.dispose());
      S.charts = S.charts.filter((c) => !c.__modal);
      $("#mbody").innerHTML = modalTab(k, rec);
      if (k === "overview") overviewCharts(rec);
      if (k === "calc") bindCalc("mc", rec);
    };
    $$(".tabs button", modal).forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
    show("overview");
  }
  function closeModal() {
    const modal = $("#modal");
    if (modal.hidden) return;
    S.charts.filter((c) => c.__modal).forEach((c) => c.dispose());
    S.charts = S.charts.filter((c) => !c.__modal);
    modal.hidden = true;
    document.body.style.overflow = "";
  }
  $$("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  function modalTab(k, rec) {
    const m = rec.model, ctx = rec.ctx;
    if (k === "overview") {
      const kv = (a, b) => `<div class="kv"><span>${a}</span><b>${b}</b></div>`;
      return `<div class="grid g2">
        <div><div class="eyebrow">${t("d.prob")}</div><div class="chart s" id="mc-prob"></div></div>
        <div><div class="eyebrow">${t("d.heat")}</div><div class="chart s" id="mc-heat"></div></div></div>
        <div class="grid g3" style="margin-top:12px">
          <div>${kv(t("d.fairAH"), `${FB.fmtSigned(m.fair_ah)} <span class="muted">${FB.ahWord(m.fair_ah)}</span>`)}${kv(t("d.fairOU"), FB.ouWord(m.fair_ou))}${kv(t("d.over25"), pct(m.p_over25))}${kv(t("d.btts"), pct(m.p_btts))}</div>
          <div>${kv(t("entropy"), entIdx(m.entropy) + " / 100")}${kv(t("d.algo"), pct(m.disagree, 1))}${kv(t("d.basis"), t("basis." + (m.basis || "model")))}${kv("Dixon–Coles ρ", num(m.rho, 3))}</div>
          <div>${kv(t("d.topScores"), "")}${(m.top_scores || []).map((s) => kv(`${s[0]} - ${s[1]}`, pct(s[2], 1))).join("")}</div></div>
        ${Object.values(rec.picks || {}).map((p) => `<div class="kv"><span>${t("m." + p.market)} · ${esc(pickText(rec, p))} @${num(p.odds)} (${srcLabel(p.src)})</span>
          <b>${t("c.p")} ${pct(p.p, 1)} · ${t("c.fair")} ${num(p.fair)} · ${t("c.ev")} <span class="${cls(p.ev)}">${signed(p.ev * 100, 1)}%</span> · ${stars(p.stars)}</b></div>`).join("")}`;
    }
    if (k === "h2h") {
      const h = ctx.h2h;
      if (!h.rows.length) return `<p class="muted">${t("d.noH2H")}</p>`;
      return `<p>${t("d.h2hSum", { n: h.total, w: h.w, d: h.d, l: h.l })}</p>${matchTable(h.rows, 10).replace(/<th>${t("h.opp")}<\/th>/, `<th>${t("h.opp")}</th>`)}`;
    }
    if (k === "form") {
      return `<div class="grid g2"><div><div class="eyebrow">${esc(team(rec.home, rec.home_name))}</div>${matchTable(ctx.home.form, 8)}</div>
        <div><div class="eyebrow">${esc(team(rec.away, rec.away_name))}</div>${matchTable(ctx.away.form, 8)}</div></div>`;
    }
    if (k === "stats") {
      const sec = (title, a, b) => (a && b ? `<div class="eyebrow" style="margin:16px 0 6px">${title}</div>${statLines(a, b)}` : "");
      return `<div class="statline" style="font-weight:600"><span class="vl">${esc(team(rec.home, rec.home_name))}</span><span></span><span class="lbl"></span><span></span><span class="vr">${esc(team(rec.away, rec.away_name))}</span></div>
        ${sec(t("d.last10"), ctx.home.last10, ctx.away.last10)}
        ${sec(t("d.homeAway"), ctx.home.home, ctx.away.away)}
        ${sec(t("d.season"), ctx.home.season, ctx.away.season)}`;
    }
    if (k === "calc") return `<p class="muted" style="margin-top:0">${t("c.sub")}</p>` + calcHTML("mc");
    return "";
  }
  function overviewCharts(rec) {
    const m = rec.model;
    const series = [];
    const labels = [t("p.home"), t("p.draw"), t("p.away")];
    const add = (name, p, color) => p && series.push({ name, type: "bar", barMaxWidth: 16, data: p, itemStyle: { color, borderRadius: [4, 4, 0, 0] } });
    add(t("d.model"), m.p_model, C.violet); add(t("d.market"), m.p_market, "#5b6f96"); add(t("d.final"), m.p, C.cyan);
    const c1 = chart($("#mc-prob"), {
      legend: { textStyle: { color: C.text }, top: 0 }, tooltip: { trigger: "axis", valueFormatter: (v) => (v * 100).toFixed(1) + "%" },
      grid: { left: 36, right: 10, top: 36, bottom: 24, containLabel: true },
      xAxis: axis({ type: "category", data: labels }), yAxis: axis({ type: "value", axisLabel: { formatter: (v) => (v * 100).toFixed(0) + "%", color: C.text } }), series,
    });
    const data = [];
    (m.matrix || []).forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
    const c2 = chart($("#mc-heat"), {
      tooltip: { trigger: "item", formatter: (p) => `${p.value[1]} - ${p.value[0]} : ${(p.value[2] * 100).toFixed(1)}%` },
      grid: { left: 36, right: 10, top: 10, bottom: 30, containLabel: true },
      xAxis: axis({ type: "category", data: [0, 1, 2, 3, 4, 5], name: S.lang === "zh" ? "客" : "Away", splitArea: { show: false } }),
      yAxis: axis({ type: "category", data: [0, 1, 2, 3, 4, 5], name: S.lang === "zh" ? "主" : "Home" }),
      visualMap: { show: false, min: 0, max: Math.max(...data.map((d) => d[2])), inRange: { color: ["#061736", "#1d4fd8", "#5ee7ff"] } },
      series: [{ type: "heatmap", data, label: { show: true, color: "#e6f0ff", fontSize: 10, formatter: (p) => (p.value[2] * 100).toFixed(0) }, itemStyle: { borderColor: "#030b1f", borderWidth: 2 } }],
    });
    [c1, c2].forEach((c) => c && (c.__modal = true));
  }

  // ------------------------------------------------------------------ router & boot
  // The cloud job runs every 3 h; GitHub can start it late or skip it. Past this age, say the data is behind
  // instead of letting finished matches pass for current ones.
  const STALE_HOURS = 12;
  function freshness() {
    if (!S.meta) return;
    const when = fmtTime(S.meta.generated, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
    const age = (Date.now() - new Date(S.meta.generated).getTime()) / 3.6e6;
    const stale = age > STALE_HOURS;
    $("#update-text").textContent = `${t("updated")} ${when}`;
    $("#update-pill").classList.toggle("stale", stale);
    const note = $("#stale-note");
    note.hidden = !stale;
    note.textContent = stale ? t("stale", { time: when, h: Math.floor(age) }) : "";
  }
  function applyStatic() {
    document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
    $$("[data-i18n]").forEach((el) => (el.innerHTML = t(el.dataset.i18n)));
    $("#lang-btn").textContent = S.lang === "zh" ? "EN" : "中文";
    freshness();
  }
  function route() {
    if (!S.meta || !S.pred) return;  // data not loaded (boot shows the error)
    closeModal();
    disposeCharts();
    const h = location.hash.replace(/^#\/?/, "") || "home";
    const [name, arg] = h.split("/");
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#/" + (name === "team" ? "teams" : name)));
    $("#nav").classList.remove("open");
    const app = $("#app");
    (views[name] || views.home)(app, arg);
    window.scrollTo(0, 0);
  }
  $("#lang-btn").addEventListener("click", () => {
    S.lang = S.lang === "zh" ? "en" : "zh";
    try { localStorage.setItem("exi-lang", S.lang); } catch (e) { /* ignore */ }
    applyStatic();
    route();
  });
  $("#menu-btn").addEventListener("click", () => $("#nav").classList.toggle("open"));
  window.addEventListener("hashchange", route);

  async function boot() {
    applyStatic();
    try {
      const [meta, pred, results, perf, teams] = await Promise.all([
        getJSON("data/meta.json"), getJSON("data/predictions.json"), getJSON("data/results.json"),
        getJSON("data/performance.json"), getJSON("data/teams.json")]);
      Object.assign(S, { meta, pred, results, perf, teams });
    } catch (e) {
      $("#app").innerHTML = `<div class="panel empty"><b>Data unavailable</b>${esc(e.message)}<br>Run <code>python -m entropy_xi daily</code> and serve the <code>site/</code> folder over HTTP.</div>`;
      return;
    }
    applyStatic();
    route();
    setInterval(freshness, 10 * 60 * 1000);  // a tab left open keeps judging the data's age
  }

  // ------------------------------------------------------------------ animated network background
  (function net() {
    const cv = $("#bg-net");
    if (!cv || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = cv.getContext("2d");
    let W, H, pts, dpr;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = cv.width = innerWidth * dpr; H = cv.height = innerHeight * dpr;
      const n = Math.round(Math.min(90, (innerWidth * innerHeight) / 18000));
      pts = Array.from({ length: n }, () => ({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - 0.5) * 0.25 * dpr, vy: (Math.random() - 0.5) * 0.25 * dpr, r: (Math.random() * 1.6 + 0.6) * dpr }));
    };
    resize();
    addEventListener("resize", resize);
    const link = 140;
    const frame = () => {
      if (!document.hidden) {
        ctx.clearRect(0, 0, W, H);
        for (const p of pts) {
          p.x += p.vx; p.y += p.vy;
          if (p.x < 0 || p.x > W) p.vx *= -1;
          if (p.y < 0 || p.y > H) p.vy *= -1;
        }
        for (let i = 0; i < pts.length; i++) {
          for (let j = i + 1; j < pts.length; j++) {
            const a = pts[i], b = pts[j], dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy);
            if (d < link * dpr) {
              ctx.strokeStyle = `rgba(94,170,255,${(1 - d / (link * dpr)) * 0.35})`;
              ctx.lineWidth = dpr * 0.7;
              ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
            }
          }
        }
        for (const p of pts) {
          ctx.fillStyle = "rgba(140,220,255,.85)";
          ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
        }
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  })();

  boot();
})();
