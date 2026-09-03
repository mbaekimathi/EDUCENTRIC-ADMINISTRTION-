(function () {
  function admissionSortKey(value) {
    const raw = String(value || "").trim().toLowerCase();
    if (!raw) return ["~", Number.POSITIVE_INFINITY, ""];
    const match = raw.match(/^(\D*?)(\d+)(.*)$/);
    if (!match) return [raw, Number.POSITIVE_INFINITY, ""];
    return [match[1], Number(match[2]), match[3]];
  }

  function nameSortKey(row) {
    return String(row.getAttribute("data-sort-name") || "").trim().toLowerCase();
  }

  function codeSortKey(row) {
    return (
      row.getAttribute("data-sort-code")
      || row.getAttribute("data-sort-admission")
      || ""
    );
  }

  function compareRows(a, b, mode) {
    if (mode === "admission") {
      const ka = admissionSortKey(codeSortKey(a));
      const kb = admissionSortKey(codeSortKey(b));
      for (let i = 0; i < ka.length; i += 1) {
        if (ka[i] < kb[i]) return -1;
        if (ka[i] > kb[i]) return 1;
      }
      const nameCmp = nameSortKey(a).localeCompare(nameSortKey(b));
      if (nameCmp) return nameCmp;
      return 0;
    }
    return nameSortKey(a).localeCompare(nameSortKey(b));
  }

  function renumber(container) {
    container.querySelectorAll("[data-student-index]").forEach((el, index) => {
      el.textContent = `${index + 1}.`;
    });
  }

  function sortContainer(container, mode) {
    const bodies = container.querySelectorAll("[data-student-sort-body]");
    const targets = bodies.length ? bodies : [container];
    targets.forEach((body) => {
      const rows = Array.from(body.querySelectorAll("[data-student-row]"));
      if (rows.length < 2) return;
      rows.sort((a, b) => compareRows(a, b, mode));
      rows.forEach((row) => body.appendChild(row));
      renumber(body);
    });
  }

  function syncToggle(toggle, mode) {
    toggle.setAttribute("data-current-sort", mode);
    const select = toggle.querySelector("[data-student-sort-select]");
    if (select && select.value !== mode) {
      select.value = mode;
    }
  }

  function urlForMode(toggle, mode) {
    if (mode === "admission") {
      return toggle.getAttribute("data-student-sort-admission-url") || "";
    }
    return toggle.getAttribute("data-student-sort-name-url") || "";
  }

  function updateUrl(url) {
    if (!url) return;
    try {
      const next = new URL(url, window.location.href);
      window.history.replaceState({}, "", next.pathname + next.search + next.hash);
    } catch (_err) {
      // Ignore malformed URLs; sorting still applies in the DOM.
    }
  }

  function syncHiddenSortInputs(mode) {
    document.querySelectorAll('input[name="sort"][data-student-sort-field]').forEach((input) => {
      if (mode === "admission") {
        input.disabled = false;
        input.value = "admission";
      } else {
        input.disabled = true;
      }
    });
  }

  function applySort(mode, url) {
    document.querySelectorAll("[data-student-sortable]").forEach((container) => {
      sortContainer(container, mode);
    });
    document.querySelectorAll("[data-student-sort-toggle]").forEach((toggle) => {
      syncToggle(toggle, mode);
    });
    syncHiddenSortInputs(mode);
    updateUrl(url);
  }

  document.querySelectorAll("[data-student-sort-toggle]").forEach((toggle) => {
    const select = toggle.querySelector("[data-student-sort-select]");
    if (!select) return;
    select.addEventListener("change", () => {
      const mode = select.value === "admission" ? "admission" : "name";
      applySort(mode, urlForMode(toggle, mode));
    });
  });
})();
