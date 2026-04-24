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
  edition?: string;
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
  inventoryCount?: number;
  totalCopies?: number;
  availableCopies?: number;
  borrowableCopies?: number;
  pendingBorrowRequests?: number;
  queueFull?: boolean;
  availabilityStatus?: "available" | "reserved" | "borrowed" | "lost" | "maintenance";
  availabilityLabel?: string;
  expectedAvailableDate?: string | null;
  availabilityNote?: string;
  canBorrow?: boolean;
  canReserve?: boolean;
  feedbackCount?: number;
  feedbackAverageRating?: number | null;
  feedbackRecommendCount?: number;
  feedbackLearnedCount?: number;
  feedbackRecommendRate?: number;
  feedbackLearnedRate?: number;
}

export interface BookRequest {
  id: string;
  requesterId?: number | null;
  resourceId?: string | null;
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
  status: "pending" | "approved" | "rejected" | "ordered" | "cancelled";
  reviewedById?: number | null;
  reviewNotes?: string;
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
  returnCondition?: "good" | "worn" | "damaged" | "torn" | null;
  returnConditionNotes?: string;
  returnEvidence?: string | null;
  returnEvidenceName?: string | null;
  notes?: string;
}

export interface BookFeedback {
  id: string;
  loanId: string;
  resourceId: string;
  borrowerId?: number | null;
  borrowerName?: string;
  borrowerEmail?: string;
  learnedSomething: "yes" | "somewhat" | "no";
  wouldRecommend: "yes" | "maybe" | "no";
  contentQuality: "excellent" | "good" | "fair" | "poor";
  starRating: number;
  comment?: string;
  submittedAt: string;
}

export interface FeedbackContext {
  loanId: string;
  resourceId?: string;
  bookTitle: string;
  borrowerName?: string;
  returnedAt?: string | null;
  alreadySubmitted: boolean;
  feedback?: BookFeedback | null;
}

export interface BookFeedbackSubmissionPayload {
  token: string;
  learnedSomething: "yes" | "somewhat" | "no";
  wouldRecommend: "yes" | "maybe" | "no";
  contentQuality: "excellent" | "good" | "fair" | "poor";
  starRating: number;
  comment?: string;
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

export interface StudentProfileUpdatePayload {
  fullName: string;
  phoneNumber?: string;
  studentIdCode?: string;
}

export interface StudentDashboard {
  user: AuthUser;
  loans: Loan[];
  requests: BookRequest[];
  supportMessages: SupportMessage[];
}
