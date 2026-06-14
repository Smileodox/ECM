"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ChatWindow } from "@/components/ChatWindow";

function ChatPage() {
  const subjectId = useSearchParams().get("subject");
  return (
    <main className="h-full">
      <ChatWindow subjectId={subjectId} />
    </main>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<main className="h-full" />}>
      <ChatPage />
    </Suspense>
  );
}
