(function () {
  const modal = document.querySelector("[data-edit-student-modal]");
  const form = document.querySelector("[data-edit-student-form]");
  const sponsorField = document.querySelector("[data-sponsor-details-field]");
  const fields = {
    firstName: document.querySelector("#edit-student-first-name"),
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
  const photoPlaceholder = document.querySelector("[data-edit-student-photo-placeholder]");
  const clearWrap = document.querySelector("[data-edit-student-clear-wrap]");

  function setPhotoPreview(url) {
    const hasPhoto = Boolean(url);
    if (photoPreview) {
      photoPreview.hidden = !hasPhoto;
      photoPreview.src = url || "";
    }
    if (photoPlaceholder) photoPlaceholder.hidden = hasPhoto;
    if (clearWrap) clearWrap.hidden = !hasPhoto;
    if (fields.clearProfileImage) fields.clearProfileImage.checked = false;
  }

  function toggleSponsorDetails() {
    const value = fields.sponsorshipCategory?.value;
    const required = value === "GOVERNMENT" || value === "BOTH";
    if (sponsorField) sponsorField.hidden = !required;
    if (fields.sponsorDetails) fields.sponsorDetails.required = required;
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
      fields.lastName.value = button.dataset.lastName || "";
      fields.dateOfBirth.value = button.dataset.dateOfBirth || "";
      fields.gender.value = button.dataset.gender || "";
      fields.academicLevel.value = button.dataset.academicLevel || "";
      fields.admissionNumber.value = button.dataset.admissionNumber || "";
      fields.classGroup.value = button.dataset.classGroup || "";
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
      setPhotoPreview(button.dataset.profileImageUrl || "");
      toggleSponsorDetails();
      setOpen(true);
    });
  });

  fields.sponsorshipCategory?.addEventListener("change", toggleSponsorDetails);
  fields.profileImage?.addEventListener("change", () => {
    const file = fields.profileImage.files && fields.profileImage.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPhotoPreview(url);
    if (fields.clearProfileImage) fields.clearProfileImage.checked = false;
  });
  fields.clearProfileImage?.addEventListener("change", () => {
    if (!fields.clearProfileImage.checked) return;
    if (fields.profileImage) fields.profileImage.value = "";
    if (photoPreview) {
      photoPreview.hidden = true;
      photoPreview.src = "";
    }
    if (photoPlaceholder) photoPlaceholder.hidden = false;
  });

  modal?.querySelectorAll("[data-edit-student-close]").forEach((button) => {
    button.addEventListener("click", () => setOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
})();
