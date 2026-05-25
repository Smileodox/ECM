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
  const { messages, isStreaming, error, programName, setProgramName, sendMessage, stopStreaming, clearMessages, retryLast } =
    useChat();
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(
    null
  );
  const [programs, setPrograms] = useState<string[]>([]);
  const [programsError, setProgramsError] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const loadPrograms = useCallback(() => {
    setProgramsError(false);
    fetchPrograms()
      .then(setPrograms)
      .catch(() => setProgramsError(true));
  }, []);

  useEffect(() => { loadPrograms(); }, [loadPrograms]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < 120) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (container) {
      setIsScrolled(container.scrollTop > 8);
    }
  }, []);

  const handleCitationClick = useCallback((citation: Citation) => {
    setSelectedCitation(citation);
  }, []);

  return (
    <div className="flex h-full flex-col lmu-gradient-bg">
      {/* Accent bar */}
      <div className="h-[3px] shrink-0 bg-gradient-to-r from-lmu-green via-lmu-green-light to-lmu-green" />

      {/* Header */}
      <header className={`flex items-center justify-between gap-4 px-6 py-3 border-b transition-all duration-300 shrink-0 ${isScrolled ? "header-scrolled border-transparent" : "bg-white/80 border-gray-100"}`}>
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-lmu-green text-white shadow-[0_2px_8px_rgba(0,102,51,0.2)]">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60 60 0 0 0-.491 6.347A48.6 48.6 0 0 1 12 20.904a48.6 48.6 0 0 1 8.232-4.41 61 61 0 0 0-.491-6.347m-15.482 0a51 51 0 0 0-3.658.816A50 50 0 0 1 12 2.25c3.67 0 7.213.394 10.643 1.136a52 52 0 0 0-3.658-.816M4.26 10.147A50.1 50.1 0 0 1 12 8.443 50.1 50.1 0 0 1 19.74 10.147" />
            </svg>
          </div>
          <div className="hidden sm:block">
            <h1 className="text-sm font-semibold text-gray-900 tracking-tight">
              campusLMU Studienassistent
            </h1>
            <span className="text-xs text-gray-400">KI-Studienberatung</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          {programsError ? (
            <button onClick={loadPrograms} className="text-xs text-red-500 hover:underline shrink-0">
              Laden fehlgeschlagen — Wiederholen
            </button>
          ) : programs.length > 0 ? (
            <select
              value={programName || ""}
              onChange={(e) => setProgramName(e.target.value || null)}
              aria-label="Studiengang auswählen"
              className="min-w-0 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 focus:border-lmu-green focus:ring-1 focus:ring-lmu-green/20 focus:outline-none transition-colors duration-150"
            >
              <option value="">Alle Studiengänge</option>
              {programs.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          ) : null}
          {messages.length > 0 && (
            <button
              onClick={() => {
                if (window.confirm("Gespräch löschen und neu starten?")) clearMessages();
              }}
              className="shrink-0 rounded-full p-2 text-gray-400 hover:bg-lmu-green-50 hover:text-lmu-green transition-colors duration-150"
              aria-label="Neues Gespräch"
              title="Neues Gespräch"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
              </svg>
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto custom-scrollbar" onScroll={handleScroll}>
        <div
          role="log"
          aria-live="polite"
          aria-label="Gesprächsverlauf"
          className="mx-auto max-w-2xl space-y-6 px-6 py-8"
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-lmu-green to-lmu-green-dark text-white shadow-lg animate-gentle-pulse animate-welcome-fade-up">
                <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60 60 0 0 0-.491 6.347A48.6 48.6 0 0 1 12 20.904a48.6 48.6 0 0 1 8.232-4.41 61 61 0 0 0-.491-6.347m-15.482 0a51 51 0 0 0-3.658.816A50 50 0 0 1 12 2.25c3.67 0 7.213.394 10.643 1.136a52 52 0 0 0-3.658-.816M4.26 10.147A50.1 50.1 0 0 1 12 8.443 50.1 50.1 0 0 1 19.74 10.147" />
                </svg>
              </div>
              <h2 className="text-2xl font-semibold text-gray-900 animate-welcome-fade-up stagger-2">
                Wie kann ich dir helfen?
              </h2>
              <p className="mt-2 max-w-md text-sm text-gray-400 animate-welcome-fade-up stagger-3">
                Fragen zu Prüfungs- und Studienordnungen, Eignungssatzungen und Zulassungsordnungen
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                {[
                  {
                    text: programName ? `Wie viele ECTS hat der Master ${programName}?` : "Wie viele ECTS hat der Master?",
                    icon: "M4.26 10.147a60 60 0 0 0-.491 6.347A48.6 48.6 0 0 1 12 20.904a48.6 48.6 0 0 1 8.232-4.41 61 61 0 0 0-.491-6.347m-15.482 0a51 51 0 0 0-3.658.816A50 50 0 0 1 12 2.25c3.67 0 7.213.394 10.643 1.136a52 52 0 0 0-3.658-.816M4.26 10.147A50.1 50.1 0 0 1 12 8.443 50.1 50.1 0 0 1 19.74 10.147",
                  },
                  {
                    text: programName ? `Zugangsvoraussetzungen für ${programName}?` : "Was sind die Zugangsvoraussetzungen?",
                    icon: "M9 12.75 11.25 15 15 9.75m-3-7.036A11.96 11.96 0 0 1 3.598 6 11.97 11.97 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622A12 12 0 0 0 20.402 6a12 12 0 0 0-8.402-3.286Z",
                  },
                  {
                    text: "Wie lange dauert die Masterarbeit?",
                    icon: "M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
                  },
                ].map((q, idx) => (
                  <button
                    key={q.text}
                    onClick={() => sendMessage(q.text)}
                    className={`flex items-center gap-2.5 rounded-2xl border border-lmu-green-100 bg-white px-5 py-3.5 text-sm text-gray-600 shadow-sm hover:shadow-md hover:border-lmu-green-200 hover:-translate-y-0.5 transition-all duration-200 animate-welcome-fade-up stagger-${idx + 4}`}
                  >
                    <svg className="h-4 w-4 shrink-0 text-lmu-green" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d={q.icon} />
                    </svg>
                    {q.text}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => {
            // Find the last user message before this assistant message
            let lastUserMsg = "";
            if (msg.role === "assistant") {
              for (let i = idx - 1; i >= 0; i--) {
                if (messages[i].role === "user") {
                  lastUserMsg = messages[i].content;
                  break;
                }
              }
            }
            return (
              <MessageBubble
                key={msg.id}
                message={msg}
                onCitationClick={handleCitationClick}
                isStreaming={isStreaming && idx === messages.length - 1 && msg.role === "assistant"}
                lastUserMessage={lastUserMsg}
                onSendMessage={sendMessage}
                isSystemHint={msg.isSystemHint}
              />
            );
          })}

          {isStreaming &&
            messages[messages.length - 1]?.role === "assistant" &&
            !messages[messages.length - 1]?.content && <TypingIndicator />}

          {error && (
            <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600 flex items-center justify-between gap-3 shadow-sm animate-message-in">
              <span>{error}</span>
              <button
                onClick={retryLast}
                className="shrink-0 rounded-full px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-100 transition-colors"
              >
                Erneut versuchen
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput onSend={sendMessage} onStop={stopStreaming} isStreaming={isStreaming} disabled={false} />

      {/* Legal disclaimer */}
      <p className="shrink-0 border-t border-gray-100 px-4 py-1.5 text-center text-[0.7rem] text-gray-400">
        KI-Antworten können Fehler enthalten — maßgeblich sind die offiziellen Ordnungen
      </p>

      {/* Citation Drawer */}
      <CitationDrawer
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />
    </div>
  );
}
