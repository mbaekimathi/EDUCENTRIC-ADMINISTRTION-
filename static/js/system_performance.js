(function () {
  function formatLatency(ms) {
    if (ms === null || ms === undefined) return "—";
    return `${ms} ms`;
  }

  function formatUpdatedAt(iso) {
    if (!iso) return "Updated just now";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "Updated just now";
    return `Updated ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  }

  function statusClass(status) {
    if (status === "healthy") return "is-ok";
    if (status === "degraded") return "is-warn";
    return "is-bad";
  }

  function meterClass(pct) {
    if (pct >= 90) return "is-bad";
    if (pct >= 80) return "is-warn";
    return "is-ok";
  }

  function latencyMeterClass(ms, warn, bad) {
    if (ms >= bad) return "is-bad";
    if (ms >= warn) return "is-warn";
    return "is-ok";
  }

  function latencyBarWidth(ms, warn, bad) {
    if (ms >= bad) return 100;
    if (ms >= warn) return 70;
    return Math.max(20, Math.min(60, Math.round(ms * 2)));
  }

  function readInitialSnapshot() {
    const node = document.getElementById("sys-perf-initial");
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  function userInitial(name) {
    return (name || "?").trim().charAt(0).toUpperCase();
  }

  function buildSparkline(values, width = 88, height = 28, pad = 2) {
    const cleaned = (values || []).filter((value) => value !== null && value !== undefined);
    if (!cleaned.length) return null;
    const series = cleaned.length === 1 ? [cleaned[0], cleaned[0]] : cleaned;
    const minValue = Math.min(...series);
    const maxValue = Math.max(...series);
    const span = Math.max(maxValue - minValue, 1);
    const plotWidth = width - pad * 2;
    const plotHeight = height - pad * 2;
    const points = series.map((value, index) => {
      const x = pad + (index / (series.length - 1)) * plotWidth;
      const y = pad + plotHeight - ((value - minValue) / span) * plotHeight;
      return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
    });
    const line = points.map((point) => `${point.x},${point.y}`).join(" ");
    const area = `${pad},${height - pad} ${line} ${width - pad},${height - pad}`;
    return { width, height, line, area };
  }

  function renderSparkline(trend, tone = "", large = false) {
    if (!trend) return "";
    return `
      <div class="sys-perf-sparkline${large ? " is-large" : ""}${tone ? ` ${tone}` : ""}" aria-hidden="true">
        <svg viewBox="0 0 ${trend.width} ${trend.height}" preserveAspectRatio="none">
          <polygon class="sys-perf-sparkline__area" points="${trend.area}"></polygon>
          <polyline class="sys-perf-sparkline__line" points="${trend.line}" fill="none"></polyline>
        </svg>
      </div>`;
  }

  function renderDeltaBadge(delta, unit = "") {
    if (!delta || delta.direction === "flat") return "";
    const suffix = unit === "ms" ? " ms" : unit === "%" ? "%" : "";
    const arrow = delta.direction === "up" ? "↑" : "↓";
    return `<span class="sys-perf-kpi__delta is-${delta.direction}">${arrow} ${delta.value}${suffix}</span>`;
  }

  function buildKpiCard(type, label, valueHtml, meterHtml, metaHtml, trendHtml = "", deltaHtml = "") {
    const iconAttrs = 'viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
    const icons = {
      db: `<svg ${iconAttrs}><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>`,
      cache: `<svg ${iconAttrs}><path d="M13 2 3 7v10l10 5 10-5V7L13 2z"/><path d="m3 7 10 5 10-5M13 12v10"/></svg>`,
      disk: `<svg ${iconAttrs}><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12h8M8 16h5"/></svg>`,
      users: `<svg ${iconAttrs}><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20a6 6 0 0 1 12 0M14 20a5 5 0 0 1 8 0"/></svg>`,
    };
    return `
      <article class="sys-perf-kpi sys-perf-kpi--${type}">
        <div class="sys-perf-kpi__icon" aria-hidden="true">${icons[type]}</div>
        <div class="sys-perf-kpi__body">
          <div class="sys-perf-kpi__head">
            <span class="sys-perf-kpi__label">${label}</span>
            ${deltaHtml || ""}
          </div>
          <strong class="sys-perf-kpi__value">${valueHtml}</strong>
          ${meterHtml || ""}
          ${trendHtml || ""}
          <span class="sys-perf-kpi__meta${metaHtml && metaHtml.includes("Unavailable") ? " is-bad" : ""}">${metaHtml}</span>
        </div>
      </article>`;
  }

  function renderStats(root, data) {
    const stats = root.querySelector("[data-sys-perf-stats]");
    if (!stats || !data) return;

    const db = data.database || {};
    const cacheInfo = data.cache || {};
    const storage = data.storage?.media || data.disk || {};
    const latency = data.latency?.summary || {};
    const sessions = data.active_sessions?.totals || {};
    const totalUsers = (sessions.employees || 0) + (sessions.students || 0) + (sessions.parents || 0);

    const dbValue = db.status === "ok" ? `${db.latency_ms}<small>ms</small>` : "—";
    const dbMeter = db.status === "ok"
      ? `<span class="sys-perf-kpi__meter ${latencyMeterClass(db.latency_ms || 0, 100, 200)}" aria-hidden="true"><span style="width: ${latencyBarWidth(db.latency_ms || 0, 100, 200)}%"></span></span>`
      : "";
    const dbMeta = db.status === "ok"
      ? `${db.name || db.engine || "database"}${db.version ? ` · ${db.version}` : ""}`
      : (db.error || "Check database connection");

    const cacheValue = cacheInfo.status === "ok" ? `${cacheInfo.latency_ms}<small>ms</small>` : "—";
    const cacheMeter = cacheInfo.status === "ok"
      ? `<span class="sys-perf-kpi__meter ${latencyMeterClass(cacheInfo.latency_ms || 0, 50, 100)}" aria-hidden="true"><span style="width: ${latencyBarWidth(cacheInfo.latency_ms || 0, 50, 100)}%"></span></span>`
      : "";
    const cacheMeta = cacheInfo.status === "ok"
      ? `${data.app?.cache_backend || "cache"} · avg ${formatLatency(latency.cache_avg_ms)}`
      : (cacheInfo.error || "Check cache service");

    const history = data.latency?.history || [];
    const deltas = data.kpi_deltas || {};
    const trends = data.kpi_trends || {
      db: buildSparkline(history.map((point) => point.db_ms)),
      cache: buildSparkline(history.map((point) => point.cache_ms)),
      disk: buildSparkline(history.map((point) => point.disk_pct)),
      sessions: buildSparkline(history.map((point) => point.sessions_total)),
    };

    stats.innerHTML = [
      buildKpiCard(
        "db",
        "Database",
        dbValue,
        dbMeter,
        dbMeta,
        renderSparkline(trends.db),
        renderDeltaBadge(deltas.db_ms, "ms")
      ),
      buildKpiCard(
        "cache",
        "Cache",
        cacheValue,
        cacheMeter,
        cacheMeta,
        renderSparkline(trends.cache, "is-cache"),
        renderDeltaBadge(deltas.cache_ms, "ms")
      ),
      buildKpiCard(
        "disk",
        "Disk usage",
        `${storage.used_pct ?? 0}<small>%</small>`,
        `<span class="sys-perf-kpi__meter ${meterClass(storage.used_pct || 0)}" aria-hidden="true"><span style="width: ${Math.min(100, storage.used_pct || 0)}%"></span></span>`,
        `${storage.free_gb ?? 0} GB free of ${storage.total_gb ?? 0} GB`,
        renderSparkline(trends.disk, "is-disk"),
        renderDeltaBadge(deltas.disk_pct, "%")
      ),
      buildKpiCard(
        "users",
        "Users in session",
        String(totalUsers),
        "",
        `${sessions.employees ?? 0} staff · ${sessions.students ?? 0} students · ${sessions.parents ?? 0} parents`,
        renderSparkline(trends.sessions, "is-users"),
        renderDeltaBadge(deltas.sessions_total)
      ),
    ].join("");
  }

  function renderUserCard(user, type, compact) {
    const avatarClass = type === "employee" ? "is-employee" : type === "student" ? "is-student" : "is-parent";
    if (type === "employee") {
      return `
        <article class="sys-perf-user-card${compact ? " is-compact" : ""}">
          <div class="sys-perf-user-card__avatar ${avatarClass}" aria-hidden="true">${userInitial(user.name)}</div>
          <div class="sys-perf-user-card__body">
            <strong>${user.name}</strong>
            <span class="sys-perf-user-card__meta">${user.role}</span>
            <span class="sys-perf-user-card__sub">Code ${user.employee_code}${user.devices > 1 ? ` · ${user.devices} devices` : ""} · ${user.last_seen_display || "Unknown"}</span>
          </div>
        </article>`;
    }
    if (type === "student") {
      return `
        <article class="sys-perf-user-card${compact ? " is-compact" : ""}">
          <div class="sys-perf-user-card__avatar ${avatarClass}" aria-hidden="true">${userInitial(user.name)}</div>
          <div class="sys-perf-user-card__body">
            <strong>${user.name}</strong>
            <span class="sys-perf-user-card__meta">${user.class_group}</span>
            <span class="sys-perf-user-card__sub">Adm ${user.admission_number}${!user.is_active || user.is_suspended ? " · inactive" : ""} · ${user.last_seen_display || "Unknown"}</span>
          </div>
        </article>`;
    }
    return `
      <article class="sys-perf-user-card${compact ? " is-compact" : ""}">
        <div class="sys-perf-user-card__avatar ${avatarClass}" aria-hidden="true">${userInitial(user.name)}</div>
        <div class="sys-perf-user-card__body">
          <strong>${user.name}</strong>
          <span class="sys-perf-user-card__meta">${user.phone_number}</span>
          <span class="sys-perf-user-card__sub">${user.children} linked student${user.children === 1 ? "" : "s"}${!user.is_active ? " · inactive" : ""} · ${user.last_seen_display || "Unknown"}</span>
        </div>
      </article>`;
  }

  function renderSessionList(users, emptyLabel, type, compact) {
    if (!users.length) return `<p class="sys-perf-empty">${emptyLabel}</p>`;
    return users.map((user) => renderUserCard(user, type, compact)).join("");
  }

  function renderSessionsSection(page, data) {
    const section = page.querySelector("[data-sys-perf-sessions-section]");
    if (!section) return;

    const activeSessions = data.active_sessions || {};
    const totals = activeSessions.totals || {};
    const truncated = activeSessions.truncated || {};
    const count = section.querySelector("[data-sys-perf-sessions-count]");
    const employeesNode = section.querySelector("[data-sys-perf-session-employees]");
    const studentsNode = section.querySelector("[data-sys-perf-session-students]");
    const parentsNode = section.querySelector("[data-sys-perf-session-parents]");

    if (count) {
      count.textContent = `${totals.employees || 0} staff · ${totals.students || 0} students · ${totals.parents || 0} parents`;
    }

    if (employeesNode) {
      const employees = activeSessions.employees || [];
      employeesNode.innerHTML =
        renderSessionList(employees, "No employees currently in session.", "employee", false) +
        (truncated.employees ? `<p class="sys-perf-empty">Showing first ${employees.length} employees.</p>` : "");
    }

    if (studentsNode) {
      const students = activeSessions.students || [];
      studentsNode.innerHTML =
        renderSessionList(students, "No students currently in session.", "student", false) +
        (truncated.students ? `<p class="sys-perf-empty">Showing first ${students.length} students.</p>` : "");
    }

    if (parentsNode) {
      const parents = activeSessions.parents || [];
      parentsNode.innerHTML =
        renderSessionList(parents, "No parents currently in session.", "parent", false) +
        (truncated.parents ? `<p class="sys-perf-empty">Showing first ${parents.length} parents.</p>` : "");
    }
  }

  function renderLineChart(chart) {
    if (!chart) return "";
    const grid = (chart.grid || [])
      .map(
        (tick) => `
        <line class="sys-perf-line-chart__grid" x1="${chart.plot_left}" y1="${tick.y}" x2="${chart.plot_right}" y2="${tick.y}"></line>
        <text class="sys-perf-line-chart__axis" x="28" y="${tick.y}" dy="0.35em" text-anchor="end">${tick.value}</text>`
      )
      .join("");
    const dbDots = (chart.db?.points || [])
      .map((point) => `<circle class="sys-perf-line-chart__dot is-db" cx="${point.x}" cy="${point.y}" r="3.4"></circle>`)
      .join("");
    const cacheDots = (chart.cache?.points || [])
      .map((point) => `<circle class="sys-perf-line-chart__dot is-cache" cx="${point.x}" cy="${point.y}" r="3.4"></circle>`)
      .join("");
    return `
      <div class="sys-perf-line-chart" data-sys-perf-line-chart>
        <svg viewBox="0 0 ${chart.width} ${chart.height}" role="img" aria-label="Response time line chart">
          ${grid}
          <polygon class="sys-perf-line-chart__area is-cache" points="${chart.cache.area}"></polygon>
          <polygon class="sys-perf-line-chart__area is-db" points="${chart.db.area}"></polygon>
          <polyline class="sys-perf-line-chart__line is-cache" points="${chart.cache.line}" fill="none"></polyline>
          <polyline class="sys-perf-line-chart__line is-db" points="${chart.db.line}" fill="none"></polyline>
          ${cacheDots}
          ${dbDots}
        </svg>
      </div>`;
  }

  function renderHero(page, data) {
    const hero = page.querySelector("[data-sys-perf-hero]");
    if (!hero) return;

    const health = data.health || {};
    const latency = data.latency?.summary || {};
    const storage = data.storage?.media || {};
    const stress = data.stress_timeline || {};
    const ring = hero.querySelector(".sys-perf-hero__score-ring");
    const ringValue = hero.querySelector(".sys-perf-hero__ring-value");
    const scoreNode = hero.querySelector("[data-sys-perf-health-score]");
    const labelNode = hero.querySelector("[data-sys-perf-health-label]");
    const updated = hero.querySelector("[data-sys-perf-updated]");

    if (ring) {
      ring.className = `sys-perf-hero__score-ring ${health.tone || statusClass(data.status)}`;
    }
    if (ringValue && health.dash !== undefined) {
      ringValue.setAttribute("stroke-dasharray", `${health.dash} ${health.gap}`);
    }
    if (scoreNode) scoreNode.textContent = health.score ?? "—";
    if (labelNode) labelNode.textContent = health.label || "—";
    if (updated) {
      updated.innerHTML = `<span class="sys-perf-sync-dot" aria-hidden="true"></span>${formatUpdatedAt(data.collected_at)}`;
    }

    const setHero = (selector, value) => {
      const node = hero.querySelector(selector);
      if (node) node.textContent = value;
    };
    setHero("[data-sys-perf-hero-db]", health.db_ms != null ? `${health.db_ms} ms` : "—");
    setHero("[data-sys-perf-hero-cache]", health.cache_ms != null ? `${health.cache_ms} ms` : "—");
    setHero("[data-sys-perf-hero-disk]", `${health.disk_pct ?? 0}%`);
    setHero("[data-sys-perf-hero-users]", String(health.active_users ?? 0));
    setHero("[data-sys-perf-hero-peak]", stress.peak ? String(stress.peak.score) : "—");
    const peakMeta = hero.querySelector("[data-sys-perf-hero-peak]")?.nextElementSibling;
    if (peakMeta) {
      peakMeta.textContent = (stress.events || []).length
        ? `${stress.events.length} events logged`
        : "No stress events";
    }
    const samplesMeta = hero.querySelector("[data-sys-perf-hero-users]")?.nextElementSibling;
    if (samplesMeta) {
      samplesMeta.textContent = `${latency.samples || 0} trend samples`;
    }
    const diskMeta = hero.querySelector("[data-sys-perf-hero-disk]")?.nextElementSibling;
    if (diskMeta) {
      diskMeta.textContent = `${storage.free_gb ?? 0} GB free`;
    }
  }

  function renderTrendCards(page, data) {
    const grid = page.querySelector("[data-sys-perf-trend-grid]");
    const count = page.querySelector("[data-sys-perf-trend-count]");
    if (!grid) return;

    const cards = data.trend_cards || [];
    if (count) {
      count.textContent = `${data.latency?.summary?.samples || 0} samples`;
    }
    grid.innerHTML = cards
      .map((card) => {
        const delta =
          card.delta && card.delta.direction !== "flat"
            ? `<span class="sys-perf-trend-card__delta is-${card.delta.direction}">${card.delta.direction === "up" ? "↑" : "↓"} ${card.delta.value}${card.unit === "ms" ? " ms" : card.unit === "%" ? "%" : ""}</span>`
            : "";
        const unitSuffix = card.unit === "ms" ? "<small>ms</small>" : card.unit === "%" ? "<small>%</small>" : "";
        return `
          <article class="sys-perf-trend-card ${card.tone}">
            <div class="sys-perf-trend-card__head">
              <span class="sys-perf-trend-card__label">${card.label}</span>
              ${delta}
            </div>
            <strong class="sys-perf-trend-card__value">${card.latest ?? "—"}${unitSuffix}</strong>
            ${renderSparkline(card.trend, card.tone, true)}
          </article>`;
      })
      .join("");
  }

  function renderLatencySection(page, data) {
    const section = page.querySelector("[data-sys-perf-latency-section]");
    const lineWrap = page.querySelector("[data-sys-perf-line-chart-wrap]");
    const chart = page.querySelector("[data-sys-perf-latency-chart]");
    const count = page.querySelector("[data-sys-perf-latency-count]");
    const history = data.latency?.history || [];
    if (!section) return;

    if (!history.length) {
      section.hidden = true;
      return;
    }

    section.hidden = false;
    if (lineWrap && data.latency?.chart) {
      lineWrap.innerHTML = renderLineChart(data.latency.chart);
    } else if (chart) {
      chart.innerHTML = history
        .map(
          (point) => `
          <div class="sys-perf-latency-bar" title="DB ${point.db_ms} ms · Cache ${point.cache_ms} ms">
            <span class="sys-perf-latency-bar-db" style="height: ${point.db_height || 0}%"></span>
            <span class="sys-perf-latency-bar-cache" style="height: ${point.cache_height || 0}%"></span>
          </div>`
        )
        .join("");
    }

    if (count) {
      const samples = data.latency?.summary?.samples || history.length;
      count.textContent = `${samples} sample${samples === 1 ? "" : "s"}`;
    }
  }

  function renderDataTrend(active, total) {
    if (!total) return "";
    const width = Math.min(100, Math.round((active / total) * 100));
    return `<span class="sys-perf-data-row__trend" aria-hidden="true"><span style="width: ${width}%"></span></span>`;
  }

  function renderCountsSection(page, data) {
    const countsNode = page.querySelector("[data-sys-perf-counts]");
    const operationsNode = page.querySelector("[data-sys-perf-operations]");
    const counts = data.counts || {};
    const operations = data.operations || {};

    if (countsNode) {
      countsNode.innerHTML = `
        <article class="sys-perf-data-row">
          <div>
            <strong>Students</strong>
            <span class="sys-perf-data-row__sub">${counts.students_inactive || 0} inactive · ${operations.portal_ready_students || 0} portal-ready</span>
            ${renderDataTrend(counts.students_active || 0, counts.students_total || 0)}
          </div>
          <span class="sys-perf-data-row__value">${counts.students_active || 0} / ${counts.students_total || 0}</span>
        </article>
        <article class="sys-perf-data-row">
          <div>
            <strong>Employees</strong>
            <span class="sys-perf-data-row__sub">${counts.employees_pending || 0} pending · ${operations.employees_suspended || 0} suspended</span>
            ${renderDataTrend(counts.employees_active || 0, counts.employees_total || 0)}
          </div>
          <span class="sys-perf-data-row__value">${counts.employees_active || 0} / ${counts.employees_total || 0}</span>
        </article>
        <article class="sys-perf-data-row">
          <div><strong>Parents</strong></div>
          <span class="sys-perf-data-row__value">${counts.parents_total || 0}</span>
        </article>
        <article class="sys-perf-data-row">
          <div><strong>Classes</strong><span class="sys-perf-data-row__sub">${counts.learning_areas || 0} learning areas</span></div>
          <span class="sys-perf-data-row__value">${counts.classes_active || 0}</span>
        </article>
        <article class="sys-perf-data-row">
          <div><strong>Exam records</strong><span class="sys-perf-data-row__sub">${counts.attendance_sessions || 0} attendance sessions</span></div>
          <span class="sys-perf-data-row__value">${counts.exam_generations || 0}</span>
        </article>`;
    }

    if (operationsNode) {
      if (operationsNode.classList.contains("sys-perf-ops-grid")) {
        operationsNode.innerHTML = `
          <article class="sys-perf-ops-card">
            <span class="sys-perf-ops-card__label">Admissions this month</span>
            <strong>${operations.students_admitted_this_month || 0}</strong>
          </article>
          <article class="sys-perf-ops-card">
            <span class="sys-perf-ops-card__label">Attendance sessions this week</span>
            <strong>${operations.attendance_sessions_this_week || 0}</strong>
          </article>
          <article class="sys-perf-ops-card">
            <span class="sys-perf-ops-card__label">Pending employee approvals</span>
            <strong>${counts.employees_pending || 0}</strong>
          </article>
          <article class="sys-perf-ops-card">
            <span class="sys-perf-ops-card__label">Portal-ready students</span>
            <strong>${operations.portal_ready_students || 0}</strong>
          </article>`;
      } else {
        operationsNode.innerHTML = `
          <article class="sys-perf-data-row">
            <div><strong>Admissions this month</strong></div>
            <span class="sys-perf-data-row__value">${operations.students_admitted_this_month || 0}</span>
          </article>
          <article class="sys-perf-data-row">
            <div><strong>Attendance sessions this week</strong></div>
            <span class="sys-perf-data-row__value">${operations.attendance_sessions_this_week || 0}</span>
          </article>
          <article class="sys-perf-data-row">
            <div><strong>Pending employee approvals</strong></div>
            <span class="sys-perf-data-row__value">${counts.employees_pending || 0}</span>
          </article>`;
      }
    }
  }

  function renderTablesSection(page, data) {
    const section = page.querySelector("[data-sys-perf-tables-section]");
    const tablesNode = page.querySelector("[data-sys-perf-tables]");
    const tables = data.tables || [];
    if (!section || !tablesNode) return;

    if (!tables.length) {
      section.hidden = true;
      return;
    }

    section.hidden = false;
    if (tablesNode.classList.contains("sys-perf-table-list")) {
      tablesNode.innerHTML = tables
        .map(
          (table) => `
          <article class="sys-perf-table-row">
            <div class="sys-perf-table-row__copy">
              <strong class="sys-perf-table-row__name">${table.name}</strong>
              <span class="sys-perf-table-row__meta">
                ${Number(table.rows || 0).toLocaleString()} rows
                ${table.size_mb !== null && table.size_mb !== undefined ? ` · ${table.size_mb} MB` : ""}
              </span>
              <span class="sys-perf-table-row__bar" aria-hidden="true"><span style="width: ${table.bar_pct || 0}%"></span></span>
            </div>
            <span class="sys-perf-table-row__value">${table.bar_pct || 0}%</span>
          </article>`
        )
        .join("");
      return;
    }

    tablesNode.innerHTML = tables
      .map(
        (table) => `
        <article class="sys-perf-table-card">
          <strong class="sys-perf-table-card__name">${table.name}</strong>
          <span class="sys-perf-table-card__rows">${Number(table.rows || 0).toLocaleString()} rows</span>
          ${table.size_mb !== null && table.size_mb !== undefined ? `<span class="sys-perf-table-card__size">${table.size_mb} MB</span>` : ""}
        </article>`
      )
      .join("");
  }

  function renderEnvironment(page, data) {
    const setText = (selector, value) => {
      const node = page.querySelector(selector);
      if (node) node.textContent = value;
    };
    const db = data.database || {};
    const app = data.app || {};
    const storage = data.storage?.media || {};

    setText(
      "[data-sys-perf-app-db]",
      `${db.name || "—"} @ ${db.host || "localhost"}${db.port ? `:${db.port}` : ""}`
    );
    setText("[data-sys-perf-app-cache]", app.cache_backend || "—");
    setText("[data-sys-perf-app-session]", app.session_engine || "—");
    setText(
      "[data-sys-perf-app-runtime]",
      `Django ${app.django_version || "—"} · Python ${app.python_version || "—"}`
    );
    setText("[data-sys-perf-app-timezone]", app.timezone || "—");
    setText("[data-sys-perf-app-debug]", app.debug ? "On" : "Off");
    setText("[data-sys-perf-disk-path]", storage.path || "—");
    setText("[data-sys-perf-app-platform]", app.platform || "—");
  }

  function formatEventTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function renderStressSessionColumn(title, users, type) {
    return `
      <section class="sys-perf-session-col">
        <h4>${title}</h4>
        <div class="sys-perf-user-list">
          ${renderSessionList(users, "None", type, true)}
        </div>
      </section>`;
  }

  function renderStressEvent(event) {
    const sessions = event.sessions || {};
    const totals = sessions.totals || {};
    const chips = (event.reasons || [])
      .map((reason) => `<span class="sys-perf-chip" title="${reason.detail}">${reason.label}</span>`)
      .join("");
    const metrics = event.metrics || {};

    return `
      <article class="sys-perf-stress-event${event.is_peak ? " is-peak" : ""} is-${event.severity}" data-stress-event>
        <div class="sys-perf-stress-event__rail" aria-hidden="true"></div>
        <div class="sys-perf-stress-event__content">
          <header class="sys-perf-stress-event__head">
            <div>
              <time>${event.at_display || formatEventTime(event.at)}</time>
              ${event.is_peak ? '<span class="sys-perf-stress-badge">Peak</span>' : ""}
            </div>
            <span class="sys-perf-stress-score">Score ${event.score}</span>
          </header>
          <details class="sys-perf-stress-details">
            <summary class="sys-perf-stress-details__summary">
              <span class="sys-perf-stress-details__label">View details</span>
              <span class="sys-perf-stress-details__hint">${event.summary || ""}</span>
            </summary>
            <div class="sys-perf-stress-details__body">
              <p class="sys-perf-stress-event__summary">${event.summary || ""}</p>
              <div class="sys-perf-chip-row">${chips}</div>
              <div class="sys-perf-metric-chips">
                <span class="sys-perf-metric-chip"><em>DB</em> ${metrics.db_ms ?? "—"} ms</span>
                <span class="sys-perf-metric-chip"><em>Cache</em> ${metrics.cache_ms ?? "—"} ms</span>
                <span class="sys-perf-metric-chip"><em>Disk</em> ${metrics.disk_pct ?? "—"}%</span>
                <span class="sys-perf-metric-chip"><em>Sessions</em> ${metrics.sessions_scanned ?? 0}</span>
              </div>
              <div class="sys-perf-stress-sessions">
                <h4 class="sys-perf-stress-sessions__title">
                  Users in session —
                  ${totals.employees || 0} staff,
                  ${totals.students || 0} students,
                  ${totals.parents || 0} parents
                </h4>
                <div class="sys-perf-sessions-grid is-nested">
                  ${renderStressSessionColumn("Employees", sessions.employees || [], "employee")}
                  ${renderStressSessionColumn("Students", sessions.students || [], "student")}
                  ${renderStressSessionColumn("Parents", sessions.parents || [], "parent")}
                </div>
              </div>
            </div>
          </details>
        </div>
      </article>`;
  }

  function renderStressSection(page, data) {
    const section = page.querySelector("[data-sys-perf-stress-section]");
    if (!section) return;

    const timeline = data.stress_timeline || {};
    const events = timeline.events || [];
    const peak = timeline.peak;
    const count = section.querySelector("[data-sys-perf-stress-count]");
    const peakNode = section.querySelector("[data-sys-perf-stress-peak]");
    const timelineNode = section.querySelector("[data-sys-perf-stress-timeline]");

    if (count) {
      count.textContent = events.length
        ? `${events.length} recorded`
        : "No stress events yet";
    }

    if (peakNode) {
      if (peak) {
        peakNode.hidden = false;
        peakNode.innerHTML = `
          <div class="sys-perf-stress-peak__score">
            <span class="sys-perf-stress-peak__label">Highest load</span>
            <strong>${peak.score}</strong>
            ${renderSparkline(timeline.score_chart, "is-stress", true)}
          </div>
          <div class="sys-perf-stress-peak__copy">
            <p>${peak.summary || ""}</p>
            <span class="sys-perf-stress-peak__time">${peak.at_display || formatEventTime(peak.at)}</span>
          </div>`;
      } else {
        peakNode.hidden = true;
        peakNode.innerHTML = "";
      }
    }

    if (timelineNode) {
      timelineNode.innerHTML = events.length
        ? events.map(renderStressEvent).join("")
        : `<p class="sys-perf-empty sys-perf-empty--panel">No peak stress moments recorded yet. Events are captured when latency, disk usage, or concurrent users push the system into an elevated load state.</p>`;
    }
  }

  function renderStatus(root, data) {
    const pill = root.querySelector("[data-sys-perf-status-pill]");
    const label = root.querySelector("[data-sys-perf-status-label]");
    const updated = root.querySelector("[data-sys-perf-updated]");
    if (pill) {
      pill.hidden = false;
      pill.className = `sys-perf-live ${statusClass(data.status)}`;
    }
    if (label) {
      const text =
        data.status === "healthy"
          ? "Healthy"
          : data.status === "degraded"
            ? "Degraded"
            : "Critical";
      label.textContent = text;
    }
    if (updated) {
      updated.innerHTML = `<span class="sys-perf-sync-dot" aria-hidden="true"></span>${formatUpdatedAt(data.collected_at)}`;
    }
  }

  function renderFullPage(root, data) {
    if (root.classList.contains("is-compact")) return;
    const page = root.closest(".sys-perf-page") || root.closest(".exam-tool-page");
    if (!page) return;
    renderHero(page, data);
    renderTrendCards(page, data);
    renderLatencySection(page, data);
    renderSessionsSection(page, data);
    renderStressSection(page, data);
    renderCountsSection(page, data);
    renderTablesSection(page, data);
    renderEnvironment(page, data);
  }

  function initSectionNav(page) {
    const nav = page.querySelector(".sys-perf-section-nav");
    if (!nav) return;
    const links = [...nav.querySelectorAll(".sys-perf-section-nav__link")];
    links.forEach((link) => {
      link.addEventListener("click", () => {
        links.forEach((item) => item.classList.remove("is-active"));
        link.classList.add("is-active");
      });
    });
  }

  function bindRefresh(page, root) {
    const button = page.querySelector("[data-sys-perf-refresh]");
    if (!button) return;
    button.addEventListener("click", () => refreshWidget(root));
  }

  async function refreshWidget(root) {
    const url = root.dataset.metricsUrl;
    if (!url) return;

    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`Metrics request failed (${response.status})`);
      const data = await response.json();
      renderStats(root, data);
      renderStatus(root, data);
      renderFullPage(root, data);
    } catch (error) {
      const updated = root.querySelector("[data-sys-perf-updated]");
      if (updated) updated.textContent = "Unable to refresh live metrics";
    }
  }

  function initWidget(root) {
    const page = root.closest(".sys-perf-page") || root.closest(".exam-tool-page");
    const initial = readInitialSnapshot();
    if (initial) {
      renderStats(root, initial);
      renderStatus(root, initial);
      renderFullPage(root, initial);
    }

    if (page) {
      initSectionNav(page);
      bindRefresh(page, root);
    }

    const interval = Number.parseInt(root.dataset.pollInterval || "30000", 10);
    if (interval > 0) {
      window.setInterval(() => refreshWidget(root), interval);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-system-performance]").forEach(initWidget);
  });
})();
