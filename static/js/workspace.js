(function () {
  const root = document.querySelector("[data-workspace]");
  if (!root) return;
  const toggle = root.querySelector("[data-workspace-toggle]");
  const backBtn = root.querySelector("[data-workspace-back]");
  const backdrop = root.querySelector("[data-workspace-backdrop]");
  const sidebar = document.getElementById("workspace-sidebar");
  const profile = root.querySelector("[data-profile-menu]");
  const profileTrigger = root.querySelector("[data-profile-trigger]");
  const profilePanel = root.querySelector("[data-profile-panel]");
  const roleModal = document.querySelector("[data-role-switch-modal]");
  const studentModal = document.querySelector("[data-student-search-modal]");
  const employeesUrl = root.dataset.employeesUrl || "";
  const studentSearchUrl = root.dataset.studentSearchUrl || "";
  const dashboardUrl = root.dataset.dashboardUrl || "/";
  const navStackKey = "educentric.workspaceNavStack";

  function currentNavKey() {
    return `${window.location.pathname}${window.location.search}`;
  }

  function readNavStack() {
    try {
      const raw = sessionStorage.getItem(navStackKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string" && item) : [];
    } catch (error) {
      return [];
    }
  }

  function writeNavStack(stack) {
    sessionStorage.setItem(navStackKey, JSON.stringify(stack.slice(-50)));
  }

  function previousNavTarget(stack, current) {
    let index = stack.length - 1;
    while (index >= 0 && stack[index] === current) index -= 1;
    return index >= 0 ? stack[index] : "";
  }

  function syncWorkspaceBack() {
    if (!backBtn) return;
    const current = currentNavKey();
    const stack = readNavStack();
    if (!stack.length || stack[stack.length - 1] !== current) {
      stack.push(current);
      writeNavStack(stack);
    }
    const previous = previousNavTarget(stack, current);
    const canGoBack = Boolean(previous && previous !== current);
    backBtn.hidden = !canGoBack;
    backBtn.disabled = !canGoBack;
  }

  function goWorkspaceBack() {
    if (!backBtn || backBtn.disabled) return;
    const current = currentNavKey();
    const stack = readNavStack();
    while (stack.length && stack[stack.length - 1] === current) stack.pop();
    const target = stack.length ? stack[stack.length - 1] : "";
    writeNavStack(stack);
    window.location.assign(target || dashboardUrl);
  }

  syncWorkspaceBack();
  if (backBtn) backBtn.addEventListener("click", goWorkspaceBack);

  document.querySelectorAll("[data-nav-drawer]").forEach(function (drawer) {
    const drawerToggle = drawer.querySelector("[data-nav-drawer-toggle]");
    const panel = drawer.querySelector(".workspace-nav-drawer-panel");
    if (!drawerToggle || !panel) return;
    drawerToggle.addEventListener("click", function () {
      const collapsed = drawer.classList.toggle("is-collapsed");
      drawerToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      panel.hidden = collapsed;
    });
  });

  function setNavOpen(open) {
    root.classList.toggle("is-nav-open", open);
    if (toggle) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    }
    if (backdrop) backdrop.hidden = !open;
  }

  function setProfileOpen(open) {
    if (!profile || !profileTrigger || !profilePanel) return;
    profile.classList.toggle("is-open", open);
    profilePanel.hidden = !open;
    profileTrigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function setRoleModalOpen(open) {
    if (!roleModal) return;
    roleModal.hidden = !open;
    roleModal.classList.toggle("is-open", open);
    document.body.classList.toggle(
      "modal-open",
      open || Boolean(studentModal && studentModal.classList.contains("is-open"))
    );
    if (open) goToRoleStep();
  }

  function setStudentModalOpen(open) {
    if (!studentModal) return;
    studentModal.hidden = !open;
    studentModal.classList.toggle("is-open", open);
    document.body.classList.toggle(
      "modal-open",
      open || Boolean(roleModal && roleModal.classList.contains("is-open"))
    );
    if (open) {
      const input = studentModal.querySelector("[data-student-search-input]");
      resetStudentSearch();
      window.setTimeout(() => input?.focus(), 30);
    }
  }

  toggle?.addEventListener("click", () => {
    setProfileOpen(false);
    setNavOpen(!root.classList.contains("is-nav-open"));
  });
  backdrop?.addEventListener("click", () => setNavOpen(false));
  sidebar?.querySelectorAll("a, [data-student-search-open]").forEach((link) => {
    link.addEventListener("click", () => setNavOpen(false));
  });

  profileTrigger?.addEventListener("click", (event) => {
    event.stopPropagation();
    setNavOpen(false);
    setProfileOpen(profilePanel.hidden);
  });
  document.addEventListener("click", (event) => {
    if (profile && !profile.contains(event.target)) setProfileOpen(false);
  });
  document.querySelectorAll("[data-role-switch-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      setProfileOpen(false);
      setNavOpen(false);
      setStudentModalOpen(false);
      setRoleModalOpen(true);
    });
  });
  document.querySelectorAll("[data-student-search-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      setProfileOpen(false);
      setNavOpen(false);
      setRoleModalOpen(false);
      setStudentModalOpen(true);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setNavOpen(false);
      setProfileOpen(false);
      setRoleModalOpen(false);
      setStudentModalOpen(false);
    }
  });

  const studentInput = studentModal?.querySelector("[data-student-search-input]");
  const studentResults = studentModal?.querySelector("[data-student-search-results]");
  const studentHint = studentModal?.querySelector("[data-student-search-hint]");
  const studentEmpty = studentModal?.querySelector("[data-student-search-empty]");
  let studentSearchTimer = null;
  let studentSearchToken = 0;

  function resetStudentSearch() {
    if (studentInput) studentInput.value = "";
    if (studentResults) studentResults.replaceChildren();
    if (studentHint) studentHint.hidden = false;
    if (studentEmpty) studentEmpty.hidden = true;
  }

  function renderStudentResults(items) {
    if (!studentResults) return;
    studentResults.replaceChildren();
    if (!items.length) {
      if (studentHint) studentHint.hidden = true;
      if (studentEmpty) studentEmpty.hidden = false;
      return;
    }
    if (studentHint) studentHint.hidden = true;
    if (studentEmpty) studentEmpty.hidden = true;
    items.forEach((student) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "student-search-option";
      button.setAttribute("role", "option");
      const initial = (student.name || "S").trim().charAt(0).toUpperCase();
      const avatar = document.createElement("span");
      avatar.className = "student-search-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = initial;
      const copyWrap = document.createElement("span");
      copyWrap.className = "student-search-option-copy";
      const name = document.createElement("span");
      name.className = "student-search-option-name";
      name.textContent = student.name;
      const meta = document.createElement("span");
      meta.className = "student-search-option-meta";
      const parts = [student.class_group, student.assessment_number];
      if (student.admission_number) parts.push(`Adm ${student.admission_number}`);
      meta.textContent = parts.filter(Boolean).join(" · ");
      copyWrap.append(name, meta);
      button.append(avatar, copyWrap);
      button.addEventListener("click", () => {
        window.location.href = student.profile_url;
      });
      studentResults.appendChild(button);
    });
  }

  async function runStudentSearch(query) {
    const token = ++studentSearchToken;
    const needle = (query || "").trim();
    if (!needle) {
      resetStudentSearch();
      return;
    }
    if (studentHint) {
      studentHint.hidden = false;
      studentHint.textContent = "Searching…";
    }
    if (studentEmpty) studentEmpty.hidden = true;
    try {
      const response = await fetch(`${studentSearchUrl}?q=${encodeURIComponent(needle)}`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (token !== studentSearchToken) return;
      if (studentHint) studentHint.textContent = "Start typing to see matching students.";
      renderStudentResults(data.students || []);
    } catch (error) {
      if (token !== studentSearchToken) return;
      if (studentHint) studentHint.textContent = "Start typing to see matching students.";
      renderStudentResults([]);
    }
  }

  studentModal?.querySelectorAll("[data-student-search-close]").forEach((button) => {
    button.addEventListener("click", () => setStudentModalOpen(false));
  });
  studentInput?.addEventListener("input", () => {
    window.clearTimeout(studentSearchTimer);
    studentSearchTimer = window.setTimeout(() => runStudentSearch(studentInput.value), 180);
  });

  if (!roleModal) return;

  const form = roleModal.querySelector("[data-role-switch-form]");
  const roleInput = roleModal.querySelector("[data-role-switch-role]");
  const employeeInput = roleModal.querySelector("[data-role-switch-employee]");
  const kicker = roleModal.querySelector("[data-role-switch-kicker]");
  const copy = roleModal.querySelector("[data-role-switch-copy]");
  const roleStep = roleModal.querySelector('[data-role-switch-step="role"]');
  const employeeStep = roleModal.querySelector('[data-role-switch-step="employee"]');
  const employeeList = roleModal.querySelector("[data-employee-list]");
  const employeeEmpty = roleModal.querySelector("[data-employee-empty]");
  const searchWrap = roleModal.querySelector("[data-role-switch-search-wrap]");
  const searchInput = roleModal.querySelector("[data-role-switch-search]");
  const nextButton = roleModal.querySelector("[data-role-switch-next]");
  const backButton = roleModal.querySelector("[data-role-switch-back]");
  const submitButton = roleModal.querySelector("[data-role-switch-submit]");
  const roleOptions = Array.from(roleModal.querySelectorAll("[data-role-option]"));
  let selectedRoleLabel = "";

  roleModal.querySelectorAll("[data-role-switch-close]").forEach((button) => {
    button.addEventListener("click", () => setRoleModalOpen(false));
  });

  function selectedRole() {
    return roleInput.value;
  }

  function setSelectedRole(value, label) {
    roleInput.value = value;
    selectedRoleLabel = label;
    roleOptions.forEach((option) => {
      option.classList.toggle("is-selected", option.dataset.roleValue === value);
    });
    nextButton.disabled = !value;
  }

  function setSelectedEmployee(id) {
    employeeInput.value = id || "";
    employeeList.querySelectorAll("[data-employee-option]").forEach((option) => {
      option.classList.toggle("is-selected", option.dataset.employeeId === String(id));
    });
    submitButton.disabled = !id;
  }

  function goToRoleStep() {
    roleStep.hidden = false;
    roleStep.classList.add("is-active");
    employeeStep.hidden = true;
    employeeStep.classList.remove("is-active");
    searchWrap.hidden = true;
    backButton.hidden = true;
    nextButton.hidden = false;
    submitButton.hidden = true;
    kicker.textContent = "Step 1 of 2";
    copy.textContent =
      "Choose the role you want to enter, then pick the employee whose session you will view.";
    setSelectedEmployee("");
    if (searchInput) searchInput.value = "";
    const current = roleOptions.find((option) => option.classList.contains("is-current"));
    if (current) setSelectedRole(current.dataset.roleValue, current.dataset.roleLabel);
  }

  function goToEmployeeStep() {
    roleStep.hidden = true;
    roleStep.classList.remove("is-active");
    employeeStep.hidden = false;
    employeeStep.classList.add("is-active");
    searchWrap.hidden = false;
    backButton.hidden = false;
    nextButton.hidden = true;
    submitButton.hidden = false;
    kicker.textContent = "Step 2 of 2";
    copy.textContent = `Select an employee to view the ${selectedRoleLabel || "selected"} session.`;
  }

  function renderEmployees(items) {
    employeeList.replaceChildren();
    if (!items.length) {
      employeeEmpty.hidden = false;
      submitButton.disabled = true;
      return;
    }
    employeeEmpty.hidden = true;
    items.forEach((employee) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "role-switch-option role-switch-employee";
      button.dataset.employeeOption = "true";
      button.dataset.employeeId = String(employee.id);
      button.dataset.search = `${employee.name} ${employee.code} ${employee.email}`.toLowerCase();
      const initial = (employee.name || "E").trim().charAt(0).toUpperCase();
      const avatar = document.createElement("span");
      avatar.className = "role-switch-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = initial;
      const copyWrap = document.createElement("span");
      copyWrap.className = "role-switch-employee-copy";
      const name = document.createElement("span");
      name.className = "role-switch-option-name";
      name.textContent = employee.name;
      const meta = document.createElement("span");
      meta.className = "role-switch-option-meta";
      meta.textContent = employee.is_self ? `${employee.code} · You` : employee.code;
      copyWrap.append(name, meta);
      button.append(avatar, copyWrap);
      button.addEventListener("click", () => setSelectedEmployee(employee.id));
      employeeList.appendChild(button);
    });
  }

  function filterEmployees(query) {
    const needle = (query || "").trim().toLowerCase();
    const buttons = employeeList.querySelectorAll("[data-employee-option]");
    let visible = 0;
    buttons.forEach((button) => {
      const match = !needle || (button.dataset.search || "").includes(needle);
      button.hidden = !match;
      if (match) visible += 1;
    });
    employeeEmpty.hidden = visible > 0;
  }

  roleOptions.forEach((option) => {
    option.addEventListener("click", () => {
      setSelectedRole(option.dataset.roleValue, option.dataset.roleLabel);
    });
  });

  nextButton.addEventListener("click", async () => {
    if (!selectedRole()) return;
    nextButton.disabled = true;
    nextButton.textContent = "Loading…";
    try {
      const response = await fetch(`${employeesUrl}?role=${encodeURIComponent(selectedRole())}`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      renderEmployees(data.employees || []);
      goToEmployeeStep();
    } catch (error) {
      renderEmployees([]);
      goToEmployeeStep();
    } finally {
      nextButton.textContent = "Continue";
      nextButton.disabled = !selectedRole();
    }
  });

  backButton.addEventListener("click", () => goToRoleStep());
  searchInput?.addEventListener("input", () => filterEmployees(searchInput.value));
  form.addEventListener("submit", (event) => {
    if (!selectedRole() || !employeeInput.value) event.preventDefault();
  });
})();
