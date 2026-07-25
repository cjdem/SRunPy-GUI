"use strict";

const AUTO_INTERFACE_TOKEN = "__auto__";

const applicationState = {
  config: null,
  connection: null,
  busy: false,
  probeResults: [],
};

const elements = {};

function cacheElements() {
  const elementIds = [
    "version-label",
    "live-badge",
    "live-badge-text",
    "refresh-button",
    "settings-button",
    "status-panel",
    "status-title",
    "status-message",
    "last-updated-label",
    "interface-select",
    "account-title",
    "credential-badge",
    "security-mode-label",
    "login-form",
    "username-input",
    "password-input",
    "password-visibility",
    "form-message",
    "primary-action",
    "metric-username",
    "metric-ip",
    "metric-traffic",
    "metric-balance",
    "auto-login-toggle",
    "auto-start-toggle",
    "self-service-button",
    "gateway-label",
    "settings-dialog",
    "settings-form",
    "close-settings-button",
    "cancel-settings-button",
    "save-settings-button",
    "gateway-input",
    "self-service-input",
    "probe-button",
    "interface-options",
    "probe-message",
    "reconnect-interval-input",
    "unverified-tls-toggle",
    "insecure-http-toggle",
    "settings-message",
  ];
  elementIds.forEach((elementId) => {
    elements[elementId] = document.getElementById(elementId);
  });
}

async function waitForBackend() {
  while (!(window.pywebview && window.pywebview.api)) {
    await new Promise((resolve) => window.setTimeout(resolve, 80));
  }
  return window.pywebview.api;
}

function activeInterfaceValue() {
  const activeIp = applicationState.config ? applicationState.config.active_ip : null;
  return activeIp === null || typeof activeIp === "undefined"
    ? AUTO_INTERFACE_TOKEN
    : String(activeIp);
}

function interfaceFromToken(interfaceToken) {
  return interfaceToken === AUTO_INTERFACE_TOKEN ? null : interfaceToken;
}

function setMessage(element, message, state = "") {
  element.textContent = message || "";
  if (state) {
    element.dataset.state = state;
  } else {
    delete element.dataset.state;
  }
}

function setBusy(isBusy, message = "") {
  applicationState.busy = isBusy;
  elements["primary-action"].disabled = isBusy;
  elements["refresh-button"].disabled = isBusy;
  elements["interface-select"].disabled = isBusy;
  if (message) {
    setMessage(elements["form-message"], message);
  }
}

function formatTraffic(rawBytes) {
  const byteCount = Number(rawBytes);
  if (!Number.isFinite(byteCount) || byteCount < 0) {
    return "--";
  }
  if (byteCount >= 1024 ** 3) {
    return `${(byteCount / 1024 ** 3).toFixed(2)} GB`;
  }
  return `${(byteCount / 1024 ** 2).toFixed(2)} MB`;
}

function renderInterfaceSelector() {
  const select = elements["interface-select"];
  select.replaceChildren();
  const selectedIps = Array.isArray(applicationState.config.selected_ips)
    ? applicationState.config.selected_ips
    : [null];

  selectedIps.forEach((interfaceIp) => {
    const option = document.createElement("option");
    option.value = interfaceIp === null ? AUTO_INTERFACE_TOKEN : String(interfaceIp);
    option.textContent = interfaceIp === null ? "自动选择" : String(interfaceIp);
    select.appendChild(option);
  });

  if (!select.options.length) {
    const option = document.createElement("option");
    option.value = AUTO_INTERFACE_TOKEN;
    option.textContent = "自动选择";
    select.appendChild(option);
  }
  select.value = activeInterfaceValue();
}

function renderConfig() {
  const config = applicationState.config;
  elements["version-label"].textContent = `Windows 客户端 v${config.version}`;
  elements["username-input"].value = config.username || "";
  elements["credential-badge"].textContent = config.has_password ? "凭据已安全保存" : "未保存凭据";
  elements["credential-badge"].dataset.active = String(Boolean(config.has_password));
  elements["auto-login-toggle"].checked = Boolean(config.auto_login);
  elements["auto-start-toggle"].checked = Boolean(config.start_with_windows);
  elements["gateway-label"].textContent = `网关：${config.gateway}`;
  if (config.allow_insecure_http) {
    elements["security-mode-label"].textContent = "已启用明文 HTTP 兼容模式";
  } else if (config.allow_unverified_tls) {
    elements["security-mode-label"].textContent = "已允许未经验证的 HTTPS 证书";
  } else {
    elements["security-mode-label"].textContent = "使用经过证书验证的 HTTPS";
  }
  renderInterfaceSelector();
}

