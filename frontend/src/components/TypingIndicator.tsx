"use client";

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-2 animate-fade-in" role="status" aria-label="Antwort wird generiert">
      <span className="h-2 w-2 rounded-full bg-lmu-green/60 animate-typing-bounce" />
      <span className="h-2 w-2 rounded-full bg-lmu-green/60 animate-typing-bounce" style={{ animationDelay: "200ms" }} />
      <span className="h-2 w-2 rounded-full bg-lmu-green/60 animate-typing-bounce" style={{ animationDelay: "400ms" }} />
      <span className="sr-only">Antwort wird generiert…</span>
    </div>
  );
}
