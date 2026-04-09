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
import { api } from "../lib/api";
import type { BookRequest, Category, Loan, Resource, SupportMessage } from "../types/library";

interface AdminDataContextValue {
  categories: Category[];
  books: Resource[];
  requests: BookRequest[];
  loans: Loan[];
  supportMessages: SupportMessage[];
  loading: boolean;
  adminLoading: boolean;
  adminLoaded: boolean;
  usingFallbackData: boolean;
  loadAdminData: () => Promise<void>;
  addBook: (book: Omit<Resource, "id">) => Promise<Resource>;
  updateBook: (id: string, updates: Partial<Resource>) => Promise<void>;
  deleteBook: (id: string) => Promise<void>;
  addRequest: (req: Omit<BookRequest, "id" | "submittedAt" | "status">) => Promise<void>;
  updateRequestStatus: (id: string, status: BookRequest["status"]) => Promise<void>;
  deleteRequest: (id: string) => Promise<void>;
  addLoan: (loan: Partial<Loan>) => Promise<Loan>;
  updateLoan: (id: string, updates: Partial<Loan>) => Promise<void>;
  deleteLoan: (id: string) => Promise<void>;
  addSupportMessage: (message: Omit<SupportMessage, "id" | "submittedAt" | "status" | "resolvedAt" | "resolvedById" | "requesterId">) => Promise<void>;
  updateSupportMessage: (id: string, updates: Partial<SupportMessage>) => Promise<void>;
  deleteSupportMessage: (id: string) => Promise<void>;
}

const AdminDataContext = createContext<AdminDataContextValue | null>(null);

export function AdminDataProvider({ children }: { children: ReactNode }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [books, setBooks] = useState<Resource[]>([]);
  const [requests, setRequests] = useState<BookRequest[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [supportMessages, setSupportMessages] = useState<SupportMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminLoaded, setAdminLoaded] = useState(false);
  const [usingFallbackData, setUsingFallbackData] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [categoryData, resourceData] = await Promise.all([
          api.listCategories(),
          api.listResources(),
        ]);

        if (cancelled) return;
        setCategories(categoryData);
        setBooks(resourceData);
        setUsingFallbackData(false);
      } catch {
        if (cancelled) return;
        setCategories([]);
        setBooks([]);
        setUsingFallbackData(false);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  const loadAdminData = useCallback(async () => {
    if (adminLoading || adminLoaded) return;
    setAdminLoading(true);
    try {
      const [requestData, loanData, supportData] = await Promise.all([
        api.listRequests(),
        api.listLoans(),
        api.listSupportMessages(),
      ]);
      setRequests(requestData);
      setLoans(loanData);
      setSupportMessages(supportData);
      setAdminLoaded(true);
    } finally {
      setAdminLoading(false);
    }
  }, [adminLoaded, adminLoading]);

  const addBook = useCallback(async (book: Omit<Resource, "id">) => {
    const created = await api.createResource(book);
    setBooks((prev) => [created, ...prev]);
    return created;
  }, [usingFallbackData]);

  const updateBook = useCallback(async (id: string, updates: Partial<Resource>) => {
    const updated = await api.updateResource(id, updates);
    setBooks((prev) => prev.map((b) => (b.id === id ? updated : b)));
  }, []);

  const deleteBook = useCallback(async (id: string) => {
    await api.deleteResource(id);
    setBooks((prev) => prev.filter((b) => b.id !== id));
  }, []);

  const addRequest = useCallback(async (req: Omit<BookRequest, "id" | "submittedAt" | "status">) => {
    const created = await api.createRequest(req);
    setRequests((prev) => [created, ...prev]);
  }, []);

  const updateRequestStatus = useCallback(async (id: string, status: BookRequest["status"]) => {
    const updated = await api.updateRequest(id, { status });
    setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)));
  }, []);

  const deleteRequest = useCallback(async (id: string) => {
    await api.deleteRequest(id);
    setRequests((prev) => prev.filter((r) => r.id !== id));
  }, []);

  const addLoan = useCallback(async (loan: Partial<Loan>) => {
    const created = await api.createLoan(loan);
    setLoans((prev) => [created, ...prev]);
    const resources = await api.listResources();
    setBooks(resources);
    return created;
  }, []);

  const updateLoan = useCallback(async (id: string, updates: Partial<Loan>) => {
    const updated = await api.updateLoan(id, updates);
    setLoans((prev) => prev.map((loan) => (loan.id === id ? updated : loan)));
    const resources = await api.listResources();
    setBooks(resources);
  }, []);

  const deleteLoan = useCallback(async (id: string) => {
    await api.deleteLoan(id);
    setLoans((prev) => prev.filter((loan) => loan.id !== id));
    const resources = await api.listResources();
    setBooks(resources);
  }, []);

  const addSupportMessage = useCallback(async (message: Omit<SupportMessage, "id" | "submittedAt" | "status" | "resolvedAt" | "resolvedById" | "requesterId">) => {
    const created = await api.createSupportMessage(message);
    setSupportMessages((prev) => [created, ...prev]);
  }, []);

  const updateSupportMessage = useCallback(async (id: string, updates: Partial<SupportMessage>) => {
    const updated = await api.updateSupportMessage(id, updates);
    setSupportMessages((prev) => prev.map((message) => (message.id === id ? updated : message)));
  }, []);

  const deleteSupportMessage = useCallback(async (id: string) => {
    await api.deleteSupportMessage(id);
    setSupportMessages((prev) => prev.filter((message) => message.id !== id));
  }, []);

  const value = useMemo(() => ({
    categories,
    books,
    requests,
    loans,
    supportMessages,
    loading,
    adminLoading,
    adminLoaded,
    usingFallbackData,
    loadAdminData,
    addBook,
    updateBook,
    deleteBook,
    addRequest,
    updateRequestStatus,
    deleteRequest,
    addLoan,
    updateLoan,
    deleteLoan,
    addSupportMessage,
    updateSupportMessage,
    deleteSupportMessage,
  }), [
    addBook,
    addLoan,
    addRequest,
    adminLoading,
    adminLoaded,
    categories,
    books,
    deleteBook,
    deleteLoan,
    deleteRequest,
    loadAdminData,
    loading,
    loans,
    supportMessages,
    requests,
    updateBook,
    updateLoan,
    updateRequestStatus,
    updateSupportMessage,
    usingFallbackData,
    addSupportMessage,
    deleteSupportMessage,
  ]);

  return createElement(AdminDataContext.Provider, { value }, children);
}

export function useAdminData() {
  const context = useContext(AdminDataContext);

  if (!context) {
    throw new Error("useAdminData must be used within AdminDataProvider");
  }

  return context;
}
