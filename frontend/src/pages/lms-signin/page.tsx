import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

export default function LmsSignIn() {
  const pending = useRef<Promise<unknown> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    if (!pending.current) {
      const assertion = new URLSearchParams(window.location.hash.slice(1)).get("assertion");
      // Remove the short-lived assertion from the address bar/history promptly.
      window.history.replaceState(null, "", window.location.pathname);
      pending.current = assertion ? api.completeLmsSignIn(assertion) : Promise.reject(new Error("Missing sign-in"));
    }
    void pending.current.then(() => {
      if (active) window.location.replace("/account");
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center bg-[#F9F4EC] px-6">
      <section className="max-w-md rounded-3xl bg-white p-8 text-center shadow-sm" aria-live="polite">
        <h1 className="text-2xl font-bold text-[#241453]">{failed ? "We couldn't sign you in" : "Opening your Library account…"}</h1>
        <p className="mt-4 text-gray-600">{failed ? "Your sign-in may have expired, or Library access is temporarily unavailable. Please try again or contact the library team." : "Using your LMS sign-in. You don't need to enter your email again."}</p>
        {failed && <a className="mt-6 inline-block rounded-xl bg-[#241453] px-5 py-3 text-white" href={api.lmsSignInUrl}>Try LMS sign-in again</a>}
      </section>
    </main>
  );
}
