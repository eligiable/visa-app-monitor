"use strict";

const $ = (selector) => document.querySelector(selector);
const loginView = $("#login-view");
const dashboardView = $("#dashboard-view");
const sections = ["overview", "jobs", "providers", "alerts", "notifications", "errors", "staff"];
const descriptions = {
  overview: "A live snapshot of monitoring and delivery activity.",
  jobs: "Availability, execution state and source for each configured job.",
  providers: "Provider health, access mode and permission review status.",
  alerts: "Verified availability events and their provenance.",
  notifications: "Outbox state by channel and recipient.",
  errors: "Operational and delivery failures recorded by the system.",
  staff: "Staff accounts provisioned by administrators.",
};
let csrfToken = "";
let currentUser = null;

function showNotice(message, kind = "") {
  const notice = $("#dashboard-message");
  notice.textContent = message;
  notice.className = `notice ${kind}`.trim();
  notice.hidden = !message;
}

function showLoginError(message) {
  $("#login-error").textContent = message;
  $("#login-error").hidden = !message;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.method && options.method !== "GET" && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401) {
    csrfToken = "";
    currentUser = null;
    dashboardView.hidden = true;
    loginView.hidden = false;
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function badge(value) {
  const element = document.createElement("span");
  const normalized = String(value ?? "UNKNOWN").toLowerCase();
  element.className = `badge ${normalized.replaceAll(/[^a-z0-9_-]/g, "_")}`;
  element.textContent = value || "UNKNOWN";
  return element;
}

function makeTable(container, columns, rows, emptyMessage = "No records to display.") {
  container.replaceChildren();
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headingRow = document.createElement("tr");
  for (const column of columns) {
    const cell = document.createElement("th");
    cell.textContent = column.label;
    headingRow.append(cell);
  }
  head.append(headingRow);
  const body = document.createElement("tbody");
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-cell";
    cell.colSpan = columns.length;
    cell.textContent = emptyMessage;
    row.append(cell);
    body.append(row);
  } else {
    for (const item of rows) {
      const row = document.createElement("tr");
      for (const column of columns) {
        const cell = document.createElement("td");
        const value = column.render ? column.render(item) : item[column.key];
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value == null || value === "" ? "—" : String(value);
        row.append(cell);
      }
      body.append(row);
    }
  }
  table.append(head, body);
  container.append(table);
}

function statusColumn(key, label = "Status") {
  return { label, render: (item) => badge(item[key]) };
}

function navigate(section) {
  if (!sections.includes(section)) return;
  if (section === "staff" && currentUser?.role !== "ADMIN") return;
  document.querySelectorAll(".dashboard-section").forEach((element) => {
    element.hidden = element.id !== `section-${section}`;
  });
  document.querySelectorAll(".nav-link").forEach((element) => {
    element.classList.toggle("active", element.dataset.section === section);
  });
  $("#page-title").textContent = section === "jobs" ? "Monitoring jobs" :
    section === "errors" ? "System errors" : section.charAt(0).toUpperCase() + section.slice(1);
  $("#page-description").textContent = descriptions[section];
  loadSection(section);
}

async function loadOverview() {
  const [overview, jobs, providers] = await Promise.all([
    request("/api/admin/dashboard/overview"),
    request("/api/admin/jobs"),
    request("/api/admin/providers"),
  ]);
  const metrics = [
    ["Active jobs", overview.active_jobs, "▤"],
    ["Available now", overview.available_jobs, "◉"],
    ["Alerts", overview.alert_count, "↗"],
    ["Pending notifications", overview.pending_notifications, "✉"],
    ["Providers", overview.provider_count, "◇"],
    ["System errors", overview.error_count, "⚠"],
  ];
  const grid = $("#metric-grid");
  grid.replaceChildren();
  for (const [label, value, icon] of metrics) {
    const card = document.createElement("article");
    card.className = "metric-card";
    card.dataset.icon = icon;
    const title = document.createElement("span");
    title.textContent = label;
    const number = document.createElement("strong");
    number.textContent = String(value);
    card.append(title, number);
    grid.append(card);
  }
  renderJobs($("#overview-jobs"), jobs.slice(0, 5), false);
  renderProviders($("#overview-providers"), providers.slice(0, 5));
}

