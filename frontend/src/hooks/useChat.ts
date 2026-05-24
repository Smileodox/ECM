"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchChatStream } from "@/lib/api";
import type { ChatMessage, Citation } from "@/types/chat";

const STORAGE_KEY_MESSAGES = "campuslmu_messages";
const STORAGE_KEY_PROGRAM = "campuslmu_program";
const MAX_STORED_MESSAGES = 50;

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_MESSAGES);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(-MAX_STORED_MESSAGES);
  } catch {
    return [];
  }
}

function loadStoredProgram(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY_PROGRAM) || null;
  } catch {
    return null;
  }
}

interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  programName: string | null;
  setProgramName: (name: string | null) => void;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
  retryLast: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadStoredMessages());
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [programName, setProgramName] = useState<string | null>(() => loadStoredProgram());

  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const isStreamingRef = useRef(isStreaming);
  isStreamingRef.current = isStreaming;

  const abortRef = useRef<AbortController | null>(null);
  const rafRef = useRef<number | null>(null);
  const bufferRef = useRef("");
  const fullContentRef = useRef("");

  useEffect(() => {
    try {
      const toStore = messages.slice(-MAX_STORED_MESSAGES).map((m) => ({
        role: m.role,
        content: m.content,
        citations: m.citations,
      }));
      localStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(toStore));
    } catch { /* quota exceeded — ignore */ }
  }, [messages]);

  useEffect(() => {
    try {
      if (programName) {
        localStorage.setItem(STORAGE_KEY_PROGRAM, programName);
      } else {
        localStorage.removeItem(STORAGE_KEY_PROGRAM);
      }
    } catch { /* ignore */ }
  }, [programName]);

  // Cleanup on unmount: abort in-flight request and cancel pending RAF
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (isStreamingRef.current) return;

      // Abort any previous request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setError(null);
      setIsStreaming(true);

      // Reset token batching state
      bufferRef.current = "";
      fullContentRef.current = "";

      const userMessage: ChatMessage = { role: "user", content };
      const updatedMessages = [...messagesRef.current, userMessage];
      setMessages(updatedMessages);

      // Prepare history (exclude the new user message -- it goes in the request body)
      const history = updatedMessages.slice(0, -1).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Add placeholder for assistant response
      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: "",
        citations: [],
      };
      setMessages([...updatedMessages, assistantMessage]);

      try {
        const response = await fetchChatStream(
          content,
          history,
          programName,
          controller.signal
        );

        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let sseBuffer = "";
        let citations: Citation[] = [];
        let preCitationMap: Record<number, { index: number; section_id: string; section_title: string; absatz: string | null; doc_name: string; doc_type: string }> = {};

        // Helper: schedule a single RAF to flush buffered tokens into state
        const scheduleFlush = () => {
          if (rafRef.current !== null) return; // already scheduled
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null;
            if (bufferRef.current) {
              fullContentRef.current += bufferRef.current;
              bufferRef.current = "";
              const snappedContent = fullContentRef.current;
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: snappedContent,
                  };
                }
                return updated;
              });
            }
          });
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          sseBuffer += decoder.decode(value, { stream: true });

          // Parse SSE events from buffer
          const lines = sseBuffer.split("\n");
          sseBuffer = lines.pop() || ""; // Keep incomplete line in buffer

          let eventType = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              const data = line.slice(6);
              try {
                const parsed = JSON.parse(data);

                if (eventType === "pre_citations" && parsed.citation_map) {
                  preCitationMap = parsed.citation_map;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last.role === "assistant") {
                      updated[updated.length - 1] = { ...last, preCitationMap };
                    }
                    return updated;
                  });
                } else if (eventType === "token" && parsed.content) {
                  // Batch tokens: append to buffer, schedule RAF
                  bufferRef.current += parsed.content;
                  scheduleFlush();
                } else if (eventType === "citations" && parsed.citations) {
                  citations = parsed.citations;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last.role === "assistant") {
                      updated[updated.length - 1] = { ...last, citations };
                    }
                    return updated;
                  });
                } else if (eventType === "error") {
                  setError(parsed.message || "Unknown error");
                }
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }

        // Stream ended — flush any remaining buffered tokens synchronously
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
        if (bufferRef.current) {
          fullContentRef.current += bufferRef.current;
          bufferRef.current = "";
          const finalContent = fullContentRef.current;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: finalContent,
              };
            }
            return updated;
          });
        }
      } catch (err) {
        // Silently ignore AbortError (user cancelled or component unmounted)
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }

        const raw = err instanceof Error ? err.message : "Connection failed";
        let friendlyError = raw;
        if (raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
          friendlyError = "Verbindung zum Server fehlgeschlagen. Bitte pruefe deine Internetverbindung.";
        } else if (raw.includes("500") || raw.includes("502") || raw.includes("503")) {
          friendlyError = "Der Server ist momentan nicht erreichbar. Bitte versuche es in wenigen Sekunden erneut.";
        } else if (raw.includes("429")) {
          friendlyError = "Zu viele Anfragen. Bitte warte einen Moment und versuche es dann erneut.";
        }
        setError(friendlyError);
        // Remove the empty assistant message on error
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && !last.content) {
            return prev.slice(0, -1);
          }
          return prev;
        });
      } finally {
        setIsStreaming(false);
      }
    },
    [programName]
  );

  const clearMessages = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    try { localStorage.removeItem(STORAGE_KEY_MESSAGES); } catch { /* ignore */ }
  }, []);

  const retryLast = useCallback(() => {
    const msgs = messagesRef.current;
    const lastUserIdx = msgs.findLastIndex((m) => m.role === "user");
    if (lastUserIdx === -1) return;
    const lastUserContent = msgs[lastUserIdx].content;
    setMessages(msgs.slice(0, lastUserIdx));
    setError(null);
    setTimeout(() => sendMessage(lastUserContent), 0);
  }, [sendMessage]);

  return { messages, isStreaming, error, programName, setProgramName, sendMessage, clearMessages, retryLast };
}
