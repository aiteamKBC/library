import { useEffect, useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Loan } from "../../../types/library";

const HISTORY_TABS = [
  {
    id: "transactions",
    label: "Transactions",
    icon: "ri-history-line",
    description: "Every returned loan record, copy by copy.",
    defaultSort: "newest",
    searchPlaceholder: "Search transactions by title, borrower, email, phone, copy number, condition, note, or record ID...",
  },
  {
    id: "students",
    label: "Students",
    icon: "ri-user-3-line",
    description: "Borrowing history grouped by student account.",
    defaultSort: "all",
    searchPlaceholder: "Search students by name, email, phone, student ID, or last returned title...",
  },
  {
    id: "books",
    label: "Books",
    icon: "ri-book-2-line",
    description: "Borrowing history grouped by title and inventory.",
    defaultSort: "most-returned",
    searchPlaceholder: "Search books by title, author, copy number, or latest borrower...",
  },
] as const;

const HISTORY_SORT_OPTIONS = {
  transactions: [
    { value: "newest", label: "Latest returns" },
    { value: "oldest", label: "Oldest returns" },
    { value: "title", label: "Title A-Z" },
  ],
  students: [
    { value: "all", label: "All borrowers" },
    { value: "late-returns", label: "Late returns" },
    { value: "damaged-last-returned", label: "Damaged & needs repair" },
  ],
  books: [
    { value: "most-returned", label: "Most returned" },
    { value: "recent", label: "Latest title activity" },
    { value: "title", label: "Title A-Z" },
  ],
} as const;

const OPEN_HISTORY_STATUSES = new Set<Loan["status"]>(["requested", "approved", "reserved", "borrowed", "overdue"]);

type HistoryTab = (typeof HISTORY_TABS)[number]["id"];

type StudentHistoryTitleSummary = {
  key: string;
  title: string;
  totalReturns: number;
  lateReturnCount: number;
  lastReturnedAt?: string | null;
  latestDueDate?: string | null;
  latestCopyNumber: string;
  latestReturnCondition?: Loan["returnCondition"];
  latestReturnedLate?: boolean;
  latestDaysLate?: number;
  latestReturnEvidence?: string | null;
  latestReturnEvidenceName?: string | null;
};

type StudentHistoryRow = {
  key: string;
  borrowerName: string;
  borrowerEmail: string;
  borrowerPhone: string;
  borrowerStudentId: string;
  totalReturns: number;
  uniqueTitles: number;
  openItems: number;
  lateReturns: number;
  conditionFlags: number;
  lastBookTitle: string;
  lastReturnedAt?: string | null;
  lastReturnCondition?: Loan["returnCondition"];
  titles: StudentHistoryTitleSummary[];
};

type BookHistoryRow = {
  key: string;
  resourceId?: string;
  bookTitle: string;
  author: string;
  totalReturns: number;
  uniqueBorrowers: number;
  copiesUsed: number;
  lateReturns: number;
  damagedOrRepairReturns: number;
  latestBorrower: string;
  latestCopyNumber: string;
  lastReturnedAt?: string | null;
  latestDueDate?: string | null;
  latestReturnCondition?: Loan["returnCondition"];
  latestReturnedLate?: boolean;
  latestDaysLate?: number;
  totalCopies: number;
  availableCopies: number;
};

type PdfExportStudentBook = {
  title: string;
  totalReturns: number;
  returnStatus: string;
  condition: string;
  returnedAt: string;
  dueDate: string;
  copyNumber: string;
};

type PdfExportRecord = {
  title: string;
  lines: string[];
  studentBooks?: PdfExportStudentBook[];
};

function formatDate(date?: string | null) {
  if (!date) return "-";
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function normalizeText(value?: string | null) {
  return (value ?? "").trim().toLowerCase();
}

function escapePdfText(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[^\x20-\x7E]/g, "?")
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
    .replace(/\r?\n/g, " ");
}

function wrapPdfText(value: string, maxChars: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return [""];

  const words = normalized.split(" ");
  const lines: string[] = [];
  let current = "";

  words.forEach((word) => {
    if (!current) {
      current = word;
      return;
    }

    if (`${current} ${word}`.length <= maxChars) {
      current = `${current} ${word}`;
      return;
    }

    lines.push(current);
    current = word;
  });

  if (current) {
    lines.push(current);
  }

  return lines;
}

function splitPdfField(line: string) {
  const separatorIndex = line.indexOf(":");
  if (separatorIndex === -1) {
    return {
      label: "Detail",
      value: line.trim() || "-",
    };
  }

  return {
    label: line.slice(0, separatorIndex).trim() || "Detail",
    value: line.slice(separatorIndex + 1).trim() || "-",
  };
}

