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
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearStoredAuthToken() {
  setAuthToken(null);
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
  const useCache = isGetRequest(init);
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
    return session;
  },
  loginStudent: async (email: string) => {
    const session = await request<AuthSession>("/auth/student-login/", {
      method: "POST",
      body: JSON.stringify({ email }),
    }, { auth: "none" });
    setAuthToken(session.token);
    return session;
  },
  getAuthMe: () => request<{ user: AuthUser }>("/auth/me/"),
  getStudentDashboard: () => request<StudentDashboard>("/auth/dashboard/"),
  updateMyProfile: (payload: StudentProfileUpdatePayload) =>
    request<{ user: AuthUser }>("/auth/me/", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }).then((response) => {
      invalidateCache("/auth/me/");
      invalidateCache("/auth/dashboard/");
      return response;
    }),
  logoutAdmin: async () => {
    try {
      await request<void>("/auth/logout/", {
        method: "POST",
      });
    } finally {
      setAuthToken(null);
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
  approveLoan: async (id: string) => {
    const approved = await request<Loan>(`/loans/${id}/approve/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
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
