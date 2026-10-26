export type Role = "platform_admin" | "school_admin" | "teacher" | "reviewer";
export type SessionUser = { id: string; name: string; email: string; role: Role; tenant_id: string | null };
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type Resource = { id: string; title: string; media_type: string; created_at: string; provenance?: {license?: string; source_uri?: string} };
export type School = { id: string; name: string; organization_id?: string };
export type Curriculum = { id: string; name: string; country?: string; title?: string; version?: string };
export type Topic = { id: string; name: string; title?: string; code?: string };
export type Job = { id: string; status: string; progress: number; error?: string | null };
export type Block = { id: string; type: string; text?: string; latex?: string; citations?: string[]; rows?: string[][]; asset_ref?: string; caption?: string; answer?: string; audience?: string };
export type Draft = { id: string; title: string; document_type: string; body: { sections: Array<{ id?: string; title?: string; blocks: Block[] }> } & Record<string, unknown>; review_state?: string; evidence_ids?: string[] };
export type Generate = { document_type: string; curriculum_id: string; level_id: string; subject_id: string; topic_ids: string[]; options: Record<string, unknown>; resource_filters: Record<string, unknown> };
export const routes = [
 {id: "dashboard", label: "Overview", group: "Workspace", symbol: "▦"},
 {id: "generate", label: "Generation studio", group: "Workspace", symbol: "✦"},
 {id: "documents", label: "My documents", group: "Workspace", symbol: "▤"},
 {id: "editor", label: "Document editor", group: "Workspace", symbol: "✎"},
 {id: "review", label: "Reviews & approvals", group: "Workspace", symbol: "✓"},
 {id: "publish", label: "Publishing center", group: "Workspace", symbol: "↗"},
 {id: "library", label: "Reference library", group: "Sources", symbol: "▣"},
 {id: "upload", label: "Upload resources", group: "Sources", symbol: "↑"},
 {id: "telegram", label: "Telegram sources", group: "Sources", symbol: "➤"},
 {id: "imports", label: "Website imports", group: "Sources", symbol: "⌁"},
 {id: "processing", label: "Processing jobs", group: "Sources", symbol: "◷"},
 {id: "curriculum", label: "Curriculum browser", group: "Intelligence", symbol: "◈"},
 {id: "evidence", label: "Research & evidence", group: "Intelligence", symbol: "⌕"},
 {id: "question-bank", label: "Question bank", group: "Intelligence", symbol: "?"},
 {id: "schools", label: "School settings", group: "Administration", symbol: "⌂"}
] as const;
export type Section = typeof routes[number]["id"];
export const documentTypes = [
 { id: "lesson_notes", title: "Lesson notes", description: "Thorough, referenced teaching notes", symbol: "▤" },
 { id: "exam", title: "Examinations", description: "Structured papers with marking guides", symbol: "☷" },
 { id: "test", title: "Class tests", description: "Topic-based formative assessment", symbol: "✓" },
 { id: "scheme_of_work", title: "Schemes of work", description: "Sequenced weeks, units and outcomes", symbol: "▦" },
 { id: "lesson_plan", title: "Lesson plans", description: "Classroom timing, activities and objectives", symbol: "◷" },
 { id: "teacher_guide", title: "Teacher guides", description: "Teaching methods and differentiated support", symbol: "✦" },
 { id: "quiz", title: "Quizzes", description: "Quick knowledge checks", symbol: "?" },
 { id: "assignment", title: "Assignments", description: "Individual learner work", symbol: "✎" }
] as const;
export function isEditor(role: Role) { return role === "school_admin" || role === "teacher" || role === "platform_admin"; }
export function canReview(role: Role) { return role === "school_admin" || role === "reviewer" || role === "platform_admin"; }
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
 if (!path.startsWith("/api/v1/")) throw new Error("API path must be versioned");
 const response = await fetch(path, { ...init, credentials: "same-origin", cache: "no-store", headers: { ...(init.body instanceof FormData ? {} : init.body ? {"Content-Type":"application/json"} : {}), ...init.headers } });
 if (response.status === 204) return undefined as T;
 let payload: unknown;
 try { payload = await response.json(); } catch { throw new Error("The server returned an invalid response (" + response.status + ")."); }
 if (!response.ok) {
  const result = payload as {error?: {message?: string}};
  throw new Error(result?.error?.message || "Request failed (" + response.status + ")");
 }
 return payload as T;
}
export function toMessage(error: unknown) { return error instanceof Error ? error.message : "Request failed"; }
export function readPage<T>(response: Page<T> | T[]): T[] { return Array.isArray(response) ? response : response.items || []; }
export function normalizeDraft(value: unknown): Draft {
 const raw = value as {document?: unknown; id?: string; title?: string; document_type?: string; body?: {sections?: unknown}; review_state?: string; evidence_ids?: string[]};
 const item = (raw?.document || raw) as typeof raw;
 if (!item || !item.id || !item.body || !Array.isArray(item.body.sections)) throw new Error("Draft is not in the shared structured document format");
 const sections = item.body.sections.map((s, i) => {
   const section = s as {id?: string; title?: string; blocks?: Block[]};
   if (!Array.isArray(section.blocks)) throw new Error("Document section has no blocks");
   return {id: section.id || "section-" + i, title: section.title || "Section " + (i + 1), blocks: section.blocks.map((b,j) => ({...b, id: b.id || "block-" + i + "-" + j}))};
 });
 return {id:item.id,title:item.title || "Untitled draft",document_type:item.document_type || "lesson_notes",body:{...item.body,sections},review_state:item.review_state,evidence_ids:item.evidence_ids};
}
