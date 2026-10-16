// Velli Draw Check UI: calls the FastAPI endpoints and renders the results.
// Every CSV-derived string goes through esc() before it is put into innerHTML.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Indian number formatting: 1,23,456.00
const rs = (n) => "₹" + Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rsInt = (n) => "₹" + Number(n).toLocaleString("en-IN");
// "2026-10-16" -> "16/10/2026"
const dmy = (iso) => iso.split("-").reverse().join("/");

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

// Show one worker's result card and fill in the English + Tamil WhatsApp message (bonus a).
function renderResult(r) {
  const req = r.request;
  const warnings = r.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join("");
  const draws = r.draws.length
    ? r.draws.map((d) => `${dmy(d.date)}: ${rs(d.amount)}${d.paid_to !== r.name ? ` (to ${esc(d.paid_to)})` : ""}`).join("<br>")
    : "None";
  $("result").innerHTML = `
    <div class="who">
      <span><strong>${esc(r.name)}</strong> · ${esc(r.emp_code)} · ${esc(r.contractor)} · ${rs(r.rate)}/day</span>
      <span class="tag ${r.status.toLowerCase() === "active" ? "" : "inactive"}">${esc(r.status)}</span>
    </div>
    <div class="eligible">
      <div class="muted">Eligible to draw on ${dmy(r.date)}</div>
      <div class="big">${rsInt(r.eligible)}</div>
    </div>
    <dl>
      <dt>Cycle</dt><dd>${dmy(r.cycle_start)} to ${dmy(r.cycle_end)}</dd>
      <dt>Days so far / cycle days</dt><dd>${r.days_so_far} / ${r.total_cycle_days}</dd>
      <dt>Paid days</dt><dd>${r.paid_days}</dd>
      <dt>Earned so far</dt><dd>${rs(r.earned)}</dd>
      <dt>PF + ESI (prorated)</dt><dd>− ${rs(r.pf_esi)}</dd>
      <dt>Net earned</dt><dd>${rs(r.net_earned)}</dd>
      <dt>Already drawn this cycle</dt><dd>${rs(r.already_drawn)}</dd>
      <dt class="muted">Draws counted</dt><dd class="muted">${draws}</dd>
    </dl>
    ${req ? `
    <div class="decision ${req.status}">
      <div class="status">${req.status}: ${rs(req.amount)}</div>
      ${req.reason ? `<div>${esc(req.reason)}</div>` : ""}
      <dl>
        <dt>Fee (2%)${req.status === "Rejected" ? " if approved" : ""}</dt><dd>${rs(req.fee)}</dd>
        <dt>Total repayable on payday${req.status === "Rejected" ? " if approved" : ""}</dt><dd>${rs(req.repayable)}</dd>
      </dl>
    </div>` : ""}
    ${warnings}`;
  $("result").hidden = false;

  // Bonus (a): ready-to-send message in English and Tamil
  const limit = rsInt(r.eligible);
  $("waText").value =
    `Hello ${r.name}, as of ${dmy(r.date)} you can draw up to ${limit} from Velli. A 2% fee is recovered on payday (10th).\n\n` +
    `வணக்கம் ${r.name}, ${dmy(r.date)} நிலவரப்படி நீங்கள் Velli-யிலிருந்து ${limit} வரை முன்பணம் பெறலாம். 2% கட்டணம் சம்பள நாளில் (10ஆம் தேதி) பிடிக்கப்படும்.`;
  $("whatsapp").hidden = false;
  $("copied").hidden = true;
}

// Bonus (b): table of every worker's limit on the chosen date.
function renderSummary(rows, date) {
  $("summaryTitle").textContent = `All workers on ${dmy(date)}`;
  $("summaryTable").innerHTML = `
    <thead><tr><th>Code</th><th>Name</th><th>Contractor</th><th>Status</th>
      <th class="num">Paid days</th><th class="num">Net earned</th><th class="num">Drawn</th><th class="num">Eligible</th></tr></thead>
    <tbody>${rows.map((r) => `
      <tr class="${r.status.toLowerCase() === "active" ? "" : "inactive"}">
        <td>${esc(r.emp_code)}</td><td>${esc(r.name)}</td><td>${esc(r.contractor)}</td><td>${esc(r.status)}</td>
        <td class="num">${r.paid_days}</td><td class="num">${rs(r.net_earned)}</td>
        <td class="num">${rs(r.already_drawn)}</td><td class="num"><strong>${rsInt(r.eligible)}</strong></td>
      </tr>`).join("")}</tbody>`;
  $("summary").hidden = false;
}

// Check one worker; the amount is sent only when it has been entered.
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const q = new URLSearchParams({ worker: $("worker").value, date: $("date").value });
  if ($("amount").value !== "") q.set("amount", $("amount").value);
  try {
    renderResult(await api("/api/eligibility?" + q));
  } catch (err) {
    showError(err.message);
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

// Copy the WhatsApp text; falls back to execCommand where the Clipboard API is blocked (e.g. plain http on a LAN IP).
$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("waText").value);
  } catch {
    $("waText").select();
    document.execCommand("copy");
  }
  $("copied").hidden = false;
});

// On load: default the date to today (local time, not UTC), then load the worker dropdown and data notes.
(async function init() {
  const today = new Date();
  $("date").value = new Date(today - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  try {
    const [workers, notes] = await Promise.all([api("/api/workers"), api("/api/notes")]);
    $("worker").innerHTML = workers
      .map((w) => `<option value="${esc(w.emp_code)}">${esc(w.emp_code)} · ${esc(w.name)} (${esc(w.contractor)})${w.status.toLowerCase() === "active" ? "" : " [" + esc(w.status) + "]"}</option>`)
      .join("");
    $("notes").innerHTML = notes.map((n) => `<li>${esc(n)}</li>`).join("");
  } catch (err) {
    showError("Could not load workers: " + err.message);
  }
})();
