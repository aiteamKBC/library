import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import net from "node:net";
import test from "node:test";
import ts from "typescript";

const forbidden = () => { throw new Error("Real network access is forbidden."); };
net.Socket.prototype.connect = forbidden;
globalThis.fetch = forbidden;
let sequence = 0;
const user = { username: "synthetic", email: "learner@example.test", fullName: "Synthetic Learner", role: "student", timeZone: null };

async function load() {
  const stored = new Map();
  globalThis.localStorage = { getItem: (key) => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value), removeItem: (key) => stored.delete(key) };
  const source = (await readFile(new URL("./api.ts", import.meta.url), "utf8"))
    .replaceAll("import.meta.env", "({})")
    .replace('"./libraryDates"', JSON.stringify(new URL("./libraryDates.ts", import.meta.url).href));
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(`${compiled}\n// test ${sequence++}`).toString("base64")}`);
}

test.afterEach(() => { globalThis.fetch = forbidden; delete globalThis.localStorage; });

test("LMS assertion is exchanged in a POST body with the browser cookie, without an old account token", async () => {
  const mod = await load();
  localStorage.setItem("kbc_auth_token", "previous-account-token");
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/api/auth/lms/exchange/");
    assert.equal(init.method, "POST");
    assert.equal(init.credentials, "include");
    assert.equal(init.headers.has("Authorization"), false);
    assert.deepEqual(JSON.parse(init.body), { assertion: "synthetic-assertion" });
    return Response.json({ token: "new-session-token", user });
  };
  await mod.api.completeLmsSignIn("synthetic-assertion");
  assert.equal(localStorage.getItem("kbc_auth_token"), "new-session-token");
  assert.equal(mod.getLibrarySessionState().user.email, user.email);
});

test("failed LMS exchange never replaces an existing Library session", async () => {
  const mod = await load();
  localStorage.setItem("kbc_auth_token", "existing-token");
  globalThis.fetch = async () => Response.json({ detail: "Expired sign-in" }, { status: 400 });
  await assert.rejects(mod.api.completeLmsSignIn("expired-assertion"));
  assert.equal(localStorage.getItem("kbc_auth_token"), "existing-token");
  assert.equal(mod.getLibrarySessionState().user, null);
});

test("an old in-flight account response cannot overwrite the new LMS identity", async () => {
  const mod = await load();
  localStorage.setItem("kbc_auth_token", "old-token");
  let resolveOld;
  const oldResponse = new Promise(resolve => { resolveOld = resolve; });
  globalThis.fetch = async url => url.endsWith("/auth/me/") ? oldResponse : Response.json({ token: "new-token", user });
  const oldRequest = mod.api.getAuthMe();
  await mod.api.completeLmsSignIn("synthetic-assertion");
  resolveOld(Response.json({ user: { ...user, email: "previous@example.test" } }));
  await oldRequest;
  assert.equal(mod.getLibrarySessionState().user.email, user.email);
  assert.equal(localStorage.getItem("kbc_auth_token"), "new-token");
});
