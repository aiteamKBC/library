import {
  createElement,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, clearStoredAuthToken, hasStoredAuthToken } from "../lib/api";
import type { AuthSession, AuthUser, StudentProfileUpdatePayload, StudentRegistrationPayload } from "../types/library";

interface LibrarySessionContextValue {
  user: AuthUser | null;
  loading: boolean;
  loginStudent: (identifier: string, password: string) => Promise<AuthSession>;
  registerStudent: (payload: StudentRegistrationPayload) => Promise<AuthSession>;
  refreshSession: () => Promise<AuthUser | null>;
  updateProfile: (payload: StudentProfileUpdatePayload) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const LibrarySessionContext = createContext<LibrarySessionContextValue | null>(null);

export function LibrarySessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshSession = useCallback(async () => {
    if (!hasStoredAuthToken()) {
      setUser(null);
      setLoading(false);
      return null;
    }

    try {
      const session = await api.getAuthMe();
      setUser(session.user);
      return session.user;
    } catch {
      clearStoredAuthToken();
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const loginStudent = useCallback(async (identifier: string, password: string) => {
    const session = await api.loginStudent(identifier, password);
    setUser(session.user);
    return session;
  }, []);

  const registerStudent = useCallback(async (payload: StudentRegistrationPayload) => {
    const session = await api.registerStudent(payload);
    setUser(session.user);
    return session;
  }, []);

  const updateProfile = useCallback(async (payload: StudentProfileUpdatePayload) => {
    const response = await api.updateMyProfile(payload);
    setUser(response.user);
    return response.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logoutAdmin();
    } finally {
      clearStoredAuthToken();
      setUser(null);
    }
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    loginStudent,
    registerStudent,
    refreshSession,
    updateProfile,
    logout,
  }), [loading, loginStudent, logout, refreshSession, registerStudent, updateProfile, user]);

  return createElement(LibrarySessionContext.Provider, { value }, children);
}

export function useLibrarySession() {
  const context = useContext(LibrarySessionContext);
  if (!context) {
    throw new Error("useLibrarySession must be used within LibrarySessionProvider");
  }
  return context;
}
