const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchChatStream(
  message: string,
  history: { role: string; content: string }[]
): Promise<Response> {
  return fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
}

export async function triggerIngest(): Promise<{
  documents_processed: number;
  chunks_created: number;
  chunks_indexed: number;
}> {
  const res = await fetch(`${API_BASE}/api/ingest`, { method: "POST" });
  if (!res.ok) throw new Error(`Ingest failed: ${res.status}`);
  return res.json();
}
