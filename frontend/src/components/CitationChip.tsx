"use client";

import type { Citation } from "@/types/chat";

interface CitationChipProps {
  citation: Citation;
  onClick: (citation: Citation) => void;
}

export function CitationChip({ citation, onClick }: CitationChipProps) {
  const label = citation.absatz
    ? `${citation.section_id}, ${citation.absatz}`
    : citation.section_id;

  return (
    <button
      onClick={() => onClick(citation)}
      className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors cursor-pointer border border-blue-200"
      title={`${citation.section_id} ${citation.section_title}, S. ${citation.page_number}`}
    >
      <svg
        className="h-3 w-3"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={2}
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
        />
      </svg>
      {label}
    </button>
  );
}
