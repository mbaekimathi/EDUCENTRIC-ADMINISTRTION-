/**
 * Student register search only. Edit modal lives in
 * templates/employees/includes/student_edit_modal_script.html
 * so it deploys with the app HTML (local + hosted).
 */
(function () {
  const root = document.querySelector("[data-student-register-search]");
  if (!root) return;

  const input = root.querySelector("[data-student-register-search-input]");
  const clearButton = root.querySelector("[data-student-register-search-clear]");
  const status = root.querySelector("[data-student-register-search-status]");
  const emptyMessage = document.querySelector("[data-student-register-search-empty]");
  const directory = document.querySelector("[data-student-directory]");
  const panel = root.querySelector("[data-student-register-search-panel]");
  const panelTitle = root.querySelector("[data-student-register-search-panel-title]");
  const results = root.querySelector("[data-student-register-search-results]");
  const rows = Array.from(document.querySelectorAll("[data-student-row]"));
  const cards = Array.from(document.querySelectorAll(".student-class-card"));
  const levelBlocks = Array.from(document.querySelectorAll(".student-level-block"));
  const searchUrl = root.dataset.studentSearchUrl || "";
  const selectedLevel = (root.dataset.selectedLevel || "").toUpperCase();
  const totalCount = rows.length;
  let searchTimer = null;
  let searchToken = 0;

  function normalize(value) {
    return (value || "").trim().toLowerCase();
  }

  function rowHaystack(row) {
    return normalize(row.dataset.search);
  }

  function updateUrl(query) {
    const url = new URL(window.location.href);
    const trimmed = (query || "").trim();
    if (trimmed) url.searchParams.set("q", trimmed);
    else url.searchParams.delete("q");
    window.history.replaceState({}, "", url);
  }

  function updateCardVisibility() {
    cards.forEach((card) => {
      const visibleRows = card.querySelectorAll("[data-student-row]:not([hidden])");
      card.hidden = visibleRows.length === 0;
      const countChip = card.querySelector(".student-count-chip.is-quiet");
      if (countChip) {
        countChip.textContent = `${visibleRows.length} enrolled`;
      }
    });
    levelBlocks.forEach((block) => {
      const visibleCards = block.querySelectorAll(".student-class-card:not([hidden])");
      block.hidden = visibleCards.length === 0;
      const countChip = block.querySelector(".student-level-header .student-count-chip");
      if (countChip) {
        const visibleRows = block.querySelectorAll("[data-student-row]:not([hidden])");
        countChip.textContent = `${visibleRows.length} student${visibleRows.length === 1 ? "" : "s"}`;
      }
    });
  }

  function setStatus(visibleCount, query) {
    if (!status) return;
    const trimmed = (query || "").trim();
    if (!trimmed) {
      status.textContent = totalCount
        ? `Showing all ${totalCount} student${totalCount === 1 ? "" : "s"} in this grade`
        : "";
      return;
    }
    if (!visibleCount) {
      status.textContent = `No matches in this grade for “${trimmed}”`;
      return;
    }
    status.textContent = `Showing ${visibleCount} of ${totalCount} student${totalCount === 1 ? "" : "s"} for “${trimmed}”`;
  }

  function filterRows(query) {
    const needle = normalize(query);
    let visibleCount = 0;
    rows.forEach((row) => {
      const match = !needle || rowHaystack(row).includes(needle);
      row.hidden = !match;
      row.classList.remove("is-search-highlight");
      if (match) visibleCount += 1;
    });
    updateCardVisibility();
    if (directory) directory.hidden = needle.length > 0 && visibleCount === 0;
    if (emptyMessage) emptyMessage.hidden = !(needle.length > 0 && visibleCount === 0);
    setStatus(visibleCount, query);
    return visibleCount;
  }

  function buildOtherGradeUrl(student, query) {
    const url = new URL(window.location.pathname, window.location.origin);
    if (student.academic_level) url.searchParams.set("level", student.academic_level);
    if (query) url.searchParams.set("q", query);
    url.hash = `student-${student.id}`;
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function renderOtherGradeResults(items, query) {
    if (!results || !panel) return;
    results.replaceChildren();
    const otherGradeItems = items.filter(
      (student) => (student.academic_level || "").toUpperCase() !== selectedLevel
    );
    if (!otherGradeItems.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    if (panelTitle) {
      panelTitle.textContent = otherGradeItems.length === 1
        ? "Found in another grade"
        : `Found in other grades (${otherGradeItems.length})`;
    }
    otherGradeItems.forEach((student) => {
      const link = document.createElement("a");
      link.className = "student-register-search-option";
      link.href = buildOtherGradeUrl(student, query);
      link.setAttribute("role", "option");
      const initial = (student.name || "S").trim().charAt(0).toUpperCase();
      const avatar = document.createElement("span");
      avatar.className = "student-register-search-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = initial;
      const copyWrap = document.createElement("span");
      copyWrap.className = "student-register-search-option-copy";
      const name = document.createElement("span");
      name.className = "student-register-search-option-name";
      name.textContent = student.name;
      const meta = document.createElement("span");
      meta.className = "student-register-search-option-meta";
      const parts = [student.level_label || student.class_group, student.assessment_number];
      if (student.admission_number) parts.push(`Adm ${student.admission_number}`);
      meta.textContent = parts.filter(Boolean).join(" · ");
      copyWrap.append(name, meta);
      link.append(avatar, copyWrap);
      results.appendChild(link);
    });
  }

  async function fetchOtherGrades(query) {
    const trimmed = (query || "").trim();
    const token = ++searchToken;
    if (!searchUrl || trimmed.length < 2) {
      if (panel) panel.hidden = true;
      if (results) results.replaceChildren();
      return;
    }
    try {
      const response = await fetch(`${searchUrl}?q=${encodeURIComponent(trimmed)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("search failed");
      const data = await response.json();
      if (token !== searchToken) return;
      renderOtherGradeResults(data.students || [], trimmed);
    } catch (error) {
      if (token !== searchToken) return;
      if (panel) panel.hidden = true;
    }
  }

  function highlightFromHash() {
    const hash = window.location.hash || "";
    if (!hash.startsWith("#student-")) return;
    const row = document.querySelector(hash);
    if (!row) return;
    row.classList.add("is-search-highlight");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function runSearch() {
    const query = input?.value || "";
    if (clearButton) clearButton.hidden = !query.trim();
    filterRows(query);
    updateUrl(query);
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => fetchOtherGrades(query), 220);
  }

  input?.addEventListener("input", runSearch);
  input?.addEventListener("search", runSearch);
  clearButton?.addEventListener("click", () => {
    if (!input) return;
    input.value = "";
    runSearch();
    input.focus();
  });

  if (input?.value) {
    runSearch();
  }
  highlightFromHash();
})();
