export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string;
  color: string;
  icon: string;
  resourceCount: number;
}

export interface Resource {
  id: string;
  title: string;
  category: string;
  categoryId: string;
  author: string;
  publisher?: string;
  publicationYear?: string;
  pageCount?: number;
  isbn13?: string;
  isbn10?: string;
  coverImage?: string;
  infoLink?: string;
  description?: string;
  type?: "Book" | "Article" | "Guide" | "Journal" | "Video" | "Template";
  level?: string;
  dateAdded?: string;
  featured?: boolean;
  popular?: boolean;
  coverColor?: string;
  totalCopies?: number;
  availableCopies?: number;
  availabilityStatus?: "available" | "reserved" | "borrowed" | "lost" | "maintenance";
  availabilityLabel?: string;
  expectedAvailableDate?: string | null;
  availabilityNote?: string;
  canBorrow?: boolean;
  canReserve?: boolean;
}

export interface BookRequest {
  id: string;
  studentName: string;
  studentEmail: string;
  studentPhone?: string;
  studentId?: string;
  bookTitle: string;
  reason: string;
  category: string;
  neededFrom?: string;
  neededUntil?: string;
  submittedAt: string;
  status: "pending" | "approved" | "rejected";
}

export interface SupportMessage {
  id: string;
  requesterId?: number | null;
  fullName: string;
  email: string;
  course?: string;
  subject: string;
  message: string;
  status: "new" | "in_progress" | "resolved";
  submittedAt: string;
  resolvedAt?: string | null;
  resolvedById?: number | null;
  internalNotes?: string;
}

export interface Loan {
  id: string;
  borrowerId?: number | null;
  borrowerName?: string;
  borrowerEmail?: string;
  borrowerPhone?: string;
  borrowerStudentId?: string;
  approvedById?: number | null;
  bookCopyId?: number;
  resourceId?: string;    // read-only: book_copy.resource_id
  requestedFrom?: string | null;
  loanType?: "borrow" | "notify";
  bookTitle: string;
  accessionNumber: string;
  availabilityStatus?: "available" | "reserved" | "borrowed" | "lost" | "maintenance";
  status: "requested" | "reserved" | "approved" | "borrowed" | "returned" | "notify" | "overdue" | "cancelled";
  requestedAt: string;
  approvedAt?: string | null;
  borrowedAt?: string | null;
  dueDate?: string | null;
  returnedAt?: string | null;
  notes?: string;
}

export interface AuthUser {
  username: string;
  email: string;
  fullName: string;
  role: "student" | "librarian" | "admin";
  phone_number?: string;
  student_id_code?: string;
}

export interface AuthSession {
  token: string;
  user: AuthUser;
  next?: string;
}
