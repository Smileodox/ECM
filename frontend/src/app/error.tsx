"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center px-4">
        <h2 className="text-lg font-semibold text-gray-900">
          Etwas ist schiefgelaufen
        </h2>
        <p className="mt-2 text-sm text-gray-500">
          Bitte lade die Seite neu oder versuche es erneut.
        </p>
        <button
          onClick={reset}
          className="mt-4 rounded-lg bg-green-700 px-4 py-2 text-sm text-white hover:bg-green-800 transition-colors"
        >
          Erneut versuchen
        </button>
      </div>
    </div>
  );
}
