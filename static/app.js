// Velli Draw Check UI: calls the FastAPI endpoints and renders the results.
// Every CSV-derived string goes through esc() before it is put into innerHTML.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Indian number formatting with a proper minus sign: −₹1,23,456.00
const rs = (n) => (n < 0 ? "−₹" : "₹") + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rsInt = (n) => "₹" + Number(n).toLocaleString("en-IN");
// "2026-10-16" -> "16 Oct 2026" (or "16 Oct" without the year). Parsed as local midnight to avoid a UTC day shift.
const fmtDate = (iso, year = true) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(year && { year: "numeric" }) });
const isActive = (status) => status.toLowerCase() === "active";
let message = "";  // last WhatsApp text, for the Copy button

// GET a JSON endpoint. On error, turn FastAPI's detail (a string, an ambiguous-name object, or 422 validation errors) into a readable message.
async function api(path) {
  const res = await fetch(path);
  const body = await res.json();
  if (!res.ok) {
    const d = body.detail;
    if (typeof d === "string") throw new Error(d);
    if (d && d.message) throw new Error(d.message + ": " + d.candidates.map((c) => `${c.emp_code} (${c.contractor})`).join(", "));
    throw new Error("Invalid input: " + (Array.isArray(d) ? d.map((e) => e.loc.at(-1) + " " + e.msg).join("; ") : res.status));
  }
  return body;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
}

// Explains the last step of rule 5 next to the eligible amount.
function eligibleNote(r) {
  if (!isActive(r.status)) return "Inactive workers can't draw";
  if (r.before_rounding <= 0) return `${rs(r.before_rounding)}, never below ₹0`;
  if (r.before_rounding >= 5000) return `${rs(r.before_rounding)}, capped at ₹5,000 per draw`;
  return `${rs(r.before_rounding)}, rounded down to ₹100`;
}