function renderJobs(container, jobs, includeActions = true) {
  const columns = [
    { label: "Job", render: (job) => `#${job.id} · ${job.city_name}, ${job.destination_country_name} · ${job.appointment_type}` },
    statusColumn("availability_status", "Availability"),
    statusColumn("execution_status", "Execution"),
    statusColumn("access_mode", "Access mode"),
    { label: "Enabled", render: (job) => job.enabled ? "Yes" : "No" },
    { label: "Last checked", render: (job) => formatDate(job.last_check_at) },
  ];
  if (includeActions) {
    columns.push({
      label: "Actions",
      render: (job) => {
        const group = document.createElement("span");
        const history = document.createElement("button");
        history.className = "row-action";
        history.type = "button";
        history.textContent = "History";
        history.addEventListener("click", () => loadHistory(job));
        const verify = document.createElement("button");
        verify.className = "row-action";
        verify.type = "button";
        verify.textContent = "Verify";
        verify.addEventListener("click", () => openVerification(job));
        group.append(history, verify);
        if (currentUser?.role === "ADMIN") {
          const edit = document.createElement("button");
          edit.className = "row-action";
          edit.type = "button";
          edit.textContent = "Edit";
          edit.addEventListener("click", () => openJobEditor(job));
          group.append(edit);
        }
        return group;
      },
    });
  }
  makeTable(container, columns, jobs, "No monitoring jobs have been configured.");
}

function renderProviders(container, providers) {
  makeTable(container, [
    { label: "Provider", key: "name" },
    { label: "Code", key: "provider_code" },
    statusColumn("health_status", "Health"),
    statusColumn("access_mode", "Access mode"),
    statusColumn("permission_status", "Permission"),
    { label: "Enabled", render: (provider) => provider.enabled ? "Yes" : "No" },
  ], providers, "No providers are configured.");
}

async function loadJobs() {
  const filter = $("#job-filter").value;
  const suffix = filter ? `?availability_status=${encodeURIComponent(filter)}` : "";
  const jobs = await request(`/api/admin/jobs${suffix}`);
  renderJobs($("#jobs-table"), jobs);
}

async function loadStaff() {
  const staff = await request("/api/admin/staff");
  makeTable($("#staff-table"), [
    { label: "Username", key: "username" },
    { label: "Role", key: "role" },
    { label: "Status", render: (item) => item.enabled ? "Enabled" : "Disabled" },
    { label: "Last sign in", render: (item) => formatDate(item.last_login_at) },
  ], staff, "No staff accounts have been created.");
}

async function loadSection(section) {
  if (!currentUser) return;
  if (section === "staff" && currentUser.role !== "ADMIN") return;
  showNotice("");
  try {
    if (section === "overview") await loadOverview();
    if (section === "jobs") await loadJobs();
    if (section === "providers") renderProviders($("#providers-table"), await request("/api/admin/providers"));
    if (section === "alerts") {
      const alerts = await request("/api/admin/alerts");
      makeTable($("#alerts-table"), [
        { label: "Alert", render: (item) => `#${item.id} · Job #${item.job_id}` },
        statusColumn("availability_status", "Availability"),
        { label: "Source", key: "verification_source" },
        { label: "Created", render: (item) => formatDate(item.created_at) },
      ], alerts);
    }
    if (section === "notifications") {
      const notifications = await request("/api/admin/notifications");
      makeTable($("#notifications-table"), [
        { label: "Delivery", render: (item) => `#${item.id} · Alert #${item.alert_event_id}` },
        { label: "Channel", key: "channel" },
        { label: "Recipient", key: "recipient_reference" },
        statusColumn("state"),
        { label: "Created", render: (item) => formatDate(item.created_at) },
        { label: "Next attempt", render: (item) => formatDate(item.next_attempt_at) },
      ], notifications);
    }
    if (section === "errors") {
      const errors = await request("/api/admin/system-errors");
      makeTable($("#errors-table"), [
        { label: "Component", key: "component" },
        statusColumn("severity"),
        { label: "Message", key: "message" },
        { label: "Occurred", render: (item) => formatDate(item.occurred_at) },
      ], errors);
    }
    if (section === "staff") await loadStaff();
  } catch (error) {
    if (currentUser) showNotice(error.message, "notice-error");
  }
}

