"use strict";

/**
 * Deterministic jsdom harness for the desktop dashboard.
 *
 * Loads the real index.html / utils.js / script.js into a jsdom window with a
 * mock pywebview backend and controllable timers, so behavior can be asserted
 * through DOM state and backend call records without a real browser or network.
 */

const { JSDOM } = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");

const HTML_PATH = path.join(__dirname, "..", "..", "srunpy", "html", "index.html");
const UTILS_PATH = path.join(__dirname, "..", "..", "srunpy", "html", "utils.js");
const SCRIPT_PATH = path.join(__dirname, "..", "..", "srunpy", "html", "script.js");

/** A 2d-context stand-in that records every call and property write. */
function createRecordingContext() {
  const calls = [];
  return {
    calls,
    __isRecordingContext: true,
  };
}

function recordingContextProxy(recording) {
  return new Proxy(recording, {
    get(target, property) {
      if (property === "calls" || property === "__isRecordingContext") {
        return target[property];
      }
      return (...args) => {
        target.calls.push({ method: String(property), args });
      };
    },
    set(target, property, value) {
      target.calls.push({ property: String(property), value });
      return true;
    },
  });
}

/** Build the default mock backend with per-test overrides and a call log. */
function makeApi(overrides = {}) {
  const calls = [];
  const record = (name, args) => calls.push({ name, args });
  const state = {
    config: {
      version: "1.0.9",
      username: "student",
      has_password: true,
      auto_login: false,
      start_with_windows: false,
      update_available: false,
      gateway: "gw.example.edu",
      self_service: "zfw.example.edu",
      active_ip: null,
      selected_ips: [null],
      available_ips: ["10.0.0.2"],
      reconnect_interval: 5,
      allow_unverified_tls: false,
      allow_insecure_http: false,
      traffic_sampling_enabled: true,
      traffic_sample_interval: 1,
      traffic_history_enabled: true,
      traffic_retention_days: 7,
    },
    connection: {
      available: true,
      online: true,
      data: {
        username: "student",
        online_ip: "10.0.0.2",
        account_total_bytes: 1048576,
        balance: "12.50",
      },
      message: null,
    },
    snapshot: {
      available: true,
      gap: false,
      interface_name: "Wi-Fi",
      interface_ip: "10.0.0.2",
      download_bytes_per_second: 1000,
      upload_bytes_per_second: 500,
      peak_download_bytes_per_second: 2000,
      peak_upload_bytes_per_second: 1000,
      monitoring_duration_seconds: 60,
    },
    historyPoints: [
      { timestamp: 1700000000, download_bytes_per_second: 1000, upload_bytes_per_second: 500, gap: false },
      { timestamp: 1700000060, download_bytes_per_second: 1500, upload_bytes_per_second: 750, gap: false },
    ],
  };

  const api = {
    calls,
    state,
    async get_app_state() {
      record("get_app_state", []);
      return state.config;
    },
    async get_connection_status(ip) {
      record("get_connection_status", [ip]);
      return state.connection;
    },
    async get_traffic_snapshot() {
      record("get_traffic_snapshot", []);
      return state.snapshot;
    },
    async get_traffic_history(range) {
      record("get_traffic_history", [range]);
      return { ok: true, range, points: state.historyPoints };
    },
    async perform_login(username, password, ip) {
      record("perform_login", [username, password, ip]);
      return { ok: true, message: "登录成功" };
    },
    async perform_logout(ip) {
      record("perform_logout", [ip]);
      return { ok: true, message: "已注销" };
    },
    async set_active_client_ip(ip) {
      record("set_active_client_ip", [ip]);
      return true;
    },
    async set_auto_login(enabled) {
      record("set_auto_login", [enabled]);
      return true;
    },
    async set_start_with_windows(enabled) {
      record("set_start_with_windows", [enabled]);
      return undefined;
    },
    async probe_gateway_ips(gateway, selfService) {
      record("probe_gateway_ips", [gateway, selfService]);
      return {
        ok: true,
        gateway,
        reachable_count: 1,
        results: [{ ip: null, label: "自动选择", reachable: true, message: "可访问" }],
      };
    },
    async update_settings(settings) {
      record("update_settings", [settings]);
      return { ok: true, message: "设置已保存" };
    },
    async clear_traffic_history() {
      record("clear_traffic_history", []);
      return { ok: true, message: "流量历史已清空" };
    },
    async open_releases_page() {
      record("open_releases_page", []);
    },
    async start_self_service(ip) {
      record("start_self_service", [ip]);
    },
  };

  for (const [name, impl] of Object.entries(overrides)) {
    api[name] = impl;
  }
  return api;
}

