(function () {
  const root = document.querySelector("[data-dash-activities]");
  const activityModal = document.querySelector('[data-modal="dash-activity"]');
  const listModal = document.querySelector('[data-modal="dash-upcoming-list"]');
  const dataNode = document.getElementById("dashboard-activities-data");
  if (!root || !activityModal || !listModal || !dataNode) return;

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MODAL_CLOSE_MS = prefersReducedMotion ? 0 : 280;

  let activities = [];
  try {
    activities = JSON.parse(dataNode.textContent || "[]");
  } catch (_err) {
    activities = [];
  }
  const byId = Object.fromEntries(activities.map((item) => [String(item.id), item]));
  const upcoming = activities.filter((item) => item.is_upcoming);

  const activityPanel = activityModal.querySelector("[data-activity-panel]");
  const activityBody = activityModal.querySelector("[data-activity-body]");
  const titleEl = activityModal.querySelector("[data-activity-title]");
  const badgeEl = activityModal.querySelector("[data-activity-badge]");
  const badgeWrap = activityModal.querySelector("[data-activity-badge-wrap]");
  const rangeEl = activityModal.querySelector("[data-activity-range]");
  const statTiming = activityModal.querySelector("[data-activity-stat-timing]");
  const statDays = activityModal.querySelector("[data-activity-stat-days]");
  const statGrades = activityModal.querySelector("[data-activity-stat-grades]");
  const descriptionBlock = activityModal.querySelector("[data-activity-description-block]");
  const descriptionEl = activityModal.querySelector("[data-activity-description]");
  const gradesEl = activityModal.querySelector("[data-activity-grades]");
  const daysEl = activityModal.querySelector("[data-activity-days]");
  const createdByEl = activityModal.querySelector("[data-activity-created-by]");
  const createdAtEl = activityModal.querySelector("[data-activity-created-at]");
  const listBody = listModal.querySelector("[data-upcoming-list]");
  const liveCountEl = listModal.querySelector("[data-upcoming-live-count]");

  function anyModalOpen() {
    return activityModal.classList.contains("is-open") || listModal.classList.contains("is-open");
  }

  function syncBodyScrollLock() {
    document.body.classList.toggle("modal-open", anyModalOpen());
  }

  function setModalOpen(modal, open) {
    if (open) {
      modal.hidden = false;
      modal.classList.remove("is-closing");
      requestAnimationFrame(() => {
        modal.classList.add("is-open");
        syncBodyScrollLock();
      });
      return;
    }

    if (!modal.classList.contains("is-open")) {
      modal.hidden = true;
      syncBodyScrollLock();
      return;
    }

    modal.classList.remove("is-open");
    modal.classList.add("is-closing");
    window.setTimeout(() => {
      modal.classList.remove("is-closing");
      modal.hidden = true;
      listModal.classList.remove("is-submerged");
      syncBodyScrollLock();
    }, MODAL_CLOSE_MS);
  }

  function daysUntilLabel(activity) {
    const days = activity.days_until_start;
    if (days === 0) return "Starts today";
    if (days === 1) return "Starts tomorrow";
    if (typeof days === "number") return `Starts in ${days} days`;
    return "Upcoming";
  }

  function activityTone(activity) {
    if (activity.is_current) return "live";
    if (activity.starts_within_three_days) return "soon";
    return "upcoming";
  }

  function runContentEnterAnimation() {
    if (prefersReducedMotion || !activityBody) return;
    activityBody.classList.remove("is-entering");
    void activityBody.offsetWidth;
    activityBody.classList.add("is-entering");
  }

  function fillModal(activity) {
    const tone = activityTone(activity);
    activityPanel.dataset.activityTone = tone;
    badgeWrap?.classList.toggle("is-pulse", tone === "soon" || tone === "live");

    titleEl.textContent = activity.title || "Activity";
    if (activity.is_current) {
      badgeEl.textContent = "Live now";
    } else if (activity.starts_within_three_days) {
      badgeEl.textContent = daysUntilLabel(activity);
    } else {
      badgeEl.textContent = "Upcoming activity";
    }
    rangeEl.textContent = activity.date_range || "";

    const dayCount = activity.day_count || 0;
    const gradeCount = activity.grade_count || 0;
    statDays.textContent = `${dayCount} day${dayCount === 1 ? "" : "s"}`;
    statGrades.textContent = `${gradeCount} grade${gradeCount === 1 ? "" : "s"}`;

    if (activity.is_current) {
      statTiming.hidden = false;
      statTiming.textContent = "Happening now";
    } else if (typeof activity.days_until_start === "number") {
      statTiming.hidden = false;
      statTiming.textContent = daysUntilLabel(activity);
    } else {
      statTiming.hidden = true;
      statTiming.textContent = "";
    }

    const description = (activity.description || "").trim();
    if (description) {
      descriptionBlock.hidden = false;
      descriptionEl.textContent = description;
    } else {
      descriptionBlock.hidden = true;
      descriptionEl.textContent = "";
    }

    gradesEl.innerHTML = "";
    const grades = activity.grades || [];
    if (!grades.length) {
      gradesEl.innerHTML = '<p class="dash-activity-muted">No grades selected</p>';
    } else {
      grades.forEach((name, index) => {
        const chip = document.createElement("span");
        chip.className = "dash-activity-grade-chip";
        chip.style.setProperty("--chip-i", String(index));
        chip.textContent = name;
        gradesEl.appendChild(chip);
      });
    }

    daysEl.innerHTML = "";
    const days = activity.days || [];
    if (!days.length) {
      daysEl.innerHTML = '<p class="dash-activity-muted">No dates scheduled</p>';
    } else {
      days.forEach((day, index) => {
        const row = document.createElement("article");
        row.className = "dash-activity-day";
        row.style.setProperty("--day-i", String(index));

        const marker = document.createElement("span");
        marker.className = "dash-activity-day-marker";
        marker.setAttribute("aria-hidden", "true");

        const content = document.createElement("div");
        content.className = "dash-activity-day-content";

        const when = document.createElement("strong");
        when.textContent = day.label || day.date || "";
        content.appendChild(when);

        if (day.description) {
          const note = document.createElement("p");
          note.textContent = day.description;
          content.appendChild(note);
        } else {
          const note = document.createElement("p");
          note.className = "dash-activity-muted";
          note.textContent = "No day description";
          content.appendChild(note);
        }

        row.append(marker, content);
        daysEl.appendChild(row);
      });
    }

    createdByEl.textContent = activity.created_by || "—";
    createdAtEl.textContent = activity.created_at || "—";
    runContentEnterAnimation();
  }

  function openActivityDetail(activity, fromList) {
    if (!activity) return;
    fillModal(activity);
    document.querySelector("[data-workspace]")?.classList.remove("is-nav-open");
    if (fromList && listModal.classList.contains("is-open")) {
      listModal.classList.add("is-submerged");
    } else {
      setModalOpen(listModal, false);
    }
    setModalOpen(activityModal, true);
    titleEl.focus?.();
  }

  function renderUpcomingList() {
    listBody.innerHTML = "";
    const count = upcoming.length;
    if (liveCountEl) {
      liveCountEl.textContent = count
        ? `${count} upcoming event${count === 1 ? "" : "s"} ready to explore`
        : "Nothing scheduled ahead";
    }

    if (!count) {
      listBody.innerHTML =
        '<p class="dash-upcoming-list-empty">No upcoming activities scheduled.</p>';
      return;
    }

    upcoming.forEach((activity, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "dash-upcoming-list-item";
      if (activity.starts_within_three_days) row.classList.add("is-soon");
      row.style.setProperty("--item-i", String(index));
      row.setAttribute("role", "listitem");
      row.dataset.openActivity = String(activity.id);

      const leading = document.createElement("span");
      leading.className = "dash-upcoming-list-item-leading";
      leading.setAttribute("aria-hidden", "true");
      leading.textContent = String(index + 1).padStart(2, "0");

      const main = document.createElement("span");
      main.className = "dash-upcoming-list-item-main";

      const badge = document.createElement("span");
      badge.className = "dash-upcoming-list-item-badge";
      badge.textContent = activity.starts_within_three_days
        ? daysUntilLabel(activity)
        : "Upcoming";

      const title = document.createElement("strong");
      title.className = "dash-upcoming-list-item-title is-uppercase";
      title.textContent = activity.title || "Activity";

      const range = document.createElement("span");
      range.className = "dash-upcoming-list-item-range";
      range.textContent = activity.date_range || "";

      const meta = document.createElement("span");
      meta.className = "dash-upcoming-list-item-meta";
      const gradeCount = activity.grade_count || 0;
      const dayCount = activity.day_count || 0;
      meta.textContent = `${gradeCount} grade${gradeCount === 1 ? "" : "s"} · ${dayCount} day${dayCount === 1 ? "" : "s"}`;

      main.append(badge, title, range, meta);

      const chevron = document.createElement("span");
      chevron.className = "dash-upcoming-list-item-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "→";

      row.append(leading, main, chevron);
      row.addEventListener("click", () => openActivityDetail(activity, true));
      listBody.appendChild(row);
    });

    listBody.classList.remove("is-stagger");
    void listBody.offsetWidth;
    listBody.classList.add("is-stagger");
  }

  root.querySelectorAll("[data-open-activity]").forEach((button) => {
    button.addEventListener("click", () => {
      openActivityDetail(byId[String(button.dataset.openActivity)], false);
    });
  });

  root.querySelector("[data-open-upcoming-list]")?.addEventListener("click", () => {
    renderUpcomingList();
    document.querySelector("[data-workspace]")?.classList.remove("is-nav-open");
    setModalOpen(activityModal, false);
    setModalOpen(listModal, true);
    listModal.querySelector("#dash-upcoming-list-title")?.focus?.();
  });

  document.querySelectorAll("[data-scroll-to-activities]").forEach((button) => {
    button.addEventListener("click", () => {
      root.scrollIntoView({ behavior: "smooth", block: "start" });
      root.classList.add("is-highlighted");
      window.setTimeout(() => root.classList.remove("is-highlighted"), 1800);
    });
  });

  activityModal.querySelectorAll('[data-modal-close="activity"]').forEach((el) => {
    el.addEventListener("click", () => {
      if (listModal.classList.contains("is-submerged")) {
        setModalOpen(activityModal, false);
        listModal.classList.remove("is-submerged");
        setModalOpen(listModal, true);
        return;
      }
      setModalOpen(activityModal, false);
    });
  });

  listModal.querySelectorAll('[data-modal-close="upcoming-list"]').forEach((el) => {
    el.addEventListener("click", () => setModalOpen(listModal, false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (activityModal.classList.contains("is-open")) {
      if (listModal.classList.contains("is-submerged")) {
        setModalOpen(activityModal, false);
        listModal.classList.remove("is-submerged");
        setModalOpen(listModal, true);
      } else {
        setModalOpen(activityModal, false);
      }
    } else if (listModal.classList.contains("is-open")) {
      setModalOpen(listModal, false);
    }
  });
})();
