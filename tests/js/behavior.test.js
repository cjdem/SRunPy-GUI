"use strict";

/**
 * Behavior tests for the desktop dashboard frontend (srunpy/html/script.js).
 *
 * These drive the real script.js through DOM events against a mock pywebview
 * backend, asserting on rendered DOM state and backend call records instead of
 * string-matching HTML/JS source.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { bootApp } = require("./helpers.js");

const OFFLINE = {
  available: true,
  online: false,
  data: {},
  message: null,
};

function hasTimer(harness, milliseconds) {
  return [...harness.scheduledTimers.values()].some((timer) => timer.ms === milliseconds);
}

// --- Initialization -----------------------------------------------------------
test("boot renders configuration and the online connection state", async (t) => {
  const h = await bootApp();
  t.after(() => h.close());

  assert.equal(h.id("version-label").textContent, "Windows 客户端 v1.0.9");
  assert.equal(h.id("username-input").value, "student");
  assert.equal(h.id("credential-badge").textContent, "凭据已安全保存");
  assert.equal(h.id("status-panel").dataset.state, "online");
  assert.equal(h.id("live-badge-text").textContent, "在线");
  assert.equal(h.id("account-title").textContent, "当前已登录");
  assert.equal(h.id("primary-action").textContent, "注销当前线路");
  assert.equal(h.id("metric-username").textContent, "student");
  assert.equal(h.id("metric-ip").textContent, "10.0.0.2");
  assert.equal(h.id("metric-traffic").textContent, "1.00 MB");
  assert.equal(h.id("metric-balance").textContent, "12.50");
  assert.equal(h.id("gateway-label").textContent, "网关：gw.example.edu");

  assert.deepEqual(
    h.api.calls.map((call) => call.name),
    ["get_app_state", "get_connection_status", "get_traffic_snapshot", "get_traffic_history"],
  );
});

test("offline connection renders the login form ready state", async (t) => {
  const h = await bootApp({ connection: OFFLINE });
  t.after(() => h.close());

  assert.equal(h.id("status-panel").dataset.state, "offline");
  assert.equal(h.id("live-badge-text").textContent, "待登录");
  assert.equal(h.id("account-title").textContent, "账号登录");
  assert.equal(h.id("primary-action").textContent, "登录校园网");
  assert.equal(h.id("retry-connection-button").hidden, false);
});

// --- Login / logout -----------------------------------------------------------
test("login submits credentials for the active interface and clears the password", async (t) => {
  const h = await bootApp({ connection: OFFLINE });
  t.after(() => h.close());

  h.id("username-input").value = "alice";
  h.id("password-input").value = "secret";
  h.id("login-form").dispatchEvent(new h.window.Event("submit", { cancelable: true }));
  await h.flush();

  const loginCall = h.api.calls.find((call) => call.name === "perform_login");
  assert.ok(loginCall, "perform_login must be called");
  assert.deepEqual(loginCall.args, ["alice", "secret", null]);
  assert.equal(h.id("form-message").textContent, "登录成功");
  assert.equal(h.id("form-message").dataset.state, "success");
  assert.equal(h.id("password-input").value, "");
});

test("logout calls perform_logout on the active interface", async (t) => {
  const h = await bootApp();
  t.after(() => h.close());

  h.id("login-form").dispatchEvent(new h.window.Event("submit", { cancelable: true }));
  await h.flush();

  const logoutCall = h.api.calls.find((call) => call.name === "perform_logout");
  assert.ok(logoutCall, "perform_logout must be called while online");
  assert.deepEqual(logoutCall.args, [null]);
});

test("failed login surfaces the backend message without clearing state", async (t) => {
  const h = await bootApp({
    connection: OFFLINE,
    apiOverrides: {
      perform_login: async () => ({ ok: false, message: "登录失败，请检查账号和网络" }),
    },
  });
  t.after(() => h.close());

  h.id("username-input").value = "alice";
  h.id("password-input").value = "wrong";
  h.id("login-form").dispatchEvent(new h.window.Event("submit", { cancelable: true }));
  await h.flush();

  assert.equal(h.id("form-message").textContent, "登录失败，请检查账号和网络");
  assert.equal(h.id("form-message").dataset.state, "error");
  // Password is preserved on failure so the user can retry.
  assert.equal(h.id("password-input").value, "wrong");
});

// --- Polling visibility -------------------------------------------------------
test("hidden document suspends traffic and connection polling", async (t) => {
  const h = await bootApp({ connection: OFFLINE });
  t.after(() => h.close());

  // Offline: connection poll (12s) and traffic poll (1s) are both scheduled.
  assert.ok(hasTimer(h, 12000), "connection poll should be scheduled while offline");
  assert.ok(hasTimer(h, 1000), "traffic poll should be scheduled while sampling");

  h.setHidden(true);
  h.fireVisibilityChange();
  assert.equal(h.scheduledTimers.size, 0, "hidden must clear every poll timer");

  h.setHidden(false);
  h.fireVisibilityChange();
  await h.flush();
  // Returning to visible schedules the traffic poll immediately (delay 0) and,
  // being offline, a connection poll too.
  assert.ok(hasTimer(h, 0), "returning to visible reschedules the traffic poll");
  assert.ok(hasTimer(h, 12000), "returning to visible reschedules the connection poll");
});

test("traffic polling is never scheduled when sampling is disabled", async (t) => {
  const h = await bootApp({
    connection: OFFLINE,
    config: { traffic_sampling_enabled: false },
  });
  t.after(() => h.close());

  assert.ok(!hasTimer(h, 1000), "no traffic poll timer when sampling is disabled");
});

test("polling while hidden does not hit the backend", async (t) => {
  const h = await bootApp({ connection: OFFLINE });
  t.after(() => h.close());

  const snapshotCallsBefore = h.api.calls.filter(
    (call) => call.name === "get_traffic_snapshot",
  ).length;

  h.setHidden(true);
  h.fireVisibilityChange();
  await h.runScheduledTimers();

  const snapshotCallsAfter = h.api.calls.filter(
    (call) => call.name === "get_traffic_snapshot",
  ).length;
  assert.equal(snapshotCallsAfter, snapshotCallsBefore);
});

// --- Settings rollback --------------------------------------------------------
test("failed settings save keeps the dialog open and reports the error", async (t) => {
  const h = await bootApp({
    apiOverrides: {
      update_settings: async () => ({ ok: false, message: "无法解析网关地址，请检查输入" }),
    },
  });
  t.after(() => h.close());

  h.id("settings-button").click();
  assert.equal(h.id("settings-dialog").hasAttribute("open"), true);

  h.id("gateway-input").value = "not-a-gateway";
  h.id("settings-form").dispatchEvent(new h.window.Event("submit", { cancelable: true }));
  await h.flush();

  assert.equal(h.id("settings-message").textContent, "无法解析网关地址，请检查输入");
  assert.equal(h.id("settings-message").dataset.state, "error");
  assert.equal(
    h.id("settings-dialog").hasAttribute("open"),
    true,
    "a failed save must not close the settings dialog",
  );
  assert.equal(h.id("save-settings-button").disabled, false);
});

test("successful settings save commits once and refreshes app state", async (t) => {
  const h = await bootApp();
  t.after(() => h.close());

  h.id("settings-button").click();
  h.id("gateway-input").value = "gw.other.edu";
  h.id("settings-form").dispatchEvent(new h.window.Event("submit", { cancelable: true }));
  await h.flush();

  const updateCalls = h.api.calls.filter((call) => call.name === "update_settings");
  assert.equal(updateCalls.length, 1, "settings must be committed exactly once");
  assert.equal(updateCalls[0].args[0].gateway, "gw.other.edu");
  assert.equal(
    h.id("settings-dialog").hasAttribute("open"),
    false,
    "a successful save closes the dialog",
  );
  assert.equal(h.id("form-message").textContent, "设置已保存");
});

// --- Multi-interface switching ------------------------------------------------
test("switching interfaces updates the active client and re-checks the new one", async (t) => {
  const h = await bootApp({
    connection: OFFLINE,
    config: { selected_ips: [null, "10.0.0.2"], active_ip: null },
  });
  t.after(() => h.close());

  const select = h.id("interface-select");
  assert.equal(select.value, "__auto__");

  select.value = "10.0.0.2";
  select.dispatchEvent(new h.window.Event("change"));
  await h.flush();

  const setCall = h.api.calls.find((call) => call.name === "set_active_client_ip");
  assert.ok(setCall, "set_active_client_ip must be called on switch");
  assert.deepEqual(setCall.args, ["10.0.0.2"]);

  const statusCalls = h.api.calls.filter((call) => call.name === "get_connection_status");
  assert.ok(
    statusCalls.some((call) => call.args[0] === "10.0.0.2"),
    "connection status must refresh for the newly selected interface",
  );
});

test("rejected interface switch restores the previous selection", async (t) => {
  const h = await bootApp({
    connection: OFFLINE,
    config: { selected_ips: [null, "10.0.0.2"], active_ip: null },
    apiOverrides: {
      set_active_client_ip: async () => false,
    },
  });
  t.after(() => h.close());

  const select = h.id("interface-select");
  select.value = "10.0.0.2";
  select.dispatchEvent(new h.window.Event("change"));
  await h.flush();

  assert.equal(h.id("form-message").textContent, "无法切换到所选线路");
  assert.equal(select.value, "__auto__", "rejected switch must revert the selector");
});

// --- Chart data ---------------------------------------------------------------
test("recent history is fetched at boot and drawn on the canvas", async (t) => {
  const h = await bootApp();
  t.after(() => h.close());

  assert.ok(
    h.api.calls.some(
      (call) => call.name === "get_traffic_history" && call.args[0] === "recent",
    ),
    "recent history should be fetched at boot",
  );
  const canvas = h.id("traffic-chart");
  assert.equal(canvas.width, 1280, "canvas is sized to device-pixel-ratio");
  assert.equal(canvas.height, 480);
  assert.ok(
    h.recording.calls.some((call) => call.method === "fillText"),
    "chart should label its axes",
  );
  assert.ok(
    h.recording.calls.some((call) => call.method === "stroke" || call.method === "fill"),
    "chart should draw the series",
  );
});

test("switching the history range refetches that range and toggles buttons", async (t) => {
  const h = await bootApp();
  t.after(() => h.close());

  h.id("traffic-range-hour").click();
  await h.flush();

  assert.ok(
    h.api.calls.some((call) => call.name === "get_traffic_history" && call.args[0] === "1h"),
    "clicking 1h must fetch the 1h range",
  );
  assert.equal(h.id("traffic-range-hour").getAttribute("aria-pressed"), "true");
  assert.equal(h.id("traffic-range-recent").getAttribute("aria-pressed"), "false");
});
