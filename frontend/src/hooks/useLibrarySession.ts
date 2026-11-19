import {
  createElement,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { api, clearStoredAuthToken, hasStoredAuthToken, observeAuthenticatedDeviceTimezone,
  getLibrarySessionState, subscribeLibrarySession, retryTimezoneSave, type TimezoneSyncStatus } from "../lib/api";
import { getDeviceTimeZone } from "../lib/libraryDates";
import type { AuthSession, AuthUser, StudentProfileUpdatePayload } from "../types/library";

interface LibrarySessionContextValue {
  user: AuthUser | null;
  loading: boolean;
  deviceTimeZone: string | null;
  timezoneStatus: TimezoneSyncStatus;
  timezoneError: string | null;
  retryTimezone: () => Promise<void>;
  setTimezone: (timeZone: string, source: "manual" | "browser") => Promise<void>;
  loginStudent: (email: string) => Promise<AuthSession>;
  refreshSession: () => Promise<AuthUser | null>;
  updateProfile: (payload: StudentProfileUpdatePayload) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const LibrarySessionContext = createContext<LibrarySessionContextValue | null>(null);

export function LibrarySessionProvider({ children }: { children: ReactNode }) {
  const { user, timezoneStatus, timezoneError } = useSyncExternalStore(
    subscribeLibrarySession, getLibrarySessionState, getLibrarySessionState,
  );
  const [loading, setLoading] = useState(true);
  const [deviceTimeZone, setDeviceTimeZone] = useState(getDeviceTimeZone);

  useEffect(() => {
    const observe = (event?: Event) => {
      setDeviceTimeZone(getDeviceTimeZone());
      if (document.visibilityState !== "hidden") void observeAuthenticatedDeviceTimezone({ force: Boolean(event) }).catch(() => null);
    };
    window.addEventListener("focus", observe);
    document.addEventListener("visibilitychange", observe);
    const interval = window.setInterval(observe, 60_000);
    return () => {
      window.removeEventListener("focus", observe);
      document.removeEventListener("visibilitychange", observe);
      window.clearInterval(interval);
    };
  }, []);

  const refreshSession = useCallback(async () => {
    if (!hasStoredAuthToken()) {
      setLoading(false);
      return null;
    }

    try {
      const session = await api.getAuthMe();
      return session.user;
    } catch {
      clearStoredAuthToken();
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const loginStudent = useCallback(async (email: string) => {
    const session = await api.loginStudent(email);
    return session;
  }, []);

  const updateProfile = useCallback(async (payload: StudentProfileUpdatePayload) => {
    const response = await api.updateMyProfile(payload);
    return response.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logoutAdmin();
    } finally {
      clearStoredAuthToken();
    }
  }, []);

  const retryTimezone = useCallback(async () => { await retryTimezoneSave(); }, []);
  const setTimezone = useCallback(async (timeZone: string, source: "manual" | "browser") => {
    await api.setMyTimezone(timeZone, source);
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    deviceTimeZone,
    timezoneStatus,
    timezoneError,
    retryTimezone,
    setTimezone,
    loginStudent,
    refreshSession,
    updateProfile,
    logout,
  }), [deviceTimeZone, loading, loginStudent, logout, refreshSession, updateProfile, user,
    timezoneStatus, timezoneError, retryTimezone, setTimezone]);

  return createElement(LibrarySessionContext.Provider, { value }, children);
}

export function useLibrarySession() {
  const context = useContext(LibrarySessionContext);
  if (!context) {
    throw new Error("useLibrarySession must be used within LibrarySessionProvider");
  }
  return context;
}

export function useDeviceTimezone() {
  return useLibrarySession().deviceTimeZone;
}
