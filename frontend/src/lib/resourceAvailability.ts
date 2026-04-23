import type { Resource } from "../types/library";

export const getResourceQueueMetrics = (resource: Resource) => {
  const availableCopies = resource.availableCopies ?? 0;
  const pendingBorrowRequests = resource.pendingBorrowRequests ?? 0;
  const borrowableCopies = resource.borrowableCopies ?? Math.max(availableCopies - pendingBorrowRequests, 0);
  const queueFull = resource.queueFull ?? (availableCopies > 0 && pendingBorrowRequests >= availableCopies);
  const canBorrow = resource.canBorrow ?? borrowableCopies > 0;

  return {
    availableCopies,
    pendingBorrowRequests,
    borrowableCopies,
    queueFull,
    canBorrow,
  };
};

export const formatResourceAvailabilityLine = (resource: Resource) => {
  const { availableCopies, pendingBorrowRequests, borrowableCopies, queueFull } = getResourceQueueMetrics(resource);

  if (queueFull) {
    return `${availableCopies} on shelf | ${pendingBorrowRequests} pending`;
  }

  if (pendingBorrowRequests > 0) {
    return `${borrowableCopies} open to borrow | ${pendingBorrowRequests} pending`;
  }

  if (availableCopies > 0) {
    return `${availableCopies} available now`;
  }

  switch (resource.availabilityStatus) {
    case "borrowed":
      return "Currently borrowed";
    case "reserved":
      return "Currently reserved";
    case "maintenance":
      return "Temporarily unavailable";
    default:
      return "Unavailable";
  }
};
