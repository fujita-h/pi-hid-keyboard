"use strict";

const grid = document.querySelector("#macros");
const tabBar = document.querySelector("#tabs");
const macroPanel = document.querySelector("#macro-panel");
const message = document.querySelector("#message");
const connection = document.querySelector("#connection");
const fileInput = document.querySelector("#file");
const importButton = document.querySelector("#import");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const inputOnly = document.body.classList.contains("input-only");
let localBusy = false;
let remoteBusy = false;
let ready = false;
let toastTimer;
let macroTabs = [];
let activeTab = -1;
const tabScrollPositions = new Map();

function notify(text, error = false, persistent = false) {
  window.clearTimeout(toastTimer);
  message.textContent = text;
  message.dataset.error = String(error);
  message.dataset.visible = "true";
  message.dataset.connection = "false";
  if (inputOnly && !error && !persistent) {
    toastTimer = window.setTimeout(() => { message.dataset.visible = "false"; }, 3000);
  }
}

function showConnection(text) {
  if (connection) {
    connection.dataset.ready = String(ready);
    connection.textContent = text;
  }
  if (!inputOnly || localBusy) return;
  if (!ready || remoteBusy) {
    if (message.textContent !== text) notify(text, !ready, true);
    message.dataset.connection = "true";
  } else if (message.dataset.connection === "true") {
    notify("操作できます。");
  }
}

function updateButtons() {
  for (const button of grid.querySelectorAll("button")) {
    button.disabled = localBusy || remoteBusy || !ready;
  }
  if (importButton) importButton.disabled = localBusy || remoteBusy;
  grid.setAttribute("aria-busy", String(localBusy || remoteBusy));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: { "X-CSRF-Token": csrf, ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
  return data;
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    ready = status.hid.ready;
    remoteBusy = status.busy;
    showConnection(remoteBusy ? "キー入力を送信中…"
      : !status.hid.device_exists ? "HIDデバイスなし"
      : !status.hid.writable ? "HIDの操作権限なし"
      : status.hid.connected === false ? "USB未接続"
      : status.hid.connected === null ? "USB接続状態不明" : "USB接続済み");
  } catch {
    ready = false;
    showConnection("サーバーに接続できません");
  }
  updateButtons();
}

function renderMacros(macros) {
  grid.replaceChildren();
  for (const macro of macros) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "macro";
    const label = document.createElement("strong");
    label.textContent = macro.label;
    button.append(label);
    if (!inputOnly) {
      const hint = document.createElement("span");
      hint.textContent = "入力を送信 ↗";
      button.append(hint);
    }
    button.addEventListener("click", () => executeMacro(macro));
    grid.append(button);
  }
  const empty = document.querySelector("#empty");
  empty.hidden = macros.length !== 0;
  if (!macroTabs.length) empty.textContent = "登録されているタブがありません。";
  else empty.textContent = "このタブにマクロはありません。";
  const count = document.querySelector("#macro-count");
  if (count) count.textContent = `${macros.length} 件`;
  updateButtons();
}

function selectTab(index) {
  if (activeTab >= 0) {
    tabScrollPositions.set(macroTabs[activeTab].id, macroPanel.scrollTop);
  }
  activeTab = index;
  for (const [i, button] of [...tabBar.children].entries()) {
    button.setAttribute("aria-selected", String(i === index));
    button.tabIndex = i === index ? 0 : -1;
  }
  macroPanel.setAttribute("aria-labelledby", `macro-tab-${index}`);
  renderMacros(macroTabs[index].macros);
  macroPanel.scrollTop = tabScrollPositions.get(macroTabs[index].id) || 0;
}

async function loadMacros() {
  const data = await api("/api/macros");
  macroTabs = data.tabs;
  activeTab = -1;
  tabScrollPositions.clear();
  tabBar.replaceChildren();
  tabBar.hidden = macroTabs.length === 0;
  macroPanel.removeAttribute("aria-labelledby");
  for (const [index, tab] of macroTabs.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "macro-tab";
    button.id = `macro-tab-${index}`;
    button.textContent = tab.label;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "macro-panel");
    button.addEventListener("click", () => selectTab(index));
    button.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % macroTabs.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + macroTabs.length) % macroTabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = macroTabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(next);
      tabBar.children[next].focus();
    });
    tabBar.append(button);
  }
  if (macroTabs.length) selectTab(0);
  else renderMacros([]);
}

async function executeMacro(macro) {
  if (localBusy || remoteBusy || !ready) return;
  localBusy = true;
  updateButtons();
  notify(`「${macro.label}」を送信中…`, false, true);
  try {
    await api(`/api/macros/${encodeURIComponent(macro.id)}/execute`, { method: "POST" });
    notify(`「${macro.label}」の送信が完了しました。`);
  } catch (error) {
    notify(`送信に失敗しました: ${error.message}。接続先の入力内容を確認してから再操作してください。`, true);
  } finally {
    localBusy = false;
    await refreshStatus();
  }
}

importButton?.addEventListener("click", () => fileInput.click());
fileInput?.addEventListener("change", async () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (!file || localBusy || remoteBusy) return;
  if (file.size > 256 * 1024) {
    notify("JSONファイルは256 KiB以下にしてください。", true);
    return;
  }
  if (!window.confirm("現在のマクロ設定を、選択したJSONファイルですべて置き換えます。続行しますか？")) return;
  localBusy = true;
  updateButtons();
  let imported = false;
  try {
    const body = new FormData();
    body.append("file", file);
    await api("/api/config/import", { method: "POST", body });
    imported = true;
    await loadMacros();
    notify("設定をインポートしました。");
  } catch (error) {
    notify(imported ? `設定は保存されました。画面を再読み込みしてください: ${error.message}`
      : `インポートできませんでした: ${error.message}`, true);
  } finally {
    localBusy = false;
    await refreshStatus();
  }
});

async function start() {
  try {
    await loadMacros();
    notify("送信するボタンを選んでください。");
  } catch (error) {
    notify(`マクロを読み込めませんでした: ${error.message}`, true);
  }
  await refreshStatus();
  // Schedule only after the previous request completes, including on slow Pi hardware.
  async function poll() {
    await refreshStatus();
    window.setTimeout(poll, 10000);
  }
  window.setTimeout(poll, 10000);
}
start();
