"use client";

import { create } from "zustand";
import { classifiedEmails, emailCategories, initialPanels, reminders } from "@/lib/data";
import { getEmailsForCategory } from "@/lib/email-filters";
import type {
  ClassifiedEmail,
  ColorMode,
  EmailCategory,
  Panel,
  ReclassificationEvent,
  Reminder,
  ThemeName,
  ToastNotice
} from "@/lib/types";

type NexusState = {
  theme: ThemeName;
  mode: ColorMode;
  panels: Panel[];
  notices: ToastNotice[];
  categories: EmailCategory[];
  emails: ClassifiedEmail[];
  reminders: Reminder[];
  reclassificationEvents: ReclassificationEvent[];
  selectedCategoryId: string;
  selectedEmailId: string;
  setTheme: (theme: ThemeName) => void;
  setMode: (mode: ColorMode) => void;
  toggleMode: () => void;
  selectCategory: (id: string) => void;
  selectEmail: (id: string) => void;
  createCategory: () => void;
  toggleEmailRead: (id: string) => void;
  createEntityReminder: (input: {
    title: string;
    entityTitle: string;
    entityType: NonNullable<Reminder["entityType"]>;
    trigger: NonNullable<Reminder["trigger"]>;
    sourceId?: string;
    note?: string;
  }) => void;
  requestReclassification: (input: {
    emailId: string;
    toCategory?: string;
    trigger: ReclassificationEvent["trigger"];
    reason: string;
  }) => void;
  addPanel: () => void;
  deletePanel: (id: string) => void;
  addNotice: (notice: Omit<ToastNotice, "id" | "time">) => void;
  dismissNotice: (id: string) => void;
};

const panelTemplates: Panel[] = [
  {
    id: "panel-template-reminders",
    title: "Reminders",
    category: "Personal ops",
    priority: "high",
    lastUpdated: "Now",
    items: [
      "Risk memo reply due at 1:30 PM",
      "Renewal draft review due at 2:45 PM",
      "PLM owner follow-up due at 5:00 PM"
    ]
  },
  {
    id: "panel-template-files",
    title: "Recent files",
    category: "Files",
    priority: "medium",
    lastUpdated: "Now",
    items: [
      "Supplier_Risk_Delta.pdf",
      "R2_release_gate.md",
      "Enterprise_Renewal_Notes.docx"
    ]
  }
];

export const useNexusStore = create<NexusState>((set, get) => ({
  theme: "editorial",
  mode: "light",
  panels: initialPanels,
  notices: [],
  categories: emailCategories,
  emails: classifiedEmails,
  reminders,
  reclassificationEvents: [
    {
      id: "reclass-seed-1",
      emailId: "email-5",
      emailSubject: "Two swarm jobs stuck in retry queue",
      fromCategory: "GitHub + swarm",
      toCategory: "Needs action",
      trigger: "chat",
      reason: "User told NexusAI that stuck runtime jobs should become action-bearing.",
      status: "applied",
      time: "12 min ago"
    }
  ],
  selectedCategoryId: "all",
  selectedEmailId: "email-1",
  setTheme: (theme) => set({ theme }),
  setMode: (mode) => set({ mode }),
  toggleMode: () =>
    set((state) => ({
      mode: state.mode === "dark" ? "light" : "dark"
    })),
  selectCategory: (id) => {
    const emails = get().emails;
    const firstEmail = getEmailsForCategory(emails, id)[0] ?? emails[0];

    set({
      selectedCategoryId: id,
      selectedEmailId: firstEmail?.id ?? get().selectedEmailId
    });
  },
  selectEmail: (id) => set({ selectedEmailId: id }),
  createCategory: () => {
    const customIndex = get().categories.filter((category) => category.isCustom).length + 1;
    const nextCategory: EmailCategory = {
      id: `custom-${Date.now()}`,
      name: `Custom signal ${customIndex}`,
      description: "User-created watchlist powered by rules and semantic matching.",
      color: "accent",
      count: 0,
      unread: 0,
      ruleCount: 0,
      aiCount: 0,
      isCustom: true
    };

    set((state) => ({
      categories: [...state.categories, nextCategory],
      selectedCategoryId: nextCategory.id
    }));
  },
  toggleEmailRead: (id) =>
    set((state) => ({
      emails: state.emails.map((email) =>
        email.id === id ? { ...email, read: !email.read } : email
      )
    })),
  createEntityReminder: (input) => {
    const nextReminder: Reminder = {
      id: `reminder-${Date.now()}`,
      title: input.title,
      dueTime: "Today, 4:30 PM",
      countdown: "later today",
      status: "scheduled",
      owner: input.trigger === "chat" || input.trigger === "agent" ? "NexusAI" : "You",
      trigger: input.trigger,
      entityType: input.entityType,
      entityTitle: input.entityTitle,
      sourceId: input.sourceId,
      note: input.note
    };

    set((state) => ({
      reminders: [nextReminder, ...state.reminders],
      notices: [
        {
          id: `notice-${Date.now()}`,
          title: "Reminder created",
          description: `${input.trigger} trigger linked to ${input.entityTitle}.`,
          tone: "success" as const,
          time: "Now"
        },
        ...state.notices
      ].slice(0, 5)
    }));
  },
  requestReclassification: ({ emailId, toCategory = "action", trigger, reason }) => {
    const email = get().emails.find((item) => item.id === emailId);
    if (!email) return;

    const categories = get().categories;
    const fromCategory = categories.find((category) => category.id === email.categoryId)?.name ?? email.categoryId;
    const toCategoryName = categories.find((category) => category.id === toCategory)?.name ?? toCategory;
    const event: ReclassificationEvent = {
      id: `reclass-${Date.now()}`,
      emailId,
      emailSubject: email.subject,
      fromCategory,
      toCategory: toCategoryName,
      trigger,
      reason,
      status: "applied",
      time: "Now"
    };

    set((state) => ({
      emails: state.emails.map((item) =>
        item.id === emailId
          ? {
              ...item,
              categoryId: toCategory,
              classificationMode: "AI",
              confidence: Math.min(99, item.confidence + 4),
              ruleMatches: ["feedback:similar-pattern", ...item.ruleMatches.filter((rule) => rule !== "feedback:similar-pattern")],
              indexedAt: "Now"
            }
          : item
      ),
      selectedCategoryId: toCategory,
      reclassificationEvents: [event, ...state.reclassificationEvents].slice(0, 6),
      notices: [
        {
          id: `notice-${Date.now()}`,
          title: "Classifier updated",
          description: `Similar emails will be routed to ${toCategoryName}.`,
          tone: "info" as const,
          time: "Now"
        },
        ...state.notices
      ].slice(0, 5)
    }));
  },
  addPanel: () => {
    const existing = get().panels;
    const nextTemplate =
      panelTemplates.find((template) => !existing.some((panel) => panel.title === template.title)) ??
      panelTemplates[existing.length % panelTemplates.length];

    set({
      panels: [
        {
          ...nextTemplate,
          id: `${nextTemplate.id}-${Date.now()}`
        },
        ...existing
      ]
    });
  },
  deletePanel: (id) =>
    set((state) => ({
      panels: state.panels.filter((panel) => panel.id !== id)
    })),
  addNotice: (notice) =>
    set((state) => ({
      notices: [
        {
          ...notice,
          id: `notice-${Date.now()}`,
          time: "Now"
        },
        ...state.notices
      ].slice(0, 5)
    })),
  dismissNotice: (id) =>
    set((state) => ({
      notices: state.notices.filter((notice) => notice.id !== id)
    }))
}));
