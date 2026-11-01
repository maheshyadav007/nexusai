import type { ClassifiedEmail } from "@/lib/types";

export const priorityCategoryIds = ["action", "exec", "customer", "release"];

export function isPriorityInboxEmail(email: ClassifiedEmail) {
  return (
    email.priority === "critical" ||
    email.priority === "high" ||
    priorityCategoryIds.includes(email.categoryId)
  );
}

export function getEmailsForCategory(emails: ClassifiedEmail[], categoryId: string) {
  if (categoryId === "all") return emails;
  if (categoryId === "priority") return emails.filter(isPriorityInboxEmail);
  return emails.filter((email) => email.categoryId === categoryId);
}

export function getUnreadCountForCategory(emails: ClassifiedEmail[], categoryId: string) {
  return getEmailsForCategory(emails, categoryId).filter((email) => !email.read).length;
}
