const params = new URLSearchParams(window.location.search);
const bundleId = params.get("bundle") || "BND-A461FE81F6B2";
const inferredApiBase = window.location.hostname === "agentproof.hrevn.com"
  ? "/api"
  : "/agentproof-api";
const apiBase = (params.get("api") || inferredApiBase).replace(/\/$/, "");

const byId = (id) => document.getElementById(id);

function shortHash(value, visible = 10) {
  if (!value || typeof value !== "string") return "-";
  const normalized = value.startsWith("0x") ? value.slice(2) : value;
  return `${normalized.slice(0, visible)}...${normalized.slice(-visible)}`;
}

function withHexPrefix(value) {
  if (!value || typeof value !== "string") return "";
  return value.startsWith("0x") ? value : `0x${value}`;
}

function setText(id, value) {
  byId(id).textContent = value;
}

function eventPresentation(event) {
  const payload = event.payload || {};
  if (event.event_type === "file_change") {
    return {
      title: `${payload.change_type || "changed"}: ${payload.path || "repository file"}`,
      detail: `after ${shortHash(payload.after_sha256)} / diff ${shortHash(payload.diff_sha256)}`,
    };
  }
  return {
    title: `Command completed with exit code ${payload.exit_code ?? "-"}`,
    detail: `command ${shortHash(payload.command_sha256)} / output ${shortHash(payload.output_sha256)}`,
  };
}

function renderTimeline(events) {
  const timeline = byId("timeline");
  timeline.replaceChildren();
  for (const event of events) {
    const view = eventPresentation(event);
    const item = document.createElement("li");

    const sequence = document.createElement("span");
    sequence.className = "timeline-sequence";
    sequence.textContent = String(event.sequence).padStart(2, "0");

    const type = document.createElement("span");
    type.className = `event-type ${event.event_type === "file_change" ? "file-change" : ""}`;
    type.textContent = event.event_type === "file_change" ? "File change" : "Command";

    const summary = document.createElement("div");
    summary.className = "event-summary";
    const title = document.createElement("strong");
    title.textContent = view.title;
    const detail = document.createElement("code");
    detail.textContent = view.detail;
    summary.append(title, detail);

    const eventHash = document.createElement("code");
    eventHash.className = "event-hash";
    eventHash.textContent = shortHash(event.event_hash, 8);

    item.append(sequence, type, summary, eventHash);
    timeline.append(item);
  }
}

function expectedRepositoryFiles(events) {
  const expected = new Map();
  for (const event of events) {
    if (event.event_type !== "file_change") continue;
    const payload = event.payload || {};
    if (payload.path) expected.set(payload.path, payload.after_sha256 || null);
  }
  return expected;
}

async function sha256(file) {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function selectedFileMap(fileList) {
  const selected = new Map();
  for (const file of fileList) {
    const raw = file.webkitRelativePath || file.name;
    const parts = raw.split("/").filter(Boolean);
    const relative = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
    selected.set(relative, file);
  }
  return selected;
}

function setRepositoryResult(state, title, copy, symbol) {
  const result = byId("repo-result");
  result.className = `console-result ${state}`;
  setText("result-title", title);
  setText("result-copy", copy);
  setText("result-symbol", symbol);
}

function renderFileResults(results) {
  const list = byId("file-results");
  list.replaceChildren();
  for (const result of results) {
    const item = document.createElement("li");
    const path = document.createElement("span");
    path.textContent = result.path;
    const status = document.createElement("span");
    status.className = result.status;
    status.textContent = result.status.toUpperCase();
    item.append(path, status);
    list.append(item);
  }
}

async function verifySelectedRepository(fileList, expected) {
  if (!fileList.length) return;
  setRepositoryResult("is-idle", "Hashing selected files", "This comparison happens only in your browser.", "...");
  const selected = selectedFileMap(fileList);
  const results = [];

  for (const [path, expectedHash] of expected.entries()) {
    const file = selected.get(path);
    if (!file) {
      results.push({ path, status: expectedHash === null ? "match" : "missing" });
      continue;
    }
    const currentHash = await sha256(file);
    const matches = expectedHash === null ? false : currentHash === expectedHash;
    results.push({ path, status: matches ? "match" : "mismatch" });
  }

  renderFileResults(results);
  const failures = results.filter((result) => result.status !== "match");
  if (failures.length) {
    setRepositoryResult(
      "is-mismatch",
      "Repository state does not match",
      `${failures.length} committed file${failures.length === 1 ? "" : "s"} changed or missing after the sealed session.`,
      "X",
    );
  } else {
    setRepositoryResult(
      "is-match",
      "Repository state matches",
      "Every committed file reproduces the SHA-256 value sealed in the AgentProof receipt.",
      "OK",
    );
  }
}

function renderVerification(data) {
  const cryptoVerification = data.cryptographic_verification || {};
  const sessionVerification = data.session_verification || {};
  const session = data.session || {};
  const anchor = cryptoVerification.anchor || {};
  const valid = Boolean(data.valid);

  const globalStatus = byId("global-status");
  globalStatus.className = `global-status ${valid ? "" : "is-invalid"}`;
  setText("global-status-text", valid ? "VERIFIED" : "FAILED");
  setText("bundle-id", data.bundle_id || bundleId);
  setText("agent-name", session.agent_name || "Codex CLI");
  setText("model-name", session.model || "-");
  setText("event-count", String(session.event_count ?? data.events?.length ?? "-"));
  setText("chain-status", sessionVerification.valid ? "Canonical order and links match" : "Event chain mismatch");
  setText("chain-hash", shortHash(session.chain_head_sha256, 12));
  setText("signature-status", cryptoVerification.signature_valid ? "Valid over the sealed EB1 root" : "Signature check failed");
  setText("signature-key", cryptoVerification.signature_public_key_id || "-");
  setText("anchor-status", anchor.status === "anchored" ? `Anchored at block ${anchor.block_number}` : "Anchor not confirmed");

  const transaction = withHexPrefix(anchor.transaction_reference);
  const etherscan = byId("etherscan-link");
  etherscan.href = transaction ? `https://sepolia.etherscan.io/tx/${transaction}` : "#";
  etherscan.textContent = transaction ? shortHash(transaction, 10) : "Transaction unavailable";
  etherscan.toggleAttribute("aria-disabled", !transaction);

  byId("download-link").href = `${apiBase}${data.download_url}`;
  renderTimeline(data.events || []);
  return expectedRepositoryFiles(data.events || []);
}

async function loadReceipt() {
  const response = await fetch(`${apiBase}/v1/public/agentproof/bundles/${encodeURIComponent(bundleId)}`);
  if (!response.ok) throw new Error(`Verification API returned ${response.status}`);
  return response.json();
}

async function main() {
  try {
    const data = await loadReceipt();
    const expected = renderVerification(data);
    const folderInput = byId("folder-input");
    byId("select-folder").addEventListener("click", () => folderInput.click());
    folderInput.addEventListener("change", async () => {
      try {
        await verifySelectedRepository(folderInput.files, expected);
      } catch (error) {
        setRepositoryResult("is-mismatch", "Could not verify this folder", error.message, "X");
      } finally {
        folderInput.value = "";
      }
    });
  } catch (error) {
    const globalStatus = byId("global-status");
    globalStatus.className = "global-status is-invalid";
    setText("global-status-text", "UNAVAILABLE");
    setText("chain-status", error.message);
    byId("timeline").replaceChildren();
    const item = document.createElement("li");
    item.className = "timeline-loading";
    item.textContent = "The public verification receipt could not be loaded.";
    byId("timeline").append(item);
  }
}

main();
