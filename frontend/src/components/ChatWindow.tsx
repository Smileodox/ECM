"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Citation } from "@/types/chat";
import { useChat } from "@/hooks/useChat";
import { fetchPrograms } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { CitationDrawer } from "./CitationDrawer";
import { TypingIndicator } from "./TypingIndicator";

export function ChatWindow() {
  const { messages, isStreaming, error, programName, setProgramName, sendMessage, clearMessages, retryLast } =
    useChat();
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(
    null
  );
  const [programs, setPrograms] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchPrograms().then(setPrograms);
  }, []);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleCitationClick = useCallback((citation: Citation) => {
    setSelectedCitation(citation);
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-700 text-white font-bold text-sm">
            LMU
          </div>
          <div>
            <h1 className="text-base font-semibold text-gray-900">
              campusLMU Studienassistent
            </h1>
            <p className="text-xs text-gray-500">
              Fragen zu Studien- und Pruefungsordnungen
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {programs.length > 0 && (
            <select
              value={programName || ""}
              onChange={(e) => setProgramName(e.target.value || null)}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-600 focus:border-green-500 focus:outline-none max-w-[200px]"
            >
              <option value="">Alle Studiengaenge</option>
              {programs.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          )}
          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              className="rounded-lg px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
            >
              Neues Gespraech
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-green-50">
                <svg
                  className="h-8 w-8 text-green-700"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5"
                  />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-gray-900">
                Willkommen beim campusLMU Studienassistenten
              </h2>
              <p className="mt-2 max-w-sm text-sm text-gray-500">
                Stelle mir Fragen zu Pruefungs- und Studienordnungen. Ich
                antworte mit Quellenangaben aus den offiziellen Dokumenten.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {[
                  "Wie viele ECTS umfasst der Master?",
                  "Was sind die Zugangsvoraussetzungen?",
                  "Wie lange dauert die Masterarbeit?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    className="rounded-full border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700 hover:border-blue-300 hover:bg-blue-50 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              onCitationClick={handleCitationClick}
            />
          ))}

          {isStreaming &&
            messages[messages.length - 1]?.role === "assistant" &&
            !messages[messages.length - 1]?.content && <TypingIndicator />}

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center justify-between gap-3">
              <span>{error}</span>
              <button
                onClick={retryLast}
                className="shrink-0 rounded-md bg-red-100 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-200 transition-colors"
              >
                Erneut versuchen
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput onSend={sendMessage} disabled={isStreaming} />

      {/* Citation Drawer */}
      <CitationDrawer
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />
    </div>
  );
}
