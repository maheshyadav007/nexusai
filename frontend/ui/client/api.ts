import type {
  ApiError,
  EventLog,
  EventLogQuery,
  GetSettings,
  Settings,
  UpdateSettings,
} from "./contracts.generated";

interface Commands {
  "settings.update": [UpdateSettings, Settings];
}

interface Queries {
  "settings.get": [GetSettings, Settings];
}

export class ApiRequestError extends Error {
  constructor(readonly detail: ApiError) {
    super(detail.message);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new ApiRequestError((await response.json()) as ApiError);
  return (await response.json()) as T;
}

export function command<K extends keyof Commands>(name: K, input: Commands[K][0]): Promise<Commands[K][1]> {
  return post(`/api/commands/${name}`, input);
}

export function query<K extends keyof Queries>(name: K, input: Queries[K][0]): Promise<Queries[K][1]> {
  return post(`/api/queries/${name}`, input);
}

export function eventLog(input: EventLogQuery): Promise<EventLog> {
  return post("/api/events/log", input);
}

export async function latestSeq(): Promise<number> {
  const response = await fetch("/api/health");
  const health = (await response.json()) as { latest_seq: number };
  return health.latest_seq;
}

export const EVENTS_URL = "/api/events";
