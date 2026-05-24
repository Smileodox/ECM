"use client";

import type { Citation } from "@/types/chat";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  if (!citation) return null;

  const location = citation.absatz
    ? `${citation.section_id} ${citation.section_title}, ${citation.absatz}`
    : `${citation.section_id} ${citation.section_title}`;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
      />
      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-lg bg-white shadow-xl z-50 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">
              Quelle {citation.index}
            </h3>
            <p className="text-sm text-gray-500">{location}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Metadata */}
        <div className="border-b px-6 py-3 bg-gray-50">
          <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
            <div>
              <span className="font-medium">Dokument:</span>{" "}
              {citation.doc_name}
            </div>
            <div>
              <span className="font-medium">Seite:</span>{" "}
              {citation.page_number}
            </div>
            <div>
              <span className="font-medium">Paragraph:</span>{" "}
              {citation.section_id} {citation.section_title}
            </div>
            {citation.absatz && (
              <div>
                <span className="font-medium">Absatz:</span>{" "}
                {citation.absatz}
              </div>
            )}
          </div>
          {citation.source_url && (
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-green-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-800 transition-colors"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
              PDF herunterladen
            </a>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">
            Originaltext
          </p>
          <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
            {citation.content}
          </div>
        </div>
      </div>
    </>
  );
}
