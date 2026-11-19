import type {
  AuthSession,
  AuthUser,
  BookFeedback,
  BookFeedbackSubmissionPayload,
  BookRequest,
  Category,
  FeedbackContext,
  Loan,
  Resource,
  StudentDashboard,
  StudentProfileUpdatePayload,
  SupportMessage,
} from "../types/library";
import { getDeviceTimeZone } from "./libraryDates";

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "/api";
const GET_CACHE_TTL_MS = 30_000;
const AUTH_TOKEN_KEY = "kbc_auth_token";

type CacheEntry = {
  expiresAt: number;
  value: unknown;
};

type RequestOptions = {
  auth?: "required" | "none" | "optional";
};

const responseCache = new Map<string, CacheEntry>();
const inflightRequests = new Map<string, Promise<unknown>>();
let lastTimezoneObservation: { token: string; zone: string; response: TimezoneObservation } | null = null;
export type TimezoneSyncStatus = "idle" | "saving" | "ready" | "error";
export type LibrarySessionState = {
  user: AuthUser | null;
  timezoneStatus: TimezoneSyncStatus;
  timezoneError: string | null;
};
let sessionState: LibrarySessionState = { user: null, timezoneStatus: "idle", timezoneError: null };
const sessionListeners = new Set<() => void>();
let timezoneOperation = 0;
let preferencePending = false;
let preferenceRetry: { token: string; timeZone: string; source: "manual" | "browser" } | null = null;

export function getLibrarySessionState() { return sessionState; }
export function subscribeLibrarySession(listener: () => void) {
  sessionListeners.add(listener);
  return () => { sessionListeners.delete(listener); };
}
function publishSession(update: Partial<LibrarySessionState>) {
  sessionState = { ...sessionState, ...update };
  sessionListeners.forEach((listener) => listener());
}
function publishUser(user: AuthUser, preserveTimezone = false) {
  const current = sessionState.user;
  // A profile GET started before a successful preference update must not undo it.
  if (current?.username === user.username && current?.email === user.email && current?.timeZoneUpdatedAt &&
      (preserveTimezone || !user.timeZoneUpdatedAt || Date.parse(current.timeZoneUpdatedAt) > Date.parse(user.timeZoneUpdatedAt))) {
    user = { ...user, timeZone: current.timeZone, timeZoneSource: current.timeZoneSource,
      timeZoneUpdatedAt: current.timeZoneUpdatedAt, timeZoneStatus: current.timeZoneStatus };
  }
  publishSession({ user });
}
const TIMEZONE_SAVE_ERROR = "We couldn't confirm your timezone. Your sign-in is still active. Retry or choose your timezone manually.";

async function timezoneRequest<T>(path: string, init: RequestInit): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([
      request<T>(path, { ...init, signal: controller.signal }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => { controller.abort(); reject(new Error(TIMEZONE_SAVE_ERROR)); }, 8000);
      }),
    ]);
  } finally {
    clearTimeout(timer!);
  }
}

export type TimezoneObservation = {
  observedTimeZone: string; savedTimeZone: string | null; saved: boolean;
  status: "saved" | "manual_preserved" | "stale_ignored";
  source: "browser" | "manual"; updatedAt: string;
};

export async function observeAuthenticatedDeviceTimezone({ force = false }: { force?: boolean } = {}): Promise<TimezoneObservation | null> {
  const token = getAuthToken();
  if (!token || preferencePending || preferenceRetry) return null;
  const zone = getDeviceTimeZone();
  if (!force && lastTimezoneObservation?.token === token && lastTimezoneObservation.zone === zone) {
    return lastTimezoneObservation.response;
  }
  const operation = ++timezoneOperation;
  publishSession({ timezoneStatus: "saving", timezoneError: null });
  try {
    if (!zone) throw new Error("Device timezone unavailable");
    const response = await timezoneRequest<TimezoneObservation>("/auth/timezone-observation/", {
      method: "POST", body: JSON.stringify({ timeZone: zone }),
    });
    if (!response.savedTimeZone || !["browser", "manual"].includes(response.source)) {
      throw new Error("No saved timezone was confirmed");
    }
    if (getAuthToken() === token && timezoneOperation === operation) {
      lastTimezoneObservation = { token, zone, response };
      const user = sessionState.user;
      if (user) publishUser({ ...user, timeZone: response.savedTimeZone,
        timeZoneSource: response.source, timeZoneUpdatedAt: response.updatedAt, timeZoneStatus: "valid" });
      publishSession({ timezoneStatus: "ready", timezoneError: null });
      invalidateCache("/auth/me/");
      invalidateCache("/auth/dashboard/");
    }
    return response;
  } catch {
    if (getAuthToken() === token && timezoneOperation === operation) {
      publishSession({ timezoneStatus: "error", timezoneError: TIMEZONE_SAVE_ERROR });
    }
    throw new Error(TIMEZONE_SAVE_ERROR);
  }
}

