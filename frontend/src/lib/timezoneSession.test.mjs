import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import net from "node:net";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const forbidden = () => { throw new Error("Real network access is forbidden."); };
net.Socket.prototype.connect = forbidden;
globalThis.fetch = forbidden;
let sequence = 0;
const student = { username: "synthetic", email: "student@example.test", fullName: "Synthetic Student", role: "student",
  timeZone: null, timeZoneSource: "", timeZoneUpdatedAt: null, timeZoneStatus: "missing" };
const stamp = "2026-11-18T09:00:00Z";
const json = (value, status = 200) => new Response(JSON.stringify(value), { status });
const observation = (zone = "Asia/Dubai", source = "browser", status = "saved") => ({
  observedTimeZone: "America/New_York", savedTimeZone: zone, saved: status === "saved", status, source, updatedAt: stamp,
});
const preference = (zone = "Asia/Dubai", source = "manual") => ({
  user: { ...student, timeZone: zone, timeZoneSource: source, timeZoneStatus: "valid", timeZoneUpdatedAt: stamp }, status: "saved",
});

function storage() {
  const values = new Map();
  globalThis.localStorage = { getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}
function asModule(source, jsx = false) {
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX } }).outputText
    .replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")))
    .replaceAll('"react"', JSON.stringify(import.meta.resolve("react")));
  return `data:text/javascript;base64,${Buffer.from(`${compiled}\n// isolated ${sequence++}`).toString("base64")}`;
}
async function load() {
  storage();
  const source = (await readFile(new URL("./api.ts", import.meta.url), "utf8"))
    .replaceAll("import.meta.env", "({})")
    .replace('"./libraryDates"', JSON.stringify(new URL("./libraryDates.ts", import.meta.url).href));
  const url = asModule(source);
  return { ...(await import(url)), url };
}
async function renderSettings(apiUrl) {
  const hookSource = (await readFile(new URL("../hooks/useLibrarySession.ts", import.meta.url), "utf8"))
    .replace('"../lib/api"', JSON.stringify(apiUrl))
    .replace('"../lib/libraryDates"', JSON.stringify(new URL("./libraryDates.ts", import.meta.url).href));
  const hookUrl = asModule(hookSource);
  const uiSource = (await readFile(new URL("../components/feature/TimezoneSettings.tsx", import.meta.url), "utf8"))
    .replace('"../../hooks/useLibrarySession"', JSON.stringify(hookUrl));
  const { LibrarySessionProvider } = await import(hookUrl);
  const { default: Settings } = await import(asModule(uiSource, true));
  return renderToStaticMarkup(createElement(LibrarySessionProvider, null, createElement(Settings)));
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test.afterEach(() => { globalThis.fetch = forbidden; delete globalThis.localStorage; });

test("student and admin login return the backend-confirmed timezone and update React's subscribed session", async () => {
  for (const role of ["student", "admin"]) {
    const mod = await load();
    const events = [];
    const stop = mod.subscribeLibrarySession(() => events.push(mod.getLibrarySessionState()));
    globalThis.fetch = async (url) => url.endsWith("timezone-observation/")
      ? json(observation()) : json({ token: "synthetic-token", user: { ...student, role } });
    const response = role === "student" ? await mod.api.loginStudent(student.email) : await mod.api.loginAdmin("synthetic", "synthetic");
    assert.equal(response.user.timeZone, "Asia/Dubai");
    assert.equal(mod.getLibrarySessionState().user.timeZoneUpdatedAt, stamp);
    assert.equal(mod.getLibrarySessionState().timezoneStatus, "ready");
    assert.ok(events.some((state) => state.user?.timeZone === "Asia/Dubai"));
    const html = await renderSettings(mod.url);
    assert.match(html, /Asia\/Dubai/);
    assert.doesNotMatch(html, /role="alert"/);
    stop();
  }
});

test("failed capture keeps sign-in, shows an alert and retry/manual controls, then updates the session after retry", async () => {
  const mod = await load();
  let attempts = 0;
  globalThis.fetch = async (url) => {
    if (url.endsWith("timezone-observation/")) return ++attempts === 1 ? json({ detail: "Synthetic failure" }, 503) : json(observation());
    return json({ token: "synthetic-token", user: student });
  };
  const response = await mod.api.loginStudent(student.email);
  assert.equal(response.token, "synthetic-token");
  assert.equal(response.user.timeZone, null);
  assert.equal(mod.hasStoredAuthToken(), true);
  assert.equal(mod.getLibrarySessionState().timezoneStatus, "error");
  let html = await renderSettings(mod.url);
  assert.match(html, /role="alert"/);
  assert.match(html, /Retry timezone save/);
  assert.match(html, /Choose your timezone/);
  assert.match(html, /Save chosen timezone/);
  assert.match(html, /Use device timezone/);
  assert.match(html, /Not saved/);
  await mod.retryTimezoneSave();
  assert.equal(attempts, 2);
  assert.equal(mod.getLibrarySessionState().user.timeZone, "Asia/Dubai");
  html = await renderSettings(mod.url);
  assert.doesNotMatch(html, /role="alert"/);
  assert.doesNotMatch(html, /Not saved/);
});

test("getAuthMe returns the saved timezone instead of its pre-observation snapshot", async () => {
  const mod = await load();
  localStorage.setItem("kbc_auth_token", "synthetic-token");
  const reads = [];
  globalThis.fetch = async (url, init) => {
    if (url.endsWith("timezone-observation/")) return json(observation());
    reads.push(init.cache);
    return json({ user: student });
  };
  assert.equal((await mod.api.getAuthMe()).user.timeZone, "Asia/Dubai");
  assert.deepEqual(reads, ["no-store"]);
  assert.equal((await mod.api.getAuthMe()).user.timeZone, "Asia/Dubai");
  assert.equal(reads.length, 2);
});

test("a manual choice and manual_preserved response remain authoritative across device observations", async () => {
  const mod = await load();
  globalThis.fetch = async (url, init) => {
    if (url.endsWith("timezone-preference/")) {
      assert.deepEqual(JSON.parse(init.body), { timeZone: "Asia/Dubai", source: "manual" });
      return json(preference());
    }
    if (url.endsWith("timezone-observation/")) return json(observation("Asia/Dubai", "manual", "manual_preserved"));
    return json({ token: "synthetic-token", user: student });
  };
  await mod.api.loginStudent(student.email);
  await mod.api.setMyTimezone("Asia/Dubai", "manual");
  await mod.observeAuthenticatedDeviceTimezone({ force: true });
  assert.equal(mod.getLibrarySessionState().user.timeZone, "Asia/Dubai");
  assert.equal(mod.getLibrarySessionState().user.timeZoneSource, "manual");
  assert.equal(mod.getLibrarySessionState().timezoneStatus, "ready");
});

test("retry repeats the failed manual choice, not the device timezone, and only explicit choice resumes device-following", async () => {
  const mod = await load();
  let writes = 0, observations = 0;
  const bodies = [];
  globalThis.fetch = async (url, init) => {
    if (url.endsWith("timezone-preference/")) {
      bodies.push(JSON.parse(init.body));
      if (++writes === 1) return json({ detail: "Synthetic invalid preference" }, 400);
      const body = JSON.parse(init.body);
      return json(preference(body.timeZone, body.source));
    }
    if (url.endsWith("timezone-observation/")) { observations++; return json(observation("Europe/London")); }
    return json({ token: "synthetic-token", user: student });
  };
  await mod.api.loginStudent(student.email);
  await assert.rejects(mod.api.setMyTimezone("Asia/Dubai", "manual"));
  assert.equal(mod.getLibrarySessionState().user.timeZone, "Europe/London");
  assert.equal(mod.getLibrarySessionState().timezoneStatus, "error");
  await mod.observeAuthenticatedDeviceTimezone({ force: true });
  assert.equal(observations, 1, "automatic focus refresh must not silently clear a failed manual choice");
  await mod.retryTimezoneSave();
  assert.deepEqual(bodies[0], bodies[1]);
  assert.equal(mod.getLibrarySessionState().user.timeZoneSource, "manual");
  await mod.api.setMyTimezone("Europe/London", "browser");
  assert.equal(mod.getLibrarySessionState().user.timeZoneSource, "browser");
});

test("a late automatic response cannot overwrite a successful manual preference", async () => {
  const mod = await load();
  const waiting = deferred(), started = deferred();
  globalThis.fetch = async (url) => {
    if (url.endsWith("timezone-observation/")) { started.resolve(); return waiting.promise; }
    if (url.endsWith("timezone-preference/")) return json(preference());
    return json({ token: "synthetic-token", user: student });
  };
  const login = mod.api.loginStudent(student.email);
  await started.promise;
  await mod.api.setMyTimezone("Asia/Dubai", "manual");
  waiting.resolve(json(observation("America/New_York")));
  assert.equal((await login).user.timeZone, "Asia/Dubai");
  assert.equal(mod.getLibrarySessionState().user.timeZoneSource, "manual");
});

test("logout while capture is pending cannot resurrect the user or show an old warning", async () => {
  const mod = await load();
  const waiting = deferred(), started = deferred();
  globalThis.fetch = async (url) => {
    if (url.endsWith("timezone-observation/")) { started.resolve(); return waiting.promise; }
    if (url.endsWith("logout/")) return new Response(null, { status: 204 });
    return json({ token: "synthetic-token", user: student });
  };
  const login = mod.api.loginStudent(student.email);
  await started.promise;
  await mod.api.logoutAdmin();
  waiting.reject(new Error("Late synthetic error"));
  await login;
  assert.equal(mod.getLibrarySessionState().user, null);
  assert.equal(mod.getLibrarySessionState().timezoneError, null);
  assert.equal(mod.hasStoredAuthToken(), false);
  assert.equal(await renderSettings(mod.url), "");
});

test("missing browser timezone is not guessed and does not turn a valid login into failure", async () => {
  const mod = await load();
  const original = Intl.DateTimeFormat;
  let captures = 0;
  globalThis.fetch = async (url) => {
    if (url.endsWith("timezone-observation/")) { captures++; return json(observation()); }
    return json({ token: "synthetic-token", user: student });
  };
  try {
    Intl.DateTimeFormat = function () { return { resolvedOptions: () => ({}) }; };
    const result = await mod.api.loginStudent(student.email);
    assert.equal(result.user.timeZone, null);
    assert.equal(captures, 0);
    assert.equal(mod.getLibrarySessionState().timezoneStatus, "error");
  } finally { Intl.DateTimeFormat = original; }
  await mod.retryTimezoneSave();
  assert.equal(captures, 1);
  assert.equal(mod.getLibrarySessionState().timezoneStatus, "ready");
});

test("a response with no saved timezone is not presented as success", async () => {
  const mod = await load();
  globalThis.fetch = async (url) => url.endsWith("timezone-observation/")
    ? json({ ...observation(), savedTimeZone: null }) : json({ token: "synthetic-token", user: student });
  await mod.api.loginStudent(student.email);
  assert.equal(mod.getLibrarySessionState().user.timeZone, null);
  assert.equal(mod.getLibrarySessionState().timezoneStatus, "error");
});

test("timezone requests have a bounded timeout while keeping authentication active", async () => {
  const mod = await load();
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout;
  let timeout, signal;
  const started = deferred();
  globalThis.fetch = async (url, init) => {
    if (url.endsWith("timezone-observation/")) { signal = init.signal; started.resolve(); return new Promise(() => {}); }
    return json({ token: "synthetic-token", user: student });
  };
  try {
    globalThis.setTimeout = (callback, delay) => { assert.equal(delay, 8000); timeout = callback; return 1; };
    globalThis.clearTimeout = () => {};
    const login = mod.api.loginStudent(student.email);
    await started.promise;
    timeout();
    await login;
    assert.equal(signal.aborted, true);
    assert.equal(mod.hasStoredAuthToken(), true);
    assert.equal(mod.getLibrarySessionState().timezoneStatus, "error");
  } finally { globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear; }
});

test("a stale profile GET cannot undo a manual save even when timestamps differ only by microseconds", async () => {
  const mod = await load();
  const waiting = deferred(), started = deferred();
  let manual = false;
  globalThis.fetch = async (url) => {
    if (url.endsWith("/auth/me/")) { started.resolve(); return waiting.promise; }
    if (url.endsWith("timezone-preference/")) {
      manual = true;
      return json({ ...preference(), user: { ...preference().user, timeZoneUpdatedAt: "2026-11-18T09:00:00.000002Z" } });
    }
    if (url.endsWith("timezone-observation/")) return json(manual
      ? { ...observation("Asia/Dubai", "manual", "manual_preserved"), updatedAt: "2026-11-18T09:00:00.000002Z" }
      : observation("Europe/London"));
    return json({ token: "synthetic-token", user: student });
  };
  await mod.api.loginStudent(student.email);
  const profile = mod.api.getAuthMe();
  await started.promise;
  await mod.api.setMyTimezone("Asia/Dubai", "manual");
  const events = [];
  const stop = mod.subscribeLibrarySession(() => events.push(mod.getLibrarySessionState().user?.timeZone));
  waiting.resolve(json({ user: { ...student, timeZone: "Europe/London", timeZoneSource: "browser", timeZoneUpdatedAt: "2026-11-18T09:00:00.000001Z" } }));
  assert.equal((await profile).user.timeZone, "Asia/Dubai");
  assert.ok(events.every((value) => value === "Asia/Dubai"));
  stop();
});

test("a pending observation for another account cannot overwrite the current account", async () => {
  const mod = await load();
  const waiting = deferred(), started = deferred();
  let logins = 0;
  const second = { ...student, username: "second", email: "second@example.test", role: "admin" };
  globalThis.fetch = async (url, init) => {
    if (url.endsWith("timezone-observation/")) {
      if (init.headers.get("Authorization") === "Token first-token") { started.resolve(); return waiting.promise; }
      return json(observation("Europe/London"));
    }
    return json(++logins === 1 ? { token: "first-token", user: student } : { token: "second-token", user: second });
  };
  const first = mod.api.loginStudent(student.email);
  await started.promise;
  await mod.api.loginAdmin("second", "synthetic");
  waiting.resolve(json(observation("Asia/Dubai")));
  await first;
  assert.equal(mod.getLibrarySessionState().user.username, "second");
  assert.equal(mod.getLibrarySessionState().user.timeZone, "Europe/London");
});
