(function () {
  const modal = document.querySelector('[data-modal="register-activity"]');
  const form = document.querySelector("[data-school-activity-form]");
  if (!modal || !form) return;

  const openers = document.querySelectorAll('[data-open-modal="register-activity"]');
  const closers = modal.querySelectorAll("[data-modal-close]");
  const firstField = modal.querySelector("input:not([type='hidden']), select, textarea");

  function setOpen(open) {
    modal.classList.toggle("is-open", open);
    modal.hidden = !open;
    document.body.classList.toggle("modal-open", open);
    if (open) firstField?.focus();
  }

  openers.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (window.location.search.includes("edit=")) {
        window.location.href = window.location.pathname;
        return;
      }
      document.querySelector("[data-workspace]")?.classList.remove("is-nav-open");
      setOpen(true);
    });
  });
  closers.forEach((el) => {
    el.addEventListener("click", () => {
      setOpen(false);
      if (window.location.search.includes("edit=")) {
        window.location.href = window.location.pathname;
      }
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      setOpen(false);
      if (window.location.search.includes("edit=")) {
        window.location.href = window.location.pathname;
      }
    }
  });

  if (modal.classList.contains("is-open")) setOpen(true);

  const datesInput = form.querySelector('input[name="activity_dates"]');
  const calendar = form.querySelector("[data-activity-calendar]");
  if (!datesInput || !calendar) return;

  const grid = calendar.querySelector("[data-cal-grid]");
  const label = calendar.querySelector("[data-cal-label]");
  const selectedWrap = form.querySelector("[data-selected-summary]");
  const selectedChips = form.querySelector("[data-selected-chips]");
  const dayNotesWrap = form.querySelector("[data-day-notes]");
  const dayNotesList = form.querySelector("[data-day-notes-list]");
  const notesNode = document.getElementById("school-activity-day-notes");

  let seededNotes = {};
  try {
    seededNotes = JSON.parse(notesNode?.textContent || "{}") || {};
  } catch (_err) {
    seededNotes = {};
  }

  const selected = new Set(
    (datesInput.value || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
  );

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let viewYear = today.getFullYear();
  let viewMonth = today.getMonth();
  const firstSelected = Array.from(selected).sort()[0];
  if (firstSelected) {
    const [y, m] = firstSelected.split("-").map(Number);
    viewYear = y;
    viewMonth = m - 1;
  }

  function isoFromParts(year, month, day) {
    const mm = String(month + 1).padStart(2, "0");
    const dd = String(day).padStart(2, "0");
    return `${year}-${mm}-${dd}`;
  }

  function formatLabel(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    return date.toLocaleDateString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  function syncHidden() {
    datesInput.value = Array.from(selected).sort().join(",");
  }

  function renderSelected() {
    const sorted = Array.from(selected).sort();
    selectedChips.innerHTML = "";
    if (!sorted.length) {
      selectedWrap.hidden = true;
      dayNotesWrap.hidden = true;
      dayNotesList.innerHTML = "";
      return;
    }

    selectedWrap.hidden = false;
    sorted.forEach((iso) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "school-activity-chip";
      chip.textContent = formatLabel(iso);
      chip.title = "Remove day";
      chip.addEventListener("click", () => {
        selected.delete(iso);
        syncHidden();
        renderSelected();
        renderCalendar();
      });
      selectedChips.appendChild(chip);
    });

    const previousNotes = { ...seededNotes };
    dayNotesList.querySelectorAll("[data-day-note]").forEach((field) => {
      previousNotes[field.dataset.dayNote] = field.value;
    });

    dayNotesList.innerHTML = "";
    if (sorted.length > 1) {
      dayNotesWrap.hidden = false;
      sorted.forEach((iso) => {
        const row = document.createElement("div");
        row.className = "field school-activity-day-note-row";
        const noteLabel = document.createElement("label");
        noteLabel.setAttribute("for", `day_description_${iso}`);
        noteLabel.textContent = formatLabel(iso);
        const input = document.createElement("input");
        input.type = "text";
        input.name = `day_description_${iso}`;
        input.id = `day_description_${iso}`;
        input.maxLength = 255;
        input.placeholder = "Short description for this day";
        input.dataset.dayNote = iso;
        input.value = previousNotes[iso] || "";
        row.appendChild(noteLabel);
        row.appendChild(input);
        dayNotesList.appendChild(row);
      });
    } else {
      dayNotesWrap.hidden = true;
    }
  }

  function renderCalendar() {
    grid.innerHTML = "";
    const first = new Date(viewYear, viewMonth, 1);
    const startPad = (first.getDay() + 6) % 7;
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    label.textContent = first.toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
    });

    for (let i = 0; i < startPad; i += 1) {
      const blank = document.createElement("span");
      blank.className = "school-activity-cal-cell is-empty";
      blank.setAttribute("aria-hidden", "true");
      grid.appendChild(blank);
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = isoFromParts(viewYear, viewMonth, day);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "school-activity-cal-cell";
      button.textContent = String(day);
      button.dataset.date = iso;
      button.setAttribute("aria-pressed", selected.has(iso) ? "true" : "false");
      if (selected.has(iso)) button.classList.add("is-selected");
      const cellDate = new Date(viewYear, viewMonth, day);
      if (cellDate.getTime() === today.getTime()) button.classList.add("is-today");
      button.addEventListener("click", () => {
        if (selected.has(iso)) selected.delete(iso);
        else selected.add(iso);
        syncHidden();
        renderSelected();
        renderCalendar();
      });
      grid.appendChild(button);
    }
  }

  calendar.querySelector("[data-cal-prev]").addEventListener("click", () => {
    viewMonth -= 1;
    if (viewMonth < 0) {
      viewMonth = 11;
      viewYear -= 1;
    }
    renderCalendar();
  });

  calendar.querySelector("[data-cal-next]").addEventListener("click", () => {
    viewMonth += 1;
    if (viewMonth > 11) {
      viewMonth = 0;
      viewYear += 1;
    }
    renderCalendar();
  });

  syncHidden();
  renderSelected();
  renderCalendar();
})();
