/*
 * app.js — the entire frontend logic for the Jummikville Fee Management System.
 *
 * WHY ONE FILE, NO BUILD STEP:
 * This app is intentionally a single static folder served by the FastAPI backend.
 * There's no npm, no bundler, no compile step — just HTML + this file + a CDN or
 * two. That makes it easy for someone new to frontends to read top-to-bottom and
 * maintain, and it means "deploying the frontend" is just "the backend serves a
 * folder". Interactivity is handled by Alpine.js (loaded in index.html); this
 * file provides the data layer and the Alpine component objects.
 *
 * HOW IT'S ORGANISED:
 *   1. CONFIG        — the one school id + API base
 *   2. api()         — a tiny fetch wrapper so every call looks the same
 *   3. helpers       — formatting, status colours, "time ago"
 *   4. Alpine stores/components — one per screen, referenced from index.html
 */

// ---------------------------------------------------------------------------
// 1. CONFIG
// ---------------------------------------------------------------------------
// The backend is multi-school, but this UI drives ONE school. Seeded data uses
// id 1 (Jummikville Academy). If you ever run this for a different school,
// change this single number.
const CONFIG = {
  SCHOOL_ID: 1,
  // Same-origin: the frontend is served by the same server as the API, so we
  // can use a relative path and never worry about CORS or hardcoded hosts.
  API_BASE: "/api/v1",
};

// ---------------------------------------------------------------------------
// 1b. SECTION_CLASSES — mirrors app/constants.py exactly.
// ---------------------------------------------------------------------------
// This is the single source of truth for the section→class mapping on the
// frontend. When you add a class in constants.py, add it here too.
const SECTION_CLASSES = {
  "Preschool": ["Preschool 1", "Preschool 2", "Preschool 3", "Reception"],
  "Primary": ["Primary 1", "Primary 2", "Primary 3", "Primary 4", "Primary 5", "Primary 6"],
  "Smart Skills High School": ["JSS1", "JSS2", "JSS3", "SS1", "SS2", "SS3"],
};
const SECTIONS = Object.keys(SECTION_CLASSES);

// Make both available globally so Alpine x-data expressions can reference them.
window.SECTION_CLASSES = SECTION_CLASSES;
window.SECTIONS = SECTIONS;

