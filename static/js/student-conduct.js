(function () {
  const modal = document.querySelector('[data-modal="register-conduct"]');
  const form = document.querySelector("[data-student-conduct-form]");
  if (!modal || !form) return;

  const openers = document.querySelectorAll('[data-open-modal="register-conduct"]');
  const closers = modal.querySelectorAll("[data-modal-close]");
  const firstField = modal.querySelector(
    "input:not([type='hidden']):not([hidden]), select, textarea, button:not([data-modal-close])"
  );

  function setOpen(open) {
    modal.classList.toggle("is-open", open);
    modal.hidden = !open;
    document.body.classList.toggle("modal-open", open);
    if (open) {
      const focusTarget =
        form.querySelector("[data-conduct-student-search]:not([hidden])") || firstField;
      focusTarget?.focus();
    }
  }

  openers.forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelector("[data-workspace]")?.classList.remove("is-nav-open");
      setOpen(true);
    });
  });
  closers.forEach((el) => {
    el.addEventListener("click", () => setOpen(false));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      setOpen(false);
    }
  });

  if (modal.classList.contains("is-open")) setOpen(true);

  const workspace = document.querySelector("[data-workspace]");
  const searchUrl =
    (workspace && workspace.getAttribute("data-student-search-url")) ||
    document.body.getAttribute("data-student-search-url") ||
    "";
  const studentInput = form.querySelector('input[name="student"]');
  const searchInput = form.querySelector("[data-conduct-student-search]");
  const resultsBox = form.querySelector("[data-conduct-student-results]");
  const selectedBox = form.querySelector("[data-conduct-student-selected]");
  const selectedName = form.querySelector("[data-conduct-student-name]");
  const selectedMeta = form.querySelector("[data-conduct-student-meta]");
  const clearBtn = form.querySelector("[data-conduct-student-clear]");
  const outcomeLabel = form.querySelector("[data-conduct-outcome-label]");
  const ratingLabel = form.querySelector("[data-conduct-rating-label]");
  const ratingHint = form.querySelector("[data-conduct-rating-hint]");
  const typeInputs = form.querySelectorAll('input[name="behaviour_type"]');

  let searchTimer = null;
  let abortController = null;

  function updateTypeLabels() {
    const selected = form.querySelector('input[name="behaviour_type"]:checked');
    const isBad = selected && selected.value === "BAD";
    if (outcomeLabel) {
      outcomeLabel.innerHTML = isBad
        ? 'Repercussion <span class="required">*</span>'
        : selected
          ? 'Reward <span class="required">*</span>'
          : 'Repercussion or reward <span class="required">*</span>';
    }
    if (ratingLabel) {
      ratingLabel.innerHTML = isBad
        ? 'Severity rating (1–5) <span class="required">*</span>'
        : selected
          ? 'Merit rating (1–5) <span class="required">*</span>'
          : 'Severity / merit (1–5) <span class="required">*</span>';
    }
    if (ratingHint) {
      ratingHint.textContent = isBad
        ? "1 = minor issue, 5 = most severe."
        : selected
          ? "1 = notable, 5 = outstanding merit."
          : "For bad behaviour rate severity. For good behaviour rate merit.";
    }
  }

  function setSelectedStudent(student) {
    if (!studentInput || !selectedBox) return;
    studentInput.value = student.id;
    if (selectedName) selectedName.textContent = student.name || "";
    if (selectedMeta) {
      const parts = [];
      if (student.admission_number) parts.push("Adm " + student.admission_number);
      if (student.level_label) parts.push(student.level_label);
      if (student.class_group) parts.push(student.class_group);
      selectedMeta.textContent = parts.join(" · ");
    }
    selectedBox.hidden = false;
    if (searchInput) {
      searchInput.value = student.name || "";
      searchInput.hidden = true;
    }
    if (resultsBox) {
      resultsBox.hidden = true;
      resultsBox.innerHTML = "";
    }
  }

  function clearSelectedStudent() {
    if (studentInput) studentInput.value = "";
    if (selectedBox) selectedBox.hidden = true;
    if (selectedName) selectedName.textContent = "";
    if (selectedMeta) selectedMeta.textContent = "";
    if (searchInput) {
      searchInput.hidden = false;
      searchInput.value = "";
      searchInput.focus();
    }
    if (resultsBox) {
      resultsBox.hidden = true;
      resultsBox.innerHTML = "";
    }
  }

  function renderResults(students) {
    if (!resultsBox) return;
    resultsBox.innerHTML = "";
    if (!students.length) {
      resultsBox.hidden = true;
      return;
    }
    students.forEach(function (student) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "student-conduct-result";
      button.setAttribute("role", "option");
      const meta = [];
      if (student.admission_number) meta.push("Adm " + student.admission_number);
      if (student.level_label) meta.push(student.level_label);
      if (student.class_group) meta.push(student.class_group);
      button.innerHTML =
        "<strong>" +
        escapeHtml(student.name) +
        "</strong><span>" +
        escapeHtml(meta.join(" · ")) +
        "</span>";
      button.addEventListener("click", function () {
        setSelectedStudent(student);
      });
      resultsBox.appendChild(button);
    });
    resultsBox.hidden = false;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function runSearch(query) {
    if (query.length < 1) {
      if (resultsBox) {
        resultsBox.hidden = true;
        resultsBox.innerHTML = "";
      }
      return;
    }

    const localScript = document.getElementById("conduct-local-students");
    if (localScript) {
      let localStudents = [];
      try {
        localStudents = JSON.parse(localScript.textContent || "[]");
      } catch (err) {
        localStudents = [];
      }
      const needle = query.toLowerCase();
      const matches = localStudents
        .filter(function (student) {
          const haystack = [
            student.name,
            student.admission_number,
            student.class_group,
            student.level_label,
          ]
            .join(" ")
            .toLowerCase();
          return haystack.indexOf(needle) !== -1;
        })
        .slice(0, 12);
      renderResults(matches);
      return;
    }

    if (!searchUrl) {
      if (resultsBox) {
        resultsBox.hidden = true;
        resultsBox.innerHTML = "";
      }
      return;
    }
    if (abortController) abortController.abort();
    abortController = new AbortController();
    fetch(searchUrl + "?q=" + encodeURIComponent(query), {
      signal: abortController.signal,
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Search failed");
        return response.json();
      })
      .then(function (data) {
        renderResults((data && data.students) || []);
      })
      .catch(function (err) {
        if (err.name === "AbortError") return;
        if (resultsBox) {
          resultsBox.hidden = true;
          resultsBox.innerHTML = "";
        }
      });
  }

  typeInputs.forEach(function (input) {
    input.addEventListener("change", updateTypeLabels);
  });
  updateTypeLabels();

  if (studentInput && studentInput.value && searchInput) {
    searchInput.hidden = true;
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", clearSelectedStudent);
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      const query = searchInput.value.trim();
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        runSearch(query);
      }, 220);
    });
  }
})();
