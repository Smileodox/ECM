"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchChatStream } from "@/lib/api";
import type { ChatMessage, Citation } from "@/types/chat";

const STORAGE_KEY_MESSAGES = "campuslmu_messages";
const STORAGE_KEY_PROGRAM = "campuslmu_program";
const MAX_STORED_MESSAGES = 50;

let _msgCounter = 0;
function genMsgId(): string {
  return `msg-${Date.now()}-${++_msgCounter}`;
}

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY_MESSAGES);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(-MAX_STORED_MESSAGES).map((m: ChatMessage) => ({
      ...m,
      id: m.id || genMsgId(),
    }));
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
  detectedLang: string | null;
  setProgramName: (name: string | null) => void;
  sendMessage: (content: string) => Promise<void>;
  stopStreaming: () => void;
  clearMessages: () => void;
  retryLast: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [programName, setProgramName] = useState<string | null>(null);
  const [detectedLang, setDetectedLang] = useState<string | null>(null);

  useEffect(() => {
    setMessages(loadStoredMessages());
    setProgramName(loadStoredProgram());
  }, []);

  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const isStreamingRef = useRef(isStreaming);
  isStreamingRef.current = isStreaming;

  const abortRef = useRef<AbortController | null>(null);
  const rafRef = useRef<number | null>(null);
  const bufferRef = useRef("");
  const fullContentRef = useRef("");
  const lastHintedProgramRef = useRef<string | null>(null);
  const detectedLangRef = useRef<string | null>(null);

  useEffect(() => {
    try {
      const toStore = messages.slice(-MAX_STORED_MESSAGES).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        citations: m.citations,
      }));
      sessionStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(toStore));
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

      const userMessage: ChatMessage = { id: genMsgId(), role: "user", content };
      const updatedMessages = [...messagesRef.current, userMessage];
      setMessages(updatedMessages);

      // Prepare history (exclude the new user message -- it goes in the request body)
      const history = updatedMessages.slice(0, -1).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Add placeholder for assistant response
      const assistantMessage: ChatMessage = {
        id: genMsgId(),
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

        // SSE parser state — kept outside the read loop so events spanning
        // multiple chunks are handled correctly (H20)
        let eventType = "";
        let dataLines: string[] = [];

        const dispatchEvent = (type: string, data: string) => {
          try {
            const parsed = JSON.parse(data);
            if (type === "pre_citations" && parsed.citation_map) {
              preCitationMap = parsed.citation_map;
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = { ...last, preCitationMap };
                }
                return updated;
              });
            } else if (type === "token" && parsed.content) {
              bufferRef.current += parsed.content;
              scheduleFlush();
            } else if (type === "citations" && parsed.citations) {
              citations = parsed.citations;
              const normalizedContent: string | undefined = parsed.normalized_content;
              if (normalizedContent) {
                // Cancel pending RAF and lock in the backend-normalized content (C6)
                if (rafRef.current !== null) {
                  cancelAnimationFrame(rafRef.current);
                  rafRef.current = null;
                }
                bufferRef.current = "";
                fullContentRef.current = normalizedContent;
              }
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    citations,
                    ...(normalizedContent ? { content: normalizedContent } : {}),
                  };
                }
                return updated;
              });
            } else if (type === "language" && parsed.lang) {
              detectedLangRef.current = parsed.lang;
              setDetectedLang(parsed.lang);
            } else if (type === "detected_program" && parsed.program_name) {
              setProgramName(parsed.program_name);
              // Show a system hint if this is a new program detection
              if (parsed.program_name !== lastHintedProgramRef.current) {
                lastHintedProgramRef.current = parsed.program_name;
                const isEnglish = detectedLangRef.current === "en";
                const hintText = isEnglish
                  ? `Answering for the program **${parsed.program_name}**. If you mean a different program, select it from the dropdown above.`
                  : `Antwort für den Studiengang **${parsed.program_name}**. Falls du einen anderen Studiengang meinst, wähle ihn oben im Dropdown aus.`;
                const hintMsg: ChatMessage = {
                  id: genMsgId(),
                  role: "assistant",
                  content: hintText,
                  isSystemHint: true,
                };
                setMessages((prev) => {
                  // Insert hint before the last (streaming) assistant message
                  const last = prev[prev.length - 1];
                  if (last?.role === "assistant") {
                    return [...prev.slice(0, -1), hintMsg, last];
                  }
                  return [...prev, hintMsg];
                });
              }
            } else if (type === "error") {
              setError(parsed.message || "Unknown error");
            }
          } catch {
            // Skip malformed JSON
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          sseBuffer += decoder.decode(value, { stream: true });

          // Parse SSE events from buffer — accumulate data lines per event
          sseBuffer = sseBuffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
          const lines = sseBuffer.split("\n");
          sseBuffer = lines.pop() || ""; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              dataLines.push(line.slice(6));
            } else if (line === "") {
              // Blank line = event boundary: dispatch accumulated data
              if (dataLines.length > 0) {
                dispatchEvent(eventType, dataLines.join("\n"));
              }
              eventType = "";
              dataLines = [];
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
          friendlyError = "Could not connect to the server. Please check your internet connection.";
        } else if (raw.includes("500") || raw.includes("502") || raw.includes("503")) {
          friendlyError = "The server is currently unavailable. Please try again in a few seconds.";
        } else if (raw.includes("429")) {
          friendlyError = "Too many requests. Please wait a moment and try again.";
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

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const clearMessages = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    try { sessionStorage.removeItem(STORAGE_KEY_MESSAGES); } catch { /* ignore */ }
  }, []);

  const retryLast = useCallback(() => {
    const msgs = messagesRef.current;
    const lastUserIdx = msgs.findLastIndex((m) => m.role === "user");
    if (lastUserIdx === -1) return;
    const lastUserContent = msgs[lastUserIdx].content;
    // Update ref directly so sendMessage reads the trimmed history immediately
    messagesRef.current = msgs.slice(0, lastUserIdx);
    setMessages(messagesRef.current);
    setError(null);
    sendMessage(lastUserContent);
  }, [sendMessage]);

  return { messages, isStreaming, error, programName, detectedLang, setProgramName, sendMessage, stopStreaming, clearMessages, retryLast };
}
