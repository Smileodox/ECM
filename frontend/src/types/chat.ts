export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

export interface Citation {
  index: number;
  section_id: string;
  section_title: string;
  absatz: string | null;
  page_number: number;
  doc_name: string;
  content: string;
}
