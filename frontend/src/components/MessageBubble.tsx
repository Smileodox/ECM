"use client";

import { Fragment, useMemo, useState } from "react";
import type { ChatMessage, Citation, PreCitationInfo } from "@/types/chat";
import { CitationChip } from "./CitationChip";
import { submitFeedback } from "@/lib/api";

interface MessageBubbleProps {
  message: ChatMessage;
  onCitationClick: (citation: Citation) => void;
  isStreaming?: boolean;
  lastUserMessage?: string;
  onSendMessage?: (text: string) => void;
  isSystemHint?: boolean;
  detectedLang?: string | null;
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
        ? "text-base font-semibold mt-4 mb-1.5 text-text-primary"
        : level === 2
          ? "text-[0.94rem] font-semibold mt-4 mb-1.5 text-text-primary"
          : level === 3
            ? "text-sm font-semibold mt-3 mb-1 text-text-secondary"
            : "text-sm font-medium mt-2 text-text-secondary";
    return <div className={className}>{renderInline(text)}</div>;
  }

  const bulletMatch = line.match(/^(\s*[-*])\s+(.*)$/);
  if (bulletMatch) {
    return (
      <span className="flex gap-2.5 ml-1 py-0.5">
        <span className="text-lmu-green select-none">•</span>
        <span>{renderInline(bulletMatch[2])}</span>
      </span>
    );
  }

  const numberedMatch = line.match(/^(\s*\d+)\.\s+(.*)$/);
  if (numberedMatch) {
    return (
      <span className="flex gap-2.5 py-0.5">
        <span className="text-text-muted select-none min-w-[1.5em] text-right tabular-nums">
          {numberedMatch[1]}.
        </span>
        <span>{renderInline(numberedMatch[2])}</span>
      </span>
    );
  }

  return renderInline(line);
}

function renderInline(text: string) {
  // Split on bold (**...**), markdown links ([text](url)), and bare URLs
  const parts = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s<>)\]]+)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-text-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      return (
        <a
          key={i}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-lmu-green underline hover:text-lmu-green-dark"
        >
          {linkMatch[1]}
        </a>
      );
    }
    if (/^https?:\/\//.test(part)) {
      const clean = part.replace(/[.,;:!?]+$/, "");
      return (
        <a
          key={i}
          href={clean}
          target="_blank"
          rel="noopener noreferrer"
          className="text-lmu-green underline hover:text-lmu-green-dark break-all"
        >
          {clean}
        </a>
      );
    }
    return part;
  });
}


function getFollowUpSuggestions(content: string, userQuestion: string, lang: string | null | undefined): string[] {
  const lower = content.toLowerCase();
  const qLower = userQuestion.toLowerCase();
  const de = lang ? lang !== "en" : (/[äöüßÄÖÜ]/.test(content) || /\b(?:die|der|das|und|ist|für|bei|des)\b/i.test(content.slice(0, 100)));
  if (/masterarbeit|master.?s?\s*thesis/i.test(lower) && !/masterarbeit|thesis/i.test(qLower)) {
    return de
      ? ["Wie melde ich mich zur Masterarbeit an?", "Kann ich die Bearbeitungszeit verlängern?"]
      : ["How do I register for the master's thesis?", "Can I extend the master's thesis deadline?"];
  }
  if (/ects|credits?/i.test(lower) && !/ects|credits?/i.test(qLower)) {
    return de
      ? ["Welche Module sind Pflicht?", "Wie wird die Note berechnet?"]
      : ["Which modules are mandatory?", "How is the grade calculated?"];
  }
  if (/wiederholung|nicht bestanden|fail|repeat/i.test(lower)) {
    return de
      ? ["Wie viele Versuche habe ich?", "Was passiert bei endgültigem Nichtbestehen?"]
      : ["How many attempts do I have?", "What happens if I permanently fail?"];
  }
  if (/eignung|zulassung|admission|eligib/i.test(lower)) {
    return de
      ? ["Welche Unterlagen brauche ich?", "Wann ist die Bewerbungsfrist?"]
      : ["What documents do I need?", "What is the application deadline?"];
  }
  return de
    ? ["Erzähl mir mehr dazu", "Welche weiteren Regelungen gibt es?"]
    : ["Tell me more about this", "What other regulations apply?"];
}

function ThumbsUpIcon({ filled }: { filled?: boolean }) {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.633 10.25c.806 0 1.533-.446 2.031-1.08a9.041 9.041 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V2.75a.75.75 0 0 1 .75-.75 2.25 2.25 0 0 1 2.25 2.25c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282m0 0h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.423-.23H5.904m7.594-9.745a12.678 12.678 0 0 0-.75 1.32" />
    </svg>
  );
}

export function MessageBubble({
  message,
  onCitationClick,
  isStreaming,
  lastUserMessage,
  onSendMessage,
  isSystemHint,
  detectedLang,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [feedbackGiven, setFeedbackGiven] = useState<"up" | "down" | null>(null);

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

  const suggestions = useMemo(
    () => (!isUser && !isStreaming && !isSystemHint && message.content ? getFollowUpSuggestions(message.content, lastUserMessage || "", detectedLang) : []),
    [isUser, isStreaming, isSystemHint, message.content, lastUserMessage, detectedLang]
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

  const handleFeedback = (rating: "up" | "down") => {
    if (feedbackGiven) return;
    setFeedbackGiven(rating);
    submitFeedback(rating, lastUserMessage || "", message.content).catch(() => {});
  };

  return (
    <div>
      <div className={`text-[0.9rem] leading-[1.7] ${isSystemHint ? "text-text-muted italic" : "text-text-secondary"}${isStreaming ? " streaming-cursor" : ""}`}>
        {rendered}
      </div>

      {/* Feedback buttons — only for non-streaming, non-hint assistant messages */}
      {!isStreaming && !isSystemHint && (
        <div className="flex justify-end gap-1 mt-1.5">
          <button
            onClick={() => handleFeedback("up")}
            disabled={feedbackGiven !== null}
            className={`p-1 rounded-md transition-colors duration-150 ${
              feedbackGiven === "up"
                ? "text-lmu-green"
                : feedbackGiven
                  ? "text-border-strong cursor-default"
                  : "text-text-muted hover:text-lmu-green hover:bg-lmu-green-50"
            }`}
            aria-label="Helpful"
            title="Helpful"
          >
            <ThumbsUpIcon filled={feedbackGiven === "up"} />
          </button>
          <button
            onClick={() => handleFeedback("down")}
            disabled={feedbackGiven !== null}
            className={`p-1 rounded-md transition-colors duration-150 rotate-180 ${
              feedbackGiven === "down"
                ? "text-red-400"
                : feedbackGiven
                  ? "text-border-strong cursor-default"
                  : "text-text-muted hover:text-red-400 hover:bg-red-50"
            }`}
            aria-label="Not helpful"
            title="Not helpful"
          >
            <ThumbsUpIcon filled={feedbackGiven === "down"} />
          </button>
        </div>
      )}

      {/* Follow-up suggestions */}
      {suggestions.length > 0 && onSendMessage && (
        <div className="flex flex-wrap gap-2 mt-3">
          {suggestions.map((text) => (
            <button
              key={text}
              onClick={() => onSendMessage(text)}
              aria-label={`Follow-up: ${text}`}
              className="flex items-center gap-1.5 rounded-xl border border-lmu-green-100 bg-surface px-3 py-1.5 text-xs text-text-secondary shadow-sm hover:shadow-md hover:border-lmu-green-200 hover:-translate-y-0.5 transition-all duration-200"
            >
              <svg className="h-3 w-3 shrink-0 text-lmu-green" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
              </svg>
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
