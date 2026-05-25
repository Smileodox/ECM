const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchChatStream(
  message: string,
  history: { role: string; content: string }[],
  programName?: string | null,
  signal?: AbortSignal
): Promise<Response> {
  return fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      program_name: programName || null,
    }),
    signal,
  });
}

export async function fetchPrograms(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/programs`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.programs || [];
}