function cacheKey(path: string) {
  return `${API_BASE}${path}`;
}

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function hasStoredAuthToken() {
  return Boolean(getAuthToken());
}

function setAuthToken(token: string | null) {
  if (getAuthToken() !== token || token === null) {
    timezoneOperation++;
    preferencePending = false;
    preferenceRetry = null;
    lastTimezoneObservation = null;
    invalidateCache();
    publishSession({ user: null, timezoneStatus: "idle", timezoneError: null });
  }
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearStoredAuthToken() {
  setAuthToken(null);
  publishSession({ user: null, timezoneStatus: "idle", timezoneError: null });
}

export async function retryTimezoneSave(): Promise<void> {
  if (preferenceRetry && preferenceRetry.token === getAuthToken()) {
    await api.setMyTimezone(preferenceRetry.timeZone, preferenceRetry.source);
  } else {
    await observeAuthenticatedDeviceTimezone({ force: true });
  }
}

function isGetRequest(init?: RequestInit) {
  return !init?.method || init.method.toUpperCase() === "GET";
}

function invalidateCache(pathStartsWith?: string) {
  if (!pathStartsWith) {
    responseCache.clear();
    inflightRequests.clear();
    return;
  }

  for (const key of [...responseCache.keys()]) {
    if (key.includes(pathStartsWith)) {
      responseCache.delete(key);
    }
  }

  for (const key of [...inflightRequests.keys()]) {
    if (key.includes(pathStartsWith)) {
      inflightRequests.delete(key);
    }
  }
}

async function request<T>(path: string, init?: RequestInit, options?: RequestOptions): Promise<T> {
  const url = `${API_BASE}${path}`;
  const useCache = isGetRequest(init) && init?.cache !== "no-store";
  const authMode = options?.auth ?? "required";

  if (useCache) {
    const cached = responseCache.get(url);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value as T;
    }

    const pending = inflightRequests.get(url);
    if (pending) {
      return pending as Promise<T>;
    }
  }

  const promise = (async () => {
    const authToken = getAuthToken();
    const headers = new Headers(init?.headers ?? {});
    const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;

    if (!isFormData && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (authMode !== "none" && authToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Token ${authToken}`);
    }

    const response = await fetch(url, {
      ...init,
      headers,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed with ${response.status}`);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const data = (await response.json()) as T;

    if (useCache) {
      responseCache.set(url, {
        expiresAt: Date.now() + GET_CACHE_TTL_MS,
        value: data,
      });
    }

    return data;
  })();

  if (useCache) {
    inflightRequests.set(url, promise);
  }

  try {
    return await promise;
  } finally {
    if (useCache) {
      inflightRequests.delete(url);
    }
  }
}

export const api = {
  loginAdmin: async (identifier: string, password: string) => {
    const session = await request<AuthSession>("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ identifier, password }),
    }, { auth: "none" });
    setAuthToken(session.token);
    publishUser(session.user);
    await observeAuthenticatedDeviceTimezone({ force: true }).catch(() => null);
    return { ...session, user: getAuthToken() === session.token ? sessionState.user! : session.user };
  },
  loginStudent: async (email: string) => {
    const session = await request<AuthSession>("/auth/student-login/", {
      method: "POST",
      body: JSON.stringify({ email }),
    }, { auth: "none" });
    setAuthToken(session.token);
    publishUser(session.user);
    await observeAuthenticatedDeviceTimezone({ force: true }).catch(() => null);
    return { ...session, user: getAuthToken() === session.token ? sessionState.user! : session.user };
  },
  getAuthMe: async () => {
    const token = getAuthToken();
    const timezoneAtStart = timezoneOperation;
    let session: { user: AuthUser };
    try {
      session = await request<{ user: AuthUser }>("/auth/me/", { cache: "no-store" });
    } catch (error) {
      if (getAuthToken() !== token) return { user: sessionState.user };
      throw error;
    }
    if (getAuthToken() !== token) return { user: sessionState.user };
    publishUser(session.user, timezoneAtStart !== timezoneOperation);
    await observeAuthenticatedDeviceTimezone({ force: true }).catch(() => null);
    return { ...session, user: sessionState.user };
  },
  getStudentDashboard: () => request<StudentDashboard>("/auth/dashboard/"),
  setMyTimezone: async (timeZone: string, source: "manual" | "browser") => {
    const token = getAuthToken();
    if (!token) throw new Error("Please sign in before choosing a timezone.");
    const operation = ++timezoneOperation;
    preferencePending = true;
    preferenceRetry = { token, timeZone, source };
    publishSession({ timezoneStatus: "saving", timezoneError: null });
    try {
      const result = await timezoneRequest<{ user: AuthUser; status: string }>("/auth/timezone-preference/", {
        method: "PUT", body: JSON.stringify({ timeZone, source }),
      });
      if (!result.user.timeZone || !["manual", "browser"].includes(result.user.timeZoneSource || "")) {
        throw new Error("No saved timezone was confirmed");
      }
      if (getAuthToken() !== token || timezoneOperation !== operation) throw new Error("Session changed");
      publishUser(result.user);
      publishSession({ timezoneStatus: "ready", timezoneError: null });
      preferenceRetry = null;
      lastTimezoneObservation = null;
      invalidateCache("/auth/me/");
      invalidateCache("/auth/dashboard/");
      return result;
    } catch {
      if (getAuthToken() === token && timezoneOperation === operation) {
        publishSession({ timezoneStatus: "error", timezoneError: "We couldn't confirm this timezone change. Check the IANA name and retry. The timezone shown is the last setting confirmed by the library." });
      }
      throw new Error("Timezone preference was not confirmed. Please retry.");
    } finally {
      if (timezoneOperation === operation) preferencePending = false;
    }
  },
  updateMyProfile: async (payload: StudentProfileUpdatePayload) => {
    const token = getAuthToken();
    const timezoneAtStart = timezoneOperation;
    const response = await request<{ user: AuthUser }>("/auth/me/", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    if (token === getAuthToken()) publishUser(response.user, timezoneAtStart !== timezoneOperation);
    invalidateCache("/auth/me/");
    invalidateCache("/auth/dashboard/");
    return response;
  },
  logoutAdmin: async () => {
    try {
      await request<void>("/auth/logout/", {
        method: "POST",
      });
    } finally {
      setAuthToken(null);
      lastTimezoneObservation = null;
      invalidateCache();
    }
  },
  listCategories: () => request<Category[]>("/categories/", undefined, { auth: "none" }),
  createCategory: async (payload: Pick<Category, "name"> & Partial<Pick<Category, "description" | "color" | "icon" | "slug">>) => {
    const created = await request<Category>("/categories/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    invalidateCache("/categories/");
    invalidateCache("/resources/");
    return created;
  },
  updateCategory: async (id: number, payload: Partial<Pick<Category, "name" | "description" | "color" | "icon" | "slug">>) => {
    const updated = await request<Category>(`/categories/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/categories/");
    invalidateCache("/resources/");
    return updated;
  },
  deleteCategory: async (id: number) => {
    await request<void>(`/categories/${id}/`, {
      method: "DELETE",
    });
    invalidateCache("/categories/");
    invalidateCache("/resources/");
  },
  listResources: () => request<Resource[]>("/resources/", undefined, { auth: "none" }),
  getFeedbackContext: (token: string) =>
    request<FeedbackContext>(`/feedback/context/?token=${encodeURIComponent(token)}`, undefined, { auth: "none" }),
  submitFeedback: async (payload: BookFeedbackSubmissionPayload) => {
    const created = await request<BookFeedback>("/feedback/", {
      method: "POST",
      body: JSON.stringify(payload),
    }, { auth: "none" });
    invalidateCache("/feedback/");
    invalidateCache("/resources/");
    return created;
  },
  createResource: async (payload: Omit<Resource, "id">) => {
    const created = await request<Resource>("/resources/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    invalidateCache("/resources/");
    invalidateCache("/categories/");
    return created;
  },
  updateResource: async (id: string, payload: Partial<Resource>) => {
    const updated = await request<Resource>(`/resources/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/resources/");
    invalidateCache("/categories/");
    return updated;
  },
  deleteResource: async (id: string) => {
    await request<void>(`/resources/${id}/`, {
      method: "DELETE",
    });
    invalidateCache("/resources/");
    invalidateCache("/categories/");
  },
  listRequests: () => request<BookRequest[]>("/requests/"),
  createRequest: async (payload: Omit<BookRequest, "id" | "submittedAt" | "status">) => {
    const created = await request<BookRequest>("/requests/", {
      method: "POST",
      body: JSON.stringify(payload),
    }, { auth: "optional" });
    invalidateCache("/requests/");
    invalidateCache("/auth/dashboard/");
    return created;
  },
  updateRequest: async (id: string, payload: Partial<BookRequest>) => {
    const updated = await request<BookRequest>(`/requests/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/requests/");
    return updated;
  },
  cancelStudentRequest: async (id: string) => {
    const updated = await request<BookRequest>(`/requests/${id}/student-cancel/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    invalidateCache("/requests/");
    invalidateCache("/auth/dashboard/");
    return updated;
  },
  deleteRequest: async (id: string) => {
    await request<void>(`/requests/${id}/`, {
      method: "DELETE",
    });
    invalidateCache("/requests/");
  },
  listLoans: () => request<Loan[]>("/loans/"),
  createLoan: async (payload: Partial<Loan>) => {
    const created = await request<Loan>("/loans/", {
      method: "POST",
      body: JSON.stringify(payload),
    }, { auth: "required" });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    invalidateCache("/auth/dashboard/");
    return created;
  },
  updateLoan: async (id: string, payload: Partial<Loan>, options?: { returnEvidenceFile?: File | null }) => {
    const evidenceFile = options?.returnEvidenceFile ?? null;

    const updated = await request<Loan>(`/loans/${id}/`, evidenceFile ? {
      method: "PATCH",
      body: (() => {
        const formData = new FormData();
        Object.entries(payload).forEach(([key, value]) => {
          if (value === undefined || value === null) {
            return;
          }
          formData.append(key, String(value));
        });
        formData.append("returnEvidence", evidenceFile);
        return formData;
      })(),
    } : {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    invalidateCache("/auth/dashboard/");
    return updated;
  },
  cancelStudentLoan: async (id: string) => {
    const updated = await request<Loan>(`/loans/${id}/student-cancel/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    invalidateCache("/auth/dashboard/");
    return updated;
  },
  previewLoanReturnDate: (id: string, deliveryDays: number) =>
    request<{ dueDate: string }>(`/loans/${id}/return-date-preview/?deliveryDays=${deliveryDays}`, { cache: "no-store" }),
  approveLoan: async (id: string, deliveryDays: number) => {
    const approved = await request<Loan>(`/loans/${id}/approve/`, {
      method: "POST",
      body: JSON.stringify({ deliveryDays }),
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    invalidateCache("/auth/dashboard/");
    return approved;
  },
  deleteLoan: async (id: string) => {
    await request<void>(`/loans/${id}/`, {
      method: "DELETE",
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
  },
  listSupportMessages: () => request<SupportMessage[]>("/support-messages/"),
  createSupportMessage: async (payload: Omit<SupportMessage, "id" | "submittedAt" | "status" | "resolvedAt" | "resolvedById" | "requesterId">) => {
    const created = await request<SupportMessage>("/support-messages/", {
      method: "POST",
      body: JSON.stringify(payload),
    }, { auth: "optional" });
    invalidateCache("/support-messages/");
    invalidateCache("/auth/dashboard/");
    return created;
  },
  updateSupportMessage: async (id: string, payload: Partial<SupportMessage>) => {
    const updated = await request<SupportMessage>(`/support-messages/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/support-messages/");
    return updated;
  },
  deleteSupportMessage: async (id: string) => {
    await request<void>(`/support-messages/${id}/`, {
      method: "DELETE",
    });
    invalidateCache("/support-messages/");
  },
};
