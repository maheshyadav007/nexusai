"use client";

import { useId, useState, type InputHTMLAttributes } from "react";
import type { Recipient } from "@/ui/client/contracts.generated";
import { useRecipientSuggestions } from "@/ui/client/mail";
import { Input } from "@/ui/primitives/Input";
import { t } from "@/ui/strings";

// The address being typed is whatever comes after the last comma or semicolon.
const LAST = /[^,;]*$/;

const typing = (value: string) => (LAST.exec(value)?.[0] ?? "").trim();

function choose(value: string, person: Recipient): string {
  return `${value.replace(LAST, (part) => (part.startsWith(" ") ? " " : ""))}${person.address}, `;
}

/** A comma-separated address field that suggests people from their own mail as they type. */
export function RecipientField({ value, onChange, invalid, ...control }: { value: string; onChange: (value: string) => void; invalid: boolean } & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const list = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const word = typing(value);
  const found = useRecipientSuggestions(word);
  const people = (found.data?.people ?? []).filter((person) => !value.toLowerCase().includes(`${person.address.toLowerCase()},`));
  const shown = open && word.length >= 2 && people.length > 0;
  const pick = (person: Recipient) => {
    onChange(choose(value, person));
    setActive(0);
  };
  return (
    <div className="relative">
      <Input
        {...control}
        invalid={invalid}
        spellCheck={false}
        autoComplete="off"
        role="combobox"
        aria-expanded={shown}
        aria-controls={list}
        aria-autocomplete="list"
        {...(shown ? { "aria-activedescendant": `${list}-${active}` } : {})}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (!shown) return;
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const step = event.key === "ArrowDown" ? 1 : people.length - 1;
            setActive((current) => (current + step) % people.length);
          } else if (event.key === "Enter" || event.key === "Tab") {
            const person = people[active];
            if (!person) return;
            event.preventDefault();
            pick(person);
          } else if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
          }
        }}
      />
      {shown ? (
        <ul id={list} role="listbox" aria-label={t("mail.suggestions")} className="absolute inset-x-0 top-full z-float mt-1 flex flex-col overflow-hidden rounded-md border border-line-subtle bg-surface-raised py-1 shadow-overlay">
          {people.map((person, index) => (
            <li
              key={person.address}
              id={`${list}-${index}`}
              role="option"
              aria-selected={index === active}
              data-testid="recipient-suggestion"
              // Chosen before the field loses focus, so the list is still there to click.
              onMouseDown={(event) => {
                event.preventDefault();
                pick(person);
              }}
              onMouseEnter={() => setActive(index)}
              className={`flex min-w-0 cursor-pointer items-baseline gap-2 px-3 py-1 text-md ${index === active ? "bg-surface-sunken" : ""}`}
            >
              {person.name ? <span className="shrink-0 text-ink-primary">{person.name}</span> : null}
              <span className="min-w-0 truncate text-ink-muted">{person.address}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
