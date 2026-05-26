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
        <h2 className="text-lg font-semibold text-text-primary">
          Something went wrong
        </h2>
        <p className="mt-2 text-sm text-text-muted">
          Please reload the page or try again.
        </p>
        <button
          onClick={reset}
          className="mt-4 rounded-lg bg-green-700 px-4 py-2 text-sm text-white hover:bg-green-800 transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
