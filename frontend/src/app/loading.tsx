export default function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex gap-1">
        <span className="h-2 w-2 rounded-full bg-text-muted animate-bounce [animation-delay:0ms]" />
        <span className="h-2 w-2 rounded-full bg-text-muted animate-bounce [animation-delay:150ms]" />
        <span className="h-2 w-2 rounded-full bg-text-muted animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  );
}