// Show one worker's result: headline amount, decision, flags, the working line by line, and the draws counted.
function renderResult(r) {
  const req = r.request;
  const ifApproved = req && req.status === "Rejected" ? " if approved" : "";

  const decision = req ? `
    <div class="decision ${req.status.toLowerCase()}">
      <div class="decision-status"><span class="decision-badge">${req.status}</span>Request ${rs(req.amount)}</div>
      ${req.reason ? `<p class="decision-reason">${esc(req.reason)}</p>` : ""}
      <dl class="decision-figs">
        <div><dt>Fee 2%${ifApproved}</dt><dd>${rs(req.fee)}</dd></div>
        <div><dt>Repayable on payday${ifApproved}</dt><dd>${rs(req.repayable)}</dd></div>
      </dl>
    </div>` : "";

  const notices = [
    ...r.flags.map((f) => `<p class="notice flag"><strong>Flag:</strong> ${esc(f.message)}</p>`),
    ...r.warnings.map((w) => `<p class="notice warn">${esc(w)}</p>`),
  ].join("");

  const draws = r.draws.length
    ? `<table><tbody>${r.draws.map((d) => `
        <tr><td>${fmtDate(d.date)}</td><td>${rs(d.amount)}</td>
          <td class="muted">${d.paid_to === r.name ? "to worker" : "to " + esc(d.paid_to)}</td>
          <td class="mono muted">${esc(d.upi_ref)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="none">None in this cycle up to ${fmtDate(r.date)}.</p>`;

  $("result").innerHTML = `
    <header class="res-head">
      <div>
        <h2 class="res-name">${esc(r.name)}</h2>
        <p class="res-sub"><span class="mono">${esc(r.emp_code)}</span> · ${esc(r.contractor)} · Grade ${esc(r.grade)} · ${rs(r.rate)} per day</p>
      </div>
      <span class="tag ${isActive(r.status) ? "" : "inactive"}">${esc(r.status)}</span>
    </header>
    <div class="headline">
      <p class="headline-label">Can draw as of ${fmtDate(r.date)}</p>
      <p class="headline-amount ${r.eligible ? "" : "zero"}">${rsInt(r.eligible)}</p>
      <p class="headline-cycle">Cycle ${fmtDate(r.cycle_start)} – ${fmtDate(r.cycle_end)} · day ${r.days_so_far} of ${r.total_cycle_days}</p>
    </div>
    ${decision}
    ${notices ? `<div class="notices">${notices}</div>` : ""}
    <table class="statement"><tbody>
      <tr><td>Paid days</td><td class="calc">P and WO, ${fmtDate(r.cycle_start, false)} – ${fmtDate(r.date, false)}</td><td>${r.paid_days}</td></tr>
      <tr><td>Earned so far</td><td class="calc">${r.paid_days} × ${rs(r.rate)}</td><td>${rs(r.earned)}</td></tr>
      <tr><td>PF + ESI</td><td class="calc">₹2,000 × ${r.days_so_far}/${r.total_cycle_days} days</td><td>− ${rs(r.pf_esi)}</td></tr>
      <tr class="subtotal"><td>Net earned</td><td class="calc"></td><td>${rs(r.net_earned)}</td></tr>
      <tr><td>50% of net earned</td><td class="calc"></td><td>${rs(r.half_net)}</td></tr>
      <tr><td>Already drawn</td><td class="calc">${r.draws.length} draw${r.draws.length === 1 ? "" : "s"} this cycle</td><td>− ${rs(r.already_drawn)}</td></tr>
      <tr class="total"><td>Eligible to draw</td><td class="calc">${eligibleNote(r)}</td><td>${rsInt(r.eligible)}</td></tr>
    </tbody></table>
    <section class="draws">
      <h3>Draws counted this cycle</h3>
      ${draws}
    </section>`;
  $("result").hidden = false;
  $("empty").hidden = true;

  // Bonus (a): ready-to-send message in English and Tamil
  const date = fmtDate(r.date);
  const limit = rsInt(r.eligible);
  const en = `Hello ${r.name}, as of ${date} you can draw up to ${limit} from Velli. A 2% fee is recovered on payday (10th).`;
  const ta = `வணக்கம் ${r.name}, ${date} நிலவரப்படி நீங்கள் Velli-யிலிருந்து ${limit} வரை முன்பணம் பெறலாம். 2% கட்டணம் சம்பள நாளில் (10ஆம் தேதி) பிடிக்கப்படும்.`;
  $("waEn").textContent = en;
  $("waTa").textContent = ta;
  message = en + "\n\n" + ta;
  $("copy").textContent = "Copy message";
  $("whatsapp").hidden = false;
}

// Bonus (b): table of every worker's limit on the chosen date. Clicking a name opens that worker above.
function renderSummary(rows, date) {
  const canDraw = rows.filter((r) => r.eligible > 0).length;
  $("summaryTitle").innerHTML = `Workforce on ${fmtDate(date)} <span class="muted">· ${canDraw} of ${rows.length} can draw</span>`;
  $("summaryTable").innerHTML = `
    <thead><tr><th>Code</th><th>Worker</th><th>Contractor</th>
      <th class="num">Paid days</th><th class="num">Net earned</th><th class="num">Drawn</th><th class="num">Eligible</th></tr></thead>
    <tbody>${rows.map((r) => `
      <tr>
        <td class="mono">${esc(r.emp_code)}</td>
        <td><button type="button" class="link" data-code="${esc(r.emp_code)}">${esc(r.name)}</button>${isActive(r.status) ? "" : `<span class="row-tag inactive">${esc(r.status)}</span>`}${r.flags.length ? `<span class="row-tag flag">Flag</span>` : ""}</td>
        <td>${esc(r.contractor)}</td>
        <td class="num">${r.paid_days}</td>
        <td class="num">${rs(r.net_earned)}</td>
        <td class="num ${r.already_drawn ? "" : "zero"}">${rs(r.already_drawn)}</td>
        <td class="num elig ${r.eligible ? "" : "zero"}">${rsInt(r.eligible)}</td>
      </tr>`).join("")}</tbody>`;
  $("summary").hidden = false;
}

// Check one worker; the amount is sent only when it has been entered.
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  if (!$("date").value) return showError("Pick a date.");
  if ($("amount").value !== "" && Number($("amount").value) < 0) return showError("Requested amount can't be negative.");
  const q = new URLSearchParams({ worker: $("worker").value, date: $("date").value });
  if ($("amount").value !== "") q.set("amount", $("amount").value);

  const btn = $("submitBtn");
  btn.disabled = true;
  btn.textContent = "Checking…";
  $("result").setAttribute("aria-busy", "true");
  try {
    renderResult(await api("/api/eligibility?" + q));
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Check eligibility";
    $("result").removeAttribute("aria-busy");
  }
});

$("showAll").addEventListener("click", async () => {
  showError("");
  if (!$("date").value) return showError("Pick a date first.");
  try {
    renderSummary(await api("/api/summary?date=" + $("date").value), $("date").value);
  } catch (err) {
    showError(err.message);
  }
});

// Keep the workforce button label in step with the chosen date
$("date").addEventListener("change", () => {
  $("showAll").textContent = $("date").value ? `Show all workers on ${fmtDate($("date").value)}` : "Show all workers";
});

// Clicking a worker in the table loads them into the form and checks them
$("summaryTable").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-code]");
  if (!btn) return;
  $("worker").value = btn.dataset.code;
  $("amount").value = "";
  $("form").requestSubmit();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// Copy the WhatsApp text; falls back to execCommand where the Clipboard API is blocked (e.g. plain http on a LAN IP).
$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(message);
  } catch {
    const t = Object.assign(document.createElement("textarea"), { value: message });
    document.body.append(t);
    t.select();
    document.execCommand("copy");
    t.remove();
  }
  $("copy").textContent = "Copied";
});

// On load: default the date to today (local time, not UTC), then load the worker dropdown, import flags and data notes.
(async function init() {
  const today = new Date();
  $("date").value = new Date(today - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  $("date").dispatchEvent(new Event("change"));
  try {
    const [workers, flags, notes] = await Promise.all([api("/api/workers"), api("/api/flags"), api("/api/notes")]);
    $("worker").innerHTML = workers
      .map((w) => `<option value="${esc(w.emp_code)}">${esc(w.emp_code)} · ${esc(w.name)} (${esc(w.contractor)})${isActive(w.status) ? "" : " · " + esc(w.status)}</option>`)
      .join("");
    const active = workers.filter((w) => isActive(w.status)).length;
    $("dataMeta").textContent = `${workers.length} workers · ${active} active · data from attendance_register.csv and draws.csv`;

    $("flagCount").textContent = flags.length;
    $("flagsTitle").textContent = flags.length === 1 ? "draw needs review" : "draws need review";
    $("flagList").innerHTML = flags.map((f) => `<li>${esc(f.message)}</li>`).join("");
    $("flags").hidden = flags.length === 0;

    $("notesCount").textContent = `(${notes.length})`;
    $("notes").innerHTML = notes.map((n) => `<li>${esc(n)}</li>`).join("");
  } catch (err) {
    showError("Could not load workers: " + err.message);
    $("dataMeta").textContent = "Register not loaded";
  }
})();
