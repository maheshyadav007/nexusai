export type ServerConfig = {
  host: string;
  port: number;
  secure: boolean;
  starttls?: boolean;
};

export type MailProfile = {
  label: string;
  imap: ServerConfig;
  smtp: ServerConfig;
  auth: { type: "password"; user: string };
  mailboxes?: string[];
};

export type MailAccountsConfig = {
  activeProfile: string;
  profiles: Record<string, MailProfile>;
};

export type Address = { name: string; address: string };

/** One message, normalized from IMAP or PST. */
export type MailMessage = {
  profile: string;
  mailbox: string;
  uid: number | null;
  messageId: string;
  threadKey: string;
  from: Address | null;
  to: Address[];
  cc: Address[];
  subject: string;
  date: string;
  bodyText: string;
  snippet: string;
  headers: Record<string, string>;
  attachmentNames: string[];
};

export type RuleField =
  | "from"
  | "fromDomain"
  | "to"
  | "cc"
  | "subject"
  | "body"
  | "hasAttachment"
  | "attachmentName"
  | `header:${string}`;

export type RuleOp = "equals" | "contains" | "startsWith" | "endsWith" | "matches" | "exists";

export type RuleCondition = { field: RuleField; op: RuleOp; value?: string; not?: boolean };
export type RuleGroup = { all: RuleNode[] } | { any: RuleNode[] };
export type RuleNode = RuleCondition | RuleGroup;

export type RuleAction = {
  bucket?: string;
  markRead?: boolean;
  skipAgent?: boolean;
  notify?: boolean;
  tag?: string;
};

export type Rule = { name: string; when: RuleNode; then: RuleAction; builtIn?: boolean };

export type RuleResult = { rule: Rule | null; action: RuleAction };
