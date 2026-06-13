const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchChatStream(
  message: string,
  history: { role: string; content: string }[],
  programName?: string | null,
  signal?: AbortSignal,
  modelName?: string | null
): Promise<Response> {
  return fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      program_name: programName || null,
      model_name: modelName || null,
    }),
    signal,
  });
}

export interface ModelOption {
  id: string;
  label: string;
}

export async function fetchModels(): Promise<ModelOption[]> {
  const res = await fetch(`${API_BASE}/api/models`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.models || [];
}

export async function fetchPrograms(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/programs`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.programs || [];
}

export async function submitFeedback(rating: "up" | "down", query: string, response: string): Promise<void> {
  await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, query, response }),
  });
}

