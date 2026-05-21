"use client";

import { Fragment, useMemo } from "react";
import type { ChatMessage, Citation } from "@/types/chat";
import { CitationChip } from "./CitationChip";

interface MessageBubbleProps {
  message: ChatMessage;
  onCitationClick: (citation: Citation) => void;
}

/**
 * Parse message content and replace [Quelle N] references with CitationChip components.
 */
function parseContent(
  content: string,
  citations: Citation[],
  onCitationClick: (citation: Citation) => void
) {
  const citationMap = new Map(citations.map((c) => [c.index, c]));
  const parts = content.split(/(\[Quelle\s+\d+\])/g);

  return parts.map((part, i) => {
    const match = part.match(/\[Quelle\s+(\d+)\]/);
    if (match) {
      const idx = parseInt(match[1], 10);
      const citation = citationMap.get(idx);
      if (citation) {
        return (
          <CitationChip
            key={i}
            citation={citation}
            onClick={onCitationClick}
          />
        );
      }
    }

    // Render text with basic line break support
    const lines = part.split("\n");
    return (
      <Fragment key={i}>
        {lines.map((line, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {renderMarkdownLine(line)}
          </Fragment>
        ))}
      </Fragment>
    );
  });
}

/** Minimal inline markdown: **bold** and bullet points. */
function renderMarkdownLine(line: string) {
  // Bullet points
  const bulletMatch = line.match(/^(\s*[-*])\s+(.*)$/);
  if (bulletMatch) {
    return (
      <span className="flex gap-2">
        <span className="text-gray-400 select-none">&bull;</span>
        <span>{renderBold(bulletMatch[2])}</span>
      </span>
    );
  }

  // Numbered lists
  const numberedMatch = line.match(/^(\s*\d+)\.\s+(.*)$/);
  if (numberedMatch) {
    return (
      <span className="flex gap-2">
        <span className="text-gray-500 select-none min-w-[1.5em] text-right">
          {numberedMatch[1]}.
        </span>
        <span>{renderBold(numberedMatch[2])}</span>
      </span>
    );
  }

  return renderBold(line);
}

/** Render **bold** text. */
function renderBold(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return part;
  });
}

export function MessageBubble({
  message,
  onCitationClick,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  const rendered = useMemo(
    () =>
      isUser
        ? message.content
        : parseContent(
            message.content,
            message.citations || [],
            onCitationClick
          ),
    [message.content, message.citations, isUser, onCitationClick]
  );

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white rounded-br-md"
            : "bg-gray-100 text-gray-800 rounded-bl-md"
        }`}
      >
        {rendered}
      </div>
    </div>
  );
}
