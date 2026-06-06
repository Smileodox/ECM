"use client";

import type { Citation } from "@/types/chat";

interface CitationChipProps {
  citation: Citation;
  onClick: (citation: Citation) => void;
}

export function CitationChip({ citation, onClick }: CitationChipProps) {
  const isWeb = citation.doc_type === "web_1x1";
  const label = isWeb
    ? `Quelle ${citation.index}`
    : citation.absatz
      ? `${citation.section_id}, ${citation.absatz}`
      : citation.section_id;

  const chipClass = isWeb
    ? "inline-flex items-center gap-1 rounded-full bg-teal-50 border border-teal-200 px-2.5 py-0.5 text-xs font-medium text-teal-700 hover:bg-teal-100 hover:shadow-sm hover:scale-105 active:scale-100 transition-all duration-150 cursor-pointer align-baseline animate-chip-highlight"
    : "inline-flex items-center gap-1 rounded-full bg-lmu-green-50 border border-lmu-green-200 px-2.5 py-0.5 text-xs font-medium text-lmu-green hover:bg-lmu-green-100 hover:shadow-sm hover:scale-105 active:scale-100 transition-all duration-150 cursor-pointer align-baseline animate-chip-highlight";

  const titleText = isWeb
    ? `${citation.doc_name}: ${citation.section_title}`
    : `${citation.section_id} ${citation.section_title}${citation.page_number > 0 ? `, p. ${citation.page_number}` : ""}`;

  return (
    <button
      onClick={() => onClick(citation)}
      className={chipClass}
      aria-label={`View source: ${titleText}`}
      title={titleText}
    >
      {isWeb ? (
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5a17.92 17.92 0 0 1-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
      )}
      <span>{label}</span>
    </button>
  );
}
