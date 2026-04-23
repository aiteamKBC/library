import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAdminData } from "../../hooks/useAdminData";
import { api } from "../../lib/api";
import StatsOverview from "./components/StatsOverview";
import BooksManager from "./components/BooksManager";
import LoansManager from "./components/LoansManager";
import CirculationHistory from "./components/CirculationHistoryManager";
import RequestsInbox from "./components/RequestsInbox";
import SupportInbox from "./components/SupportInbox";

const NAV = [
  { id: "overview", label: "Overview", icon: "ri-dashboard-3-line" },
  { id: "books", label: "Books & Resources", icon: "ri-book-shelf-line" },
  { id: "loans", label: "Loans & Reservations", icon: "ri-bookmark-3-line" },
  { id: "history", label: "History", icon: "ri-history-line" },
  { id: "requests", label: "Book Suggestions", icon: "ri-inbox-line", badge: true },
  { id: "support", label: "Support Inbox", icon: "ri-mail-unread-line", badge: true },
];

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const { requests, loans, supportMessages, adminLoading, adminLoaded, loadAdminData } = useAdminData();
  const pendingCount = requests.filter((r) => r.status === "pending").length;
  const newSupportCount = supportMessages.filter((message) => message.status === "new").length;
  const activeLoanCount = loans.filter((loan) => ["borrowed", "reserved", "overdue"].includes(loan.status)).length;

  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      try {
        const session = await api.getAuthMe();
        if (!["admin", "librarian"].includes(session.user.role)) {
          throw new Error("Not a library admin account");
        }
        if (!cancelled) {
          setAuthed(true);
        }
      } catch {
        if (!cancelled) {
          setAuthed(false);
        }
      } finally {
        if (!cancelled) {
          setAuthChecking(false);
        }
      }
    }

    void checkSession();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authed || adminLoaded) return;
    void loadAdminData();
  }, [authed, adminLoaded, loadAdminData]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (authSubmitting) return;
    setAuthSubmitting(true);
    try {
      await api.loginAdmin(identifier, password);
      setAuthed(true);
      setError("");
    } catch {
      setError("Incorrect password. Please try again.");
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await api.logoutAdmin();
    setAuthed(false);
  };

  const adminContent = adminLoading && (tab === "loans" || tab === "history" || tab === "requests")
    ? (
      <div className="w-full space-y-6">
        <div>
          <div className="h-7 w-56 rounded bg-gray-200 animate-pulse mb-2" />
          <div className="h-4 w-72 rounded bg-gray-100 animate-pulse" />
        </div>
        <div className="flex gap-2 flex-wrap">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-10 w-28 rounded-full bg-white border border-gray-200 animate-pulse" />
          ))}
        </div>
        <div className="h-12 rounded-xl bg-white border border-gray-200 animate-pulse" />
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="h-36 rounded-2xl bg-white border border-gray-200 animate-pulse" />
          ))}
        </div>
      </div>
    )
    : (
      <>
        {tab === "overview" && <StatsOverview onNavigate={setTab} />}
        {tab === "books" && <BooksManager />}
        {tab === "loans" && <LoansManager />}
        {tab === "history" && <CirculationHistory />}
        {tab === "requests" && <RequestsInbox />}
        {tab === "support" && <SupportInbox />}
      </>
    );

  if (authChecking) {
    return (
      <div className="min-h-screen bg-[#F9F4EC] flex items-center justify-center p-4">
        <div className="flex items-center gap-3 rounded-full border border-[#E9D9BD] bg-white px-5 py-3 shadow-sm">
          <div className="h-2.5 w-2.5 rounded-full bg-[#442F73] animate-pulse" />
            <p className="text-sm font-medium text-[#241453]">Checking library admin session...</p>
        </div>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="min-h-screen bg-[#F9F4EC] flex items-center justify-center p-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <div className="w-14 h-14 mx-auto bg-[#442F73] rounded-2xl flex items-center justify-center mb-4">
              <i className="ri-shield-keyhole-line text-white text-2xl" />
            </div>
            <h1 className="text-2xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
              Library Admin Portal
            </h1>
            <p className="text-gray-400 text-sm mt-1">KBC Digital Library</p>
          </div>

          <div className="bg-white rounded-2xl border border-[#E9D9BD] p-7 shadow-sm">
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5">Username or Email</label>
                <div className="relative">
                  <i className="ri-user-line absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
                  <input
                    type="text"
                    value={identifier}
                    onChange={(e) => { setIdentifier(e.target.value); setError(""); }}
                    disabled={authSubmitting}
                    placeholder="Use your library admin email"
                    className="w-full pl-10 pr-4 py-3 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5">Password</label>
                <div className="relative">
                  <i className="ri-lock-line absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); setError(""); }}
                    disabled={authSubmitting}
                    placeholder="Enter your library admin password"
                    className="w-full pl-10 pr-4 py-3 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400"
                  />
                </div>
                {error && (
                  <p className="text-rose-500 text-xs mt-1.5 flex items-center gap-1">
                    <i className="ri-error-warning-line" />{error}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={authSubmitting}
                className="w-full py-3 bg-[#442F73] hover:bg-[#241453] text-white font-semibold text-sm rounded-xl transition-colors duration-200 cursor-pointer disabled:cursor-not-allowed disabled:bg-[#442F73]/75 disabled:text-white/90"
              >
                {authSubmitting ? (
                  <span className="inline-flex items-center justify-center gap-2">
                    <i className="ri-loader-4-line animate-spin" />
                    Signing in...
                  </span>
                ) : (
                  "Sign In to Library Admin"
                )}
              </button>
            </form>

            <div className="mt-5 pt-5 border-t border-gray-100 flex items-center justify-center">
              <Link to="/" className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-[#442F73] transition-colors cursor-pointer">
                <i className="ri-arrow-left-line" />
                Back to Library
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-[#1a0d3d] flex flex-col transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        } lg:translate-x-0 lg:static lg:z-auto`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-white/8">
          <div className="w-8 h-8 bg-[#CEA869] rounded-lg flex items-center justify-center flex-none">
            <i className="ri-book-shelf-line text-[#241453] text-sm" />
          </div>
          <div>
            <p className="text-white font-bold text-sm" style={{ fontFamily: "'Playfair Display', serif" }}>KBC Library</p>
            <p className="text-white/40 text-[10px]">Library Admin Dashboard</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => { setTab(item.id); setSidebarOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer text-left ${
                tab === item.id
                  ? "bg-white/12 text-white"
                  : "text-white/50 hover:bg-white/6 hover:text-white/80"
              }`}
            >
              <i className={`${item.icon} text-base flex-none`} />
              {item.label}
              {item.badge && item.id === "requests" && pendingCount > 0 && (
                <span className="ml-auto bg-[#CEA869] text-[#241453] text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {pendingCount}
                </span>
              )}
              {item.badge && item.id === "support" && newSupportCount > 0 && (
                <span className="ml-auto bg-[#CEA869] text-[#241453] text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {newSupportCount}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Bottom */}
        <div className="px-3 py-4 border-t border-white/8 space-y-1">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-white/40 hover:text-rose-300 hover:bg-white/6 transition-all cursor-pointer"
          >
            <i className="ri-logout-box-line" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="bg-white border-b border-gray-200 px-6 md:px-12 xl:px-16 h-14 flex-none">
          <div className="mx-auto flex h-full w-full max-w-[1400px] items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(true)}
                className="lg:hidden w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer"
              >
                <i className="ri-menu-line text-gray-600" />
              </button>
              <div>
                <p className="text-base font-bold text-[#442F73] md:text-lg">
                  {NAV.find((n) => n.id === tab)?.label}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 md:gap-3">
              {pendingCount > 0 && (
                <button
                  onClick={() => setTab("requests")}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-50 border border-amber-200 text-amber-700 text-xs font-semibold rounded-full cursor-pointer hover:bg-amber-100 transition-colors whitespace-nowrap"
                >
                  <i className="ri-notification-3-line" />
                  {pendingCount} pending request{pendingCount > 1 ? "s" : ""}
                </button>
              )}
              {newSupportCount > 0 && (
                <button
                  onClick={() => setTab("support")}
                  className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-violet-50 border border-violet-200 text-violet-700 text-xs font-semibold rounded-full cursor-pointer hover:bg-violet-100 transition-colors whitespace-nowrap"
                >
                  <i className="ri-mail-line" />
                  {newSupportCount} new support message{newSupportCount > 1 ? "s" : ""}
                </button>
              )}
              {activeLoanCount > 0 && (
                <button
                  onClick={() => setTab("loans")}
                  className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-sky-50 border border-sky-200 text-sky-700 text-xs font-semibold rounded-full cursor-pointer hover:bg-sky-100 transition-colors whitespace-nowrap"
                >
                  <i className="ri-bookmark-line" />
                  {activeLoanCount} active circulation
                </button>
              )}
              <Link
                to="/"
                className="inline-flex items-center gap-2 rounded-full border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 shadow-sm transition-all duration-200 hover:border-violet-300 hover:bg-violet-100 hover:text-violet-800 whitespace-nowrap"
              >
                <i className="ri-external-link-line text-sm" />
                <span className="hidden sm:inline">View Library Site</span>
              </Link>
              <div className="w-8 h-8 rounded-full bg-[#442F73] flex items-center justify-center">
                <i className="ri-user-line text-white text-xs" />
              </div>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto px-6 py-4 md:px-12 md:py-8 xl:px-16">
          <div className="mx-auto w-full max-w-[1400px]">
            {adminContent}
          </div>
        </main>
      </div>
    </div>
  );
}