function renderConnection() {
  const connection = applicationState.connection;
  const statusPanel = elements["status-panel"];
  const connectionData = connection && connection.data ? connection.data : {};

  if (!connection) {
    statusPanel.dataset.state = "loading";
    elements["live-badge"].dataset.state = "loading";
    elements["live-badge-text"].textContent = "检查中";
    elements["status-title"].textContent = "正在检查网络";
    elements["status-message"].textContent = "正在连接校园网网关...";
  } else if (connection.online) {
    statusPanel.dataset.state = "online";
    elements["live-badge"].dataset.state = "online";
    elements["live-badge-text"].textContent = "在线";
    elements["status-title"].textContent = "校园网已连接";
    elements["status-message"].textContent = "当前线路认证正常";
  } else if (connection.available) {
    statusPanel.dataset.state = "offline";
    elements["live-badge"].dataset.state = "offline";
    elements["live-badge-text"].textContent = "待登录";
    elements["status-title"].textContent = "等待登录";
    elements["status-message"].textContent = "网关可访问，登录后即可使用校园网";
  } else {
    statusPanel.dataset.state = "error";
    elements["live-badge"].dataset.state = "error";
    elements["live-badge-text"].textContent = "不可用";
    elements["status-title"].textContent = "网关不可用";
    elements["status-message"].textContent = connection.message || "请检查网络接口或网关设置";
  }

  if (connection) {
    elements["last-updated-label"].textContent = new Date().toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  const footerDot = document.querySelector(".footer-dot");
  if (footerDot) {
    footerDot.style.background = connection && connection.online ? "var(--accent)" : "var(--muted-foreground)";
  }

  const isOnline = Boolean(connection && connection.online);
  elements["account-title"].textContent = isOnline ? "当前已登录" : "账号登录";
  elements["primary-action"].textContent = isOnline ? "注销当前线路" : "登录校园网";
  elements["username-input"].disabled = isOnline;
  elements["password-input"].disabled = isOnline;
  elements["password-visibility"].disabled = isOnline;

  elements["metric-username"].textContent = connectionData.user_name || "--";
  elements["metric-ip"].textContent = connectionData.online_ip || connectionData.client_ip || "--";
  elements["metric-traffic"].textContent = formatTraffic(connectionData.sum_bytes);
  elements["metric-balance"].textContent =
    typeof connectionData.user_balance !== "undefined" ? `${connectionData.user_balance} 元` : "--";
}

async function loadApplication() {
  const backend = await waitForBackend();
  try {
    applicationState.config = await backend.get_app_state();
    renderConfig();
    await refreshConnection();
  } catch (error) {
    applicationState.connection = {
      available: false,
      online: false,
      data: {},
      message: String(error),
    };
    renderConnection();
  }
}

async function refreshConnection() {
  const backend = await waitForBackend();
  applicationState.connection = null;
  renderConnection();
  applicationState.connection = await backend.get_connection_status(
    interfaceFromToken(activeInterfaceValue()),
  );
  renderConnection();
}

async function handlePrimaryAction(event) {
  event.preventDefault();
  if (applicationState.busy) {
    return;
  }
  const backend = await waitForBackend();
  const isOnline = Boolean(applicationState.connection && applicationState.connection.online);
  setBusy(true, isOnline ? "正在注销..." : "正在登录...");

  try {
    let result;
    if (isOnline) {
      result = await backend.perform_logout(interfaceFromToken(activeInterfaceValue()));
    } else {
      result = await backend.perform_login(
        elements["username-input"].value,
        elements["password-input"].value,
        interfaceFromToken(activeInterfaceValue()),
      );
    }
    setMessage(elements["form-message"], result.message, result.ok ? "success" : "error");
    if (result.ok) {
      elements["password-input"].value = "";
      applicationState.config = await backend.get_app_state();
      renderConfig();
      await refreshConnection();
    }
  } catch (error) {
    setMessage(elements["form-message"], String(error), "error");
  } finally {
    setBusy(false);
  }
}

async function handleInterfaceChange() {
  const backend = await waitForBackend();
  const selectedIp = interfaceFromToken(elements["interface-select"].value);
  const changed = await backend.set_active_client_ip(selectedIp);
  if (!changed) {
    elements["interface-select"].value = activeInterfaceValue();
    setMessage(elements["form-message"], "无法切换到所选线路", "error");
    return;
  }
  applicationState.config.active_ip = selectedIp;
  await refreshConnection();
}

async function handleAutoLoginToggle() {
  const backend = await waitForBackend();
  const desiredValue = elements["auto-login-toggle"].checked;
  const changed = await backend.set_auto_login(desiredValue);
  if (!changed) {
    elements["auto-login-toggle"].checked = false;
    setMessage(elements["form-message"], "请先使用正确凭据成功登录一次", "error");
  }
  applicationState.config = await backend.get_app_state();
  renderConfig();
}

async function handleAutoStartToggle() {
  const backend = await waitForBackend();
  elements["auto-start-toggle"].disabled = true;
  try {
    await backend.set_start_with_windows(elements["auto-start-toggle"].checked);
    applicationState.config = await backend.get_app_state();
    renderConfig();
  } catch (error) {
    elements["auto-start-toggle"].checked = !elements["auto-start-toggle"].checked;
    setMessage(elements["form-message"], `无法修改开机启动：${error}`, "error");
  } finally {
    elements["auto-start-toggle"].disabled = false;
  }
}

function openSettings() {
  const config = applicationState.config;
  elements["gateway-input"].value = config.gateway || "";
  elements["self-service-input"].value = config.self_service || "";
  elements["reconnect-interval-input"].value = String(config.reconnect_interval || 5);
  elements["unverified-tls-toggle"].checked = Boolean(config.allow_unverified_tls);
  elements["insecure-http-toggle"].checked = Boolean(config.allow_insecure_http);
  applicationState.probeResults = [];
  renderInterfaceOptions();
  setMessage(elements["probe-message"], "");
  setMessage(elements["settings-message"], "");
  elements["settings-dialog"].showModal();
}

function getSettingsInterfaces() {
  if (applicationState.probeResults.length) {
    return applicationState.probeResults;
  }
  const availableIps = Array.isArray(applicationState.config.available_ips)
    ? applicationState.config.available_ips
    : [];
  return [
    { ip: null, label: "自动选择", reachable: null, message: "使用系统默认路由" },
    ...availableIps.map((interfaceIp) => ({
      ip: interfaceIp,
      label: interfaceIp,
      reachable: null,
      message: "本机 IPv4 地址",
    })),
  ];
}

function renderInterfaceOptions() {
  const selectedTokens = new Set(
    (applicationState.config.selected_ips || [null]).map((interfaceIp) =>
      interfaceIp === null ? AUTO_INTERFACE_TOKEN : String(interfaceIp),
    ),
  );
  const activeToken = activeInterfaceValue();
  elements["interface-options"].replaceChildren();

  getSettingsInterfaces().forEach((interfaceInfo) => {
    const interfaceToken = interfaceInfo.ip === null ? AUTO_INTERFACE_TOKEN : String(interfaceInfo.ip);
    const row = document.createElement("div");
    row.className = "interface-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = interfaceToken;
    checkbox.checked = selectedTokens.has(interfaceToken);
    checkbox.dataset.role = "selected-interface";

    const description = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = interfaceInfo.label || interfaceToken;
    const detail = document.createElement("small");
    detail.textContent = interfaceInfo.message || "";
    description.append(title, document.createElement("br"), detail);

    const radioLabel = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "active-interface";
    radio.value = interfaceToken;
    radio.checked = interfaceToken === activeToken;
    radio.dataset.role = "active-interface";
    radio.addEventListener("change", () => {
      checkbox.checked = true;
    });
    radioLabel.append(radio, " 当前");
    row.append(checkbox, description, radioLabel);
    elements["interface-options"].appendChild(row);
  });
}

async function probeInterfaces() {
  const backend = await waitForBackend();
  elements["probe-button"].disabled = true;
  setMessage(elements["probe-message"], "正在检查各网络接口...");
  try {
    const result = await backend.probe_gateway_ips(
      elements["gateway-input"].value,
      elements["self-service-input"].value,
    );
    if (!result.ok) {
      setMessage(elements["probe-message"], result.error || "检查失败", "error");
      return;
    }
    applicationState.probeResults = Array.isArray(result.results) ? result.results : [];
    renderInterfaceOptions();
    setMessage(
      elements["probe-message"],
      `已检查 ${applicationState.probeResults.length} 条线路，${result.reachable_count} 条可访问`,
      result.reachable_count > 0 ? "success" : "error",
    );
  } catch (error) {
    setMessage(elements["probe-message"], `检查失败：${error}`, "error");
  } finally {
    elements["probe-button"].disabled = false;
  }
}

function collectInterfaceSettings() {
  const selectedCheckboxes = elements["interface-options"].querySelectorAll(
    'input[data-role="selected-interface"]:checked',
  );
  const selectedIps = Array.from(selectedCheckboxes).map((checkbox) =>
    interfaceFromToken(checkbox.value),
  );
  const activeRadio = elements["interface-options"].querySelector(
    'input[data-role="active-interface"]:checked',
  );
  const activeIp = activeRadio ? interfaceFromToken(activeRadio.value) : selectedIps[0] || null;
  return { selectedIps: selectedIps.length ? selectedIps : [null], activeIp };
}

async function saveSettings(event) {
  event.preventDefault();
  const backend = await waitForBackend();
  const interfaceSettings = collectInterfaceSettings();
  elements["save-settings-button"].disabled = true;
  setMessage(elements["settings-message"], "正在保存设置...");
  try {
    const result = await backend.update_preferences({
      gateway: elements["gateway-input"].value,
      self_service: elements["self-service-input"].value,
      reconnect_interval: Number(elements["reconnect-interval-input"].value),
      selected_ips: interfaceSettings.selectedIps,
      active_ip: interfaceSettings.activeIp,
      allow_unverified_tls: elements["unverified-tls-toggle"].checked,
      allow_insecure_http: elements["insecure-http-toggle"].checked,
    });
    if (!result.ok) {
      setMessage(elements["settings-message"], result.message, "error");
      return;
    }
    applicationState.config = await backend.get_app_state();
    renderConfig();
    elements["settings-dialog"].close();
    setMessage(elements["form-message"], result.message, "success");
    await refreshConnection();
  } catch (error) {
    setMessage(elements["settings-message"], String(error), "error");
  } finally {
    elements["save-settings-button"].disabled = false;
  }
}

function togglePasswordVisibility() {
  const isPassword = elements["password-input"].type === "password";
  elements["password-input"].type = isPassword ? "text" : "password";
  elements["password-visibility"].textContent = isPassword ? "隐藏" : "显示";
}

function bindEvents() {
  elements["login-form"].addEventListener("submit", handlePrimaryAction);
  elements["refresh-button"].addEventListener("click", refreshConnection);
  elements["interface-select"].addEventListener("change", handleInterfaceChange);
  elements["auto-login-toggle"].addEventListener("change", handleAutoLoginToggle);
  elements["auto-start-toggle"].addEventListener("change", handleAutoStartToggle);
  elements["password-visibility"].addEventListener("click", togglePasswordVisibility);
  elements["settings-button"].addEventListener("click", openSettings);
  elements["close-settings-button"].addEventListener("click", () => elements["settings-dialog"].close());
  elements["cancel-settings-button"].addEventListener("click", () => elements["settings-dialog"].close());
  elements["settings-form"].addEventListener("submit", saveSettings);
  elements["probe-button"].addEventListener("click", probeInterfaces);
  elements["self-service-button"].addEventListener("click", async () => {
    const backend = await waitForBackend();
    await backend.start_self_service(interfaceFromToken(activeInterfaceValue()));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  cacheElements();
  bindEvents();
  await loadApplication();
});