/** Flush pending promise continuations so async boot/flows settle. */
async function flushMicrotasks(times = 8) {
  for (let index = 0; index < times; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

/**
 * Boot the real dashboard inside jsdom.
 *
 * Options:
 *  - apiOverrides: object mapping backend method name -> replacement (or a
 *    custom backend object via `api`).
 *  - hidden: initial document.hidden value.
 *  - config / connection / snapshot / historyPoints: mutate the mock state.
 */
async function bootApp(options = {}) {
  const {
    apiOverrides = {},
    hidden = false,
    config,
    connection,
    snapshot,
    historyPoints,
  } = options;
  const html = fs.readFileSync(HTML_PATH, "utf-8");
  const scheduledTimers = new Map();
  const recording = createRecordingContext();
  const domContentLoadedHandlers = [];

  const dom = new JSDOM(html, {
    url: "http://localhost/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    beforeParse(window) {
      // Intercept DOMContentLoaded registrations so the boot runs exactly once,
      // on our schedule. jsdom also fires its own DOMContentLoaded asynchronously,
      // which would otherwise double-boot the dashboard (double bindEvents).
      const originalDocumentAddEventListener = window.document.addEventListener.bind(
        window.document,
      );
      window.document.addEventListener = (type, handler, ...rest) => {
        if (type === "DOMContentLoaded") {
          domContentLoadedHandlers.push(handler);
          return;
        }
        return originalDocumentAddEventListener(type, handler, ...rest);
      };

      // Controllable timers: nothing fires on its own; tests flush explicitly.
      let nextTimerId = 1;
      window.setTimeout = (fn, ms = 0, ...args) => {
        const timerId = nextTimerId;
        nextTimerId += 1;
        scheduledTimers.set(timerId, { fn, ms, args });
        return timerId;
      };
      window.clearTimeout = (timerId) => {
        scheduledTimers.delete(timerId);
      };
      window.setInterval = () => 0;
      window.clearInterval = () => {};
      window.requestAnimationFrame = (fn) => {
        fn(0);
        return 0;
      };

      // Canvas stub so chart drawing runs without node-canvas.
      window.HTMLCanvasElement.prototype.getContext = () =>
        recordingContextProxy(recording);
      window.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
        width: 640,
        height: 240,
        top: 0,
        left: 0,
        right: 640,
        bottom: 240,
        x: 0,
        y: 0,
        toJSON() {
          return {};
        },
      });

      // <dialog> modal methods (jsdom lacks real modal behavior).
      window.HTMLDialogElement.prototype.showModal = function showModal() {
        this.setAttribute("open", "");
      };
      window.HTMLDialogElement.prototype.close = function close() {
        this.removeAttribute("open");
      };

      window.matchMedia = () => ({
        matches: false,
        addEventListener() {},
        removeEventListener() {},
      });
      Object.defineProperty(window, "devicePixelRatio", { value: 2, configurable: true });
      Object.defineProperty(window.document, "hidden", {
        value: Boolean(hidden),
        configurable: true,
      });
    },
  });

  const { window } = dom;
  const api = makeApi(apiOverrides);
  if (config) api.state.config = { ...api.state.config, ...config };
  if (connection) api.state.connection = { ...api.state.connection, ...connection };
  if (snapshot) api.state.snapshot = { ...api.state.snapshot, ...snapshot };
  if (historyPoints) api.state.historyPoints = historyPoints;
  window.pywebview = { api };

  window.eval(fs.readFileSync(UTILS_PATH, "utf-8"));
  window.eval(fs.readFileSync(SCRIPT_PATH, "utf-8"));

  // Boot the dashboard exactly once, then drain the async init chain.
  for (const handler of domContentLoadedHandlers) {
    handler();
  }
  await flushMicrotasks();

  const harness = {
    window,
    document: window.document,
    api,
    scheduledTimers,
    recording,
    id(elementId) {
      return window.document.getElementById(elementId);
    },
    setHidden(isHidden) {
      Object.defineProperty(window.document, "hidden", {
        value: Boolean(isHidden),
        configurable: true,
      });
    },
    fireVisibilityChange() {
      window.document.dispatchEvent(new window.Event("visibilitychange"));
    },
    async flush() {
      await flushMicrotasks();
    },
    /** Invoke the callbacks of every currently scheduled timer and flush. */
    async runScheduledTimers() {
      const entries = Array.from(scheduledTimers.entries());
      scheduledTimers.clear();
      for (const [, { fn, args }] of entries) {
        await fn(...args);
      }
      await flushMicrotasks();
    },
    close() {
      window.close();
    },
  };
  return harness;
}

module.exports = { bootApp, makeApi, flushMicrotasks };
