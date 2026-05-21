"use client";

import { useCallback, useRef, useState } from "react";
import { fetchChatStream } from "@/lib/api";
import type { ChatMessage, Citation } from "@/types/chat";

interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      if (isStreaming) return;

      setError(null);
      setIsStreaming(true);

      // Add user message
      const userMessage: ChatMessage = { role: "user", content };
      const updatedMessages = [...messages, userMessage];
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
        const response = await fetchChatStream(content, history);

        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let fullContent = "";
        let citations: Citation[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse SSE events from buffer
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer

          let eventType = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              const data = line.slice(6);
              try {
                const parsed = JSON.parse(data);

                if (eventType === "token" && parsed.content) {
                  fullContent += parsed.content;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last.role === "assistant") {
                      updated[updated.length - 1] = {
                        ...last,
                        content: fullContent,
                      };
                    }
                    return updated;
                  });
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
      } catch (err) {
        setError(err instanceof Error ? err.message : "Connection failed");
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
    [messages, isStreaming]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, isStreaming, error, sendMessage, clearMessages };
}