async function loadHistory(job) {
  try {
    const history = await request(`/api/admin/jobs/${job.id}/history`);
    $("#history-title").textContent = `Availability history · Job #${job.id}`;
    makeTable($("#job-history-table"), [
      { label: "Previous", render: (item) => item.previous_status || "Initial" },
      statusColumn("new_status", "New status"),
      { label: "Detected", render: (item) => formatDate(item.detected_at) },
      { label: "Source", render: (item) => item.manual_verification_id ? "Manual verification" : "Automated check" },
    ], history, "No availability transitions have been recorded.");
    $("#job-history-panel").hidden = false;
    $("#job-history-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showNotice(error.message, "notice-error");
  }
}

function openVerification(job) {
  $("#verification-job-id").value = String(job.id);
  $("#verification-job-label").textContent = `Job #${job.id} · ${job.appointment_type}`;
  $("#verification-url").value = job.official_source_url || "";
  $("#verification-notes").value = "";
  $("#manual-alert-enabled").checked = false;
  $("#verification-error").hidden = true;
  $("#verification-dialog").showModal();
}

async function refreshDashboard() {
  await loadSection(document.querySelector(".nav-link.active")?.dataset.section || "overview");
}

async function activateUser(user) {
  currentUser = user;
  $("#account-username").textContent = user.username;
  $("#account-role").textContent = user.role;
  $("#account-avatar").textContent = user.username.slice(0, 1).toUpperCase();
  document.querySelectorAll("[data-admin-only]").forEach((element) => {
    element.hidden = user.role !== "ADMIN";
  });
  loginView.hidden = true;
  dashboardView.hidden = false;
  await loadSection("overview");
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  showLoginError("");
  const loginForm = event.currentTarget;
  const form = new FormData(loginForm);
  const button = loginForm.querySelector("button[type=submit]");
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Sign-in failed.");
    csrfToken = data.csrf_token;
    loginForm.reset();
    await activateUser({ username: data.username, role: data.role });
  } catch (error) {
    showLoginError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Sign in";
  }
});

$("#logout-button").addEventListener("click", async () => {
  try {
    await request("/api/auth/logout", { method: "POST" });
  } catch (error) {
    showNotice(error.message, "notice-error");
  }
  csrfToken = "";
  currentUser = null;
  dashboardView.hidden = true;
  loginView.hidden = false;
  showNotice("");
  showLoginError("");
});

document.querySelectorAll(".nav-link").forEach((button) => {
  button.addEventListener("click", () => navigate(button.dataset.section));
});
document.querySelectorAll("[data-open-section]").forEach((button) => {
  button.addEventListener("click", () => navigate(button.dataset.openSection));
});
$("#refresh-button").addEventListener("click", refreshDashboard);
$("#job-filter").addEventListener("change", loadJobs);
$("#close-history").addEventListener("click", () => { $("#job-history-panel").hidden = true; });
$("#close-dialog").addEventListener("click", () => $("#verification-dialog").close());
$("#cancel-verification").addEventListener("click", () => $("#verification-dialog").close());
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = document.getElementById(button.dataset.closeDialog);
    dialog.close();
    if (dialog.id === "staff-dialog") $("#staff-form").reset();
    if (dialog.id === "job-dialog") $("#job-form").reset();
  });
});

function addSelectOptions(select, items, placeholder) {
  select.replaceChildren(new Option(placeholder, ""));
  for (const item of items) {
    select.add(new Option(`${item.name}${item.code ? ` (${item.code})` : ""}`, item.id));
  }
}