// ---------------------------------------------------------------------------
// 2. api() — one wrapper for every backend call
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const url = `${CONFIG.API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    // Send the httpOnly session cookie on every request. It's same-origin so
    // this is the default, but we're explicit so the intent is obvious.
    credentials: "same-origin",
    ...options,
  });

  if (!res.ok) {
    // A 401 means the session is missing or expired. Bounce the user back to
    // the login screen — except on the auth endpoints themselves, which handle
    // their own 401s (a failed login shouldn't trigger the "session expired"
    // path, and /auth/me returning 401 is the normal "not logged in" signal).
    if (res.status === 401 && !path.startsWith("/auth/")) {
      const auth = window.Alpine && Alpine.store("auth");
      if (auth) auth.onUnauthorized();
    }

    // Try to surface the backend's error detail; fall back to a generic message.
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }

  // 204 No Content or empty body → return null instead of throwing on .json()
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

// ---------------------------------------------------------------------------
// 3. Small helpers
// ---------------------------------------------------------------------------

// Map a status string to Tailwind classes for the coloured pill/badge.
// Palette is deliberately narrow (blue / yellow / grey, with GREEN as the one
// approved exception for "Paid"), so we separate the five statuses by HUE
// FAMILY + tint depth rather than five unrelated colours:
//   • green  = done        → Paid (the one exception to the palette)
//   • blue   = on-track    → Partial (light blue, "on the way to paid")
//   • yellow = attention   → Unpaid (strong yellow) vs Overpaid (soft gold)
//   • grey   = nothing set → No fee set
function statusBadge(status) {
  switch (status) {
    case "paid":
      // Green — fully settled, the positive "done" state.
      return { label: "Paid", cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" };
    case "overpaid":
      // Soft gold — parent paid more than owed; credit to return. Attention,
      // but gentler than Unpaid, and a distinct tint so the two don't clash.
      return { label: "Overpaid", cls: "bg-accent-50 text-accent-700 ring-accent-600/30" };
    case "partial":
      // Light blue — partway to Paid. Same hue as Paid but lighter, so it reads
      // as "on the way there" while staying clearly distinguishable.
      return { label: "Partially Paid", cls: "bg-brand-50 text-brand-700 ring-brand-600/20" };
    case "no_fee":
      // Neutral grey — no fees assigned yet. Not success, not debt.
      return { label: "No fee set", cls: "bg-slate-100 text-slate-600 ring-slate-500/20" };
    case "unpaid":
      // Strong yellow — nothing paid, needs the most attention.
      return { label: "Unpaid", cls: "bg-accent-100 text-accent-700 ring-accent-600/40" };
    default:
      return { label: "Unpaid", cls: "bg-accent-100 text-accent-700 ring-accent-600/40" };
  }
}

// Format an integer kobo amount as "₦75,000". Shared so every screen formats
// money the same way. (The backend also sends *_display strings for most values;
// this is for the few places we only have raw kobo, like the fee-type default.)
function nairaFromKobo(kobo) {
  return "₦" + (Number(kobo || 0) / 100).toLocaleString("en-NG");
}

// Icon (emoji, to stay dependency-free) for each activity type.
function activityIcon(action) {
  switch (action) {
    case "payment_recorded":
      return "✅";
    case "reminder_sent":
      return "📩";
    default:
      return "•";
  }
}

// "3 minutes ago" style relative time from an ISO timestamp.
function timeAgo(isoString) {
  const then = new Date(isoString);
  const seconds = Math.floor((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" });
}

// A readable date-time, e.g. "31 Jul 2026, 2:15 PM"
function formatDateTime(isoString) {
  return new Date(isoString).toLocaleString("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// 4. Alpine components — one object per screen
// ---------------------------------------------------------------------------
// Registered on the `alpine:init` event so they're available to x-data in HTML.
document.addEventListener("alpine:init", () => {
  // -- Global app shell: which screen is showing, plus a toast notifier -------
  Alpine.store("app", {
    screen: "dashboard", // 'dashboard' | 'parents' | 'setup' | 'activity'
    toast: { show: false, message: "", kind: "success" },

    go(screen) {
      const auth = Alpine.store("auth");
      if ((screen === "payroll" || screen === "admins") && auth.user && !auth.isDirector) {
        this.notify("Director role required to access " + screen + ".", "error");
        this.screen = "dashboard";
        return;
      }
      this.screen = screen;
    },

    notify(message, kind = "success") {
      this.toast = { show: true, message, kind };
      setTimeout(() => (this.toast.show = false), 4000);
    },
  });

  // -- Auth store: who's logged in, plus login/logout + idle timeout ----------
  // The whole app is gated behind this. On load we ask the backend "who am I?"
  // (GET /auth/me); a 200 shows the app, a 401 shows the login screen. The
  // session token lives in an httpOnly cookie we never touch from JS — we only
  // track the *state* (logged in or not) here.
  Alpine.store("auth", {
    // 'checking' while the initial /me call is in flight, so we don't flash the
    // login form before we know whether there's already a valid session.
    status: "checking", // 'checking' | 'in' | 'out'
    user: null,

    // Idle timeout mirrors the backend's sliding session. If the user does
    // nothing for this long, we log them out client-side too so the UI matches
    // reality (the cookie would have expired anyway). Kept a touch under the
    // backend's 30 min so the UI never shows stale "logged in" state.
    IDLE_MINUTES: 30,
    _idleTimer: null,

    get isAuthenticated() {
      return this.status === "in";
    },

    get isDirector() {
      return this.user && (this.user.role === "director" || this.user.role === "admin");
    },

    async init() {
      try {
        this.user = await api("/auth/me");
        this.status = "in";
        this._startIdleWatch();
      } catch (_) {
        // 401 (or anything else) → treat as logged out and show the login form.
        this.status = "out";
        this.user = null;
      }
    },

    async login(email, password) {
      // Throws on failure so the login form can show the message; the caller
      // (loginForm) handles the try/catch and error display.
      this.user = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      this.status = "in";
      this._startIdleWatch();
      // Land on the dashboard after a fresh login.
      Alpine.store("app").go("dashboard");
    },

    async logout() {
      try {
        await api("/auth/logout", { method: "POST" });
      } catch (_) {
        /* even if the call fails, we still clear local state below */
      }
      this._endSession();
      Alpine.store("app").notify("You've been logged out.");
    },

    // Called by api() when any protected request comes back 401 — the session
    // expired or was revoked server-side mid-use.
    onUnauthorized() {
      if (this.status === "out") return; // already showing the login screen
      this._endSession();
      Alpine.store("app").notify("Your session expired. Please log in again.", "error");
    },

    // Shared teardown for logout and expiry.
    _endSession() {
      this.status = "out";
      this.user = null;
      this._stopIdleWatch();
    },

    // --- idle timeout: any activity resets the countdown ---
    _startIdleWatch() {
      this._stopIdleWatch();
      const reset = () => this._resetIdle();
      // Store the handler so we can remove exactly it later.
      this._idleReset = reset;
      ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((evt) =>
        window.addEventListener(evt, reset, { passive: true })
      );
      this._resetIdle();
    },

    _resetIdle() {
      if (this._idleTimer) clearTimeout(this._idleTimer);
      this._idleTimer = setTimeout(() => {
        // Idle limit hit — clear the session and tell the user why.
        this._endSession();
        Alpine.store("app").notify("Logged out after 30 minutes of inactivity.", "error");
      }, this.IDLE_MINUTES * 60 * 1000);
    },

    _stopIdleWatch() {
      if (this._idleTimer) {
        clearTimeout(this._idleTimer);
        this._idleTimer = null;
      }
      if (this._idleReset) {
        ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((evt) =>
          window.removeEventListener(evt, this._idleReset)
        );
        this._idleReset = null;
      }
    },
  });

  // -- Login form component (used by the login screen) ------------------------
  Alpine.data("loginForm", () => ({
    email: "",
    password: "",
    submitting: false,
    error: "",

    async submit() {
      if (this.submitting) return;
      this.error = "";
      if (!this.email.trim() || !this.password) {
        this.error = "Enter your email and password.";
        return;
      }
      this.submitting = true;
      try {
        await Alpine.store("auth").login(this.email.trim(), this.password);
        // Clear the password from memory once we're in.
        this.password = "";
      } catch (e) {
        this.error = e.message || "Login failed. Please try again.";
      } finally {
        this.submitting = false;
      }
    },
  }));

  // -- Dashboard screen -------------------------------------------------------
  Alpine.data("dashboard", () => ({
    loading: true,
    sending: false,
    summary: null,
    recent: [],
    chart: null,
    section: "all",   // 'all' | 'Preschool' | 'Primary' | 'Smart Skills High School'
    activeClass: null, // null = section-level view; 'Primary 3' etc = class-level view
    classSummaries: [], // ClassSummary[] for the class-tab row
    classStudents: [],  // StudentOverview[] for the class drill-down student list

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        // Build query params for the summary endpoint.
        // 'all' means whole-school (no section param).
        let summaryUrl = `/dashboard/summary?school_id=${CONFIG.SCHOOL_ID}`;
        if (this.section !== "all") summaryUrl += `&section=${encodeURIComponent(this.section)}`;
        if (this.activeClass) summaryUrl += `&class_name=${encodeURIComponent(this.activeClass)}`;

        const [summary, recent] = await Promise.all([
          api(summaryUrl),
          api(`/activity/?school_id=${CONFIG.SCHOOL_ID}&limit=6`),
        ]);
        this.summary = summary;
        this.recent = recent || [];
        // Draw the chart on the next tick, once the <canvas> is in the DOM.
        this.$nextTick(() => this.drawChart());
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // Load class-level summaries for the current section (populates the class tab row).
    async loadClasses() {
      if (this.section === "all") {
        this.classSummaries = [];
        return;
      }
      try {
        this.classSummaries = await api(
          `/dashboard/classes?school_id=${CONFIG.SCHOOL_ID}&section=${encodeURIComponent(this.section)}`
        );
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      }
    },

    // Switch the whole dashboard to a section (or back to whole-school).
    async switchSection(section) {
      if (this.section === section && this.activeClass === null) return;
      this.section = section;
      this.activeClass = null;
      await Promise.all([this.load(), this.loadClasses()]);
    },

    // Drill down into a specific class.
    async switchClass(className) {
      if (this.activeClass === className) return;
      this.activeClass = className;
      await Promise.all([this.load(), this.loadClassStudents()]);
    },

    // Go back up to the section-level view.
    async backToSection() {
      if (this.activeClass === null) return;
      this.activeClass = null;
      this.classStudents = [];
      await this.load();
    },

    // Load the roster for the drilled-in class (the student list on the
    // class page). Scoped to exactly the active section + class so the admin
    // sees only that class's students and who hasn't paid.
    async loadClassStudents() {
      if (!this.activeClass || this.section === "all") {
        this.classStudents = [];
        return;
      }
      try {
        this.classStudents = await api(
          `/dashboard/students?school_id=${CONFIG.SCHOOL_ID}` +
          `&section=${encodeURIComponent(this.section)}` +
          `&class_name=${encodeURIComponent(this.activeClass)}`
        );
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      }
    },

    drawChart() {
      const canvas = this.$refs.paidChart;
      if (!canvas || !this.summary) return;
      if (this.chart) this.chart.destroy(); // redraw cleanly on reload

      this.chart = new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: ["Fully Paid", "Overpaid", "Partially Paid", "Unpaid", "No fee set"],
          datasets: [
            {
              data: [
                this.summary.students_paid,
                this.summary.students_overpaid || 0,
                this.summary.students_partial,
                this.summary.students_unpaid,
                this.summary.students_no_fee || 0,
              ],
              // Green (paid — the one palette exception), soft gold (overpaid),
              // light blue (partial), strong yellow (unpaid), slate (no fee).
              // Matches the status badges exactly.
              backgroundColor: ["#059669", "#caa02a", "#93c5fd", "#facc15", "#94a3b8"],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "68%",
          plugins: {
            legend: { position: "bottom", labels: { padding: 16, usePointStyle: true } },
          },
        },
      });
    },

    // The "Send Reminders Now" button — triggers the real WhatsApp flow.
    // When a class is active, scopes the send to that class only.
    async sendReminders() {
      if (this.sending) return;
      const outstanding = (this.summary?.students_partial || 0) + (this.summary?.students_unpaid || 0);
      const scope = this.activeClass
        ? `parents in ${this.activeClass}`
        : this.section !== "all"
        ? `parents in ${this.section}`
        : "every parent";
      if (!confirm(
        `Send a WhatsApp reminder to ${scope} with an outstanding balance` +
        (outstanding ? ` (about ${outstanding} student${outstanding === 1 ? "" : "s"})?` : "?")
      )) return;

      this.sending = true;
      try {
        let url = `/reminders/send?school_id=${CONFIG.SCHOOL_ID}&include_payment_link=false`;
        if (this.activeClass) {
          url += `&class_name=${encodeURIComponent(this.activeClass)}`;
        } else if (this.section !== "all") {
          url += `&section=${encodeURIComponent(this.section)}`;
        }
        const result = await api(url, { method: "POST" });
        Alpine.store("app").notify(result.message || "Reminders sent.");
        await this.load(); // refresh the mini-feed so the new entries show
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.sending = false;
      }
    },

    // Class tab helpers
    get classTabsForSection() {
      return this.classSummaries;
    },

    // How many students in a class need attention (partial + unpaid)
    classAttentionCount(cls) {
      return (cls.students_partial || 0) + (cls.students_unpaid || 0);
    },

    // expose helpers to the template
    activityIcon,
    timeAgo,
    nairaFromKobo,
  }));

  // -- Parents / Students screen ---------------------------------------------
  Alpine.data("parents", () => ({
    loading: true,
    students: [],
    search: "",
    statusFilter: "all", // 'all' | 'paid' | 'partial' | 'unpaid' | 'overpaid'
    sectionFilter: "all", // 'all' | 'Preschool' | 'Primary' | 'Smart Skills High School'

    // detail drawer
    drawerOpen: false,
    detailLoading: false,
    detail: null,

    // manual payment modal
    payOpen: false,
    paySubmitting: false,
    payForm: { fee_record_id: "", amount_naira: "", method: "cash", recorded_by: "", note: "" },

    // online (Paystack) payment-link modal
    linkOpen: false,
    linkLoading: false,        // true while Paystack is generating the link
    linkStudentName: "",
    linkFeeLines: [],          // outstanding fee lines to pick from
    linkForm: { fee_record_id: "", amount_naira: "" },
    linkResult: null,          // { authorization_url, reference, amount_kobo } once generated
    linkCopied: false,

    // add-student modal. A fee type + amount are REQUIRED here so a student can
    // never be created with no fees set (which used to look misleadingly "paid").
    addOpen: false,
    addSubmitting: false,
    addForm: {
      student_name: "", section: "Primary", class_name: "", parent_name: "", parent_phone: "", parent_email: "",
      fee_type_id: "", amount_naira: "",
    },

    // edit-student modal
    editOpen: false,
    editSubmitting: false,
    editForm: { id: null, student_name: "", section: "Primary", class_name: "", parent_name: "", parent_phone: "", parent_email: "" },

    // assign-fee modal
    assignOpen: false,
    assignSubmitting: false,
    feeTypes: [],
    assignForm: { student_id: null, student_name: "", fee_type_id: "", amount_naira: "" },

    // per-parent reminder
    remindingId: null,

    // delete student modal
    deleteConfirmOpen: false,
    deleteTarget: null, // { student_id, student_name, parent_name }
    deleting: false,

    // reset all data modal (Director only)
    resetConfirmOpen: false,
    resetting: false,

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.students = await api(`/dashboard/students?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    get filtered() {
      const q = this.search.trim().toLowerCase();
      return this.students.filter((s) => {
        const matchesText =
          !q ||
          s.student_name.toLowerCase().includes(q) ||
          s.parent_name.toLowerCase().includes(q) ||
          (s.parent_phone || "").includes(q);
        const matchesStatus = this.statusFilter === "all" || s.status === this.statusFilter;
        const matchesSection = this.sectionFilter === "all" || s.section === this.sectionFilter;
        return matchesText && matchesStatus && matchesSection;
      });
    },

    // Returns the valid class list for whichever section is selected in addForm.
    get addClassOptions() {
      return SECTION_CLASSES[this.addForm.section] || [];
    },

    // Returns the valid class list for whichever section is selected in editForm.
    get editClassOptions() {
      return SECTION_CLASSES[this.editForm.section] || [];
    },

    statusBadge,
    nairaFromKobo,

    // --- detail drawer ---
    async openDetail(studentId) {
      this.drawerOpen = true;
      this.detailLoading = true;
      this.detail = null;
      try {
        this.detail = await api(`/dashboard/students/${studentId}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
        this.drawerOpen = false;
      } finally {
        this.detailLoading = false;
      }
    },

    closeDetail() {
      this.drawerOpen = false;
    },

    // --- manual (cash/POS) payment ---
    // Opens the modal pre-scoped to a student. We let staff pick which fee line
    // the payment applies to (a student can owe tuition AND books).
    openPayment(student) {
      this.payForm = {
        student_name: student.student_name,
        fee_record_id: "",
        amount_naira: "",
        method: "cash",
        recorded_by: "",
        note: "",
      };
      // We need this student's fee lines to choose from — reuse the detail call.
      this.payFeeLines = [];
      api(`/dashboard/students/${student.student_id}`)
        .then((d) => {
          // Only show lines that still have a balance to pay.
          this.payFeeLines = (d.fee_records || []).filter(
            (r) => (r.remaining_kobo ?? r.balance_kobo) > 0
          );
          if (this.payFeeLines.length === 1) {
            this.payForm.fee_record_id = this.payFeeLines[0].fee_record_id;
          }
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.payOpen = true;
    },
    payFeeLines: [],

    closePayment() {
      this.payOpen = false;
    },

    async submitPayment() {
      if (this.paySubmitting) return;
      const naira = parseFloat(this.payForm.amount_naira);
      if (!this.payForm.fee_record_id) {
        Alpine.store("app").notify("Please choose which fee this payment is for.", "error");
        return;
      }
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid amount.", "error");
        return;
      }
      if (!this.payForm.recorded_by.trim()) {
        Alpine.store("app").notify("Enter who is recording this payment.", "error");
        return;
      }

      this.paySubmitting = true;
      try {
        await api(`/payments/cash`, {
          method: "POST",
          body: JSON.stringify({
            fee_record_id: Number(this.payForm.fee_record_id),
            amount_kobo: Math.round(naira * 100), // naira → kobo for the backend
            method: this.payForm.method,
            recorded_by: this.payForm.recorded_by.trim(),
            note: this.payForm.note.trim() || null,
          }),
        });
        Alpine.store("app").notify(
          `Payment recorded. A WhatsApp confirmation has been sent to the parent.`
        );
        this.payOpen = false;
        await this.load(); // refresh balances in the table
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.paySubmitting = false;
      }
    },

    // --- online payment link (Paystack) ---
    // Opens a modal scoped to a student, lets staff pick which fee line and
    // (optionally) an amount, then calls /payments/initialize to generate a
    // Paystack checkout link the parent can open to pay online. When they pay,
    // Paystack's webhook updates the balance automatically.
    openPayLink(student) {
      this.linkStudentName = student.student_name;
      this.linkForm = { fee_record_id: "", amount_naira: "" };
      this.linkResult = null;
      this.linkCopied = false;
      this.linkFeeLines = [];
      // Reuse the detail call to load this student's outstanding fee lines.
      api(`/dashboard/students/${student.student_id}`)
        .then((d) => {
          this.linkFeeLines = (d.fee_records || []).filter(
            (r) => (r.remaining_kobo ?? r.balance_kobo) > 0
          );
          if (this.linkFeeLines.length === 1) {
            this.linkForm.fee_record_id = this.linkFeeLines[0].fee_record_id;
          }
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.linkOpen = true;
    },

    closePayLink() {
      this.linkOpen = false;
    },

    async generatePayLink() {
      if (this.linkLoading) return;
      if (!this.linkForm.fee_record_id) {
        Alpine.store("app").notify("Please choose which fee this link is for.", "error");
        return;
      }
      // Amount is optional — the backend defaults to the full remaining balance.
      const body = { fee_record_id: Number(this.linkForm.fee_record_id) };
      const naira = parseFloat(this.linkForm.amount_naira);
      if (this.linkForm.amount_naira !== "" && (!naira || naira <= 0)) {
        Alpine.store("app").notify("Enter a valid amount, or leave it blank for the full balance.", "error");
        return;
      }
      if (naira > 0) body.amount_kobo = Math.round(naira * 100);

      this.linkLoading = true;
      try {
        this.linkResult = await api(`/payments/initialize`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        Alpine.store("app").notify("Payment link generated & sent to parent via WhatsApp!");
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.linkLoading = false;
      }
    },

    async copyPayLink() {
      if (!this.linkResult?.authorization_url) return;
      try {
        await navigator.clipboard.writeText(this.linkResult.authorization_url);
        this.linkCopied = true;
        setTimeout(() => (this.linkCopied = false), 2000);
      } catch (e) {
        Alpine.store("app").notify("Couldn't copy — select the link and copy it manually.", "error");
      }
    },

    // --- add a new student (with a required fee assignment) ---
    openAdd() {
      this.addForm = {
        student_name: "",
        section: "Primary",
        class_name: "",
        parent_name: "",
        parent_phone: "",
        parent_email: "",
        fee_type_id: "",
        amount_naira: "",
      };
      // Load the fee-type catalog so the form can pick one.
      this.feeTypes = [];
      api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`)
        .then((types) => {
          this.feeTypes = types || [];
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.addOpen = true;
    },

    closeAdd() {
      this.addOpen = false;
    },

    async submitAdd() {
      if (this.addSubmitting) return;
      if (!this.addForm.student_name.trim()) {
        Alpine.store("app").notify("Enter the student's name.", "error");
        return;
      }
      if (!this.addForm.section) {
        Alpine.store("app").notify("Choose a section.", "error");
        return;
      }
      if (!this.addForm.parent_name.trim()) {
        Alpine.store("app").notify("Enter the parent's name.", "error");
        return;
      }
      if (!this.addForm.parent_phone.trim()) {
        Alpine.store("app").notify("Enter the parent's phone number.", "error");
        return;
      }
      // Fees are REQUIRED — this is what stops a student being created with a
      // misleading "No fee set" status by accident.
      if (!this.addForm.fee_type_id) {
        Alpine.store("app").notify("Choose a fee type for this student.", "error");
        return;
      }
      const feeNaira = parseFloat(this.addForm.amount_naira);
      if (!feeNaira || feeNaira <= 0) {
        Alpine.store("app").notify("Enter the total fees for this student.", "error");
        return;
      }

      this.addSubmitting = true;
      try {
        // Step 1: create the student.
        const student = await api(`/students/`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            student_name: this.addForm.student_name.trim(),
            section: this.addForm.section,
            class_name: this.addForm.class_name.trim() || null,
            parent_name: this.addForm.parent_name.trim(),
            parent_phone: this.addForm.parent_phone.trim(),
            parent_email: this.addForm.parent_email.trim() || null,
          }),
        });

        // Step 2: assign the required fee to the new student. If this fails we
        // surface it clearly — the student exists but has no fee yet, and will
        // show as "No fee set" so the gap is visible rather than hidden.
        try {
          await api(`/fees/records`, {
            method: "POST",
            body: JSON.stringify({
              student_id: student.id,
              fee_type_id: Number(this.addForm.fee_type_id),
              total_fees_kobo: Math.round(feeNaira * 100),
            }),
          });
          Alpine.store("app").notify("Student added and fee assigned.");
        } catch (feeErr) {
          Alpine.store("app").notify(
            `Student added, but assigning the fee failed: ${feeErr.message}. ` +
            `You can assign it from their record.`,
            "error"
          );
        }

        this.addOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.addSubmitting = false;
      }
    },

    // --- edit an existing student (opened from the detail drawer) ---
    openEdit() {
      if (!this.detail) return;
      this.editForm = {
        id: this.detail.student_id,
        student_name: this.detail.student_name || "",
        section: this.detail.section || "Primary",
        class_name: this.detail.class_name || "",
        parent_name: this.detail.parent_name || "",
        parent_phone: this.detail.parent_phone || "",
        parent_email: this.detail.parent_email || "",
      };
      this.editOpen = true;
    },

    closeEdit() {
      this.editOpen = false;
    },

    async submitEdit() {
      if (this.editSubmitting) return;
      if (!this.editForm.student_name.trim()) {
        Alpine.store("app").notify("Enter the student's name.", "error");
        return;
      }
      if (!this.editForm.parent_phone.trim()) {
        Alpine.store("app").notify("Enter the parent's phone number.", "error");
        return;
      }

      this.editSubmitting = true;
      try {
        await api(`/students/${this.editForm.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            student_name: this.editForm.student_name.trim(),
            section: this.editForm.section,
            class_name: this.editForm.class_name.trim() || null,
            parent_name: this.editForm.parent_name.trim(),
            parent_phone: this.editForm.parent_phone.trim(),
            parent_email: this.editForm.parent_email.trim() || null,
          }),
        });
        Alpine.store("app").notify("Student updated.");
        this.editOpen = false;
        await this.load();
        // Refresh the open drawer so it reflects the new details.
        await this.openDetail(this.editForm.id);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.editSubmitting = false;
      }
    },

    // --- assign a fee to the student in the open drawer ---
    openAssign() {
      if (!this.detail) return;
      this.assignForm = {
        student_id: this.detail.student_id,
        student_name: this.detail.student_name,
        fee_type_id: "",
        amount_naira: "",
      };
      // Load this school's fee-type catalog to pick from.
      this.feeTypes = [];
      api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`)
        .then((types) => {
          this.feeTypes = types || [];
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.assignOpen = true;
    },

    closeAssign() {
      this.assignOpen = false;
    },

    // When a fee type is chosen, pre-fill the amount with its default.
    onAssignFeeTypeChange() {
      const chosen = this.feeTypes.find(
        (t) => String(t.id) === String(this.assignForm.fee_type_id)
      );
      if (chosen) {
        this.assignForm.amount_naira = (chosen.amount_kobo / 100).toString();
      }
    },

    async submitAssign() {
      if (this.assignSubmitting) return;
      if (!this.assignForm.fee_type_id) {
        Alpine.store("app").notify("Choose a fee type.", "error");
        return;
      }
      const naira = parseFloat(this.assignForm.amount_naira);
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid amount.", "error");
        return;
      }

      this.assignSubmitting = true;
      try {
        await api(`/fees/records`, {
          method: "POST",
          body: JSON.stringify({
            student_id: this.assignForm.student_id,
            fee_type_id: Number(this.assignForm.fee_type_id),
            total_fees_kobo: Math.round(naira * 100),
          }),
        });
        Alpine.store("app").notify("Fee assigned to student.");
        this.assignOpen = false;
        await this.load();
        await this.openDetail(this.assignForm.student_id);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.assignSubmitting = false;
      }
    },

    // --- send a reminder to just this one parent (WhatsApp only) ---
    async remindOne(studentId) {
      if (this.remindingId) return;
      if (!confirm("Send a WhatsApp fee reminder to this parent now?")) return;

      this.remindingId = studentId;
      try {
        // student_id scopes it to one parent; include_payment_link=true → include Paystack link.
        const result = await api(
          `/reminders/send?school_id=${CONFIG.SCHOOL_ID}&student_id=${studentId}&include_payment_link=true`,
          { method: "POST" }
        );
        Alpine.store("app").notify(result.message || "Reminder sent with payment link.");

        // If the drawer is open on this student, refresh its message history.
        if (this.detail && this.detail.student_id === studentId) {
          await this.openDetail(studentId);
        }
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.remindingId = null;
      }
    },

    // --- delete student permanently ---
    confirmDelete(student) {
      this.deleteTarget = {
        student_id: student.student_id || student.id,
        student_name: student.student_name,
        parent_name: student.parent_name,
      };
      this.deleteConfirmOpen = true;
    },

    closeDeleteConfirm() {
      this.deleteConfirmOpen = false;
      this.deleteTarget = null;
    },

    async executeDelete() {
      if (!this.deleteTarget || this.deleting) return;
      this.deleting = true;
      try {
        const res = await api(`/students/${this.deleteTarget.student_id}?permanent=true`, {
          method: "DELETE",
        });
        Alpine.store("app").notify(res.message || "Student and parent data deleted successfully.");
        const deletedId = this.deleteTarget.student_id;
        this.closeDeleteConfirm();
        if (this.drawerOpen && (this.detail?.student_id === deletedId || this.detail?.id === deletedId)) {
          this.closeDetail();
        }
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.deleting = false;
      }
    },

    // --- reset all student data to start fresh (Director only) ---
    confirmResetAll() {
      this.resetConfirmOpen = true;
    },

    closeResetConfirm() {
      this.resetConfirmOpen = false;
    },

    async executeResetAll() {
      if (this.resetting) return;
      this.resetting = true;
      try {
        const res = await api(`/students/reset-data`, {
          method: "POST",
        });
        Alpine.store("app").notify(res.message || "All student records cleared. Fresh database ready.");
        this.closeResetConfirm();
        if (this.drawerOpen) this.closeDetail();
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.resetting = false;
      }
    },

    activityIcon,
    timeAgo,
    formatDateTime,
  }));

  // -- Terms screen: the academic terms the school runs -----------------------
  // A term ("First Term 2025/2026") is the spine fees, payments and reports key
  // off. Exactly one term is "current" at a time — the backend enforces that
  // invariant (term_service.set_current_term); this screen just calls it.
  Alpine.data("terms", () => ({
    loading: true,
    items: [],

    // create/edit modal
    formOpen: false,
    submitting: false,
    editing: null, // the term being edited, or null when creating
    form: { name: "", start_date: "", end_date: "", is_current: false },

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.items = await api(`/terms?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // A readable "1 Sep 2025 – 20 Dec 2025", or a partial/placeholder when unset.
    dateRange(t) {
      const fmt = (d) =>
        new Date(d + "T00:00:00").toLocaleDateString("en-NG", {
          day: "numeric",
          month: "short",
          year: "numeric",
        });
      if (t.start_date && t.end_date) return `${fmt(t.start_date)} – ${fmt(t.end_date)}`;
      if (t.start_date) return `From ${fmt(t.start_date)}`;
      if (t.end_date) return `Until ${fmt(t.end_date)}`;
      return "—";
    },

    openCreate() {
      this.editing = null;
      this.form = { name: "", start_date: "", end_date: "", is_current: false };
      this.formOpen = true;
    },

    openEdit(t) {
      this.editing = t;
      this.form = {
        name: t.name,
        start_date: t.start_date || "",
        end_date: t.end_date || "",
        is_current: t.is_current,
      };
      this.formOpen = true;
    },

    closeForm() {
      this.formOpen = false;
    },

    async submitForm() {
      if (this.submitting) return;
      const name = this.form.name.trim();
      if (!name) {
        Alpine.store("app").notify("Enter a term name.", "error");
        return;
      }
      if (this.form.start_date && this.form.end_date && this.form.end_date < this.form.start_date) {
        Alpine.store("app").notify("End date can't be before the start date.", "error");
        return;
      }

      this.submitting = true;
      try {
        if (this.editing) {
          await api(`/terms/${this.editing.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name,
              start_date: this.form.start_date || null,
              end_date: this.form.end_date || null,
            }),
          });
          Alpine.store("app").notify("Term updated.");
        } else {
          await api(`/terms`, {
            method: "POST",
            body: JSON.stringify({
              school_id: CONFIG.SCHOOL_ID,
              name,
              start_date: this.form.start_date || null,
              end_date: this.form.end_date || null,
              is_current: this.form.is_current,
            }),
          });
          Alpine.store("app").notify("Term created.");
        }
        this.formOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    async setCurrent(t) {
      try {
        await api(`/terms/${t.id}/set-current`, { method: "POST" });
        Alpine.store("app").notify(`"${t.name}" is now the current term.`);
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      }
    },

    async remove(t) {
      if (!confirm(`Delete the term "${t.name}"? This can't be undone.`)) return;
      try {
        await api(`/terms/${t.id}`, { method: "DELETE" });
        Alpine.store("app").notify("Term deleted.");
        await this.load();
      } catch (e) {
        // The backend refuses if any fee type still belongs to it — show that.
        Alpine.store("app").notify(e.message, "error");
      }
    },
  }));

  // -- Reports screen: term-scoped report preview + PDF/CSV downloads ----------
  // The on-screen preview renders the SAME TermReportResponse the PDF/CSV exports
  // are built from (GET /api/v1/reports/terms/{id}), so what you see is what you
  // download. The term dropdown is loaded from /terms and defaults to the current
  // term. Downloads are plain <a> links in the HTML — the session cookie rides
  // along same-origin, exactly like the receipt links.
  Alpine.data("reports", () => ({
    mode: "single", // "single" or "compare"
    loading: false,
    terms: [],
    termId: null,
    report: null,

    // Term Comparison state (Part E)
    termId1: null,
    termId2: null,
    comparison: null,
    loadingComparison: false,

    async init() {
      await this.loadTerms();
      if (this.termId) await this.load();
      if (this.terms.length >= 2) {
        this.termId1 = this.terms[1]?.id ?? this.terms[0]?.id;
        this.termId2 = this.terms[0]?.id;
      }
    },

    async loadTerms() {
      try {
        this.terms = await api(`/terms?school_id=${CONFIG.SCHOOL_ID}`);
        // Default to the current term, else the newest (the API returns newest first).
        const current = this.terms.find((t) => t.is_current);
        this.termId = current ? current.id : this.terms[0]?.id ?? null;
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      }
    },

    async load() {
      if (!this.termId) {
        this.report = null;
        return;
      }
      this.loading = true;
      try {
        this.report = await api(
          `/reports/terms/${this.termId}?school_id=${CONFIG.SCHOOL_ID}`
        );
      } catch (e) {
        this.report = null;
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async loadComparison() {
      if (!this.termId1 || !this.termId2) {
        this.comparison = null;
        return;
      }
      this.loadingComparison = true;
      try {
        this.comparison = await api(
          `/reports/compare?school_id=${CONFIG.SCHOOL_ID}&term_id_1=${this.termId1}&term_id_2=${this.termId2}`
        );
      } catch (e) {
        this.comparison = null;
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loadingComparison = false;
      }
    },

    nairaFromKobo,
  }));


  // -- Expenses screen: record & review the school's outgoing spending --------
  // Money going OUT (fuel, repairs, textbooks, "Nepa Light", ...). Visible to and
  // recordable by every admin; the acting admin is stamped server-side. Amounts
  // are entered in naira and converted to kobo (× 100) on submit, mirroring the
  // cash-payment modal. Expenses reduce the dashboard's Net Available — they never
  // touch a student's fee balance.
  Alpine.data("expenses", () => ({
    loading: true,
    items: [],
    categories: [],
    filterCategory: "",
    totalKobo: 0,

    // create/edit modal
    formOpen: false,
    submitting: false,
    editing: null, // the expense being edited, or null when creating
    form: {
      category: "",
      amount_naira: "",
      purpose: "",
      expense_date: "",
      receipt_ref: "",
      note: "",
    },

    async init() {
      await this.loadCategories();
      await this.load();
    },

    get totalDisplay() {
      return nairaFromKobo(this.totalKobo);
    },

    async loadCategories() {
      try {
        this.categories = await api(`/expenses/categories`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      }
    },

    async load() {
      this.loading = true;
      try {
        const q = this.filterCategory
          ? `&category=${encodeURIComponent(this.filterCategory)}`
          : "";
        this.items = await api(`/expenses?school_id=${CONFIG.SCHOOL_ID}${q}`);
        this.totalKobo = this.items.reduce(
          (sum, e) => sum + (e.amount_kobo || 0),
          0
        );
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    setFilter(cat) {
      this.filterCategory = cat;
      this.load();
    },

    // "1 Sep 2025" from an ISO date string.
    fmtDate(d) {
      if (!d) return "—";
      return new Date(d + "T00:00:00").toLocaleDateString("en-NG", {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
    },

    _today() {
      return new Date().toISOString().slice(0, 10);
    },

    openCreate() {
      this.editing = null;
      this.form = {
        category: this.categories[0] || "",
        amount_naira: "",
        purpose: "",
        expense_date: this._today(),
        receipt_ref: "",
        note: "",
      };
      this.formOpen = true;
    },

    openEdit(e) {
      this.editing = e;
      this.form = {
        category: e.category,
        amount_naira: (e.amount_kobo || 0) / 100,
        purpose: e.purpose,
        expense_date: e.expense_date || this._today(),
        receipt_ref: e.receipt_ref || "",
        note: e.note || "",
      };
      this.formOpen = true;
    },

    closeForm() {
      this.formOpen = false;
    },

    async submitForm() {
      if (this.submitting) return;

      const category = this.form.category;
      const purpose = (this.form.purpose || "").trim();
      const amountNaira = Number(this.form.amount_naira);

      if (!category) {
        Alpine.store("app").notify("Pick a category.", "error");
        return;
      }
      if (!purpose) {
        Alpine.store("app").notify("Enter what the money was spent on.", "error");
        return;
      }
      if (!amountNaira || amountNaira <= 0) {
        Alpine.store("app").notify("Enter an amount greater than zero.", "error");
        return;
      }

      // Naira → kobo. Round to avoid floating-point drift (e.g. 15000.1 * 100).
      const amount_kobo = Math.round(amountNaira * 100);

      const payload = {
        category,
        amount_kobo,
        purpose,
        expense_date: this.form.expense_date || null,
        receipt_ref: this.form.receipt_ref?.trim() || null,
        note: this.form.note?.trim() || null,
      };

      this.submitting = true;
      try {
        if (this.editing) {
          await api(`/expenses/${this.editing.id}?school_id=${CONFIG.SCHOOL_ID}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          });
          Alpine.store("app").notify("Expense updated.");
        } else {
          await api(`/expenses?school_id=${CONFIG.SCHOOL_ID}`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          Alpine.store("app").notify("Expense recorded.");
        }
        this.formOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    async remove(e) {
      if (!confirm(`Delete this ${e.category} expense (${e.amount_display})?`)) return;
      try {
        await api(`/expenses/${e.id}?school_id=${CONFIG.SCHOOL_ID}`, {
          method: "DELETE",
        });
        Alpine.store("app").notify("Expense deleted.");
        await this.load();
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      }
    },
  }));


  // Fee TYPES are the templates (e.g. "Tuition — First Term", ₦75,000). Assigning
  // one to a student creates a fee RECORD (handled on the Parents screen). This
  // screen is where staff define and review those templates.
  Alpine.data("setup", () => ({
    loading: true,
    feeTypes: [],

    // fee categories (the master list)
    catLoading: true,
    categories: [],

    // add-category form
    categoryOpen: false,
    categorySubmitting: false,
    categoryForm: { name: "" },

    // create-fee-type form
    createOpen: false,
    createSubmitting: false,
    createForm: { category_id: "", section: "Primary", term: "", amount_naira: "" },

    // start-new-term (rollover) modal
    rolloverOpen: false,
    rolloverSubmitting: false,
    rolloverForm: { from_term: "", to_term: "", section: "", carry_forward: true },
    rolloverResult: null, // summary returned after a successful rollover

    // Returns the list of all sections for the fee-type section dropdown.
    get sectionOptions() {
      return SECTIONS;
    },

    // Distinct terms already defined in the catalog — used to pick the FROM term.
    get existingTerms() {
      return [...new Set(this.feeTypes.map((t) => t.term))].filter(Boolean);
    },

    async init() {
      await Promise.all([this.load(), this.loadCategories()]);
    },

    async load() {
      this.loading = true;
      try {
        this.feeTypes = await api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async loadCategories() {
      this.catLoading = true;
      try {
        this.categories = await api(`/fees/categories?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.catLoading = false;
      }
    },

    // --- categories ---
    openCategory() {
      this.categoryForm = { name: "" };
      this.categoryOpen = true;
    },

    closeCategory() {
      this.categoryOpen = false;
    },

    async submitCategory() {
      if (this.categorySubmitting) return;
      if (!this.categoryForm.name.trim()) {
        Alpine.store("app").notify("Enter a category name.", "error");
        return;
      }
      this.categorySubmitting = true;
      try {
        await api(`/fees/categories`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            name: this.categoryForm.name.trim(),
          }),
        });
        Alpine.store("app").notify("Category added.");
        this.categoryOpen = false;
        await this.loadCategories();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.categorySubmitting = false;
      }
    },

    async deleteCategory(cat) {
      if (!confirm(`Delete the "${cat.name}" category? This can't be undone.`)) return;
      try {
        await api(`/fees/categories/${cat.id}`, { method: "DELETE" });
        Alpine.store("app").notify("Category deleted.");
        await this.loadCategories();
      } catch (e) {
        // The backend refuses if any fee type still uses it — show that reason.
        Alpine.store("app").notify(e.message, "error");
      }
    },

    // --- fee types ---
    openCreate() {
      if (this.categories.length === 0) {
        Alpine.store("app").notify("Add a fee category first.", "error");
        return;
      }
      this.createForm = { category_id: "", section: "Primary", term: "", amount_naira: "" };
      this.createOpen = true;
    },

    closeCreate() {
      this.createOpen = false;
    },

    async submitCreate() {
      if (this.createSubmitting) return;
      if (!this.createForm.category_id) {
        Alpine.store("app").notify("Choose a category.", "error");
        return;
      }
      if (!this.createForm.section) {
        Alpine.store("app").notify("Choose a section.", "error");
        return;
      }
      if (!this.createForm.term.trim()) {
        Alpine.store("app").notify("Enter the term (e.g. First Term).", "error");
        return;
      }
      const naira = parseFloat(this.createForm.amount_naira);
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid default amount.", "error");
        return;
      }

      this.createSubmitting = true;
      try {
        await api(`/fees/types`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            category_id: Number(this.createForm.category_id),
            section: this.createForm.section,
            term: this.createForm.term.trim(),
            amount_kobo: Math.round(naira * 100),
          }),
        });
        Alpine.store("app").notify("Fee type created.");
        this.createOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.createSubmitting = false;
      }
    },

    async deleteFeeType(t) {
      if (!confirm(`Delete "${t.name} · ${t.section} · ${t.term}"?`)) return;
      try {
        await api(`/fees/types/${t.id}`, { method: "DELETE" });
        Alpine.store("app").notify("Fee type deleted.");
        await this.load();
      } catch (e) {
        // Refused if any student has it assigned — show that reason.
        Alpine.store("app").notify(e.message, "error");
      }
    },

    // --- start a new term (rollover) ---
    openRollover() {
      this.rolloverResult = null;
      this.rolloverForm = {
        from_term: this.existingTerms[0] || "",
        to_term: "",
        section: "",
        carry_forward: true,
      };
      this.rolloverOpen = true;
    },

    closeRollover() {
      this.rolloverOpen = false;
    },

    async submitRollover() {
      if (this.rolloverSubmitting) return;
      const from = this.rolloverForm.from_term.trim();
      const to = this.rolloverForm.to_term.trim();
      if (!from || !to) {
        Alpine.store("app").notify("Enter both the current and new term.", "error");
        return;
      }
      if (from === to) {
        Alpine.store("app").notify("The new term must differ from the current term.", "error");
        return;
      }
      this.rolloverSubmitting = true;
      try {
        this.rolloverResult = await api(`/fees/terms/rollover`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            from_term: from,
            to_term: to,
            section: this.rolloverForm.section || null,
            carry_forward: this.rolloverForm.carry_forward,
          }),
        });
        Alpine.store("app").notify(`New term "${to}" started.`);
        await this.load(); // refresh the fee-type list (new-term clones appear)
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.rolloverSubmitting = false;
      }
    },

    nairaFromKobo,
  }));

  // -- Activity screen --------------------------------------------------------
  Alpine.data("activity", () => ({
    loading: true,
    items: [],

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.items = await api(`/activity/?school_id=${CONFIG.SCHOOL_ID}&limit=100`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    activityIcon,
    timeAgo,
    formatDateTime,
  }));

  // -- Admins management screen (Director-only) -------------------------------
  Alpine.data("admins", () => ({
    users: [],
    loading: true,
    formOpen: false,
    editing: null,
    submitting: false,
    form: { email: "", password: "", role: "staff_admin" },

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.users = await api(`/users?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    openCreate() {
      this.editing = null;
      this.form = { email: "", password: "", role: "staff_admin" };
      this.formOpen = true;
    },

    openEdit(u) {
      this.editing = u;
      this.form = { email: u.email, password: "", role: u.role };
      this.formOpen = true;
    },

    closeForm() {
      this.formOpen = false;
    },

    async submitForm() {
      if (!this.form.email.trim()) {
        Alpine.store("app").notify("Email is required", "error");
        return;
      }
      if (!this.editing && !this.form.password) {
        Alpine.store("app").notify("Password is required for new accounts", "error");
        return;
      }
      this.submitting = true;
      try {
        if (this.editing) {
          const payload = { email: this.form.email, role: this.form.role };
          if (this.form.password) payload.password = this.form.password;
          await api(`/users/${this.editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
          Alpine.store("app").notify("Admin account updated.");
        } else {
          await api("/users", {
            method: "POST",
            body: JSON.stringify({ ...this.form, school_id: CONFIG.SCHOOL_ID }),
          });
          Alpine.store("app").notify("New admin account created.");
        }
        this.closeForm();
        await this.load();
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    async toggleStatus(u) {
      try {
        await api(`/users/${u.id}`, {
          method: "PATCH",
          body: JSON.stringify({ is_active: !u.is_active }),
        });
        Alpine.store("app").notify(`Account ${!u.is_active ? 'activated' : 'deactivated'}.`);
        await this.load();
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      }
    },
  }));

  // -- Payroll & Staff Management screen (Director-only) ----------------------
  Alpine.data("payroll", () => ({
    subTab: "overview", // 'overview' | 'staff' | 'compare'
    summary: null,
    staffList: [],
    terms: [],
    termId: "",
    filters: { class_taught: "", staff_role: "", payment_status: "" },
    loading: true,
    submitting: false,

    // Staff modal
    staffModalOpen: false,
    editingStaff: null,
    staffForm: {
      id: null,
      full_name: "",
      role_title: "Teacher",
      phone_number: "",
      email: "",
      bank_name: "",
      account_number: "",
      account_name: "",
      classes_taught: [],
    },

    // Delete confirmation modal
    deleteModalOpen: false,
    staffToDelete: null,

    // Term Salary Setup modal
    salaryModalOpen: false,
    salaryForm: { staff_id: "", term_id: "", amount_naira: "", note: "" },

    // Payout modal
    payoutModalOpen: false,
    payoutForm: { payroll_record_id: "", staff_name: "", remaining_display: "", amount_naira: "", method: "bank_transfer", note: "" },

    // Term comparison state
    compareForm: { term_id_1: "", term_id_2: "" },
    comparisonResult: null,

    async init() {
      await Promise.all([this.loadTerms(), this.loadStaff(), this.loadSummary()]);
    },

    async loadTerms() {
      try {
        this.terms = await api(`/terms?school_id=${CONFIG.SCHOOL_ID}`);
        const current = this.terms.find(t => t.is_current);
        if (current) {
          this.termId = current.id;
          if (this.terms.length >= 2) {
            const previous = this.terms.find(t => t.id !== current.id);
            if (previous) {
              this.compareForm = { term_id_1: previous.id, term_id_2: current.id };
            }
          }
        }
      } catch (_) {}
    },

    async loadSummary() {
      this.loading = true;
      try {
        let q = `/payroll/summary?school_id=${CONFIG.SCHOOL_ID}`;
        if (this.termId) q += `&term_id=${this.termId}`;
        if (this.filters.class_taught) q += `&class_taught=${encodeURIComponent(this.filters.class_taught)}`;
        if (this.filters.staff_role) q += `&staff_role=${encodeURIComponent(this.filters.staff_role)}`;
        if (this.filters.payment_status) q += `&payment_status=${encodeURIComponent(this.filters.payment_status)}`;

        this.summary = await api(q);
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async loadStaff() {
      try {
        this.staffList = await api(`/staff?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (_) {}
    },

    // Staff Directory CRUD
    openAddStaff() {
      this.editingStaff = null;
      this.staffForm = {
        id: null,
        full_name: "",
        role_title: "Teacher",
        phone_number: "",
        email: "",
        bank_name: "",
        account_number: "",
        account_name: "",
        classes_taught: [],
      };
      this.staffModalOpen = true;
    },

    openEditStaff(s) {
      this.editingStaff = s;
      this.staffForm = {
        id: s.id,
        full_name: s.full_name,
        role_title: s.role_title,
        phone_number: s.phone_number,
        email: s.email || "",
        bank_name: s.bank_name || "",
        account_number: s.account_number || "",
        account_name: s.account_name || "",
        classes_taught: [...(s.classes_taught || [])],
      };
      this.staffModalOpen = true;
    },

    toggleStaffClass(c) {
      const idx = this.staffForm.classes_taught.indexOf(c);
      if (idx >= 0) this.staffForm.classes_taught.splice(idx, 1);
      else this.staffForm.classes_taught.push(c);
    },

    async saveStaff() {
      if (!this.staffForm.full_name.trim() || !this.staffForm.phone_number.trim()) {
        Alpine.store("app").notify("Full name and phone number are required.", "error");
        return;
      }
      this.submitting = true;
      try {
        if (this.editingStaff) {
          await api(`/staff/${this.editingStaff.id}`, {
            method: "PATCH",
            body: JSON.stringify({ ...this.staffForm }),
          });
          Alpine.store("app").notify("Staff member details updated.");
        } else {
          await api("/staff", {
            method: "POST",
            body: JSON.stringify({ ...this.staffForm, school_id: CONFIG.SCHOOL_ID }),
          });
          Alpine.store("app").notify("New staff member created.");
        }
        this.staffModalOpen = false;
        await Promise.all([this.loadStaff(), this.loadSummary()]);
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    promptDeleteStaff(s) {
      this.staffToDelete = s;
      this.deleteModalOpen = true;
    },

    async confirmDeleteStaff() {
      if (!this.staffToDelete) return;
      this.submitting = true;
      try {
        await api(`/staff/${this.staffToDelete.id}`, { method: "DELETE" });
        Alpine.store("app").notify(`Staff member '${this.staffToDelete.full_name}' deactivated. Historical payroll preserved.`);
        this.deleteModalOpen = false;
        this.staffToDelete = null;
        await Promise.all([this.loadStaff(), this.loadSummary()]);
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    // Salary Setup & Payout Modals
    openSalarySetup(staffId = "") {
      this.salaryForm = {
        staff_id: staffId || (this.staffList.length ? this.staffList[0].id : ""),
        term_id: this.termId || (this.terms.length ? this.terms[0].id : ""),
        amount_naira: "",
        note: "",
      };
      this.salaryModalOpen = true;
    },

    async saveSalarySetup() {
      const amount = parseFloat(this.salaryForm.amount_naira);
      if (!this.salaryForm.staff_id || !this.salaryForm.term_id || isNaN(amount) || amount <= 0) {
        Alpine.store("app").notify("Please select a staff member, term, and valid salary amount.", "error");
        return;
      }
      this.submitting = true;
      try {
        await api("/payroll/setup", {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            staff_id: Number(this.salaryForm.staff_id),
            term_id: Number(this.salaryForm.term_id),
            amount_scheduled_kobo: Math.round(amount * 100),
            note: this.salaryForm.note,
          }),
        });
        Alpine.store("app").notify("Staff term salary scheduled.");
        this.salaryModalOpen = false;
        await this.loadSummary();
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    openPayout(record) {
      this.payoutForm = {
        payroll_record_id: record.id,
        staff_name: record.staff_name,
        remaining_display: record.remaining_display,
        amount_naira: (record.remaining_kobo / 100).toString(),
        method: "bank_transfer",
        note: "",
      };
      this.payoutModalOpen = true;
    },

    async savePayout() {
      const amount = parseFloat(this.payoutForm.amount_naira);
      if (isNaN(amount) || amount <= 0) {
        Alpine.store("app").notify("Please enter a valid payout amount.", "error");
        return;
      }
      this.submitting = true;
      try {
        await api("/payroll/payments", {
          method: "POST",
          body: JSON.stringify({
            payroll_record_id: Number(this.payoutForm.payroll_record_id),
            amount_kobo: Math.round(amount * 100),
            method: this.payoutForm.method,
            note: this.payoutForm.note,
          }),
        });
        Alpine.store("app").notify("Salary payout recorded & WhatsApp notification dispatched!");
        this.payoutModalOpen = false;
        await this.loadSummary();
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      } finally {
        this.submitting = false;
      }
    },

    // Term Comparison
    async runComparison() {
      if (!this.compareForm.term_id_1 || !this.compareForm.term_id_2) {
        Alpine.store("app").notify("Please select two terms to compare.", "error");
        return;
      }
      try {
        this.comparisonResult = await api(`/payroll/compare?term_id_1=${this.compareForm.term_id_1}&term_id_2=${this.compareForm.term_id_2}&school_id=${CONFIG.SCHOOL_ID}`);
      } catch (err) {
        Alpine.store("app").notify(err.message, "error");
      }
    },

    // PDF Export
    downloadReportPdf() {
      if (!this.termId) {
        Alpine.store("app").notify("Please select a term to export.", "error");
        return;
      }
      window.open(`/api/v1/payroll/reports/terms/${this.termId}/export.pdf`, "_blank");
    },
  }));
});
