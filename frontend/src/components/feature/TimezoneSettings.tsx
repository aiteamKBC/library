import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useLibrarySession } from "../../hooks/useLibrarySession";

export default function TimezoneSettings() {
  const { user, deviceTimeZone, timezoneStatus, timezoneError, retryTimezone, setTimezone } = useLibrarySession();
  const [expanded, setExpanded] = useState(false);
  const [selection, setSelection] = useState("");
  const previousPreference = useRef<{ username?: string; zone?: string | null }>({});
  const listId = useId();
  const busy = timezoneStatus === "saving";
  useEffect(() => {
    const previous = previousPreference.current;
    // A device change must not erase a manual choice still being typed.
    if (!expanded || previous.username !== user?.username || previous.zone !== user?.timeZone) {
      setSelection(user?.timeZone || deviceTimeZone || "");
    }
    previousPreference.current = { username: user?.username, zone: user?.timeZone };
  }, [user?.timeZone, user?.username, deviceTimeZone, expanded]);
  useEffect(() => { if (!user) setExpanded(false); }, [user]);
  const zones = useMemo(() => {
    try {
      const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
      return [...new Set([user?.timeZone, deviceTimeZone, ...(intl.supportedValuesOf?.("timeZone") || [])].filter(Boolean))];
    } catch { return [user?.timeZone, deviceTimeZone].filter(Boolean); }
  }, [user?.timeZone, deviceTimeZone]);
  if (!user) return null;
  const open = expanded || Boolean(timezoneError);
  return (
    <section aria-label="Timezone preferences" className="fixed bottom-4 right-4 z-[60] max-h-[calc(100dvh_-_2rem)] w-[calc(100vw_-_2rem)] overflow-y-auto rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 text-sm text-[#241453] shadow-lg sm:w-[36rem]">
      <div className="mx-auto max-w-7xl">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p aria-live="polite">Saved timezone: <strong>{user.timeZone || "Not saved"}</strong>
            {user.timeZoneSource === "manual" ? " (manual)" : user.timeZoneSource === "browser" ? " (device)" : ""}
            {busy && <span> — Checking with the library…</span>}
          </p>
          {!timezoneError && <button type="button" aria-expanded={open} aria-controls={`${listId}-editor`} onClick={() => setExpanded(!expanded)}
            className="font-semibold underline underline-offset-2">{open ? "Close settings" : "Change timezone"}</button>}
        </div>
        {timezoneError && <div role="alert" className="mt-2 rounded border border-amber-300 bg-amber-50 p-3 text-amber-950">
          <p>{timezoneError}</p>
          <button type="button" disabled={busy} onClick={() => { void retryTimezone().catch(() => null); }}
            className="mt-2 rounded bg-[#442F73] px-3 py-1.5 font-semibold text-white disabled:opacity-50">Retry timezone save</button>
        </div>}
        {open && <form id={`${listId}-editor`} className="mt-3 flex flex-wrap items-end gap-3 pb-2"
          onSubmit={(event) => { event.preventDefault(); void setTimezone(selection.trim(), "manual").catch(() => null); }}>
          <div>
            <label htmlFor={`${listId}-zone`} className="block font-medium">Choose your timezone</label>
            <input id={`${listId}-zone`} list={listId} value={selection} required disabled={busy} autoComplete="off"
              onChange={(event) => setSelection(event.target.value)} placeholder="IANA name: Area/City"
              className="mt-1 w-72 max-w-full rounded border border-purple-200 bg-white px-3 py-2" />
            <datalist id={listId}>{zones.map((zone) => <option key={zone} value={zone} />)}</datalist>
          </div>
          <button type="submit" disabled={busy || !selection.trim()} className="rounded bg-[#442F73] px-3 py-2 font-semibold text-white disabled:opacity-50">Save chosen timezone</button>
          <button type="button" disabled={busy || !deviceTimeZone} onClick={() => {
            if (deviceTimeZone) void setTimezone(deviceTimeZone, "browser").catch(() => null);
          }} className="rounded border border-purple-300 bg-white px-3 py-2 disabled:opacity-50">Use device timezone</button>
          <p className="w-full text-xs text-slate-600">Device: {deviceTimeZone || "Unavailable"}. A manual choice stays selected until you choose to use your device timezone. Existing loan return dates stay unchanged.</p>
        </form>}
      </div>
    </section>
  );
}
