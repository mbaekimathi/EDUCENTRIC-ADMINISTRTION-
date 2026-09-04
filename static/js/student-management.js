(function () {
  const modal = document.querySelector("[data-edit-student-modal]");
  const form = document.querySelector("[data-edit-student-form]");
  const sponsorField = document.querySelector("[data-sponsor-details-field]");
  const fields = {
    firstName: document.querySelector("#edit-student-first-name"),
    middleName: document.querySelector("#edit-student-middle-name"),
    lastName: document.querySelector("#edit-student-last-name"),
    dateOfBirth: document.querySelector("#edit-student-dob"),
    gender: document.querySelector("#edit-student-gender"),
    academicLevel: document.querySelector("#edit-student-level"),
    admissionNumber: document.querySelector("#edit-student-admission"),
    classGroup: document.querySelector("#edit-student-class-group"),
    assessmentNumber: document.querySelector("#edit-student-assessment"),
    previousSchool: document.querySelector("#edit-student-previous-school"),
    sponsorshipCategory: document.querySelector("#edit-student-sponsorship"),
    sponsorDetails: document.querySelector("#edit-student-sponsor"),
    parentGuardianName: document.querySelector("#edit-student-parent-name"),
    relationshipToStudent: document.querySelector("#edit-student-relationship"),
    parentPhone: document.querySelector("#edit-student-parent-phone"),
    parentEmail: document.querySelector("#edit-student-parent-email"),
    homeAddress: document.querySelector("#edit-student-address"),
    medicalNotes: document.querySelector("#edit-student-medical"),
    specialNeeds: document.querySelector("#edit-student-needs"),
    emergencyContact: document.querySelector("#edit-student-emergency"),
    profileImage: document.querySelector("#edit-student-photo"),
    clearProfileImage: document.querySelector("[data-edit-student-clear-photo]"),
  };
  const photoPreview = document.querySelector("[data-edit-student-photo-preview]");
  const photoInitials = document.querySelector("[data-edit-student-photo-initials]");
  const photoTrigger = document.querySelector("[data-edit-student-photo-trigger]");
  const photoFilename = document.querySelector("[data-edit-student-photo-filename]");
  const removePhotoButton = document.querySelector("[data-edit-student-remove-photo]");
  let hasServerPhoto = false;

  const catalogNode = document.getElementById("student-edit-level-catalog");
  let levelCatalog = { levels: [] };
  try {
    levelCatalog = catalogNode ? JSON.parse(catalogNode.textContent) : { levels: [] };
  } catch (error) {
    levelCatalog = { levels: [] };
  }
  const levelsByValue = new Map(
    (levelCatalog.levels || []).map((level) => [String(level.value || "").toUpperCase(), level])
  );

  function initialsFromName(firstName, lastName) {
    const first = (firstName || "").trim().charAt(0);
    const last = (lastName || "").trim().charAt(0);
    const value = `${first}${last}`.toUpperCase();
    return value || "--";
  }

  function updateInitials() {
    if (!photoInitials) return;
    photoInitials.textContent = initialsFromName(fields.firstName?.value, fields.lastName?.value);
  }

  function setPhotoPreview(url, filename) {
    const hasPhoto = Boolean(url);
    if (photoPreview) {
      photoPreview.hidden = !hasPhoto;
      photoPreview.src = url || "";
      photoPreview.onerror = () => {
        photoPreview.hidden = true;
        photoPreview.src = "";
        if (photoInitials) photoInitials.hidden = false;
        if (removePhotoButton) removePhotoButton.hidden = true;
      };
    }
    if (photoInitials) photoInitials.hidden = hasPhoto;
    if (removePhotoButton) removePhotoButton.hidden = !hasPhoto;
    if (photoFilename) {
      if (filename) {
        photoFilename.textContent = filename;
        photoFilename.hidden = false;
      } else {
        photoFilename.textContent = "";
        photoFilename.hidden = true;
      }
    }
    if (fields.clearProfileImage) fields.clearProfileImage.checked = false;
    if (photoTrigger) photoTrigger.classList.toggle("has-photo", hasPhoto);
  }

  function toggleSponsorDetails() {
    const value = fields.sponsorshipCategory?.value;
    const required = value === "GOVERNMENT" || value === "BOTH";
    if (sponsorField) sponsorField.hidden = !required;
    if (fields.sponsorDetails) fields.sponsorDetails.required = required;
  }

  function ensureLevelOption(value, label) {
    if (!fields.academicLevel || !value) return;
    const key = String(value).toUpperCase();
    const exists = Array.from(fields.academicLevel.options).some(
      (option) => String(option.value || "").toUpperCase() === key
    );
    if (exists) return;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label || value.replace(/_/g, " ");
    fields.academicLevel.appendChild(option);
  }

  function classesForLevel(levelValue) {
    const level = levelsByValue.get(String(levelValue || "").toUpperCase());
    return level ? level.classes || [] : [];
  }

  function valueMatchesClass(item, selectedKey) {
    if (!selectedKey) return false;
    if (String(item.value || "").toUpperCase() === selectedKey) return true;
    if (String(item.label || "").toUpperCase() === selectedKey) return true;
    return (item.aliases || []).some(
      (alias) => String(alias || "").toUpperCase() === selectedKey
    );
  }

  function fillClassOptions(levelValue, selectedValue) {
    if (!fields.classGroup) return;
    const classes = classesForLevel(levelValue);
    const selected = (selectedValue || "").trim();
    const selectedKey = selected.toUpperCase();
    fields.classGroup.replaceChildren();

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = classes.length
      ? "Select class…"
      : levelValue
        ? "No classes configured for this level"
        : "Select academic level first…";
    fields.classGroup.appendChild(placeholder);

    let matched = false;
    classes.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label || item.value;
      if (valueMatchesClass(item, selectedKey)) {
        option.selected = true;
        matched = true;
      }
      fields.classGroup.appendChild(option);
    });

    if (selected && !matched) {
      const option = document.createElement("option");
      option.value = selected;
      option.textContent = `${selected} (current)`;
      option.selected = true;
      fields.classGroup.appendChild(option);
    }

    fields.classGroup.disabled = !levelValue;
    fields.classGroup.required = Boolean(levelValue) && classes.length > 0;
  }

  function setOpen(open) {
    if (!modal) return;
    modal.hidden = !open;
    modal.classList.toggle("is-open", open);
    document.body.classList.toggle("modal-open", open);
    if (open) fields.firstName?.focus();
  }

  document.querySelectorAll("[data-edit-student]").forEach((button) => {
    button.addEventListener("click", () => {
      form.action = button.dataset.updateUrl;
      fields.firstName.value = button.dataset.firstName || "";
      if (fields.middleName) fields.middleName.value = button.dataset.middleName || "";
      fields.lastName.value = button.dataset.lastName || "";
      fields.dateOfBirth.value = button.dataset.dateOfBirth || "";
      fields.gender.value = button.dataset.gender || "";
      const academicLevel = button.dataset.academicLevel || "";
      ensureLevelOption(academicLevel, academicLevel.replace(/_/g, " "));
      fields.academicLevel.value = academicLevel;
      fields.admissionNumber.value = button.dataset.admissionNumber || "";
      fillClassOptions(academicLevel, button.dataset.classGroup || "");
      fields.assessmentNumber.value = button.dataset.assessmentNumber || "";
      fields.previousSchool.value = button.dataset.previousSchool || "";
      fields.sponsorshipCategory.value = button.dataset.sponsorshipCategory || "";
      fields.sponsorDetails.value = button.dataset.sponsorDetails || "";
      fields.parentGuardianName.value = button.dataset.parentGuardianName || "";
      fields.relationshipToStudent.value = button.dataset.relationshipToStudent || "";
      fields.parentPhone.value = button.dataset.parentPhone || "";
      fields.parentEmail.value = button.dataset.parentEmail || "";
      fields.homeAddress.value = button.dataset.homeAddress || "";
      fields.medicalNotes.value = button.dataset.medicalNotes || "";
      fields.specialNeeds.value = button.dataset.specialNeeds || "";
      fields.emergencyContact.value = button.dataset.emergencyContact || "";
      if (fields.profileImage) fields.profileImage.value = "";
      hasServerPhoto = Boolean(button.dataset.profileImageUrl);
      updateInitials();
      setPhotoPreview(button.dataset.profileImageUrl || "");
      toggleSponsorDetails();
      setOpen(true);
    });
  });

  fields.firstName?.addEventListener("input", updateInitials);
  fields.lastName?.addEventListener("input", updateInitials);
  fields.sponsorshipCategory?.addEventListener("change", toggleSponsorDetails);
  fields.academicLevel?.addEventListener("change", () => {
    fillClassOptions(fields.academicLevel.value, "");
  });

  photoTrigger?.addEventListener("click", () => fields.profileImage?.click());

  fields.profileImage?.addEventListener("change", () => {
    const file = fields.profileImage.files && fields.profileImage.files[0];
    if (!file) return;
    hasServerPhoto = false;
    const url = URL.createObjectURL(file);
    setPhotoPreview(url, file.name);
    if (fields.clearProfileImage) fields.clearProfileImage.checked = false;
  });

  removePhotoButton?.addEventListener("click", () => {
    if (fields.profileImage) fields.profileImage.value = "";
    if (fields.clearProfileImage) fields.clearProfileImage.checked = hasServerPhoto;
    hasServerPhoto = false;
    setPhotoPreview("");
    updateInitials();
  });

  modal?.querySelectorAll("[data-edit-student-close]").forEach((button) => {
    button.addEventListener("click", () => setOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });

  fillClassOptions("", "");
})();

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
