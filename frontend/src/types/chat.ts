export interface PreCitationInfo {
  index: number;
  section_id: string;
  section_title: string;
  absatz: string | null;
  doc_name: string;
  doc_type: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  preCitationMap?: Record<number, PreCitationInfo>;
  isSystemHint?: boolean;
}

export interface Citation {
  index: number;
  section_id: string;
  section_title: string;
  absatz: string | null;
  page_number: number;
  doc_name: string;
  source_url: string;
  content: string;
  doc_type?: string;
}
