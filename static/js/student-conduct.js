(function () {
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getCsrfToken() {
    const field = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (field && field.value) return field.value;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function initConductRecordLiveSearch() {
    const form = document.querySelector("[data-conduct-record-search-form]");
    const input = document.querySelector("[data-conduct-record-search-input]");
    const results = document.querySelector("[data-conduct-record-results]");
    const status = document.querySelector("[data-conduct-record-status]");
    const clearBtn = document.querySelector("[data-conduct-record-search-clear]");
    if (!form || !input || !results) return;

    let searchTimer = null;
    let abortController = null;
    let searchToken = 0;

    function updateUrl(query) {
      const url = new URL(form.action, window.location.origin);
      const trimmed = (query || "").trim();
      if (trimmed) url.searchParams.set("q", trimmed);
      else url.searchParams.delete("q");
      window.history.replaceState({}, "", url.pathname + url.search);
    }

    function setStatus(query, count) {
      if (!status) return;
      const trimmed = (query || "").trim();
      if (!trimmed) {
        status.textContent = count
          ? `${count} recent record${count === 1 ? "" : "s"}`
          : "No conduct records yet";
        return;
      }
      if (!count) {
        status.textContent = `No matches for “${trimmed}”`;
        return;
      }
      status.textContent = `Showing ${count} match${count === 1 ? "" : "es"} for “${trimmed}”`;
    }

    function renderScoreBars(rating) {
      let html = "";
      for (let i = 1; i <= 5; i += 1) {
        html +=
          '<span class="student-conduct-score-bar' +
          (i <= rating ? " is-filled" : "") +
          '"></span>';
      }
      return html;
    }

    function renderRecords(records, query) {
      if (!records.length) {
        const trimmed = (query || "").trim();
        results.innerHTML =
          '<div class="student-conduct-empty">' +
          '<span class="student-conduct-empty-icon" aria-hidden="true">' +
          '<svg viewBox="0 0 24 24"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3zM5 17l.8 2.2L8 20l-2.2.8L5 23l-.8-2.2L2 20l2.2-.8L5 17zM18.5 14l.7 1.8L21 16.5l-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
          "</span>" +
          "<h3>" +
          (trimmed ? "No matches" : "No conduct records yet") +
          "</h3>" +
          "<p>" +
          (trimmed
            ? "Nothing matched “" +
              escapeHtml(trimmed) +
              "”. Try another name or admission number."
            : 'Use <strong>Register conduct</strong> to log the first good or bad behaviour entry.') +
          "</p>" +
          (trimmed
            ? ""
            : '<button type="button" class="primary-button" data-open-modal="register-conduct">Register conduct</button>') +
          "</div>";
        bindOpeners(results);
        return;
      }

      const csrf = escapeHtml(getCsrfToken());
      const cards = records
        .map(function (record) {
          const student = record.student || {};
          const isGood = record.behaviour_type === "GOOD";
          const avatar = student.profile_image_url
            ? '<img class="pending-admit-avatar" src="' +
              escapeHtml(student.profile_image_url) +
              '" alt="" loading="lazy" decoding="async">'
            : '<span class="pending-admit-avatar is-fallback" aria-hidden="true">' +
              escapeHtml(student.initials || "?") +
              "</span>";
          const placement = [
            student.level_label,
            student.class_group,
            student.admission_number ? "Adm " + student.admission_number : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            '<article class="student-conduct-card is-' +
            escapeHtml(String(record.behaviour_type || "").toLowerCase()) +
            '">' +
            '<div class="student-conduct-card-identity">' +
            avatar +
            '<div class="student-conduct-card-copy">' +
            '<div class="student-conduct-card-top">' +
            '<h4 class="is-uppercase">' +
            escapeHtml(student.name) +
            "</h4>" +
            '<span class="status-pill is-uppercase ' +
            (isGood ? "is-active" : "is-danger") +
            '">' +
            escapeHtml(record.behaviour_label) +
            "</span>" +
            "</div>" +
            '<p class="student-conduct-placement">' +
            escapeHtml(placement) +
            "</p>" +
            "</div>" +
            "</div>" +
            '<p class="student-conduct-description">' +
            escapeHtml(record.description) +
            "</p>" +
            '<div class="student-conduct-meta">' +
            "<span><em>Date</em>" +
            escapeHtml(record.incident_date) +
            "</span>" +
            "<span><em>Witness</em>" +
            escapeHtml(record.witness) +
            "</span>" +
            "<span><em>" +
            escapeHtml(record.outcome_label) +
            "</em>" +
            escapeHtml(record.consequence_or_reward) +
            "</span>" +
            (record.recorded_by
              ? "<span><em>Recorded by</em>" + escapeHtml(record.recorded_by) + "</span>"
              : "") +
            "</div>" +
            '<div class="student-conduct-card-foot">' +
            '<div class="student-conduct-score" aria-label="' +
            escapeHtml(record.rating_label) +
            " " +
            escapeHtml(record.rating) +
            ' out of 5">' +
            '<span class="student-conduct-score-label">' +
            escapeHtml(record.rating_label) +
            "</span>" +
            '<div class="student-conduct-score-bars" aria-hidden="true">' +
            renderScoreBars(Number(record.rating) || 0) +
            "</div>" +
            "<strong>" +
            escapeHtml(record.rating) +
            "/5</strong>" +
            "</div>" +
            '<form method="post" action="' +
            escapeHtml(record.delete_url) +
            '" data-conduct-delete-form data-student-name="' +
            escapeHtml(student.name) +
            '">' +
            '<input type="hidden" name="csrfmiddlewaretoken" value="' +
            csrf +
            '">' +
            '<button type="submit" class="ghost-button is-danger">Remove</button>' +
            "</form>" +
            "</div>" +
            "</article>"
          );
        })
        .join("");

      results.innerHTML = '<div class="student-conduct-cards">' + cards + "</div>";
      results.querySelectorAll("[data-conduct-delete-form]").forEach(function (deleteForm) {
        deleteForm.addEventListener("submit", function (event) {
          const name = deleteForm.getAttribute("data-student-name") || "this student";
          if (!window.confirm("Remove this conduct record for " + name + "?")) {
            event.preventDefault();
          }
        });
      });
    }

    function bindOpeners(root) {
      root.querySelectorAll('[data-open-modal="register-conduct"]').forEach(function (btn) {
        btn.addEventListener("click", function () {
          const heroOpener = document.querySelector(
            '.pending-admit-hero-actions [data-open-modal="register-conduct"]'
          );
          if (heroOpener) {
            heroOpener.click();
            return;
          }
          const modal = document.querySelector('[data-modal="register-conduct"]');
          if (!modal) return;
          modal.classList.add("is-open");
          modal.hidden = false;
          document.body.classList.add("modal-open");
        });
      });
    }

    async function runSearch(query) {
      const trimmed = (query || "").trim();
      const token = ++searchToken;
      if (clearBtn) clearBtn.hidden = !trimmed;
      updateUrl(trimmed);
      results.setAttribute("aria-busy", "true");

      if (abortController) abortController.abort();
      abortController = new AbortController();

      try {
        const url = new URL(form.action, window.location.origin);
        if (trimmed) url.searchParams.set("q", trimmed);
        url.searchParams.set("format", "json");
        const response = await fetch(url.toString(), {
          signal: abortController.signal,
          headers: {
            Accept: "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
        });
        if (!response.ok) throw new Error("Search failed");
        const data = await response.json();
        if (token !== searchToken) return;
        const records = (data && data.records) || [];
        setStatus(trimmed, records.length);
        renderRecords(records, trimmed);
      } catch (err) {
        if (err.name === "AbortError") return;
        if (token !== searchToken) return;
        // Fall back to classic submit if live fetch fails.
        form.requestSubmit();
      } finally {
        if (token === searchToken) {
          results.removeAttribute("aria-busy");
        }
      }
    }

    function scheduleSearch() {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        runSearch(input.value);
      }, 220);
    }

    input.addEventListener("input", scheduleSearch);
    input.addEventListener("search", function () {
      window.clearTimeout(searchTimer);
      runSearch(input.value);
    });

    form.addEventListener("submit", function (event) {
      // Prefer live AJAX; keep native submit as progressive enhancement only
      // when JS fetch path is unavailable.
      if (window.fetch) {
        event.preventDefault();
        window.clearTimeout(searchTimer);
        runSearch(input.value);
      }
    });

    clearBtn?.addEventListener("click", function (event) {
      event.preventDefault();
      input.value = "";
      window.clearTimeout(searchTimer);
      runSearch("");
      input.focus();
    });
  }

  function initConductRegisterModal() {
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
  }

  initConductRecordLiveSearch();
  initConductRegisterModal();
})();
