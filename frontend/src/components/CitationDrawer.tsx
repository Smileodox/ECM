"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { Citation } from "@/types/chat";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  const isOpen = citation !== null;
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    closeRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const isWeb = citation?.doc_type === "web_1x1";
  const location = isWeb
    ? (citation?.section_title || citation?.doc_name || "")
    : citation?.absatz
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
        aria-hidden="true"
      />
      {/* Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={citation ? `Source ${citation.index}: ${location}` : "Source details"}
        className={`fixed right-0 top-0 h-full w-full max-w-lg bg-surface z-50 flex flex-col overflow-hidden transition-transform duration-300 ease-out ${isOpen ? "translate-x-0" : "translate-x-full"}`}
        style={{ boxShadow: isOpen ? "var(--drawer-shadow)" : "none" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Green accent bar */}
        <div className="h-1 bg-gradient-to-r from-lmu-green to-lmu-green-light shrink-0" />

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-default px-6 py-4">
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              Source {citation?.index}
            </h3>
            <p className="text-sm text-text-muted mt-0.5">{location}</p>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close source view"
            className="rounded-lg p-1.5 text-text-muted hover:text-text-secondary hover:bg-surface-secondary transition-all duration-150"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Metadata */}
        {citation && (
          <div className={`border-b border-border-default px-6 py-3 ${isWeb ? "bg-teal-50/50" : "bg-lmu-green-50/50"}`}>
            <div className="grid grid-cols-2 gap-2 text-xs text-text-secondary">
              <div>
                <span className="font-semibold text-text-muted">{isWeb ? "Page:" : "Document:"}</span>{" "}
                {citation.doc_name}
              </div>
              {!isWeb && citation.page_number > 0 && (
                <div>
                  <span className="font-semibold text-text-muted">Page:</span>{" "}
                  {citation.page_number}
                </div>
              )}
              {isWeb ? (
                <div>
                  <span className="font-semibold text-text-muted">Section:</span>{" "}
                  {citation.section_title}
                </div>
              ) : (
                <div>
                  <span className="font-semibold text-text-muted">Section:</span>{" "}
                  {citation.section_id} {citation.section_title}
                </div>
              )}
              {!isWeb && citation.absatz && (
                <div>
                  <span className="font-semibold text-text-muted">Subsection:</span>{" "}
                  {citation.absatz}
                </div>
              )}
            </div>
            {citation.source_url && (
              <a
                href={citation.source_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={isWeb ? `View on LMU website: ${citation.doc_name}` : `Download PDF of ${citation.doc_name}`}
                className={`mt-3 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-sm hover:shadow-md transition-all duration-200 ${isWeb ? "bg-gradient-to-r from-teal-600 to-teal-500 hover:from-teal-700 hover:to-teal-600" : "bg-gradient-to-r from-lmu-green to-lmu-green-light hover:from-lmu-green-dark hover:to-lmu-green"}`}
              >
                {isWeb ? (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                ) : (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
                  </svg>
                )}
                {isWeb ? "View on LMU website" : "Download PDF"}
              </a>
            )}
          </div>
        )}

        {/* Content */}
        {citation && (
          <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar">
            <p className="text-xs font-medium text-lmu-green uppercase tracking-wide mb-3">
              Original text
            </p>
            <div className="rounded-xl border border-lmu-green-100 bg-lmu-green-50/30 p-4 text-sm text-text-secondary leading-relaxed citation-markdown">
              <ReactMarkdown
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  strong: ({ children }) => <strong className="font-semibold text-text-primary">{children}</strong>,
                  h1: ({ children }) => <h3 className="font-semibold text-text-primary mt-3 mb-1 text-base">{children}</h3>,
                  h2: ({ children }) => <h3 className="font-semibold text-text-primary mt-3 mb-1">{children}</h3>,
                  h3: ({ children }) => <h4 className="font-semibold text-text-primary mt-2 mb-1">{children}</h4>,
                  ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
                  li: ({ children }) => <li className="mb-0.5">{children}</li>,
                }}
              >
                {citation.content}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
