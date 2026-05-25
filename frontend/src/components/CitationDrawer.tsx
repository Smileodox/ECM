"use client";

import { useEffect } from "react";
import type { Citation } from "@/types/chat";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  const isOpen = citation !== null;

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const location = citation?.absatz
    ? `${citation.section_id} ${citation.section_title}, ${citation.absatz}`
    : citation
      ? `${citation.section_id} ${citation.section_title}`
      : "";

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 bg-black/20 z-40 transition-opacity duration-300 ${isOpen ? "opacity-100" : "opacity-0 pointer-events-none"}`}
        onClick={onClose}
      />
      {/* Drawer */}
      <div
        className={`fixed right-0 top-0 h-full w-full max-w-lg bg-white z-50 flex flex-col overflow-hidden transition-transform duration-300 ease-out ${isOpen ? "translate-x-0" : "translate-x-full"}`}
        style={{ boxShadow: isOpen ? "var(--drawer-shadow)" : "none" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Green accent bar */}
        <div className="h-1 bg-gradient-to-r from-lmu-green to-lmu-green-light shrink-0" />

        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">
              Quelle {citation?.index}
            </h3>
            <p className="text-sm text-gray-500 mt-0.5">{location}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-all duration-150"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Metadata */}
        {citation && (
          <div className="border-b px-6 py-3 bg-lmu-green-50/50">
            <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
              <div>
                <span className="font-semibold text-gray-500">Dokument:</span>{" "}
                {citation.doc_name}
              </div>
              {citation.page_number > 0 && (
                <div>
                  <span className="font-semibold text-gray-500">Seite:</span>{" "}
                  {citation.page_number}
                </div>
              )}
              <div>
                <span className="font-semibold text-gray-500">Paragraph:</span>{" "}
                {citation.section_id} {citation.section_title}
              </div>
              {citation.absatz && (
                <div>
                  <span className="font-semibold text-gray-500">Absatz:</span>{" "}
                  {citation.absatz}
                </div>
              )}
            </div>
            {citation.source_url && (
              <a
                href={citation.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-lmu-green to-lmu-green-light px-4 py-2 text-sm font-medium text-white shadow-sm hover:shadow-md hover:from-lmu-green-dark hover:to-lmu-green transition-all duration-200"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
                PDF herunterladen
              </a>
            )}
          </div>
        )}

        {/* Content */}
        {citation && (
          <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar">
            <p className="text-xs font-medium text-lmu-green uppercase tracking-wide mb-3">
              Originaltext
            </p>
            <div className="rounded-xl border border-lmu-green-100 bg-lmu-green-50/30 p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
              {citation.content}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