function buildPdfBlob(values: {
  title: string;
  summaryLines: string[];
  records: PdfExportRecord[];
}) {
  const pageWidth = 595.28;
  const pageHeight = 841.89;
  const marginX = 34;
  const bottomMargin = 34;
  const titleSize = 22;
  const bodySize = 10;
  const bodyLineHeight = 12;
  const cardPadding = 16;
  const summaryFields = values.summaryLines.map(splitPdfField);
  const summaryMap = new Map(summaryFields.map((field) => [field.label.toLowerCase(), field.value]));

  const palette = {
    purple: [68, 47, 115],
    purpleDark: [36, 20, 83],
    purpleSoft: [244, 239, 252],
    purpleSurface: [251, 248, 255],
    gold: [206, 168, 105],
    goldSoft: [252, 250, 246],
    border: [233, 217, 189],
    ink: [32, 35, 45],
    muted: [126, 120, 144],
    line: [226, 221, 235],
    white: [255, 255, 255],
    emerald: [40, 146, 96],
    emeraldSoft: [234, 247, 239],
    rose: [191, 75, 75],
    roseSoft: [254, 239, 239],
    orange: [201, 121, 49],
    orangeSoft: [255, 245, 235],
    slate: [94, 104, 122],
    shadow: [236, 232, 244],
  } as const;

  const pageContents: string[] = [];
  let currentPageCommands: string[] = [];
  let pageNumber = 0;
  let y = 0;

  const rgb = (color: readonly number[]) => color.map((value) => (value / 255).toFixed(3)).join(" ");
  const estimateTextWidth = (text: string, fontSize: number, bold = false) => text.length * fontSize * (bold ? 0.58 : 0.52);

  const addRect = (x: number, yPosition: number, width: number, height: number, options: {
    fill?: readonly number[];
    stroke?: readonly number[];
    lineWidth?: number;
  } = {}) => {
    const commands: string[] = [];

    if (options.fill) {
      commands.push(`${rgb(options.fill)} rg`);
    }
    if (options.stroke) {
      commands.push(`${rgb(options.stroke)} RG`);
      commands.push(`${(options.lineWidth ?? 1).toFixed(2)} w`);
    }

    commands.push(`${x.toFixed(2)} ${yPosition.toFixed(2)} ${width.toFixed(2)} ${height.toFixed(2)} re`);
    commands.push(options.fill && options.stroke ? "B" : options.fill ? "f" : "S");
    currentPageCommands.push(commands.join("\n"));
  };

  const addText = (
    text: string,
    x: number,
    yPosition: number,
    fontSize: number,
    options: {
      bold?: boolean;
      color?: readonly number[];
      align?: "left" | "right" | "center";
    } = {},
  ) => {
    const textWidth = estimateTextWidth(text, fontSize, options.bold);
    const width =
      options.align === "right"
        ? textWidth
        : options.align === "center"
          ? textWidth / 2
          : 0;
    currentPageCommands.push(
      `${rgb(options.color ?? palette.ink)} rg BT /F${options.bold ? "2" : "1"} ${fontSize} Tf 1 0 0 1 ${(x - width).toFixed(2)} ${yPosition.toFixed(2)} Tm (${escapePdfText(text)}) Tj ET`,
    );
  };

  const addRule = (x1: number, x2: number, yPosition: number, color: readonly number[] = palette.line, width = 0.8) => {
    currentPageCommands.push(
      `${rgb(color)} RG ${width.toFixed(2)} w ${x1.toFixed(2)} ${yPosition.toFixed(2)} m ${x2.toFixed(2)} ${yPosition.toFixed(2)} l S`,
    );
  };

  const addVerticalRule = (x: number, y1: number, y2: number, color: readonly number[] = palette.line, width = 0.8) => {
    currentPageCommands.push(
      `${rgb(color)} RG ${width.toFixed(2)} w ${x.toFixed(2)} ${y1.toFixed(2)} m ${x.toFixed(2)} ${y2.toFixed(2)} l S`,
    );
  };

  const addWrappedText = (
    value: string,
    x: number,
    topY: number,
    fontSize: number,
    maxChars: number,
    options: {
      bold?: boolean;
      color?: readonly number[];
      lineHeight?: number;
    } = {},
  ) => {
    const lines = wrapPdfText(value, maxChars);
    let currentY = topY;

    lines.forEach((line) => {
      addText(line, x, currentY, fontSize, {
        bold: options.bold,
        color: options.color,
      });
      currentY -= options.lineHeight ?? bodyLineHeight;
    });

    return lines.length;
  };

  const addChip = (
    text: string,
    x: number,
    yPosition: number,
    options: {
      fill: readonly number[];
      stroke?: readonly number[];
      textColor: readonly number[];
      fontSize?: number;
      bold?: boolean;
      paddingX?: number;
      height?: number;
    },
  ) => {
    const fontSize = options.fontSize ?? 9;
    const paddingX = options.paddingX ?? 10;
    const height = options.height ?? 20;
    const width = estimateTextWidth(text, fontSize, options.bold) + paddingX * 2;

    addRect(x, yPosition, width, height, {
      fill: options.fill,
      stroke: options.stroke ?? options.fill,
      lineWidth: 0.7,
    });
    addText(text, x + width / 2, yPosition + 6.2, fontSize, {
      bold: options.bold,
      color: options.textColor,
      align: "center",
    });

    return width;
  };

  const getToneForField = (label: string, value: string) => {
    const normalizedLabel = label.toLowerCase();
    const normalizedValue = value.toLowerCase();

    if (normalizedLabel.includes("status")) {
      if (normalizedValue.includes("late")) {
        return {
          fill: palette.roseSoft,
          stroke: palette.rose,
          text: palette.rose,
        };
      }
      if (normalizedValue.includes("on time")) {
        return {
          fill: palette.emeraldSoft,
          stroke: palette.emerald,
          text: palette.emerald,
        };
      }
    }

    if (normalizedLabel.includes("condition")) {
      if (normalizedValue.includes("damage")) {
        return {
          fill: palette.roseSoft,
          stroke: palette.rose,
          text: palette.rose,
        };
      }
      if (normalizedValue.includes("repair")) {
        return {
          fill: palette.orangeSoft,
          stroke: palette.orange,
          text: palette.orange,
        };
      }
      if (normalizedValue.includes("good")) {
        return {
          fill: palette.emeraldSoft,
          stroke: palette.emerald,
          text: palette.emerald,
        };
      }
    }

    return {
      fill: palette.purpleSoft,
      stroke: palette.border,
      text: palette.purpleDark,
    };
  };

  const finalizePage = () => {
    addRule(marginX, pageWidth - marginX, 24, palette.line, 0.7);
    addText("KBC Library History Report", marginX, 12, 9, { color: palette.muted });
    addText(`Page ${pageNumber}`, pageWidth - marginX, 12, 9, { color: palette.muted, align: "right" });
    pageContents.push(currentPageCommands.join("\n"));
  };

  const isWideField = (label: string) => {
    const normalized = label.toLowerCase();
    return normalized.includes("books") || normalized.includes("attachment") || normalized.includes("notes");
  };

  const isBadgeField = (label: string) => {
    const normalized = label.toLowerCase();
    return normalized.includes("status") || normalized === "condition";
  };

  const estimateFieldHeight = (field: { label: string; value: string }, wide = false) => {
    const lineCount = wrapPdfText(field.value, wide ? 82 : 30).length;
    return 16 + lineCount * bodyLineHeight + 6;
  };

  const renderFieldValue = (
    field: { label: string; value: string },
    x: number,
    topY: number,
    wide = false,
  ) => {
    addText(field.label.toUpperCase(), x, topY - 2, 7.8, {
      bold: true,
      color: palette.muted,
    });

    const tone = getToneForField(field.label, field.value);

    addWrappedText(field.value, x, topY - 18, bodySize, wide ? 82 : 30, {
      color: isBadgeField(field.label) ? tone.text : palette.ink,
      bold: isBadgeField(field.label) || field.label.toLowerCase().includes("returned count") || field.label.toLowerCase().includes("records"),
    });
  };

  const estimateStudentBookHeight = (book: PdfExportStudentBook) => {
    const titleLineCount = wrapPdfText(book.title, 48).length;
    return 78 + titleLineCount * 14;
  };

  const renderStudentBookBlock = (
    book: PdfExportStudentBook,
    x: number,
    topY: number,
    width: number,
    highlighted = false,
  ) => {
    const height = estimateStudentBookHeight(book);
    const titleLines = wrapPdfText(book.title, 48);
    const statusTone = getToneForField("Return status", book.returnStatus);
    const conditionTone = getToneForField("Condition", book.condition);
    const infoGap = 8;
    const infoWidth = (width - 28 - infoGap * 2) / 3;
    const boxTop = topY - 44 - titleLines.length * 14;
    const boxBottom = boxTop - 34;

    addRect(x, topY - height, width, height, {
      fill: highlighted ? palette.goldSoft : palette.white,
      stroke: palette.line,
      lineWidth: 0.7,
    });

    let titleY = topY - 18;
    titleLines.forEach((line) => {
      addText(line, x + 14, titleY, 10.6, {
        bold: true,
        color: palette.purpleDark,
      });
      titleY -= 14;
    });

    const metaY = topY - 22 - titleLines.length * 14;
    addText(book.returnStatus, x + 14, metaY, 9, {
      bold: true,
      color: statusTone.text,
    });
    addText(book.condition, x + width / 2, metaY, 9, {
      bold: true,
      color: conditionTone.text,
      align: "center",
    });
    addText(`${book.totalReturns} return${book.totalReturns === 1 ? "" : "s"}`, x + width - 14, metaY, 9, {
      bold: true,
      color: palette.purpleDark,
      align: "right",
    });

    const infoBoxes = [
      { label: "Returned", value: book.returnedAt },
      { label: "Due Date", value: book.dueDate },
      { label: "Copy Number", value: book.copyNumber },
    ];

    infoBoxes.forEach((item, index) => {
      const boxX = x + 14 + index * (infoWidth + infoGap);
      addRect(boxX, boxBottom, infoWidth, 34, {
        fill: palette.white,
        stroke: palette.line,
        lineWidth: 0.6,
      });
      addText(item.label.toUpperCase(), boxX + 8, boxTop - 10, 6.6, {
        bold: true,
        color: palette.muted,
      });
      addWrappedText(item.value, boxX + 8, boxTop - 22, 8.8, 14, {
        bold: true,
        color: palette.purpleDark,
        lineHeight: 10,
      });
    });

    return height;
  };

  const openPage = (includeSummary: boolean) => {
    if (pageNumber > 0) {
      finalizePage();
    }

    pageNumber += 1;
    currentPageCommands = [];
    addRect(0, 0, pageWidth, pageHeight, { fill: palette.white });
    addRect(0, pageHeight - 10, pageWidth, 10, { fill: palette.purple });

    addText("KBC LIBRARY", marginX, pageHeight - 30, 8.8, {
      bold: true,
      color: palette.muted,
    });
    addText(values.title, marginX, pageHeight - 54, titleSize, {
      bold: true,
      color: palette.purpleDark,
    });

    addText(`Page ${pageNumber}`, pageWidth - marginX, pageHeight - 30, 8.8, {
      bold: true,
      color: palette.purple,
      align: "right",
    });
    addRule(marginX, pageWidth - marginX, pageHeight - 84, palette.purple, 1.1);

    if (includeSummary) {
      const summaryTop = pageHeight - 102;
      const summaryDisplayFields = summaryFields.slice(0, 4);
      const summaryRowCount = summaryDisplayFields.length > 2 ? 2 : 1;
      const summaryHeight = summaryRowCount === 2 ? 82 : 48;
      const summaryBottom = summaryTop - summaryHeight;
      const middleX = pageWidth / 2;
      const splitY = summaryBottom + 34;

      addText("REPORT DETAILS", marginX, pageHeight - 98, 8.5, {
        bold: true,
        color: palette.muted,
      });
      addRect(marginX, summaryBottom, pageWidth - marginX * 2, summaryHeight, {
        fill: palette.white,
        stroke: palette.line,
        lineWidth: 0.8,
      });
      addVerticalRule(middleX, summaryBottom + 12, summaryTop - 12, palette.line, 0.6);
      if (summaryRowCount === 2) {
        addRule(marginX + 12, pageWidth - marginX - 12, splitY, palette.line, 0.6);
      }

      const renderSummaryField = (field: { label: string; value: string }, x: number, topY: number) => {
        addText(field.label.toUpperCase(), x, topY, 7.8, {
          bold: true,
          color: palette.muted,
        });
        addWrappedText(field.value, x, topY - 14, 10, 25, {
          bold: true,
          color: palette.purpleDark,
          lineHeight: 11,
        });
      };

      if (summaryDisplayFields[0]) {
        renderSummaryField(summaryDisplayFields[0], marginX + 14, summaryTop - 18);
      }
      if (summaryDisplayFields[1]) {
        renderSummaryField(summaryDisplayFields[1], middleX + 14, summaryTop - 18);
      }
      if (summaryRowCount === 2 && summaryDisplayFields[2]) {
        renderSummaryField(summaryDisplayFields[2], marginX + 14, splitY - 10);
      }
      if (summaryRowCount === 2 && summaryDisplayFields[3]) {
        renderSummaryField(summaryDisplayFields[3], middleX + 14, splitY - 10);
      }

      y = summaryBottom - 18;
    } else {
      addText("CONTINUED RECORDS", marginX, pageHeight - 98, 8.5, {
        bold: true,
        color: palette.muted,
      });
      y = pageHeight - 118;
    }
  };

  openPage(true);

  values.records.forEach((record, index) => {
    const fields = record.lines.map(splitPdfField);
    const studentBooks = record.studentBooks ?? [];
    const titleLines = wrapPdfText(record.title, 52);
    const regularFields = fields.filter((field) => !isWideField(field.label));
    const wideFields = fields.filter((field) => isWideField(field.label));
    const headerHeight = 28 + titleLines.length * 15;
    const regularRowCount = Math.ceil(regularFields.length / 2);
    const rowWidth = pageWidth - marginX * 2 - 24;
    const columnGap = 18;
    const columnWidth = (rowWidth - columnGap) / 2;

    let regularRowsHeight = 0;
    for (let rowIndex = 0; rowIndex < regularRowCount; rowIndex += 1) {
      const leftField = regularFields[rowIndex * 2];
      const rightField = regularFields[rowIndex * 2 + 1];
      regularRowsHeight += Math.max(
        leftField ? estimateFieldHeight(leftField, false) : 0,
        rightField ? estimateFieldHeight(rightField, false) : 0,
      ) + 10;
    }

    const wideRowsHeight = wideFields.reduce((total, field) => total + estimateFieldHeight(field, true) + 10, 0);
    const studentBooksHeight =
      studentBooks.length > 0
        ? 26 + studentBooks.reduce((total, book) => total + estimateStudentBookHeight(book) + 10, 0)
        : 0;
    const estimatedHeight = headerHeight + regularRowsHeight + wideRowsHeight + studentBooksHeight + 20;

    if (y - estimatedHeight < bottomMargin) {
      openPage(false);
    }

    const cardX = marginX;
    const cardWidth = pageWidth - marginX * 2;
    const cardTop = y;
    const cardBottom = y - estimatedHeight;
    addRect(cardX, cardBottom, cardWidth, estimatedHeight, {
      fill: palette.white,
      stroke: palette.line,
      lineWidth: 0.8,
    });
    addRect(cardX, cardTop - 4, cardWidth, 4, { fill: palette.purple });

    addText(`RECORD ${String(index + 1).padStart(2, "0")}`, cardX + cardPadding, cardTop - 18, 8.3, {
      bold: true,
      color: palette.muted,
    });

    let currentTitleY = cardTop - 36;
    titleLines.forEach((line) => {
      addText(line, cardX + cardPadding, currentTitleY, 12, {
        bold: true,
        color: palette.purpleDark,
      });
      currentTitleY -= 15;
    });

    if (studentBooks.length > 0) {
      const countLabel = `${studentBooks.length} book${studentBooks.length === 1 ? "" : "s"}`;
      const chipPadding = 9;
      const chipWidth = estimateTextWidth(countLabel, 8.5, true) + chipPadding * 2;
      addChip(countLabel, cardX + cardWidth - chipWidth - 16, cardTop - 30, {
        fill: palette.purpleSoft,
        stroke: palette.border,
        textColor: palette.purpleDark,
        fontSize: 8.5,
        bold: true,
        paddingX: chipPadding,
        height: 18,
      });
    }

    let currentTop = cardTop - headerHeight - 2;

    for (let rowIndex = 0; rowIndex < regularRowCount; rowIndex += 1) {
      const leftField = regularFields[rowIndex * 2];
      const rightField = regularFields[rowIndex * 2 + 1];
      const rowHeight = Math.max(
        leftField ? estimateFieldHeight(leftField, false) : 0,
        rightField ? estimateFieldHeight(rightField, false) : 0,
      ) + 10;

      addRect(cardX + 12, currentTop - rowHeight, rowWidth, rowHeight, {
        fill: rowIndex % 2 === 0 ? palette.goldSoft : palette.white,
      });
      addVerticalRule(cardX + 12 + columnWidth + columnGap / 2, currentTop - rowHeight + 8, currentTop - 8, palette.line, 0.5);

      if (leftField) {
        renderFieldValue(leftField, cardX + 24, currentTop - 10);
      }
      if (rightField) {
        renderFieldValue(rightField, cardX + 24 + columnWidth + columnGap, currentTop - 10);
      }

      currentTop -= rowHeight;
      addRule(cardX + 12, cardX + cardWidth - 12, currentTop, palette.line, 0.45);
    }

    wideFields.forEach((field, fieldIndex) => {
      const rowHeight = estimateFieldHeight(field, true) + 10;
      addRect(cardX + 12, currentTop - rowHeight, rowWidth, rowHeight, {
        fill: (regularRowCount + fieldIndex) % 2 === 0 ? palette.goldSoft : palette.white,
      });
      renderFieldValue(field, cardX + 24, currentTop - 10, true);
      currentTop -= rowHeight;
      addRule(cardX + 12, cardX + cardWidth - 12, currentTop, palette.line, 0.45);
    });

    if (studentBooks.length > 0) {
      currentTop -= 6;
      addText("BOOKS", cardX + 24, currentTop - 2, 7.8, {
        bold: true,
        color: palette.muted,
      });
      currentTop -= 16;

      studentBooks.forEach((book, bookIndex) => {
        const blockHeight = renderStudentBookBlock(
          book,
          cardX + 12,
          currentTop,
          rowWidth,
          bookIndex % 2 === 0,
        );
        currentTop -= blockHeight + 10;
      });
    }

    y = cardBottom - 16;
  });

  finalizePage();

  const objects: Array<{ id: number; body: string }> = [
    { id: 1, body: "<< /Type /Catalog /Pages 2 0 R >>" },
  ];
  const fontRegularId = 3;
  const fontBoldId = 4;
  let nextId = 5;
  const pageIds: number[] = [];

  pageContents.forEach((content) => {
    const contentId = nextId;
    const pageId = nextId + 1;
    nextId += 2;

    objects.push({
      id: contentId,
      body: `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    });
    objects.push({
      id: pageId,
      body: `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth.toFixed(2)} ${pageHeight.toFixed(2)}] /Resources << /Font << /F1 ${fontRegularId} 0 R /F2 ${fontBoldId} 0 R >> >> /Contents ${contentId} 0 R >>`,
    });
    pageIds.push(pageId);
  });

  objects.push({
    id: 2,
    body: `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${pageIds.length} >>`,
  });
  objects.push({ id: fontRegularId, body: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>" });
  objects.push({ id: fontBoldId, body: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>" });

  const sortedObjects = objects.sort((first, second) => first.id - second.id);
  const offsets: number[] = [0];
  let pdf = "%PDF-1.4\n";

  sortedObjects.forEach((object) => {
    offsets[object.id] = pdf.length;
    pdf += `${object.id} 0 obj\n${object.body}\nendobj\n`;
  });

  const xrefStart = pdf.length;
  pdf += `xref\n0 ${sortedObjects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";

  for (let index = 1; index <= sortedObjects.length; index += 1) {
    pdf += `${String(offsets[index] ?? 0).padStart(10, "0")} 00000 n \n`;
  }

  pdf += `trailer\n<< /Size ${sortedObjects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;

  return new Blob([pdf], { type: "application/pdf" });
}

function formatBorrowerLine(loan: Loan) {
  const name = (loan.borrowerName ?? "").trim();
  const email = (loan.borrowerEmail ?? "").trim();

  if (!name && !email) return "Unknown borrower";
  if (name && email && name.toLowerCase() !== email.toLowerCase()) {
    return `${name} / ${email}`;
  }

  return name || email;
}

function getBorrowerDisplayName(values: {
  borrowerName?: string | null;
  borrowerEmail?: string | null;
}) {
  const name = (values.borrowerName ?? "").trim();
  const email = (values.borrowerEmail ?? "").trim();
  return name || email || "Unknown borrower";
}

function getHistoryTimestamp(loan: Loan) {
  return new Date(loan.returnedAt ?? loan.borrowedAt ?? loan.requestedAt).getTime();
}

function getDateTimestamp(value?: string | null) {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getCalendarDayTimestamp(value?: string | null) {
  if (!value) return null;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) {
    const [, year, month, day] = match;
    return new Date(Number(year), Number(month) - 1, Number(day)).getTime();
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate()).getTime();
}

function formatReturnCondition(condition?: Loan["returnCondition"]) {
  const labels: Record<NonNullable<Loan["returnCondition"]>, string> = {
    good: "Good",
    worn: "Worn / Used",
    damaged: "Damaged",
    torn: "Needs Repair",
  };

  if (!condition) {
    return "Not recorded";
  }

  return labels[condition] ?? condition;
}

function returnConditionBadgeClass(condition?: Loan["returnCondition"]) {
  const tones: Record<NonNullable<Loan["returnCondition"]>, string> = {
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    worn: "border-amber-200 bg-amber-50 text-amber-700",
    damaged: "border-rose-200 bg-rose-50 text-rose-700",
    torn: "border-orange-200 bg-orange-50 text-orange-700",
  };

  if (!condition) {
    return "border-gray-200 bg-gray-50 text-gray-600";
  }

  return tones[condition] ?? "border-gray-200 bg-gray-50 text-gray-600";
}

function getReturnTimingSummary(values: {
  dueDate?: string | null;
  returnedAt?: string | null;
}) {
  const dueDay = getCalendarDayTimestamp(values.dueDate);
  const returnedDay = getCalendarDayTimestamp(values.returnedAt);

  if (dueDay == null || returnedDay == null) {
    return { late: false, daysLate: 0, label: "Due date not recorded" };
  }

  const daysLate = Math.round((returnedDay - dueDay) / 86_400_000);
  if (daysLate > 0) {
    return {
      late: true,
      daysLate,
      label: `Late by ${daysLate} day${daysLate === 1 ? "" : "s"}`,
    };
  }

  return {
    late: false,
    daysLate: 0,
    label: "Returned on time",
  };
}

function returnTimingBadgeClass(isLate?: boolean, hasDueDate?: boolean) {
  if (!hasDueDate) {
    return "border-gray-200 bg-gray-50 text-gray-600";
  }

  return isLate
    ? "border-rose-200 bg-rose-50 text-rose-700"
    : "border-sky-200 bg-sky-50 text-sky-700";
}

function hasConditionFlag(condition?: Loan["returnCondition"]) {
  return Boolean(condition && condition !== "good");
}

function isDamagedOrNeedsRepair(condition?: Loan["returnCondition"]) {
  return condition === "damaged" || condition === "torn";
}

function getVisibleStudentTitles(titles: StudentHistoryTitleSummary[], studentFilter: string) {
  if (studentFilter === "late-returns") {
    return titles.filter((title) => title.lateReturnCount > 0);
  }

  if (studentFilter === "damaged-last-returned") {
    return titles.filter((title) => isDamagedOrNeedsRepair(title.latestReturnCondition));
  }

  return titles;
}

function getReturnTimingLabel(values: {
  dueDate?: string | null;
  returnedAt?: string | null;
  late?: boolean;
  daysLate?: number;
}) {
  if (!values.dueDate) {
    return "Due date not recorded";
  }

  if (values.late) {
    const daysLate = values.daysLate ?? 0;
    return `Late by ${daysLate} day${daysLate === 1 ? "" : "s"}`;
  }

  return "Returned on time";
}

function getBorrowerIdentityKey(loan: Loan) {
  return (
    normalizeText(loan.borrowerStudentId) ||
    normalizeText(loan.borrowerEmail) ||
    normalizeText(loan.borrowerPhone) ||
    normalizeText(loan.borrowerName) ||
    loan.id
  );
}

function defaultSortForTab(tab: HistoryTab) {
  return HISTORY_TABS.find((item) => item.id === tab)?.defaultSort ?? "newest";
}

function getTabConfig(tab: HistoryTab) {
  return HISTORY_TABS.find((item) => item.id === tab) ?? HISTORY_TABS[0];
}

export default function CirculationHistoryManager() {
  const { books, loans, deleteLoan, bulkDeleteLoans } = useAdminData();
  const [tab, setTab] = useState<HistoryTab>("transactions");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<string>(defaultSortForTab("transactions"));
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);

  useEffect(() => {
    setSearch("");
    setSortBy(defaultSortForTab(tab));
    setSelectedIds([]);
    setDeletingId(null);
    setBulkDeleting(false);
  }, [tab]);

  const historyLoans = useMemo(() => loans.filter((loan) => loan.status === "returned"), [loans]);

  const resourceById = useMemo(() => new Map(books.map((book) => [book.id, book] as const)), [books]);
  const resourceByTitle = useMemo(
    () => new Map(books.map((book) => [normalizeText(book.title), book] as const)),
    [books],
  );

  const openLoanCountByBorrower = useMemo(() => {
    const counts = new Map<string, number>();

    loans.forEach((loan) => {
      if (!OPEN_HISTORY_STATUSES.has(loan.status)) return;
      const key = getBorrowerIdentityKey(loan);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });

    return counts;
  }, [loans]);

  const studentHistory = useMemo(() => {
    const grouped = new Map<
      string,
      StudentHistoryRow & {
        titleSet: Set<string>;
        titleMap: Map<string, StudentHistoryTitleSummary>;
      }
    >();

    historyLoans.forEach((loan) => {
      const returnTimingSummary = getReturnTimingSummary({ dueDate: loan.dueDate, returnedAt: loan.returnedAt });
      const key = getBorrowerIdentityKey(loan);
      const existing = grouped.get(key) ?? {
        key,
        borrowerName: (loan.borrowerName ?? "").trim(),
        borrowerEmail: (loan.borrowerEmail ?? "").trim(),
        borrowerPhone: (loan.borrowerPhone ?? "").trim(),
        borrowerStudentId: (loan.borrowerStudentId ?? "").trim(),
        totalReturns: 0,
        uniqueTitles: 0,
        openItems: 0,
        lateReturns: 0,
        conditionFlags: 0,
        lastBookTitle: loan.bookTitle,
        lastReturnedAt: loan.returnedAt,
        lastReturnCondition: loan.returnCondition,
        titles: [],
        titleSet: new Set<string>(),
        titleMap: new Map<string, StudentHistoryTitleSummary>(),
      };

      existing.totalReturns += 1;
      existing.titleSet.add(loan.bookTitle);
      if (returnTimingSummary.late) {
        existing.lateReturns += 1;
      }
      if (hasConditionFlag(loan.returnCondition)) {
        existing.conditionFlags += 1;
      }

      if (!existing.borrowerName && loan.borrowerName) existing.borrowerName = loan.borrowerName.trim();
      if (!existing.borrowerEmail && loan.borrowerEmail) existing.borrowerEmail = loan.borrowerEmail.trim();
      if (!existing.borrowerPhone && loan.borrowerPhone) existing.borrowerPhone = loan.borrowerPhone.trim();
      if (!existing.borrowerStudentId && loan.borrowerStudentId) existing.borrowerStudentId = loan.borrowerStudentId.trim();

      if (getHistoryTimestamp(loan) >= getDateTimestamp(existing.lastReturnedAt)) {
        existing.lastReturnedAt = loan.returnedAt;
        existing.lastBookTitle = loan.bookTitle;
        existing.lastReturnCondition = loan.returnCondition;
      }

      const titleKey = normalizeText(loan.bookTitle) || loan.id;
      const existingTitle = existing.titleMap.get(titleKey) ?? {
        key: titleKey,
        title: loan.bookTitle,
        totalReturns: 0,
        lateReturnCount: 0,
        lastReturnedAt: loan.returnedAt,
        latestDueDate: loan.dueDate,
        latestCopyNumber: loan.accessionNumber,
        latestReturnCondition: loan.returnCondition,
        latestReturnedLate: returnTimingSummary.late,
        latestDaysLate: returnTimingSummary.daysLate,
        latestReturnEvidence: loan.returnEvidence,
        latestReturnEvidenceName: loan.returnEvidenceName,
      };
      existingTitle.totalReturns += 1;
      if (returnTimingSummary.late) {
        existingTitle.lateReturnCount += 1;
      }
      if (getHistoryTimestamp(loan) >= getDateTimestamp(existingTitle.lastReturnedAt)) {
        existingTitle.lastReturnedAt = loan.returnedAt;
        existingTitle.latestDueDate = loan.dueDate;
        existingTitle.latestCopyNumber = loan.accessionNumber;
        existingTitle.latestReturnCondition = loan.returnCondition;
        existingTitle.latestReturnedLate = returnTimingSummary.late;
        existingTitle.latestDaysLate = returnTimingSummary.daysLate;
        existingTitle.latestReturnEvidence = loan.returnEvidence;
        existingTitle.latestReturnEvidenceName = loan.returnEvidenceName;
      }
      existing.titleMap.set(titleKey, existingTitle);

      grouped.set(key, existing);
    });

    return Array.from(grouped.values()).map(({ titleSet, titleMap, ...row }) => ({
      ...row,
      uniqueTitles: titleSet.size,
      openItems: openLoanCountByBorrower.get(row.key) ?? 0,
      titles: Array.from(titleMap.values()).sort((first, second) => {
        return (
          getDateTimestamp(second.lastReturnedAt) - getDateTimestamp(first.lastReturnedAt) ||
          second.totalReturns - first.totalReturns ||
          first.title.localeCompare(second.title)
        );
      }),
    }));
  }, [historyLoans, openLoanCountByBorrower]);

  const bookHistory = useMemo(() => {
    const grouped = new Map<
      string,
      BookHistoryRow & {
        borrowerSet: Set<string>;
        copySet: Set<string>;
      }
    >();

    historyLoans.forEach((loan) => {
      const returnTimingSummary = getReturnTimingSummary({ dueDate: loan.dueDate, returnedAt: loan.returnedAt });
      const matchedResource =
        (loan.resourceId ? resourceById.get(loan.resourceId) : undefined) ??
        resourceByTitle.get(normalizeText(loan.bookTitle));
      const key = loan.resourceId ?? (normalizeText(loan.bookTitle) || loan.id);

      const existing = grouped.get(key) ?? {
        key,
        resourceId: matchedResource?.id ?? loan.resourceId,
        bookTitle: matchedResource?.title ?? loan.bookTitle,
        author: matchedResource?.author ?? "Unknown author",
        totalReturns: 0,
        uniqueBorrowers: 0,
        copiesUsed: 0,
        lateReturns: 0,
        damagedOrRepairReturns: 0,
        latestBorrower: getBorrowerDisplayName(loan),
        latestCopyNumber: loan.accessionNumber,
        lastReturnedAt: loan.returnedAt,
        latestDueDate: loan.dueDate,
        latestReturnCondition: loan.returnCondition,
        latestReturnedLate: returnTimingSummary.late,
        latestDaysLate: returnTimingSummary.daysLate,
        totalCopies: matchedResource?.totalCopies ?? 0,
        availableCopies: matchedResource?.availableCopies ?? 0,
        borrowerSet: new Set<string>(),
        copySet: new Set<string>(),
      };

      existing.totalReturns += 1;
      if (returnTimingSummary.late) {
        existing.lateReturns += 1;
      }
      if (isDamagedOrNeedsRepair(loan.returnCondition)) {
        existing.damagedOrRepairReturns += 1;
      }
      existing.borrowerSet.add(getBorrowerIdentityKey(loan));
      if (loan.accessionNumber) {
        existing.copySet.add(loan.accessionNumber);
      }
      existing.totalCopies = matchedResource?.totalCopies ?? existing.totalCopies;
      existing.availableCopies = matchedResource?.availableCopies ?? existing.availableCopies;
      existing.author = matchedResource?.author ?? existing.author;
      existing.bookTitle = matchedResource?.title ?? existing.bookTitle;
      existing.resourceId = matchedResource?.id ?? existing.resourceId;

      if (getHistoryTimestamp(loan) >= getDateTimestamp(existing.lastReturnedAt)) {
        existing.lastReturnedAt = loan.returnedAt;
        existing.latestBorrower = getBorrowerDisplayName(loan);
        existing.latestCopyNumber = loan.accessionNumber;
        existing.latestDueDate = loan.dueDate;
        existing.latestReturnCondition = loan.returnCondition;
        existing.latestReturnedLate = returnTimingSummary.late;
        existing.latestDaysLate = returnTimingSummary.daysLate;
      }

      grouped.set(key, existing);
    });

    return Array.from(grouped.values()).map(({ borrowerSet, copySet, ...row }) => ({
      ...row,
      uniqueBorrowers: borrowerSet.size,
      copiesUsed: copySet.size,
    }));
  }, [historyLoans, resourceById, resourceByTitle]);

  const filteredTransactions = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    const filteredLoans = historyLoans.filter((loan) => {
      const searchableFields = [
        loan.bookTitle,
        loan.accessionNumber,
        loan.borrowerName ?? "",
        loan.borrowerEmail ?? "",
        loan.borrowerPhone ?? "",
        loan.borrowerStudentId ?? "",
        loan.returnCondition ?? "",
        loan.returnConditionNotes ?? "",
        loan.returnEvidenceName ?? "",
        loan.notes ?? "",
        loan.id,
      ].map((value) => value.toLowerCase());
      return !normalizedSearch || searchableFields.some((value) => value.includes(normalizedSearch));
    });

    return filteredLoans.sort((first, second) => {
      if (sortBy === "title") {
        return first.bookTitle.localeCompare(second.bookTitle);
      }

      const firstDate = getHistoryTimestamp(first);
      const secondDate = getHistoryTimestamp(second);
      return sortBy === "oldest" ? firstDate - secondDate : secondDate - firstDate;
    });
  }, [historyLoans, search, sortBy]);

  const studentRowsByFilter = useMemo(() => {
    return studentHistory.filter((student) => {
      return getVisibleStudentTitles(student.titles, sortBy).length > 0;
    });
  }, [sortBy, studentHistory]);

  const filteredStudents = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    const rows = studentRowsByFilter.filter((student) => {
      const searchableFields = [
        student.borrowerName,
        student.borrowerEmail,
        student.borrowerPhone,
        student.borrowerStudentId,
        student.lastBookTitle,
        ...student.titles.map((title) => title.title),
        ...student.titles.map((title) => formatReturnCondition(title.latestReturnCondition)),
        ...student.titles.map((title) => getReturnTimingSummary({ dueDate: title.latestDueDate, returnedAt: title.lastReturnedAt }).label),
        ...student.titles.map((title) => title.latestReturnEvidenceName ?? ""),
      ].map((value) => value.toLowerCase());
      return !normalizedSearch || searchableFields.some((value) => value.includes(normalizedSearch));
    });

    return rows.sort((first, second) => {
      if (sortBy === "late-returns") {
        return second.lateReturns - first.lateReturns || getDateTimestamp(second.lastReturnedAt) - getDateTimestamp(first.lastReturnedAt);
      }

      return getDateTimestamp(second.lastReturnedAt) - getDateTimestamp(first.lastReturnedAt);
    });
  }, [search, sortBy, studentRowsByFilter]);

  const filteredBooks = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    const rows = bookHistory.filter((book) => {
      const searchableFields = [
        book.bookTitle,
        book.author,
        book.latestCopyNumber,
        book.latestBorrower,
      ].map((value) => value.toLowerCase());
      return !normalizedSearch || searchableFields.some((value) => value.includes(normalizedSearch));
    });

    return rows.sort((first, second) => {
      if (sortBy === "title") {
        return first.bookTitle.localeCompare(second.bookTitle);
      }
      if (sortBy === "most-returned") {
        return second.totalReturns - first.totalReturns || getDateTimestamp(second.lastReturnedAt) - getDateTimestamp(first.lastReturnedAt);
      }
      return getDateTimestamp(second.lastReturnedAt) - getDateTimestamp(first.lastReturnedAt);
    });
  }, [bookHistory, search, sortBy]);

  const filteredTransactionIdSet = useMemo(() => new Set(filteredTransactions.map((loan) => loan.id)), [filteredTransactions]);

  useEffect(() => {
    if (tab !== "transactions") return;
    setSelectedIds((previous) => {
      const next = previous.filter((id) => filteredTransactionIdSet.has(id));
      return next.length === previous.length ? previous : next;
    });
  }, [filteredTransactionIdSet, tab]);

  const allShownSelected =
    tab === "transactions" &&
    filteredTransactions.length > 0 &&
    filteredTransactions.every((loan) => selectedIds.includes(loan.id));

  const hasActiveFilters = search.trim().length > 0 || sortBy !== defaultSortForTab(tab);

  const currentResultCount =
    tab === "transactions" ? filteredTransactions.length : tab === "students" ? filteredStudents.length : filteredBooks.length;
  const currentTotalCount =
    tab === "transactions" ? historyLoans.length : tab === "students" ? studentRowsByFilter.length : bookHistory.length;
  const studentCountLabel =
    sortBy === "late-returns"
      ? currentTotalCount === 1
        ? "person with late returns"
        : "people with late returns"
      : sortBy === "damaged-last-returned"
        ? currentTotalCount === 1
          ? "person with damaged or repair-needed returns"
          : "people with damaged or repair-needed returns"
        : currentTotalCount === 1
          ? "person who borrowed books"
          : "people who borrowed books";
  const studentCountSummary =
    search.trim().length > 0 && currentResultCount !== currentTotalCount
      ? `Showing ${currentResultCount} of ${currentTotalCount} ${studentCountLabel}`
      : `${currentTotalCount} ${studentCountLabel}`;
  const studentSummaryDescription =
    sortBy === "late-returns"
      ? "Only borrowers with at least one returned book that includes a late return are shown here."
      : sortBy === "damaged-last-returned"
        ? "Only borrowers with at least one returned book whose latest return was marked damaged or needs repair are shown here."
        : "This view groups completed returns by borrower, so the admin team can quickly see how many people borrowed books and review each student's history.";

  const exportPdf = () => {
    let records: PdfExportRecord[] = [];
    let fileName = "circulation-history";
    let title = "Circulation History Export";

    if (tab === "students") {
      records = filteredStudents.map((student) => {
        const visibleTitles = getVisibleStudentTitles(student.titles, sortBy);

        return {
          title: getBorrowerDisplayName(student),
          lines: [
            `Email: ${student.borrowerEmail || "No email address"}`,
            `Phone: ${student.borrowerPhone || "No phone number"}`,
          ],
          studentBooks: visibleTitles.map((book) => ({
            title: book.title,
            totalReturns: book.totalReturns,
            returnStatus: getReturnTimingLabel({
              dueDate: book.latestDueDate,
              returnedAt: book.lastReturnedAt,
              late: book.latestReturnedLate,
              daysLate: book.latestDaysLate,
            }),
            condition: formatReturnCondition(book.latestReturnCondition),
            returnedAt: formatDate(book.lastReturnedAt),
            dueDate: formatDate(book.latestDueDate),
            copyNumber: book.latestCopyNumber || "Not set",
          })),
        };
      });
      fileName = "circulation-history-students";
      title = "History Export - Students";
    } else if (tab === "books") {
      records = filteredBooks.map((book) => ({
        title: book.bookTitle,
        lines: [
          `Author: ${book.author}`,
          `Returned count: ${book.totalReturns}`,
        ],
      }));
      fileName = "circulation-history-books";
      title = "History Export - Books";
    } else {
      records = filteredTransactions.map((loan) => ({
        title: loan.bookTitle,
        lines: [
          `Borrower: ${getBorrowerDisplayName(loan)}`,
          `Email: ${(loan.borrowerEmail ?? "").trim() || "No email address"}`,
          `Phone: ${loan.borrowerPhone || "No phone number"}`,
          ...((loan.borrowerStudentId ?? "").trim() ? [`Student ID: ${loan.borrowerStudentId}`] : []),
          `Copy number: ${loan.accessionNumber || "Not set"}`,
          `Borrowed at: ${formatDate(loan.borrowedAt)}`,
          `Due date: ${formatDate(loan.dueDate)}`,
          `Returned at: ${formatDate(loan.returnedAt)}`,
          `Return status: ${getReturnTimingLabel({
            dueDate: loan.dueDate,
            returnedAt: loan.returnedAt,
            ...getReturnTimingSummary({ dueDate: loan.dueDate, returnedAt: loan.returnedAt }),
          })}`,
          `Condition: ${formatReturnCondition(loan.returnCondition)}`,
          ...((loan.returnConditionNotes ?? "").trim() ? [`Condition notes: ${loan.returnConditionNotes.trim()}`] : []),
          ...((loan.notes ?? "").trim() ? [`Notes: ${loan.notes.trim()}`] : []),
        ],
      }));
      fileName = "circulation-history-transactions";
      title = "History Export - Transactions";
    }

    const stamp = new Date();
    const stampFile = stamp.toISOString().slice(0, 10);
    const summaryLines = [
      `View: ${getTabConfig(tab).label}`,
      `Records: ${records.length}`,
      ...(search.trim() ? [`Search: ${search.trim()}`] : []),
    ];

    const blob = buildPdfBlob({ title, summaryLines, records });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${fileName}-${stampFile}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const toggleRowSelection = (loanId: string) => {
    setSelectedIds((previous) => (
      previous.includes(loanId)
        ? previous.filter((id) => id !== loanId)
        : [...previous, loanId]
    ));
  };

  const handleSelectAllShownAction = () => {
    if (tab !== "transactions") return;

    if (allShownSelected) {
      setSelectedIds((previous) => previous.filter((id) => !filteredTransactionIdSet.has(id)));
      return;
    }

    setSelectedIds((previous) => {
      const next = new Set(previous);
      filteredTransactions.forEach((loan) => next.add(loan.id));
      return Array.from(next);
    });
  };

  const handleDeleteOne = async (loan: Loan) => {
    const confirmed = window.confirm(`Delete the record for "${loan.bookTitle}"?\n\nThis action cannot be undone.`);
    if (!confirmed) return;

    setDeletingId(loan.id);
    try {
      await deleteLoan(loan.id);
      setSelectedIds((previous) => previous.filter((id) => id !== loan.id));
    } finally {
      setDeletingId(null);
    }
  };

  const handleBulkDelete = async (ids: string[], scopeLabel: string) => {
    if (!ids.length) return;
    const confirmed = window.confirm(`Delete ${ids.length} ${scopeLabel} record${ids.length === 1 ? "" : "s"}?\n\nThis action cannot be undone.`);
    if (!confirmed) return;

    setBulkDeleting(true);
    try {
      await bulkDeleteLoans(ids);
      setSelectedIds([]);
    } finally {
      setBulkDeleting(false);
    }
  };

  const resetView = () => {
    setSearch("");
    setSortBy(defaultSortForTab(tab));
    setSelectedIds([]);
  };

  const activeTabConfig = getTabConfig(tab);
  const currentSortOptions = HISTORY_SORT_OPTIONS[tab];

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
            History
          </h2>
          <p className="mt-0.5 text-sm text-gray-400">
            Switch between raw transactions, borrower history, and title history without losing the original circulation log.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {hasActiveFilters && (
            <button
              onClick={resetView}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-600 transition-colors hover:border-[#442F73]/20 hover:text-[#442F73]"
            >
              <i className="ri-refresh-line" />
              Reset view
            </button>
          )}
          <button
            onClick={exportPdf}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#442F73] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#241453] whitespace-nowrap"
          >
            <i className="ri-download-2-line" />
            Export PDF
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-3">
          {HISTORY_TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`rounded-2xl border px-4 py-4 text-left transition-all ${
                tab === item.id
                  ? "border-[#442F73] bg-[#F7F2FF] shadow-sm"
                  : "border-gray-200 bg-white hover:border-[#442F73]/20 hover:bg-gray-50"
              }`}
            >
              <div className="flex items-start gap-3">
                <div className={`flex h-11 w-11 items-center justify-center rounded-2xl ${
                  tab === item.id ? "bg-[#442F73] text-white" : "bg-[#F9F4EC] text-[#442F73]"
                }`}>
                  <i className={`${item.icon} text-lg`} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900">{item.label}</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">{item.description}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4 md:p-5">
        <div className="flex flex-col gap-3 xl:flex-row">
          <div className="relative flex-1">
            <i className="ri-search-line absolute left-3.5 top-1/2 -translate-y-1/2 text-sm text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={activeTabConfig.searchPlaceholder}
              className="w-full rounded-xl border border-gray-200 bg-white py-2.5 pl-10 pr-4 text-sm text-gray-800 outline-none focus:border-[#442F73] placeholder-gray-400"
            />
          </div>

          <div className="flex flex-col gap-3 sm:flex-row xl:w-auto">
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value)}
              className="min-w-52 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-700 outline-none focus:border-[#442F73]"
            >
              {currentSortOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        </div>

        {tab === "transactions" ? (
          <div
            className={`mt-4 flex flex-col gap-3 rounded-2xl p-4 lg:flex-row lg:items-center lg:justify-between ${
              selectedIds.length
                ? "border border-[#442F73]/12 bg-[#F7F2FF]"
                : "border border-dashed border-[#E9D9BD] bg-[#F9F4EC]"
            }`}
          >
            <div>
              <p className="text-sm font-semibold text-[#241453]">
                Showing {filteredTransactions.length} of {historyLoans.length} record{historyLoans.length === 1 ? "" : "s"}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {selectedIds.length
                  ? `${selectedIds.length} selected${allShownSelected ? " across all shown records" : ""}.`
                  : hasActiveFilters
                    ? "Filters are active. Narrow the history or reset the view."
                    : "Use search, filters, or bulk actions to manage the raw return log faster."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleSelectAllShownAction}
                disabled={!filteredTransactions.length || bulkDeleting}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:border-[#442F73]/20 hover:text-[#442F73] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <i className={allShownSelected ? "ri-close-circle-line" : "ri-checkbox-multiple-line"} />
                {allShownSelected ? "Deselect All Shown" : "Select All Shown"}
              </button>
              {selectedIds.length > 0 && (
                <button
                  onClick={() => void handleBulkDelete(selectedIds, "selected")}
                  disabled={bulkDeleting}
                  className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <i className={bulkDeleting ? "ri-loader-4-line animate-spin" : "ri-delete-bin-5-line"} />
                  Delete Selected ({selectedIds.length})
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-2xl border border-dashed border-[#E9D9BD] bg-[#F9F4EC] p-4">
            <p className="text-sm font-semibold text-[#241453]">
              {tab === "students" ? studentCountSummary : `Showing ${currentResultCount} of ${currentTotalCount} titles`}
            </p>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              {tab === "students"
                ? studentSummaryDescription
                : "This view groups completed returns by title, so the admin team can review book-level circulation patterns without leaving the history screen."}
            </p>
          </div>
        )}
      </div>

      {tab === "transactions" && (
        <>
          <div className="hidden overflow-hidden rounded-2xl border border-gray-200 bg-white lg:block">
            <div className="grid grid-cols-[44px_2fr_1.75fr_1.4fr_0.95fr_92px] gap-4 border-b border-gray-100 px-5 py-4 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              <label className="flex items-center justify-center">
                <input
                  type="checkbox"
                  checked={allShownSelected}
                  onChange={(event) => {
                    if (event.target.checked) {
                      setSelectedIds(filteredTransactions.map((loan) => loan.id));
                    } else {
                      setSelectedIds([]);
                    }
                  }}
                  className="h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                />
              </label>
              <span>Book</span>
              <span>Borrower</span>
              <span>Borrowed / Returned</span>
              <span>Copy</span>
              <span>Actions</span>
            </div>

            {filteredTransactions.map((loan) => {
              const timingSummary = getReturnTimingSummary({ dueDate: loan.dueDate, returnedAt: loan.returnedAt });
              const timingLabel = getReturnTimingLabel({
                dueDate: loan.dueDate,
                returnedAt: loan.returnedAt,
                ...timingSummary,
              });
              const borrowerDisplayName = getBorrowerDisplayName(loan);
              const borrowerEmail = (loan.borrowerEmail ?? "").trim();

              return (
                <div
                  key={loan.id}
                  className={`grid grid-cols-[44px_2fr_1.75fr_1.4fr_0.95fr_92px] gap-4 border-b border-gray-100 px-5 py-4 last:border-b-0 ${selectedIds.includes(loan.id) ? "bg-[#F9F4EC]" : ""}`}
                >
                  <label className="flex items-start justify-center pt-1">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(loan.id)}
                      onChange={() => toggleRowSelection(loan.id)}
                      className="h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                    />
                  </label>
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{loan.bookTitle}</p>
                    {loan.notes && <p className="mt-1 line-clamp-2 text-xs text-gray-400">{loan.notes}</p>}
                    <p className="mt-1 text-[11px] text-gray-400">ID: {loan.id}</p>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{borrowerDisplayName}</p>
                    <div className="mt-2 space-y-1.5 text-xs text-gray-500">
                      <p className="flex items-center gap-2">
                        <i className="ri-mail-line text-[#442F73]" />
                        <span className="truncate">{borrowerEmail || "No email address"}</span>
                      </p>
                      <p className="flex items-center gap-2">
                        <i className="ri-phone-line text-[#442F73]" />
                        <span>{loan.borrowerPhone || "No phone number"}</span>
                      </p>
                    </div>
                  </div>
                  <div>
                    <div className="grid gap-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded-xl border border-gray-100 bg-gray-50/70 px-3 py-2">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Borrowed</p>
                          <p className="mt-1 text-sm font-semibold text-gray-900">{formatDate(loan.borrowedAt)}</p>
                        </div>
                        <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 px-3 py-2">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-700">Returned</p>
                          <p className="mt-1 text-sm font-semibold text-emerald-700">{formatDate(loan.returnedAt)}</p>
                        </div>
                      </div>
                      <div className="rounded-xl border border-gray-100 bg-gray-50/70 px-3 py-2">
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Due Date</p>
                        <p className="mt-1 text-sm font-semibold text-gray-700">{formatDate(loan.dueDate)}</p>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${returnTimingBadgeClass(
                          timingSummary.late,
                          Boolean(loan.dueDate),
                        )}`}
                      >
                        {timingLabel}
                      </span>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${returnConditionBadgeClass(loan.returnCondition)}`}>
                        {formatReturnCondition(loan.returnCondition)}
                      </span>
                    </div>
                    {loan.returnConditionNotes && (
                      <p className="mt-1 line-clamp-2 text-xs text-gray-400">{loan.returnConditionNotes}</p>
                    )}
                    {loan.returnEvidence && (
                      <a
                        href={loan.returnEvidence}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-[#E9D9BD] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                      >
                        <i className="ri-attachment-2" />
                        {loan.returnEvidenceName || "View Evidence"}
                      </a>
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-gray-700">{loan.accessionNumber}</p>
                    {loan.borrowerStudentId && (
                      <p className="mt-1 text-xs text-gray-400">{loan.borrowerStudentId}</p>
                    )}
                  </div>
                  <div className="flex flex-col gap-2">
                    <button
                      onClick={() => void handleDeleteOne(loan)}
                      disabled={deletingId === loan.id}
                      className="inline-flex items-center justify-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-500 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <i className={deletingId === loan.id ? "ri-loader-4-line animate-spin" : "ri-delete-bin-line"} />
                      Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="space-y-3 lg:hidden">
            {filteredTransactions.map((loan) => {
              const timingSummary = getReturnTimingSummary({ dueDate: loan.dueDate, returnedAt: loan.returnedAt });
              const timingLabel = getReturnTimingLabel({
                dueDate: loan.dueDate,
                returnedAt: loan.returnedAt,
                ...timingSummary,
              });

              return (
                <div key={loan.id} className={`space-y-4 rounded-2xl border border-gray-200 bg-white p-4 ${selectedIds.includes(loan.id) ? "ring-2 ring-[#442F73]/10" : ""}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(loan.id)}
                        onChange={() => toggleRowSelection(loan.id)}
                        className="mt-1 h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                      />
                      <div>
                        <p className="text-sm font-semibold text-gray-900">{loan.bookTitle}</p>
                        <p className="mt-1 text-xs text-gray-400">{formatBorrowerLine(loan)}</p>
                        <p className="mt-1 text-[11px] text-gray-400">ID: {loan.id}</p>
                      </div>
                    </div>
                    <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                      Returned
                    </span>
                  </div>

                  <div className="grid gap-2 text-xs text-gray-500 sm:grid-cols-2">
                    <p><span className="font-semibold text-gray-700">Borrowed:</span> {formatDate(loan.borrowedAt)}</p>
                    <p><span className="font-semibold text-gray-700">Returned:</span> {formatDate(loan.returnedAt)}</p>
                    <p><span className="font-semibold text-gray-700">Due:</span> {formatDate(loan.dueDate)}</p>
                    <p><span className="font-semibold text-gray-700">Copy:</span> {loan.accessionNumber}</p>
                    <p><span className="font-semibold text-gray-700">Condition:</span> {formatReturnCondition(loan.returnCondition)}</p>
                    <p><span className="font-semibold text-gray-700">Phone:</span> {loan.borrowerPhone || "No phone number"}</p>
                    {loan.borrowerStudentId && (
                      <p><span className="font-semibold text-gray-700">Student ID:</span> {loan.borrowerStudentId}</p>
                    )}
                  </div>

                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${returnTimingBadgeClass(
                      timingSummary.late,
                      Boolean(loan.dueDate),
                    )}`}
                  >
                    {timingLabel}
                  </span>

                  {loan.returnConditionNotes && (
                    <div className="rounded-xl border border-gray-100 bg-emerald-50/50 px-3 py-2">
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">Return Condition Notes</p>
                      <p className="text-xs leading-relaxed text-gray-600">{loan.returnConditionNotes}</p>
                    </div>
                  )}

                  {loan.returnEvidence && (
                    <a
                      href={loan.returnEvidence}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 rounded-xl border border-[#E9D9BD] bg-[#FCFAF6] px-3 py-2 text-xs font-semibold text-[#442F73] transition-colors hover:border-[#442F73]/30 hover:text-[#241453]"
                    >
                      <i className="ri-attachment-2" />
                      {loan.returnEvidenceName || "Open return evidence"}
                    </a>
                  )}

                  {loan.notes && (
                    <div className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2">
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Notes</p>
                      <p className="text-xs leading-relaxed text-gray-600">{loan.notes}</p>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => void handleDeleteOne(loan)}
                      disabled={deletingId === loan.id}
                      className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-500 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <i className={deletingId === loan.id ? "ri-loader-4-line animate-spin" : "ri-delete-bin-line"} />
                      Delete Row
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {tab === "students" && (
        <div className="grid gap-4 sm:[grid-template-columns:repeat(auto-fit,minmax(420px,1fr))]">
          {filteredStudents.map((student) => {
            const displayName = getBorrowerDisplayName(student);
            const visibleTitles = getVisibleStudentTitles(student.titles, sortBy);
            const studentBooksHeading =
              sortBy === "late-returns"
                ? "Returned books with late returns linked to this student"
                : sortBy === "damaged-last-returned"
                  ? "Returned books marked damaged or needs repair linked to this student"
                  : "All returned books linked to this student";

            return (
              <div key={student.key} className="overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-[#F1E3CB] bg-gradient-to-r from-[#FCFAF6] via-white to-white px-5 py-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="flex items-start gap-4">
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[#E9D9BD] bg-white text-[#442F73] shadow-sm">
                        <i className="ri-user-3-line text-lg" />
                      </div>
                      <div>
                        <p className="text-lg font-semibold text-[#241453]">{displayName}</p>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                          <span className="inline-flex items-center gap-2 rounded-full border border-[#E9D9BD] bg-white px-3 py-1.5 text-gray-600">
                            <i className="ri-mail-line text-[#442F73]" />
                            {student.borrowerEmail || "No email on file"}
                          </span>
                          <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 ${
                            student.borrowerPhone
                              ? "border-[#E9D9BD] bg-white text-gray-600"
                              : "border-gray-200 bg-gray-50 text-gray-500"
                          }`}>
                            <i className="ri-phone-line text-[#442F73]" />
                            {student.borrowerPhone || "No phone number"}
                          </span>
                        </div>
                      </div>
                    </div>

                    <span className="inline-flex h-fit rounded-full border border-[#E9D9BD] bg-white px-3 py-1.5 text-xs font-semibold text-[#442F73]">
                      {visibleTitles.length} book{visibleTitles.length === 1 ? "" : "s"}
                    </span>
                  </div>
                </div>

                <div className="p-5">
                  <div className="rounded-2xl border border-[#E9D9BD] bg-[#FCFAF6] px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-[11px] uppercase tracking-wide text-gray-400">Books</p>
                        <p className="mt-1 text-sm font-medium text-gray-900">{studentBooksHeading}</p>
                      </div>
                      <span className="inline-flex rounded-full border border-[#E9D9BD] bg-white px-3 py-1 text-[11px] font-semibold text-[#442F73]">
                        {visibleTitles.length} book{visibleTitles.length === 1 ? "" : "s"}
                      </span>
                    </div>

                    <div className="mt-3 space-y-3">
                      {visibleTitles.map((title) => {
                        const timingLabel = getReturnTimingLabel({
                          dueDate: title.latestDueDate,
                          returnedAt: title.lastReturnedAt,
                          late: title.latestReturnedLate,
                          daysLate: title.latestDaysLate,
                        });

                        return (
                          <div key={title.key} className="rounded-2xl border border-[#F1E3CB] bg-white px-4 py-4">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                              <div className="flex items-start gap-3">
                                <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-2xl bg-[#F6EFE3] text-[#442F73]">
                                  <i className="ri-book-2-line text-base" />
                                </div>
                                <div>
                                  <p className="text-sm font-semibold text-[#241453]">{title.title}</p>
                                  <p className="mt-1 text-xs text-gray-500">Latest circulation snapshot for this title</p>
                                </div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                                <span
                                  className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${returnTimingBadgeClass(title.latestReturnedLate, Boolean(title.latestDueDate))}`}
                                >
                                  {timingLabel}
                                </span>
                                <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${returnConditionBadgeClass(title.latestReturnCondition)}`}>
                                  {formatReturnCondition(title.latestReturnCondition)}
                                </span>
                                <span className="inline-flex rounded-full border border-[#E9D9BD] bg-[#FCFAF6] px-2.5 py-1 text-[11px] font-semibold text-[#6A4711]">
                                  {title.totalReturns} return{title.totalReturns === 1 ? "" : "s"}
                                </span>
                              </div>
                            </div>

                            <div className="mt-3 grid gap-2 sm:grid-cols-3">
                              <div className="rounded-xl border border-[#F3E9DA] bg-[#FCFAF6] px-3 py-3">
                                <p className="text-[10px] uppercase tracking-wide text-gray-400">Returned</p>
                                <p className="mt-1 text-sm font-semibold text-[#241453]">{formatDate(title.lastReturnedAt)}</p>
                              </div>
                              <div className="rounded-xl border border-[#F3E9DA] bg-[#FCFAF6] px-3 py-3">
                                <p className="text-[10px] uppercase tracking-wide text-gray-400">Due Date</p>
                                <p className="mt-1 text-sm font-semibold text-[#241453]">{formatDate(title.latestDueDate)}</p>
                              </div>
                              <div className="rounded-xl border border-[#F3E9DA] bg-[#FCFAF6] px-3 py-3">
                                <p className="text-[10px] uppercase tracking-wide text-gray-400">Copy Number</p>
                                <p className="mt-1 text-sm font-semibold text-[#241453]">{title.latestCopyNumber || "Not set"}</p>
                              </div>
                            </div>

                            {title.latestReturnEvidence && (
                              <a
                                href={title.latestReturnEvidence}
                                target="_blank"
                                rel="noreferrer"
                                className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-[#F3E9DA] bg-[#FCFAF6] px-3 py-3 text-sm text-gray-600 transition-colors hover:border-[#E9D9BD] hover:bg-white"
                              >
                                <div className="flex min-w-0 items-center gap-3">
                                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#E9D9BD] bg-white text-[#442F73]">
                                    <i className="ri-attachment-2" />
                                  </div>
                                  <div className="min-w-0">
                                    <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Attachment</p>
                                    <p className="truncate text-sm font-medium text-[#241453]">
                                      {title.latestReturnEvidenceName || "Open attachment"}
                                    </p>
                                  </div>
                                </div>
                                <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[#E9D9BD] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#442F73]">
                                  Open
                                  <i className="ri-arrow-right-up-line" />
                                </span>
                              </a>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === "books" && (
        <div className="grid gap-4 sm:[grid-template-columns:repeat(auto-fit,minmax(420px,1fr))]">
          {filteredBooks.map((book) => (
            <div key={book.key} className="rounded-[28px] border border-gray-200 bg-gradient-to-br from-white via-white to-[#FCFAF6] p-5 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-[#E9D9BD] bg-white text-[#442F73] shadow-sm">
                    <i className="ri-book-2-line text-lg" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-lg font-semibold leading-snug text-[#241453]">{book.bookTitle}</p>
                    <p className="mt-1 text-sm text-gray-500">{book.author}</p>
                  </div>
                </div>
                <div className="min-w-[104px] rounded-2xl border border-[#E9D9BD] bg-white px-4 py-3 text-center shadow-sm">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9B8AB8]">Returned</p>
                  <p className="mt-2 text-3xl font-bold leading-none text-[#241453]">{book.totalReturns}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {currentResultCount === 0 && (
        <div className="rounded-2xl border border-gray-200 bg-white py-16 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-gray-50">
            <i className={`${tab === "students" ? "ri-user-search-line" : tab === "books" ? "ri-book-line" : "ri-history-line"} text-2xl text-gray-300`} />
          </div>
          <p className="mb-1 font-medium text-gray-500">
            {tab === "students"
              ? "No borrower history found"
              : tab === "books"
                ? "No book history found"
                : "No returned records found"}
          </p>
          <p className="text-sm text-gray-400">
            {tab === "students"
              ? "Student summaries will appear here after books are returned and grouped by borrower."
              : tab === "books"
                ? "Book summaries will appear here after books are returned and grouped by title."
                : "Completed returns will appear here after books are marked as returned."}
          </p>
        </div>
      )}
    </div>
  );
}

