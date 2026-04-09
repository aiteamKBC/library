import type { AuthSession, AuthUser, BookRequest, Category, Loan, Resource, SupportMessage } from "../types/library";

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "/api";
const GET_CACHE_TTL_MS = 30_000;
const AUTH_TOKEN_KEY = "kbc_auth_token";

type CacheEntry = {
  expiresAt: number;
  value: unknown;
};

const responseCache = new Map<string, CacheEntry>();
const inflightRequests = new Map<string, Promise<unknown>>();

function cacheKey(path: string) {
  return `${API_BASE}${path}`;
}

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function setAuthToken(token: string | null) {
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_KEY, token);
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const useCache = isGetRequest(init);

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
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(getAuthToken() ? { Authorization: `Token ${getAuthToken()}` } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
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
    });
    setAuthToken(session.token);
    return session;
  },
  getAuthMe: () => request<{ user: AuthUser }>("/auth/me/"),
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
  listCategories: () => request<Category[]>("/categories/"),
  listResources: () => request<Resource[]>("/resources/"),
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
    });
    invalidateCache("/requests/");
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
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    return created;
  },
  updateLoan: async (id: string, payload: Partial<Loan>) => {
    const updated = await request<Loan>(`/loans/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    invalidateCache("/loans/");
    invalidateCache("/resources/");
    return updated;
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
    });
    invalidateCache("/support-messages/");
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