async function openJobEditor(job = null) {
  const form = $("#job-form");
  const creating = job === null;
  form.reset();
  $("#job-dialog-title").textContent = creating ? "Create monitoring job" : `Edit job #${job.id}`;
  $("#job-id").value = creating ? "" : String(job.id);
  $("#job-error").hidden = true;
  $("#job-create-fields").hidden = !creating;
  $("#job-create-fields").querySelectorAll("input, select").forEach((field) => {
    field.disabled = !creating;
  });
  if (creating) {
    try {
      const options = await request("/api/admin/job-options");
      addSelectOptions($("#job-origin"), options.origins, "Select applicant origin");
      addSelectOptions($("#job-country"), options.countries, "Select destination country");
      addSelectOptions($("#job-provider"), options.providers, "Select provider");
      $("#job-appointment-type").value = "";
      $("#job-source-url").value = "";
      $("#job-polling-interval").value = "3600";
      $("#job-jitter").value = "30";
      $("#job-enabled").checked = false;
    } catch (error) {
      showNotice(error.message, "notice-error");
      return;
    }
  } else {
    $("#job-appointment-type").value = job.appointment_type;
    $("#job-source-url").value = job.official_source_url;
    $("#job-polling-interval").value = String(job.polling_interval);
    $("#job-jitter").value = String(job.jitter_seconds);
    $("#job-enabled").checked = job.enabled;
  }
  form.dataset.creating = String(creating);
  $("#job-dialog").showModal();
}

$("#create-job-button").addEventListener("click", () => openJobEditor());
$("#create-staff-button").addEventListener("click", () => {
  $("#staff-form").reset();
  $("#staff-error").hidden = true;
  $("#staff-dialog").showModal();
});

$("#staff-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#staff-error");
  error.hidden = true;
  const password = $("#staff-password").value;
  if (password !== $("#staff-password-confirm").value) {
    error.textContent = "The passwords do not match.";
    error.hidden = false;
    return;
  }
  try {
    await request("/api/admin/staff", {
      method: "POST",
      body: JSON.stringify({
        username: $("#staff-username").value,
        password,
      }),
    });
    $("#staff-dialog").close();
    showNotice("Staff account created.");
    await loadStaff();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
});
$("#staff-dialog").addEventListener("close", () => $("#staff-form").reset());
$("#job-dialog").addEventListener("close", () => $("#job-form").reset());

$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#job-error");
  error.hidden = true;
  const creating = $("#job-form").dataset.creating === "true";
  const payload = {
    appointment_type: $("#job-appointment-type").value,
    official_source_url: $("#job-source-url").value,
    polling_interval: Number($("#job-polling-interval").value),
    jitter_seconds: Number($("#job-jitter").value),
    enabled: $("#job-enabled").checked,
  };
  if (creating) {
    Object.assign(payload, {
      origin_id: Number($("#job-origin").value),
      destination_country_id: Number($("#job-country").value),
      provider_id: Number($("#job-provider").value),
      city_name: $("#job-city").value,
      visa_centre_name: $("#job-centre").value,
      category_name: $("#job-category").value,
      category_code: $("#job-category-code").value,
    });
  }
  try {
    const url = creating ? "/api/admin/jobs" : `/api/admin/jobs/${$("#job-id").value}`;
    await request(url, {
      method: creating ? "POST" : "PATCH",
      body: JSON.stringify(payload),
    });
    $("#job-dialog").close();
    showNotice(creating ? "Monitoring job created." : "Monitoring job updated.");
    await loadJobs();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
});

$("#verification-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobId = $("#verification-job-id").value;
  const error = $("#verification-error");
  error.hidden = true;
  try {
    await request(`/api/admin/jobs/${jobId}/manual-verification`, {
      method: "POST",
      body: JSON.stringify({
        recorded_status: $("#verification-status").value,
        official_source_url: $("#verification-url").value,
        internal_notes: $("#verification-notes").value || null,
        manual_alert_enabled: $("#manual-alert-enabled").checked,
      }),
    });
    $("#verification-dialog").close();
    showNotice(`Manual verification recorded for job #${jobId}.`);
    await loadJobs();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
});

(async function initialize() {
  try {
    const user = await request("/api/auth/me");
    const token = await request("/api/auth/csrf", { method: "POST" });
    csrfToken = token.csrf_token;
    await activateUser(user);
  } catch {
    loginView.hidden = false;
    dashboardView.hidden = true;
  }
})();
