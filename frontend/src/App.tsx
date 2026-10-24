import { useEffect, useState } from "react";

type ApiState = "loading" | "ok" | "error";

export default function App() {
  const [state, setState] = useState<ApiState>("loading");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then((res) => setState(res.ok ? "ok" : "error"))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setState("error");
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>FlowOps</h1>
      {state === "loading" && <p role="status">Checking API…</p>}
      {state === "ok" && <p role="status">API is reachable.</p>}
      {state === "error" && <p role="alert">Could not reach the API.</p>}
    </main>
  );
}
