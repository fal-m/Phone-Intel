import json
import os
import sqlite3
import subprocess
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="Private Phone Intelligence")
ROOT = Path.home() / "original-tower-collector"
API_URL = "http://127.0.0.1:8010/number-intelligence"
CLI = ROOT / "cli" / "phoneintel.py"
PYTHON = ROOT / ".venv" / "bin" / "python"

if not PYTHON.exists():
    import sys
    PYTHON = Path(sys.executable)

DATABASES = {
    "Tower observations": ROOT / "data" / "tower_observations.db",
    "Local cell intelligence": ROOT / "data" / "local_cell_intelligence.db",
    "Cell metadata snapshots": Path.home() / "cell-metadata-monitor/data/cells.sqlite3",
}

HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Private Phone Intelligence</title>
<style>
:root{color-scheme:dark;--bg:#0b1120;--panel:#131d30;--line:#283750;
--text:#e8eef9;--muted:#9aabc3;--accent:#76a9ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:16px system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:auto;padding:25px 16px 55px}
.panel{background:var(--panel);border:1px solid var(--line);
border-radius:14px;padding:18px;margin:14px 0}
h1{font-size:clamp(25px,4vw,36px)}
p,.muted{color:var(--muted);line-height:1.5}
form{display:flex;gap:10px;flex-wrap:wrap}
input{flex:1;min-width:220px;padding:13px;border-radius:9px;
border:1px solid var(--line);background:var(--bg);color:var(--text)}
button{padding:12px 16px;border:0;border-radius:9px;
background:var(--accent);color:#071328;font-weight:700;cursor:pointer}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}
.tabs button{background:#202d43;color:var(--text)}
.tabs button.active{background:var(--accent);color:#071328}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.item{padding:12px;border:1px solid var(--line);border-radius:9px;overflow-wrap:anywhere}
.key{font-size:12px;text-transform:uppercase;color:var(--muted);margin-bottom:7px}
.val{font-weight:600;white-space:pre-wrap;overflow-wrap:anywhere}
.notice{padding:12px;border-radius:9px;background:#202d43;line-height:1.5}
.error{background:#44252b;color:#ffd8dc}
.tablewrap{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
th{color:var(--muted)}
pre{white-space:pre-wrap;overflow-wrap:anywhere}
.hidden{display:none}
</style>
</head>
<body><main>
<h1>Private Phone Intelligence</h1>
<p>Local-first analysis · CLI integration · Local cell records · No public tunnel</p>

<section class="panel">
<h2>Analyze a phone number</h2>
<form id="search">
<input id="number" autocomplete="off" placeholder="+91..." required
aria-label="Phone number">
<button id="submit" type="submit">Analyze</button>
</form>
<p class="muted">Analysis runs against your local CLI and local API.
Use only numbers and records you are authorized to examine.</p>
<div id="status" class="notice" role="status">Ready.</div>
</section>

<nav class="tabs" aria-label="Analysis variants">
<button class="active" data-tab="basic">1 · Basic details</button>
<button data-tab="timeline">2 · Cell timeline</button>
<a href="/tower-map" style="display:inline-block;padding:10px 14px;margin:6px;border:1px solid #5684ff;border-radius:9px;color:inherit;text-decoration:none;font-weight:600">🗺️ India Tower Map</a>
<button data-tab="public">3 · Public references</button>
<button type="button" data-section-target="recent-call-data">4 · Recent Call Data</button>
</nav>

<section id="basic" class="panel">
<h2>Variant 1 — Number overview</h2>
<div id="fields" class="grid">Enter a number and select Analyze.</div>
<details style="margin-top:15px">
<summary>Full local CLI/API JSON</summary><pre id="raw"></pre>
</details>
</section>

<section id="timeline" class="panel hidden">
<h2>Variant 2 — Local cell records</h2>
<p>These are database observations, not proof that the entered phone used
a particular cell. The timestamp belongs to the record, not necessarily
to the phone.</p>
<button id="reload">Reload local records</button>
<div id="dbsummary" class="grid" style="margin:14px 0"></div>
<div id="records" class="tablewrap"></div>
</section>

<section id="public" class="panel hidden">
<h2>Public Records &amp; Investigation</h2>
<div class="notice">
Check configured local sources only. This does not retrieve private telecom
call logs or track live phone location.
</div>

<div id="public-search-links"
     style="margin:14px 0;padding:12px;border:1px solid #888;border-radius:8px">
  <h3>Public web search</h3>
  <p>Search the number entered in Section 1, both with and without India's +91 country code.</p>
  <p id="publicSearchPreview" class="muted">Enter a phone number in Section 1 first.</p>
  <button type="button" id="searchAllPublic">Search All — 6 tabs</button>
  <p id="publicSearchNote" role="status"></p>
</div>
<script>
(() => {
  const phone = document.getElementById("number");
  const button = document.getElementById("searchAllPublic");
  const preview = document.getElementById("publicSearchPreview");
  const note = document.getElementById("publicSearchNote");

  const providers = [
    q => "https://www.google.com/search?q=" + encodeURIComponent(q),
    q => "https://www.bing.com/search?q=" + encodeURIComponent(q),
    q => "https://duckduckgo.com/?q=" + encodeURIComponent(q)
  ];

  function variants() {
    const entered = phone.value.trim();
    const digits = entered.replace(/\D/g, "");
    let national = digits;

    if (digits.length === 12 && digits.startsWith("91")) {
      national = digits.slice(2);
    } else if (digits.length === 10) {
      national = digits;
    } else if (entered.startsWith("+91") && digits.length > 2) {
      national = digits.slice(2);
    }

    if (!national) return [];
    const local = national;
    const international = national.length === 10
      ? "+91 " + national
      : entered;

    return [...new Set([international, local].filter(Boolean))];
  }

  function updatePreview() {
    const terms = variants();
    preview.textContent = terms.length
      ? "Search terms: " + terms.join("  |  ")
      : "Enter a phone number in Section 1 first.";
  }

  phone.addEventListener("input", updatePreview);
  updatePreview();

  button.addEventListener("click", () => {
    const terms = variants();
    if (!terms.length) {
      note.textContent = "Enter a phone number in Section 1 first.";
      phone.focus();
      return;
    }

    let opened = 0;
    for (const term of terms) {
      for (const makeUrl of providers) {
        const tab = window.open(makeUrl(term), "_blank");
        if (tab) opened++;
      }
    }

    note.textContent = opened === terms.length * providers.length
      ? "Opened " + opened + " public search tabs. Results come from the search providers."
      : "The browser opened " + opened + " of " +
        (terms.length * providers.length) +
        " tabs. Allow pop-ups for this local dashboard and click Search All again if needed.";
  });
})();
</script>

<button id="investigate" type="button">Start Investigation</button>
<div id="investigationProgress" class="notice" role="status" style="margin-top:12px">
Ready. No scan has started.
</div>
<div id="investigationSources" class="grid" style="margin-top:12px"></div>
<p id="publicnote">Public-web lookup is not configured.</p>
</section>

<footer class="muted">Local interface. Keep both services bound to 127.0.0.1.</footer>
</main>
<script>
const $ = id => document.getElementById(id);

const mainPhoneInput = $("number");
const callPhoneInput = $("callSearch");
if (mainPhoneInput && callPhoneInput) {
  mainPhoneInput.addEventListener("input", () => {
    callPhoneInput.value = mainPhoneInput.value;
  });
  callPhoneInput.value = mainPhoneInput.value;
}
const pretty = v => v === null || v === undefined || v === ""
  ? "Not available" : typeof v === "object" ? JSON.stringify(v) : String(v);

document.querySelectorAll("[data-tab]").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach(b =>
      b.classList.toggle("active", b === button));
    ["basic","timeline","public"].forEach(id =>
      $(id).classList.toggle("hidden", id !== button.dataset.tab));
  });
});

function field(container, key, value) {
  const item = document.createElement("div");
  item.className = "item";
  const k = document.createElement("div");
  k.className = "key";
  k.textContent = key.replaceAll("_", " ");
  const v = document.createElement("div");
  v.className = "val";
  v.textContent = pretty(value);
  item.append(k, v);
  container.append(item);
}

$("search").addEventListener("submit", async e => {
  e.preventDefault();
  const number = $("number").value.trim();
  $("submit").disabled = true;
  $("status").textContent = "Running local CLI analysis…";
  try {
    const r = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({number, region:"IN"})
    });
    const data = await r.json();
    if (!r.ok) throw Error(data.detail || "Analysis failed");
    const fields = $("fields");
    fields.replaceChildren();
    const preferred = [
      "international_format","e164","national_format","country_calling_code",
      "region_code","possible","valid_numbering_range","number_type",
      "region_description","truecaller_lookup","carrier_allocation_metadata","current_carrier","current_carrier_status","current_carrier_source","carrier_verification_note","porting_status","porting_status_source","porting_status_note","network_requests_made",
      "cell_matches","limitations"
    ];
    preferred.forEach(k => {
      if (Object.prototype.hasOwnProperty.call(data,k)) field(fields,k,data[k]);
    });
    $("raw").textContent = JSON.stringify(data,null,2);
    $("status").textContent =
      "Analysis complete. Metadata is not proof of subscriber identity or live location.";
  } catch (err) {
    $("status").textContent = "Analysis error: " + err.message;
    $("status").className = "notice error";
  } finally {
    $("submit").disabled = false;
  }
});


async function startInvestigation() {
  const button = $("investigate");
  const progress = $("investigationProgress");
  const box = $("investigationSources");

  button.disabled = true;
  box.replaceChildren();
  progress.className = "notice";
  progress.textContent = "Step 1/3 — Checking local sources…";

  try {
    const r = await fetch("/api/investigation");
    const result = await r.json();
    if (!r.ok) throw Error(result.detail || "Source check failed");

    progress.textContent = "Step 2/3 — Refreshing timeline…";
    await loadTimeline();

    result.sources.forEach(source => {
      const item = document.createElement("div");
      item.className = "item";

      const title = document.createElement("strong");
      title.textContent = source.name;

      const detail = document.createElement("div");
      detail.className = "muted";
      detail.textContent = source.status +
        (source.count === undefined ? "" : " · " + source.count + " record(s)");

      item.append(title, detail);
      box.append(item);
    });

    progress.textContent = "Step 3/3 — Complete. " +
      result.records_found + " local observation records found. " +
      "Timeline opened below.";

    document.querySelectorAll("[data-tab]").forEach(b =>
      b.classList.toggle("active", b.dataset.tab === "timeline"));
    ["basic", "timeline", "public"].forEach(id =>
      $(id).classList.toggle("hidden", id !== "timeline"));

    window.scrollTo({top: 0, behavior: "smooth"});
  } catch (e) {
    progress.className = "notice error";
    progress.textContent = "Investigation error: " + e.message;
  } finally {
    button.disabled = false;
  }
}

$("investigate").addEventListener("click", startInvestigation);

async function loadTimeline() {
  $("dbsummary").textContent = "Reading local databases…";
  $("records").textContent = "";
  try {
    const r = await fetch("/api/timeline");
    const data = await r.json();
    if (!r.ok) throw Error(data.detail || "Read failed");
    data.records.sort((a, b) =>
      String(b.observed_at || "").localeCompare(String(a.observed_at || "")));
    const summary = $("dbsummary");
    summary.replaceChildren();
    data.databases.forEach(db => {
      const item = document.createElement("div");
      item.className = "item";
      item.textContent = db.name + ": " + db.status +
        (db.count === undefined ? "" : " · " + db.count + " record(s)");
      summary.append(item);
    });
    if (!data.records.length) {
      $("records").textContent = "No local cell observations found.";
      return;
    }
    const table = document.createElement("table");
    const headers = ["Database","Table","Observed at","Radio","MCC","MNC",
      "LAC/TAC","Cell ID","Latitude","Longitude","Source","Verified"];
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    headers.forEach(h => {
      const th = document.createElement("th"); th.textContent = h; hr.append(th);
    });
    thead.append(hr); table.append(thead);
    const tbody = document.createElement("tbody");
    data.records.forEach(rec => {
      const tr = document.createElement("tr");
      ["database","table","observed_at","radio","mcc","mnc","lac_tac",
       "cell_id","latitude","longitude","source","verified"].forEach(k => {
        const td = document.createElement("td");
        td.textContent = pretty(rec[k]); tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(tbody); $("records").append(table);
  } catch (err) {
    $("dbsummary").textContent = "Timeline error: " + err.message;
  }
}
$("reload").addEventListener("click", loadTimeline);
loadTimeline();
</script>

<section id="recent-call-data"
 style="margin:24px 0;padding:16px;border:1px solid #888;border-radius:10px">
  <h2>Recent Call Data</h2>
  <p>Default view: last 48 hours (rolling window from current time). Results come only from imported, authorized call-log CSV records.</p>

  <label for="callCsv">Import call-log CSV</label>
  <textarea id="callCsv" rows="5"
    style="display:block;width:100%;margin:8px 0"
    placeholder="timestamp,phone_number,call_type,duration_seconds,contact_name"></textarea>
  <button type="button" id="importCalls">Import call log</button>

  <hr>
  <h3>Filter call records</h3>

  <label for="callSearch">Exact phone number (optional)</label>
  <input id="callSearch" type="text" placeholder="+919876543210"
    style="display:block;margin:6px 0 12px;width:100%;box-sizing:border-box">

  <label for="callStart">From date and time (optional)</label>
  <input id="callStart" type="datetime-local"
    style="display:block;margin:6px 0 12px;max-width:100%">

  <label for="callEnd">To date and time (optional)</label>
  <input id="callEnd" type="datetime-local"
    style="display:block;margin:6px 0 12px;max-width:100%">

  <p>If both date/time fields are blank, the last 24 hours are shown.
  If using a custom range, fill both fields.</p>

  <button type="button" id="searchCalls">Apply filters</button>
  <button type="button" id="resetCallFilters">Reset to last 48 hours</button>
  <pre id="callResults"
    style="white-space:pre-wrap;overflow-wrap:anywhere;margin-top:12px"></pre>

  <script>
  (() => {
    const $ = id => document.getElementById(id);
    const out = $('callResults');

    $('importCalls').addEventListener('click', async () => {
      out.textContent = 'Importing...';
      try {
        const res = await fetch('/api/recent-calls/import', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({csv_text: $('callCsv').value})
        });
        const data = await res.json();
        out.textContent = JSON.stringify(data, null, 2);
        if (res.ok && data.ok) await searchCalls();
      } catch (e) {
        out.textContent = 'Import failed: ' + e.message;
      }
    });

    async function searchCalls() {
      out.textContent = 'Searching imported records...';
      try {
        const number = $('callSearch').value.trim();
        const start = $('callStart').value;
        const end = $('callEnd').value;

        if ((start && !end) || (!start && end)) {
          out.textContent = 'For a custom date range, provide both From and To.';
          return;
        }
        if (start && end && start > end) {
          out.textContent = 'From date/time must be earlier than To date/time.';
          return;
        }

        const params = new URLSearchParams();
        if (number) params.set('number', number);
        if (start && end) {
          params.set('start', start);
          params.set('end', end);
        }

        const res = await fetch('/api/recent-calls?' + params.toString());
        const data = await res.json();
        out.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        out.textContent = 'Search failed: ' + e.message;
      }
    }

    $('searchCalls').addEventListener('click', searchCalls);
    $('resetCallFilters').addEventListener('click', () => {
      $('callSearch').value = '';
      $('callStart').value = '';
      $('callEnd').value = '';
      searchCalls();
    });

    searchCalls();
  })();
  </script>
</section>





<script id="nav4-recent-call-handler">
(() => {
  document.querySelectorAll('[data-section-target="recent-call-data"]').forEach(button => {
    button.addEventListener('click', () => {
      const section = document.getElementById('recent-call-data');
      if (section) section.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
  });
})();
</script>

</body></html>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML

@app.get("/health")
def health():
    return {"status": "healthy", "service": "private-phone-intelligence-ui"}


@app.post("/api/recent-calls/import")
async def import_authorized_recent_calls(payload: dict):
    if os.getenv("PHONE_INTEL_PUBLIC_DEMO", "false").lower() == "true":
        raise HTTPException(403, "Call-log import is disabled on the public demo.")
    import csv
    import io
    from pathlib import Path
    from datetime import datetime, timezone

    raw = payload.get("csv_text", "")
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "error": "Paste an exported call-log CSV first."}

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return {"ok": False, "error": "CSV header row is missing."}

    def get_value(row, *names):
        normalized = {str(k).strip().lower().replace(" ", "_"): v
                      for k, v in row.items() if k is not None}
        for name in names:
            value = normalized.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    records = []
    for row in reader:
        phone = get_value(row, "phone_number", "phone", "number", "phone_number")
        if not phone:
            continue
        records.append({
            "timestamp": get_value(row, "timestamp", "datetime", "date_time", "date"),
            "phone_number": phone,
            "call_type": get_value(row, "call_type", "type", "call_status", "status") or "unknown",
            "duration_seconds": get_value(row, "duration_seconds", "duration", "duration_sec") or "0",
            "contact_name": get_value(row, "contact_name", "name", "contact"),
            "source": "User-imported call log",
            "imported_at": datetime.now(timezone.utc).isoformat()
        })

    if not records:
        return {
            "ok": False,
            "error": "No usable rows found. Include a phone/number column in the CSV."
        }

    path = Path.home() / "original-tower-collector" / "data" / "authorized-call-logs.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp", "phone_number", "call_type", "duration_seconds",
              "contact_name", "source", "imported_at"]
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(records)

    return {"ok": True, "imported": len(records), "storage": str(path)}


@app.get("/api/recent-calls")
async def get_authorized_recent_calls(
    number: str = "",
    start: str = "",
    end: str = ""
):
    if os.getenv("PHONE_INTEL_PUBLIC_DEMO", "false").lower() == "true":
        raise HTTPException(403, "Call-log retrieval is disabled on the public demo.")
    import csv
    from pathlib import Path
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    path = Path.home() / "original-tower-collector" / "data" / "authorized-call-logs.csv"
    local_tz = ZoneInfo("Asia/Kolkata")
    local_now = datetime.now(local_tz)

    def parse_dt(value):
        value = (value or "").strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
                "%d-%m-%Y %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    pass
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz)
        return dt.astimezone(local_now.tzinfo)

    if bool(start) != bool(end):
        raise HTTPException(400, "Provide both start and end for a custom date range.")

    if start and end:
        start_dt = parse_dt(start)
        end_dt = parse_dt(end)
        if start_dt is None or end_dt is None:
            raise HTTPException(400, "Invalid date/time. Use valid ISO date/time values.")
        if start_dt > end_dt:
            raise HTTPException(400, "Start must be earlier than or equal to end.")
        mode = "custom_range"
    else:
        end_dt = local_now
        start_dt = end_dt.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mode = "today_local"

    wanted = "".join(c for c in number if c.isdigit())
    if not path.exists():
        return {
            "count": 0,
            "records": [],
            "filters": {
                "mode": mode,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "number": number.strip() or None,
            },
            "note": "No imported call-log CSV records exist yet."
        }

    matched = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for record in csv.DictReader(f):
            digits = "".join(
                c for c in record.get("phone_number", "") if c.isdigit()
            )
            if wanted and digits != wanted:
                continue

            # Missing/unparseable timestamps cannot be proven to fall in range.
            call_dt = parse_dt(record.get("timestamp", ""))
            if call_dt is None or not (start_dt <= call_dt <= end_dt):
                continue

            record["timestamp"] = call_dt.isoformat()
            matched.append((call_dt, record))

    matched.sort(key=lambda item: item[0], reverse=True)
    records = [record for _, record in matched]

    return {
        "count": len(records),
        "records": records[:500],
        "truncated": len(records) > 500,
        "filters": {
            "mode": mode,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "number": number.strip() or None,
        },
        "note": "Results are from imported call logs, not live telecom records."
    }


@app.post("/api/analyze")
async def analyze(payload: dict):
    number = payload.get("number")
    region = str(payload.get("region", "IN")).upper()
    if not isinstance(number, str) or not number.strip():
        raise HTTPException(400, "Enter a phone number.")

    if not CLI.is_file():
        raise HTTPException(500, f"CLI not found: {CLI}")

    # Run the existing CLI locally; no public lookup is requested.
    try:
        proc = subprocess.run(
            [str(PYTHON), str(CLI), number.strip(),
             "--region", region, "--json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Local CLI timed out.")
    if proc.returncode != 0:
        raise HTTPException(500, "CLI failed: " + (proc.stderr[-1200:] or "unknown error"))
    try:
        cli_result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(500, "CLI did not return valid JSON.")

    # Keep the existing API available and include its result when reachable.
    api_result = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                API_URL, json={"number": number.strip(), "region": region}
            )
            response.raise_for_status()
            api_result = response.json()
    except (httpx.HTTPError, ValueError):
        pass

    return {
        **cli_result,
        "cli_result": cli_result,
        "api_result": api_result,
        "integration_status": "local_cli_success",
        "network_requests_made": False,
        "note": "Number metadata does not establish live GPS, subscriber identity, or current serving cell."
    }

def readonly_connect(path):
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=3)

@app.get("/api/timeline")
def timeline():
    statuses, records = [], []
    for label, path in DATABASES.items():
        if not path.is_file():
            statuses.append({"name": label, "status": "file not found", "count": 0})
            continue
        try:
            with readonly_connect(path) as db:
                tables = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if label == "Tower observations" and "observations" in tables:
                    table = "observations"
                    rows = db.execute("""
                        SELECT observed_at, radio, mcc, mnc, lac_tac, cell_id,
                               latitude, longitude, source, NULL AS verified
                        FROM observations ORDER BY observed_at DESC LIMIT 200
                    """).fetchall()
                    count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
                elif label == "Local cell intelligence" and "cell_records" in tables:
                    table = "cell_records"
                    rows = db.execute("""
                        SELECT observed_at, radio, mcc, mnc, lac_tac, cell_id,
                               latitude, longitude, source, verified
                        FROM cell_records ORDER BY observed_at DESC LIMIT 200
                    """).fetchall()
                    count = db.execute("SELECT COUNT(*) FROM cell_records").fetchone()[0]
                elif label == "Cell metadata snapshots" and "snapshots" in tables:
                    table = "snapshots"
                    rows = db.execute("""
                        SELECT observed_at, payload FROM snapshots
                        ORDER BY observed_at DESC LIMIT 200
                    """).fetchall()
                    count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                    for observed_at, payload in rows:
                        try:
                            d = json.loads(payload)
                        except (ValueError, TypeError):
                            d = {}
                        records.append({
                            "database": label, "table": table,
                            "observed_at": observed_at, "radio": d.get("radio"),
                            "mcc": d.get("mcc"), "mnc": d.get("mnc"),
                            "lac_tac": d.get("lac") or d.get("tac"),
                            "cell_id": d.get("cellid", d.get("cid")),
                            "latitude": d.get("lat"), "longitude": d.get("lon"),
                            "source": d.get("source"), "verified": None
                        })
                    statuses.append({"name": label, "status": "ok", "count": count})
                    continue
                else:
                    statuses.append({"name": label, "status": "expected table unavailable", "count": 0})
                    continue

                for row in rows:
                    (observed_at, radio, mcc, mnc, lac_tac, cell_id,
                     latitude, longitude, source, verified) = row
                    records.append({
                        "database": label, "table": table,
                        "observed_at": observed_at, "radio": radio,
                        "mcc": mcc, "mnc": mnc, "lac_tac": lac_tac,
                        "cell_id": cell_id, "latitude": latitude,
                        "longitude": longitude, "source": source,
                        "verified": verified
                    })
                statuses.append({"name": label, "status": "ok", "count": count})
        except sqlite3.Error as exc:
            statuses.append({"name": label, "status": "read error: " + str(exc), "count": 0})

    # Rolling 48-hour window, recalculated on every timeline request.
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)

    def within_last_48_hours(value):
        if not value:
            return False
        try:
            stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            return cutoff <= stamp <= now
        except (ValueError, TypeError, OverflowError):
            return False

    records = [
        record for record in records
        if within_last_48_hours(record.get("observed_at"))
    ]
    records.sort(key=lambda r: str(r.get("observed_at") or ""), reverse=True)

    return {
        "databases": statuses,
        "records": records[:500],
        "note": "Showing records observed in the last 48 hours (rolling window). Cell records are not linked to the submitted phone number.",
        "window_start": cutoff.isoformat(),
        "window_end": now.isoformat(),
    }

@app.get("/api/investigation")
def investigation():
    """Check configured local cell sources through the existing read-only reader."""
    result = timeline()
    if not isinstance(result, dict) or "databases" not in result or "records" not in result:
        raise HTTPException(500, "Unexpected timeline response.")

    records = result["records"]
    latest = sorted(
        records,
        key=lambda row: str(row.get("observed_at") or ""),
        reverse=True,
    )[:20]

    return {
        "status": "complete",
        "sources": result["databases"],
        "records_found": len(records),
        "latest_records": latest,
        "scope": "local cell databases only",
    }



# Restored local tower-map routes.
from fastapi.responses import FileResponse as _TowerMapFileResponse

_TOWER_MAP_HTML = Path.home() / "tower-public-data" / "tower_map.html"
_TOWER_MAP_GEOJSON = Path.home() / "tower-public-data" / "maharashtra_towers.geojson"

@app.get("/tower-map")
def restored_tower_map():
    if not _TOWER_MAP_HTML.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tower map HTML not found")
    return _TowerMapFileResponse(
        str(_TOWER_MAP_HTML),
        media_type="text/html",
    )

@app.get("/maharashtra_towers.geojson")
def restored_tower_geojson():
    if not _TOWER_MAP_GEOJSON.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tower GeoJSON not found")
    return _TowerMapFileResponse(
        str(_TOWER_MAP_GEOJSON),
        media_type="application/geo+json",
    )
