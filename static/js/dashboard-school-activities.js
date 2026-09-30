(function () {
  const root = document.querySelector("[data-dash-activities]");
  const modal = document.querySelector('[data-modal="dash-activity"]');
  const dataNode = document.getElementById("dashboard-activities-data");
  if (!root || !modal || !dataNode) return;

  let activities = [];
  try {
    activities = JSON.parse(dataNode.textContent || "[]");
  } catch (_err) {
    activities = [];
  }
  const byId = Object.fromEntries(activities.map((item) => [String(item.id), item]));

  const titleEl = modal.querySelector("[data-activity-title]");
  const badgeEl = modal.querySelector("[data-activity-badge]");
  const rangeEl = modal.querySelector("[data-activity-range]");
  const descriptionBlock = modal.querySelector("[data-activity-description-block]");
  const descriptionEl = modal.querySelector("[data-activity-description]");
  const gradesEl = modal.querySelector("[data-activity-grades]");
  const daysEl = modal.querySelector("[data-activity-days]");
  const createdByEl = modal.querySelector("[data-activity-created-by]");
  const createdAtEl = modal.querySelector("[data-activity-created-at]");

  function setOpen(open) {
    modal.classList.toggle("is-open", open);
    modal.hidden = !open;
    document.body.classList.toggle("modal-open", open);
  }

  function fillModal(activity) {
    titleEl.textContent = activity.title || "Activity";
    badgeEl.textContent = activity.is_current
      ? "Current activity"
      : "Upcoming activity";
    rangeEl.textContent = activity.date_range || "";

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
      grades.forEach((name) => {
        const chip = document.createElement("span");
        chip.className = "dash-activity-grade-chip";
        chip.textContent = name;
        gradesEl.appendChild(chip);
      });
    }

    daysEl.innerHTML = "";
    const days = activity.days || [];
    if (!days.length) {
      daysEl.innerHTML = '<p class="dash-activity-muted">No dates scheduled</p>';
    } else {
      days.forEach((day) => {
        const row = document.createElement("article");
        row.className = "dash-activity-day";
        const when = document.createElement("strong");
        when.textContent = day.label || day.date || "";
        row.appendChild(when);
        if (day.description) {
          const note = document.createElement("p");
          note.textContent = day.description;
          row.appendChild(note);
        } else {
          const note = document.createElement("p");
          note.className = "dash-activity-muted";
          note.textContent = "No day description";
          row.appendChild(note);
        }
        daysEl.appendChild(row);
      });
    }

    createdByEl.textContent = activity.created_by || "—";
    createdAtEl.textContent = activity.created_at || "—";
  }

  root.querySelectorAll("[data-open-activity]").forEach((button) => {
    button.addEventListener("click", () => {
      const activity = byId[String(button.dataset.openActivity)];
      if (!activity) return;
      fillModal(activity);
      document.querySelector("[data-workspace]")?.classList.remove("is-nav-open");
      setOpen(true);
      titleEl.focus?.();
    });
  });

  modal.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", () => setOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      setOpen(false);
    }
  });
})();
