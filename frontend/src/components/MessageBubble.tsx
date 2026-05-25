"use client";

import { Fragment, useMemo } from "react";
import type { ChatMessage, Citation, PreCitationInfo } from "@/types/chat";
import { CitationChip } from "./CitationChip";

interface MessageBubbleProps {
  message: ChatMessage;
  onCitationClick: (citation: Citation) => void;
  isStreaming?: boolean;
}

function buildPreCitation(info: PreCitationInfo): Citation {
  return {
    index: info.index,
    section_id: info.section_id,
    section_title: info.section_title,
    absatz: info.absatz,
    page_number: 0,
    doc_name: info.doc_name,
    source_url: "",
    content: "",
    doc_type: info.doc_type,
  };
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseContent(
  content: string,
  citations: Citation[],
  preCitationMap: Record<number, PreCitationInfo> | undefined,
  onCitationClick: (citation: Citation) => void
) {
  const citationMap = new Map(citations.map((c) => [c.index, c]));
  const parts = content.split(/(<<cite:\d+>>|\[Quelle\s+\d+\])/g);

  return parts.map((part, i) => {
    const match = part.match(/(?:<<cite:(\d+)>>|\[Quelle\s+(\d+)\])/);
    if (match) {
      const idx = parseInt(match[1] || match[2], 10);
      const citation = citationMap.get(idx)
        ?? (preCitationMap?.[idx] ? buildPreCitation(preCitationMap[idx]) : undefined);
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

    // Escape HTML entities before markdown parsing to prevent XSS
    const sanitized = escapeHtml(part);
    const lines = sanitized.split("\n");
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

function renderMarkdownLine(line: string) {
  const headingMatch = line.match(/^(#{1,4})\s+(.*)$/);
  if (headingMatch) {
    const level = headingMatch[1].length;
    const text = headingMatch[2];
    const className =
      level === 1
        ? "text-base font-semibold mt-4 mb-1.5 text-gray-900"
        : level === 2
          ? "text-[0.94rem] font-semibold mt-4 mb-1.5 text-gray-900"
          : level === 3
            ? "text-sm font-semibold mt-3 mb-1 text-gray-800"
            : "text-sm font-medium mt-2 text-gray-800";
    return <div className={className}>{renderBold(text)}</div>;
  }

  const bulletMatch = line.match(/^(\s*[-*])\s+(.*)$/);
  if (bulletMatch) {
    return (
      <span className="flex gap-2.5 ml-1 py-0.5">
        <span className="text-lmu-green select-none">•</span>
        <span>{renderBold(bulletMatch[2])}</span>
      </span>
    );
  }

  const numberedMatch = line.match(/^(\s*\d+)\.\s+(.*)$/);
  if (numberedMatch) {
    return (
      <span className="flex gap-2.5 py-0.5">
        <span className="text-gray-400 select-none min-w-[1.5em] text-right tabular-nums">
          {numberedMatch[1]}.
        </span>
        <span>{renderBold(numberedMatch[2])}</span>
      </span>
    );
  }

  return renderBold(line);
}

function renderBold(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-gray-900">
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
  isStreaming,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  const rendered = useMemo(
    () =>
      isUser
        ? message.content
        : parseContent(
            message.content,
            message.citations || [],
            message.preCitationMap,
            onCitationClick
          ),
    [message.content, message.citations, message.preCitationMap, isUser, onCitationClick]
  );

  if (isUser) {
    return (
      <div className="flex justify-end animate-user-message-in">
        <div className="rounded-2xl rounded-br-md bg-gradient-to-br from-lmu-green to-lmu-green-dark px-4 py-2.5 text-sm text-white max-w-[75%] shadow-md">
          {rendered}
        </div>
      </div>
    );
  }

  if (!message.content) return null;

  return (
    <div className={`text-[0.9rem] leading-[1.7] text-gray-700${isStreaming ? " streaming-cursor" : ""}`}>
      {rendered}
    </div>
  );
}
