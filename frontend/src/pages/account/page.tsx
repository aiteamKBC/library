import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import Navbar from "../../components/feature/Navbar";
import Footer from "../../components/feature/Footer";
import { useLibrarySession } from "../../hooks/useLibrarySession";
import { api } from "../../lib/api";
import type { BookRequest, Loan, StudentDashboard } from "../../types/library";

const ACTIVE_LOAN_STATUSES = new Set(["approved", "reserved", "borrowed", "overdue"]);
const PENDING_REQUEST_STATUSES = new Set(["requested"]);
const HIDEABLE_LOAN_STATUSES = new Set<Loan["status"]>(["returned", "notify", "cancelled"]);
const HIDEABLE_BOOK_REQUEST_STATUSES = new Set<BookRequest["status"]>(["approved", "rejected", "ordered", "cancelled"]);

function hiddenLoansStorageKey(accountEmail: string) {
  return `kbc-hidden-account-loans:${accountEmail.trim().toLowerCase()}`;
}

function hiddenRequestsStorageKey(accountEmail: string) {
  return `kbc-hidden-account-requests:${accountEmail.trim().toLowerCase()}`;
}

function readHiddenLoanIds(accountEmail: string) {
  if (typeof window === "undefined") return [];
  try {
    const stored = window.localStorage.getItem(hiddenLoansStorageKey(accountEmail));
    if (!stored) return [];
    const parsed = JSON.parse(stored) as unknown;
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function writeHiddenLoanIds(accountEmail: string, loanIds: string[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(hiddenLoansStorageKey(accountEmail), JSON.stringify(loanIds));
}

function readHiddenRequestIds(accountEmail: string) {
  if (typeof window === "undefined") return [];
  try {
    const stored = window.localStorage.getItem(hiddenRequestsStorageKey(accountEmail));
    if (!stored) return [];
    const parsed = JSON.parse(stored) as unknown;
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function writeHiddenRequestIds(accountEmail: string, requestIds: string[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(hiddenRequestsStorageKey(accountEmail), JSON.stringify(requestIds));
}

function getStudentLoanActionLabel(loan: Loan) {
  if (loan.status !== "requested") return null;
  return loan.loanType === "notify" ? "Remove Alert" : "Cancel Request";
}

function canHideLoan(loan: Loan) {
  return HIDEABLE_LOAN_STATUSES.has(loan.status);
}

function getStudentBookRequestActionLabel(request: BookRequest) {
  if (request.status !== "pending") return null;
  return "Cancel Request";
}

function canHideBookRequest(request: BookRequest) {
  return HIDEABLE_BOOK_REQUEST_STATUSES.has(request.status);
}

function formatDate(value?: string | null) {
  if (!value) return "Not set";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function titleCaseStatus(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function flattenStructuredError(value: unknown): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    const firstString = value.find((item) => typeof item === "string");
    return typeof firstString === "string" ? firstString : null;
  }
  if (value && typeof value === "object") {
    for (const nestedValue of Object.values(value)) {
      const nestedMessage = flattenStructuredError(nestedValue);
      if (nestedMessage) {
        return nestedMessage;
      }
    }
  }
  return null;
}

function formatApiError(message: string) {
  const trimmed = message.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      const nested = flattenStructuredError(parsed);
      if (nested) {
        return nested;
      }
    } catch {
      // Fall through to the raw message.
    }
  }
  if (trimmed.includes("sign in directly")) {
    return "Use your approved email address to sign in directly.";
  }
  if (trimmed.includes("library admin portal")) {
    return "This account should sign in through the Library Admin portal.";
  }
  if (trimmed.includes("student accounts only")) {
    return "This area is available to student accounts only.";
  }
  if (trimmed.includes("not approved")) {
    return "This email address is not approved for the KBC Library system.";
  }
  if (trimmed.includes("no longer approved")) {
    return "This email address is no longer approved for the KBC Library system.";
  }
  if (trimmed.includes("not configured yet")) {
    return "Student sign-in is not fully configured yet. Please contact the library team.";
  }
  return trimmed || "We could not complete this action right now.";
}

function statusBadgeClass(status: string) {
  const tone: Record<string, string> = {
    requested: "bg-amber-50 text-amber-700 border-amber-200",
    pending: "bg-amber-50 text-amber-700 border-amber-200",
    approved: "bg-emerald-50 text-emerald-700 border-emerald-200",
    ordered: "bg-sky-50 text-sky-700 border-sky-200",
    reserved: "bg-violet-50 text-violet-700 border-violet-200",
    borrowed: "bg-[#F3E9DA] text-[#6A4711] border-[#E9D9BD]",
    overdue: "bg-rose-50 text-rose-700 border-rose-200",
    returned: "bg-gray-100 text-gray-700 border-gray-200",
    notify: "bg-sky-50 text-sky-700 border-sky-200",
    rejected: "bg-rose-50 text-rose-700 border-rose-200",
    cancelled: "bg-gray-100 text-gray-700 border-gray-200",
    new: "bg-amber-50 text-amber-700 border-amber-200",
    in_progress: "bg-violet-50 text-violet-700 border-violet-200",
    resolved: "bg-emerald-50 text-emerald-700 border-emerald-200",
  };

  return tone[status] ?? "bg-gray-100 text-gray-700 border-gray-200";
}

export default function AccountPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const {
    user,
    loading: sessionLoading,
    loginStudent,
    updateProfile,
    logout,
  } = useLibrarySession();
  const isLibraryStaff = user ? ["admin", "librarian"].includes(user.role) : false;
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authError, setAuthError] = useState("");
  const [dashboard, setDashboard] = useState<StudentDashboard | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [intentMessage, setIntentMessage] = useState(() => {
    const state = location.state as { intentMessage?: string } | null;
    return state?.intentMessage ?? "";
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMessage, setProfileMessage] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const [activityFeedback, setActivityFeedback] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [requestFeedback, setRequestFeedback] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [actingLoanId, setActingLoanId] = useState<string | null>(null);
  const [actingRequestId, setActingRequestId] = useState<string | null>(null);
  const [loanPendingConfirmation, setLoanPendingConfirmation] = useState<Loan | null>(null);
  const [requestPendingConfirmation, setRequestPendingConfirmation] = useState<BookRequest | null>(null);
  const [hiddenLoanIds, setHiddenLoanIds] = useState<string[]>([]);
  const [hiddenRequestIds, setHiddenRequestIds] = useState<string[]>([]);
  const [loginForm, setLoginForm] = useState({
    email: "",
  });
  const [profileForm, setProfileForm] = useState({
    fullName: "",
    phoneNumber: "",
  });

  const loadDashboard = useCallback(async () => {
    if (!user || user.role !== "student") {
      setDashboard(null);
      setDashboardError("");
      return;
    }
    setDashboardLoading(true);
    setDashboardError("");
    try {
      const response = await api.getStudentDashboard();
      setDashboard(response);
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not load your dashboard.";
      setDashboardError(formatApiError(rawMessage));
    } finally {
      setDashboardLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const state = location.state as { intentMessage?: string } | null;
    setIntentMessage(state?.intentMessage ?? "");
  }, [location.state]);

  useEffect(() => {
    if (sessionLoading || !isLibraryStaff) return;
    navigate("/libraryadmin", { replace: true });
  }, [isLibraryStaff, navigate, sessionLoading]);

  useEffect(() => {
    if (!user || user.role !== "student") {
      setDashboard(null);
      return;
    }
    setProfileForm({
      fullName: user.fullName ?? "",
      phoneNumber: user.phone_number ?? "",
    });
    void loadDashboard();
  }, [loadDashboard, user]);

  useEffect(() => {
    if (!user) {
      setHiddenLoanIds([]);
      setHiddenRequestIds([]);
      return;
    }
    setHiddenLoanIds(readHiddenLoanIds(user.email));
    setHiddenRequestIds(readHiddenRequestIds(user.email));
  }, [user]);

  const activeLoans = useMemo(
    () =>
      dashboard?.loans.filter((loan) => loan.loanType !== "notify" && ACTIVE_LOAN_STATUSES.has(loan.status)).length ?? 0,
    [dashboard],
  );
  const pendingRequests = useMemo(
    () =>
      dashboard?.loans.filter((loan) => loan.loanType !== "notify" && PENDING_REQUEST_STATUSES.has(loan.status)).length ?? 0,
    [dashboard],
  );
  const visibleLoans = useMemo(() => {
    const hidden = new Set(hiddenLoanIds);
    return dashboard?.loans.filter((loan) => !hidden.has(loan.id)) ?? [];
  }, [dashboard, hiddenLoanIds]);
  const shouldStretchBorrowingCard = dashboardLoading || visibleLoans.length > 0;
  const visibleBookRequests = useMemo(() => {
    const hidden = new Set(hiddenRequestIds);
    return dashboard?.requests.filter((request) => !hidden.has(request.id)) ?? [];
  }, [dashboard, hiddenRequestIds]);

  const completeStudentSignIn = () => {
    const state = location.state as { redirectTo?: string } | null;
    if (state?.redirectTo) {
      navigate(state.redirectTo, { replace: true });
    }
  };

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (authSubmitting) return;
    const email = loginForm.email.trim().toLowerCase();
    if (!email) return;
    setAuthSubmitting(true);
    setAuthError("");
    try {
      await loginStudent(email);
      setLoginForm({ email: "" });
      completeStudentSignIn();
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not sign you in.";
      setAuthError(formatApiError(rawMessage));
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleSaveProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (savingProfile) return;
    setSavingProfile(true);
    setProfileMessage("");
    try {
      const updatedUser = await updateProfile({
        fullName: profileForm.fullName.trim(),
        phoneNumber: profileForm.phoneNumber.trim(),
      });
      setDashboard((prev) => (prev ? { ...prev, user: updatedUser } : prev));
      setProfileMessage("Your profile has been updated.");
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not save your profile.";
      setProfileMessage(formatApiError(rawMessage));
    } finally {
      setSavingProfile(false);
    }
  };

  const openLoanConfirmation = (loan: Loan) => {
    if (actingLoanId) return;
    setActivityFeedback(null);
    setLoanPendingConfirmation(loan);
  };

  const closeLoanConfirmation = () => {
    if (actingLoanId) return;
    setLoanPendingConfirmation(null);
  };

  const handleCancelLoan = async () => {
    const loan = loanPendingConfirmation;
    if (!loan) return;
    if (actingLoanId) return;
    setActingLoanId(loan.id);
    setActivityFeedback(null);
    try {
      const updatedLoan = await api.cancelStudentLoan(loan.id);
      setDashboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          loans: prev.loans.map((item) => (item.id === updatedLoan.id ? updatedLoan : item)),
        };
      });
      setActivityFeedback({
        tone: "success",
        text: loan.loanType === "notify" ? "Your availability alert has been removed." : "Your request has been cancelled.",
      });
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not update this request right now.";
      setActivityFeedback({ tone: "error", text: formatApiError(rawMessage) });
    } finally {
      setActingLoanId(null);
      setLoanPendingConfirmation(null);
    }
  };

  const handleHideLoan = (loanId: string) => {
    if (!user) return;
    setActivityFeedback(null);
    setHiddenLoanIds((prev) => {
      if (prev.includes(loanId)) return prev;
      const next = [...prev, loanId];
      writeHiddenLoanIds(user.email, next);
      return next;
    });
  };

  const handleShowHiddenLoans = () => {
    if (!user) return;
    writeHiddenLoanIds(user.email, []);
    setHiddenLoanIds([]);
    setActivityFeedback(null);
  };

  const openRequestConfirmation = (request: BookRequest) => {
    if (actingRequestId) return;
    setRequestFeedback(null);
    setRequestPendingConfirmation(request);
  };

  const closeRequestConfirmation = () => {
    if (actingRequestId) return;
    setRequestPendingConfirmation(null);
  };

  const handleCancelBookRequest = async () => {
    const request = requestPendingConfirmation;
    if (!request) return;
    if (actingRequestId) return;
    setActingRequestId(request.id);
    setRequestFeedback(null);
    try {
      const updatedRequest = await api.cancelStudentRequest(request.id);
      setDashboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          requests: prev.requests.map((item) => (item.id === updatedRequest.id ? updatedRequest : item)),
        };
      });
      setRequestFeedback({
        tone: "success",
        text: "Your book request has been cancelled.",
      });
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "We could not update this book request right now.";
      setRequestFeedback({ tone: "error", text: formatApiError(rawMessage) });
    } finally {
      setActingRequestId(null);
      setRequestPendingConfirmation(null);
    }
  };

  const handleHideBookRequest = (requestId: string) => {
    if (!user) return;
    setRequestFeedback(null);
    setHiddenRequestIds((prev) => {
      if (prev.includes(requestId)) return prev;
      const next = [...prev, requestId];
      writeHiddenRequestIds(user.email, next);
      return next;
    });
  };

  const handleShowHiddenRequests = () => {
    if (!user) return;
    writeHiddenRequestIds(user.email, []);
    setHiddenRequestIds([]);
    setRequestFeedback(null);
  };

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
      setDashboard(null);
      setProfileMessage("");
      setActivityFeedback(null);
      setRequestFeedback(null);
      setHiddenLoanIds([]);
      setHiddenRequestIds([]);
      setLoanPendingConfirmation(null);
      setRequestPendingConfirmation(null);
    } finally {
      setLoggingOut(false);
    }
  };

  if (sessionLoading) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <main className="pt-32 pb-24 bg-[#F9F4EC] min-h-screen">
          <div className="max-w-7xl mx-auto px-4 md:px-6">
            <div className="flex items-center justify-center py-24">
              <div className="flex items-center gap-3 rounded-full border border-[#E9D9BD] bg-white px-5 py-3 shadow-sm">
                <div className="h-2.5 w-2.5 rounded-full bg-[#442F73] animate-pulse" />
                <p className="text-sm font-medium text-[#241453]">Loading your library account...</p>
              </div>
            </div>
          </div>
        </main>
        <Footer />
      </div>
    );
  }

  if (user && isLibraryStaff) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <main className="pt-32 pb-24 bg-[#F9F4EC] min-h-screen">
          <div className="max-w-7xl mx-auto px-4 md:px-6">
            <div className="flex items-center justify-center py-24">
              <div className="flex items-center gap-3 rounded-full border border-[#E9D9BD] bg-white px-5 py-3 shadow-sm">
                <div className="h-2.5 w-2.5 rounded-full bg-[#442F73] animate-pulse" />
                <p className="text-sm font-medium text-[#241453]">Redirecting to the library admin portal...</p>
              </div>
            </div>
          </div>
        </main>
        <Footer />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />

        <section
          className="relative pt-36 pb-20 overflow-hidden"
          style={{ background: "linear-gradient(135deg, #241453 0%, #442F73 60%, #644D93 100%)" }}
        >
          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-12 right-16 w-72 h-72 rounded-full bg-white/20 blur-3xl" />
            <div className="absolute bottom-0 left-8 w-64 h-64 rounded-full bg-[#CEA869]/25 blur-3xl" />
          </div>
          <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-white/10 backdrop-blur-sm border border-white/20 rounded-full mb-5">
                <i className="ri-user-star-line text-[#CEA869] text-xs" />
                <span className="text-white text-xs font-medium">Library Account</span>
              </div>
              <h1
                className="text-4xl md:text-5xl font-bold text-white mb-4 leading-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Manage your library account in one place
              </h1>
              <p className="text-[#EEE7FF] text-base md:text-lg max-w-2xl leading-relaxed">
                Use your Aptem email to access your library account and track your loans, requests and library updates in one place.
              </p>
            </div>
          </div>
        </section>

        <section className="bg-[#F9F4EC] py-16">
          <div className="max-w-7xl mx-auto px-4 md:px-6 grid lg:grid-cols-[1.1fr_0.9fr] gap-8 items-start">
            <div className="space-y-5">
              <div className="bg-white rounded-3xl border border-[#E9D9BD] p-6 md:p-8 shadow-sm">
                <div className="flex items-center gap-3 mb-5">
                  <div className="w-11 h-11 rounded-2xl bg-[#241453] flex items-center justify-center">
                    <i className="ri-book-open-line text-white text-lg" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                      Why sign in with your Aptem email?
                    </h2>
                    <p className="text-sm text-gray-500">Fast access for approved learners using only the email already listed by the college.</p>
                  </div>
                </div>
                <div className="grid sm:grid-cols-2 gap-4">
                  {[
                    { icon: "ri-mail-check-line", title: "Approved Access Only", text: "Only Aptem email addresses listed by the college can access the library system." },
                    { icon: "ri-shield-user-line", title: "Instant Sign-In", text: "Enter your Aptem email and the system signs you in immediately when the address is recognised." },
                    { icon: "ri-bookmark-3-line", title: "Loan and Request Tracking", text: "See your borrow requests, return history and book suggestions in one place." },
                    { icon: "ri-notification-3-line", title: "Availability Alerts", text: "Keep your activity linked to your student profile so follow-up stays simple." },
                  ].map((item) => (
                    <div key={item.title} className="rounded-2xl border border-[#F1E3CB] bg-[#FCFAF6] px-4 py-4">
                      <div className="w-10 h-10 rounded-xl bg-[#F3E9DA] text-[#241453] flex items-center justify-center mb-3">
                        <i className={`${item.icon} text-lg`} />
                      </div>
                      <p className="font-semibold text-[#241453]">{item.title}</p>
                      <p className="text-sm text-gray-500 mt-1 leading-6">{item.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="bg-white rounded-3xl border border-[#E9D9BD] p-6 md:p-8 shadow-sm">
              <div className="inline-flex items-center gap-2 rounded-full border border-[#E9D9BD] bg-[#FCFAF6] px-3.5 py-1.5 mb-6">
                <i className="ri-shield-keyhole-line text-[#442F73] text-sm" />
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E5A99]">
                  Student Sign In
                </span>
              </div>

              <div className="mb-6">
                <h2 className="text-2xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                  Sign in with your Aptem email
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  Enter the Aptem email address already listed in the college allowlist to access your student library account.
                </p>
              </div>

              {authError && (
                <div className="mb-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {authError}
                </div>
              )}

              {intentMessage && (
                <div className="mb-5 rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] px-4 py-3 text-sm text-[#5C4520]">
                  {intentMessage}
                </div>
              )}

              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1.5">Aptem Email Address</label>
                  <input
                    required
                    type="email"
                    value={loginForm.email}
                    onChange={(event) => setLoginForm({ email: event.target.value })}
                    placeholder="Enter your Aptem email"
                    className="w-full px-4 py-3 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                  />
                </div>
                <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] px-4 py-4">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl bg-white text-[#442F73] shadow-sm">
                      <i className="ri-check-double-line text-base" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-[#241453]">Allowlisted Aptem email access</p>
                      <p className="mt-1 text-sm leading-6 text-gray-500">
                        If this Aptem email exists in the college allowlist, you will be signed in directly to your library account.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={authSubmitting}
                  className="w-full py-3 rounded-xl bg-[#241453] text-white text-sm font-semibold cursor-pointer hover:bg-[#160a34] transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
                >
                  {authSubmitting ? "Signing In..." : "Sign In"}
                </button>
              </form>
            </div>
          </div>
        </section>

        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      <Navbar />

      <section
        className="relative overflow-hidden pt-36 pb-16 md:pb-20"
        style={{ background: "linear-gradient(135deg, #241453 0%, #442F73 60%, #644D93 100%)" }}
      >
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-8 right-16 w-72 h-72 rounded-full bg-white/20 blur-3xl" />
          <div className="absolute bottom-0 left-8 w-64 h-64 rounded-full bg-[#CEA869]/25 blur-3xl" />
        </div>
        <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6">
          <nav className="flex items-center gap-2 text-white/50 text-xs mb-5">
            <Link to="/" className="hover:text-white transition-colors duration-200 cursor-pointer">Home</Link>
            <i className="ri-arrow-right-s-line" />
            <span className="text-white/80">My Account</span>
          </nav>

          <div className="flex flex-col lg:flex-row gap-6 lg:items-end lg:justify-between">
            <div>
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3.5 py-1.5 backdrop-blur-sm">
                <i className="ri-id-card-line text-[#CEA869] text-xs" />
                <span className="text-xs font-medium text-white">Library Member Profile</span>
              </div>
              <h1
                className="text-4xl md:text-5xl font-bold text-white mb-3 leading-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                {user.fullName}
              </h1>
              <p className="max-w-2xl text-base leading-relaxed text-white md:text-lg">
                Keep your contact details, borrow requests, and account activity together in one place.
              </p>
              <div className="mt-6 flex flex-wrap gap-3 text-sm text-white">
                <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3.5 py-2">
                  <i className="ri-mail-line" />
                  {user.email}
                </span>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3.5 py-2">
                  <i className="ri-user-star-line" />
                  {titleCaseStatus(user.role)}
                </span>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link
                to="/resources"
                className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-[#CEA869] hover:bg-[#B27715] text-[#241453] font-bold text-sm rounded-full transition-all duration-200 cursor-pointer whitespace-nowrap"
              >
                <i className="ri-book-open-line" />
                Browse Books
              </Link>
              <button
                type="button"
                onClick={() => void handleLogout()}
                disabled={loggingOut}
                className="inline-flex items-center justify-center gap-2 rounded-full border border-white/20 bg-white/10 px-6 py-3 text-sm font-semibold text-white transition-all duration-200 hover:bg-white/20 cursor-pointer whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-70"
              >
                <i className={loggingOut ? "ri-loader-4-line animate-spin" : "ri-logout-box-r-line"} />
                {loggingOut ? "Signing Out..." : "Sign Out"}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[#F9F4EC] py-12">
        <div className="max-w-7xl mx-auto px-4 md:px-6 space-y-8">
          <div className="grid md:grid-cols-2 gap-4">
            {[
              { label: "Active Loans", value: activeLoans, icon: "ri-bookmark-3-line" },
              { label: "Pending Requests", value: pendingRequests, icon: "ri-inbox-line" },
            ].map((item) => (
              <div key={item.label} className="rounded-3xl bg-white border border-[#E9D9BD] p-5 shadow-sm">
                <div className="w-11 h-11 rounded-2xl bg-[#F3E9DA] text-[#241453] flex items-center justify-center mb-4">
                  <i className={`${item.icon} text-lg`} />
                </div>
                <p className="text-sm text-gray-500">{item.label}</p>
                <p className="text-3xl font-bold text-[#241453] mt-2" style={{ fontFamily: "'Playfair Display', serif" }}>
                  {item.value}
                </p>
              </div>
            ))}
          </div>

          <div className="space-y-8">
            <div className="rounded-3xl bg-white border border-[#E9D9BD] p-6 md:p-7 shadow-sm">
                <div className="flex items-center justify-between gap-4 mb-6">
                  <div>
                    <h2 className="text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                      Profile Details
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">Update the information the library uses for your requests.</p>
                  </div>
                  <div className="w-11 h-11 rounded-2xl bg-[#241453] text-white flex items-center justify-center">
                    <i className="ri-user-settings-line text-lg" />
                  </div>
                </div>

                <form onSubmit={handleSaveProfile} className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-600 mb-1.5">Full Name</label>
                    <input
                      required
                      type="text"
                      value={profileForm.fullName}
                      onChange={(event) => setProfileForm((prev) => ({ ...prev, fullName: event.target.value }))}
                      className="w-full px-4 py-3 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-600 mb-1.5">Email Address</label>
                    <input
                      type="email"
                      value={user.email}
                      readOnly
                      className="w-full px-4 py-3 text-sm border border-gray-200 rounded-xl bg-gray-50 text-gray-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-600 mb-1.5">Phone Number</label>
                    <input
                      type="tel"
                      value={profileForm.phoneNumber}
                      onChange={(event) => setProfileForm((prev) => ({ ...prev, phoneNumber: event.target.value }))}
                      placeholder="Add your phone number"
                      className="w-full px-4 py-3 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
                    />
                  </div>
                  {profileMessage && (
                    <div className={`rounded-2xl px-4 py-3 text-sm ${
                      profileMessage.includes("updated")
                        ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                        : "bg-rose-50 border border-rose-200 text-rose-700"
                    }`}>
                      {profileMessage}
                    </div>
                  )}
                  <button
                    type="submit"
                    disabled={savingProfile}
                    className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[#241453] text-white text-sm font-semibold cursor-pointer hover:bg-[#160a34] transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
                  >
                    <i className={savingProfile ? "ri-loader-4-line animate-spin" : "ri-save-line"} />
                    {savingProfile ? "Saving..." : "Save Changes"}
                  </button>
                </form>
            </div>

            <div className={`rounded-3xl bg-white border border-[#E9D9BD] p-6 md:p-7 shadow-sm flex flex-col ${shouldStretchBorrowingCard ? "md:min-h-[620px] xl:min-h-[760px]" : ""}`}>
                <div className="flex items-center justify-between gap-4 mb-6">
                  <div>
                    <h2 className="text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                      My Borrowing Activity
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">Requests, active borrowing, and availability alerts linked to your account.</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {hiddenLoanIds.length ? (
                      <button
                        type="button"
                        onClick={handleShowHiddenLoans}
                        className="inline-flex items-center rounded-full border border-[#E9D9BD] bg-white px-3 py-1.5 text-xs font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                      >
                        Show Hidden
                      </button>
                    ) : null}
                    <div className="w-11 h-11 rounded-2xl bg-[#F3E9DA] text-[#241453] flex items-center justify-center">
                      <i className="ri-bookmark-3-line text-lg" />
                    </div>
                  </div>
                </div>

                {dashboardError && (
                  <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {dashboardError}
                  </div>
                )}

                {activityFeedback && (
                  <div className={`mb-4 rounded-2xl border px-4 py-3 text-sm ${
                    activityFeedback.tone === "success"
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-rose-200 bg-rose-50 text-rose-700"
                  }`}>
                    {activityFeedback.text}
                  </div>
                )}

                {dashboardLoading ? (
                  <div className="space-y-3 min-h-0 flex-1 overflow-y-auto pr-2">
                    {Array.from({ length: 3 }).map((_, index) => (
                      <div key={index} className="h-28 rounded-2xl bg-[#FCFAF6] border border-[#F1E3CB] animate-pulse" />
                    ))}
                  </div>
                ) : visibleLoans.length ? (
                  <div className="space-y-3 min-h-0 flex-1 overflow-y-auto pr-2">
                    {visibleLoans.map((loan) => (
                      <div key={loan.id} className="rounded-2xl border border-[#F1E3CB] bg-[#FCFAF6] px-4 py-4">
                        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                          <div>
                            <p className="font-semibold text-[#241453]">{loan.bookTitle}</p>
                            <p className="text-sm text-gray-500 mt-1">
                              {loan.loanType === "notify" ? "Availability alert" : "Borrow flow"}
                              {loan.accessionNumber ? ` • ${loan.accessionNumber}` : ""}
                            </p>
                          </div>
                          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${statusBadgeClass(loan.status)}`}>
                            {titleCaseStatus(loan.status)}
                          </span>
                        </div>
                        <div className="grid sm:grid-cols-3 gap-3 mt-4 text-sm">
                          <div className="rounded-xl bg-white border border-[#F1E3CB] px-3 py-3">
                            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">Requested</p>
                            <p className="font-medium text-[#241453]">{formatDate(loan.requestedAt)}</p>
                          </div>
                          <div className="rounded-xl bg-white border border-[#F1E3CB] px-3 py-3">
                            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">Due Date</p>
                            <p className="font-medium text-[#241453]">{formatDate(loan.dueDate)}</p>
                          </div>
                          <div className="rounded-xl bg-white border border-[#F1E3CB] px-3 py-3">
                            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">Returned</p>
                            <p className="font-medium text-[#241453]">{formatDate(loan.returnedAt)}</p>
                          </div>
                        </div>
                        {loan.notes && (
                          <p className="text-sm text-gray-600 mt-3 leading-6">{loan.notes}</p>
                        )}
                        {(getStudentLoanActionLabel(loan) || canHideLoan(loan)) && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {getStudentLoanActionLabel(loan) ? (
                              <button
                                type="button"
                                onClick={() => openLoanConfirmation(loan)}
                                disabled={actingLoanId === loan.id}
                                className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3.5 py-2 text-xs font-semibold text-amber-700 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-70"
                              >
                                <i className={actingLoanId === loan.id ? "ri-loader-4-line animate-spin" : "ri-close-circle-line"} />
                                {actingLoanId === loan.id ? "Updating..." : getStudentLoanActionLabel(loan)}
                              </button>
                            ) : null}
                            {canHideLoan(loan) ? (
                              <button
                                type="button"
                                onClick={() => handleHideLoan(loan.id)}
                                className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-600 transition-colors hover:border-gray-300 hover:text-gray-800"
                              >
                                <i className="ri-eye-off-line" />
                                Hide
                              </button>
                            ) : null}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#D9C6A5] bg-[#FCFAF6] px-5 py-6 text-sm text-gray-500">
                    {dashboard?.loans.length ? (
                      <div className="space-y-3">
                        <p>All hidden activity has been removed from this view.</p>
                        <button
                          type="button"
                          onClick={handleShowHiddenLoans}
                          className="inline-flex items-center gap-2 rounded-full border border-[#E9D9BD] bg-white px-4 py-2 text-xs font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                        >
                          <i className="ri-eye-line" />
                          Show Hidden Activity
                        </button>
                      </div>
                    ) : (
                      "No borrow activity yet. Start from the resources page and submit your first borrow or notify request."
                    )}
                  </div>
                )}
            </div>

            <div className="rounded-3xl bg-white border border-[#E9D9BD] p-6 md:p-7 shadow-sm">
                <div className="flex items-center justify-between gap-4 mb-6">
                  <div>
                    <h2 className="text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                      Book Requests
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">Suggestions and purchase requests you submitted to the library.</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {hiddenRequestIds.length ? (
                      <button
                        type="button"
                        onClick={handleShowHiddenRequests}
                        className="inline-flex items-center rounded-full border border-[#E9D9BD] bg-white px-3 py-1.5 text-xs font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                      >
                        Show Hidden
                      </button>
                    ) : null}
                    <Link
                      to="/support"
                      className="text-sm font-semibold text-[#442F73] hover:text-[#241453] transition-colors"
                    >
                      Suggest a Book
                    </Link>
                  </div>
                </div>

                {requestFeedback && (
                  <div className={`mb-4 rounded-2xl border px-4 py-3 text-sm ${
                    requestFeedback.tone === "success"
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-rose-200 bg-rose-50 text-rose-700"
                  }`}>
                    {requestFeedback.text}
                  </div>
                )}

                {dashboardLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 2 }).map((_, index) => (
                      <div key={index} className="h-24 rounded-2xl bg-[#FCFAF6] border border-[#F1E3CB] animate-pulse" />
                    ))}
                  </div>
                ) : visibleBookRequests.length ? (
                  <div className="space-y-3">
                    {visibleBookRequests.map((request) => (
                      <div key={request.id} className="rounded-2xl border border-[#F1E3CB] bg-[#FCFAF6] px-4 py-4">
                        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                          <div>
                            <p className="font-semibold text-[#241453]">{request.bookTitle}</p>
                            <p className="text-sm text-gray-500 mt-1">
                              {request.category} • {formatDate(request.submittedAt)}
                            </p>
                          </div>
                          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${statusBadgeClass(request.status)}`}>
                            {titleCaseStatus(request.status)}
                          </span>
                        </div>
                        {request.reason && (
                          <p className="text-sm text-gray-600 mt-3 leading-6">{request.reason}</p>
                        )}
                        {request.reviewNotes && (
                          <div className="mt-3 rounded-xl border border-[#E9D9BD] bg-white px-3 py-3">
                            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">Library Note</p>
                            <p className="text-sm text-[#241453] leading-6">{request.reviewNotes}</p>
                          </div>
                        )}
                        {(getStudentBookRequestActionLabel(request) || canHideBookRequest(request)) && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {getStudentBookRequestActionLabel(request) ? (
                              <button
                                type="button"
                                onClick={() => openRequestConfirmation(request)}
                                disabled={actingRequestId === request.id}
                                className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3.5 py-2 text-xs font-semibold text-amber-700 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-70"
                              >
                                <i className={actingRequestId === request.id ? "ri-loader-4-line animate-spin" : "ri-close-circle-line"} />
                                {actingRequestId === request.id ? "Updating..." : getStudentBookRequestActionLabel(request)}
                              </button>
                            ) : null}
                            {canHideBookRequest(request) ? (
                              <button
                                type="button"
                                onClick={() => handleHideBookRequest(request.id)}
                                className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3.5 py-2 text-xs font-semibold text-gray-600 transition-colors hover:border-gray-300 hover:text-gray-800"
                              >
                                <i className="ri-eye-off-line" />
                                Hide
                              </button>
                            ) : null}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#D9C6A5] bg-[#FCFAF6] px-5 py-6 text-sm text-gray-500">
                    {dashboard?.requests.length ? (
                      <div className="space-y-3">
                        <p>All hidden book requests have been removed from this view.</p>
                        <button
                          type="button"
                          onClick={handleShowHiddenRequests}
                          className="inline-flex items-center gap-2 rounded-full border border-[#E9D9BD] bg-white px-4 py-2 text-xs font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                        >
                          <i className="ri-eye-line" />
                          Show Hidden Requests
                        </button>
                      </div>
                    ) : (
                      "No new-book requests yet. Use the support area if there is a title you want the library to consider."
                    )}
                  </div>
                )}
            </div>
          </div>

        </div>
      </section>

      {loanPendingConfirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-[#E9D9BD] bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-[#F3E9DA] px-6 py-5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-600">
                  {loanPendingConfirmation.loanType === "notify" ? "Alert Update" : "Request Update"}
                </p>
                <h3 className="mt-1 text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                  {loanPendingConfirmation.loanType === "notify" ? "Remove this alert?" : "Cancel this request?"}
                </h3>
                <p className="mt-2 text-sm leading-6 text-gray-500">
                  {loanPendingConfirmation.bookTitle}
                </p>
              </div>
              <button
                type="button"
                onClick={closeLoanConfirmation}
                disabled={actingLoanId === loanPendingConfirmation.id}
                className="flex h-10 w-10 items-center justify-center rounded-2xl text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <i className="ri-close-line text-lg" />
              </button>
            </div>

            <div className="px-6 py-6">
              <div className="rounded-2xl border border-amber-100 bg-amber-50/70 px-4 py-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-amber-600 shadow-sm">
                    <i className={loanPendingConfirmation.loanType === "notify" ? "ri-notification-off-line text-lg" : "ri-close-circle-line text-lg"} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-amber-800">
                      {loanPendingConfirmation.loanType === "notify"
                        ? "This availability alert will stop notifying you."
                        : "This request will be marked as cancelled."}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-amber-700">
                      {loanPendingConfirmation.loanType === "notify"
                        ? "You can create a new alert later if you want to follow the book again."
                        : "The record will stay in your activity history, but it will no longer be considered active by the library team."}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-[#F3E9DA] px-6 py-5">
              <button
                type="button"
                onClick={closeLoanConfirmation}
                disabled={actingLoanId === loanPendingConfirmation.id}
                className="rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-600 transition-colors hover:border-gray-300 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Keep It
              </button>
              <button
                type="button"
                onClick={() => void handleCancelLoan()}
                disabled={actingLoanId === loanPendingConfirmation.id}
                className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <i className={actingLoanId === loanPendingConfirmation.id ? "ri-loader-4-line animate-spin" : "ri-check-line"} />
                {actingLoanId === loanPendingConfirmation.id
                  ? "Updating..."
                  : loanPendingConfirmation.loanType === "notify"
                    ? "Remove Alert"
                    : "Cancel Request"}
              </button>
            </div>
          </div>
        </div>
      )}

      {requestPendingConfirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-[#E9D9BD] bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-[#F3E9DA] px-6 py-5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-600">Book Request</p>
                <h3 className="mt-1 text-xl font-bold text-[#241453]" style={{ fontFamily: "'Playfair Display', serif" }}>
                  Cancel this request?
                </h3>
                <p className="mt-2 text-sm leading-6 text-gray-500">
                  {requestPendingConfirmation.bookTitle}
                </p>
              </div>
              <button
                type="button"
                onClick={closeRequestConfirmation}
                disabled={actingRequestId === requestPendingConfirmation.id}
                className="flex h-10 w-10 items-center justify-center rounded-2xl text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <i className="ri-close-line text-lg" />
              </button>
            </div>

            <div className="px-6 py-6">
              <div className="rounded-2xl border border-amber-100 bg-amber-50/70 px-4 py-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-amber-600 shadow-sm">
                    <i className="ri-close-circle-line text-lg" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-amber-800">
                      This book request will be marked as cancelled.
                    </p>
                    <p className="mt-1 text-sm leading-6 text-amber-700">
                      The record will stay in your request history, but the library team will no longer treat it as an active request.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-[#F3E9DA] px-6 py-5">
              <button
                type="button"
                onClick={closeRequestConfirmation}
                disabled={actingRequestId === requestPendingConfirmation.id}
                className="rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-600 transition-colors hover:border-gray-300 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Keep It
              </button>
              <button
                type="button"
                onClick={() => void handleCancelBookRequest()}
                disabled={actingRequestId === requestPendingConfirmation.id}
                className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <i className={actingRequestId === requestPendingConfirmation.id ? "ri-loader-4-line animate-spin" : "ri-check-line"} />
                {actingRequestId === requestPendingConfirmation.id ? "Updating..." : "Cancel Request"}
              </button>
            </div>
          </div>
        </div>
      )}

      <Footer />
    </div>
  );
}
