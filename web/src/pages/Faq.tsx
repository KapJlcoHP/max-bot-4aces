import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { FaqItem, FaqResponse } from "../types";
import { ErrorView, Header, LoadingView } from "../components/ui";

export default function Faq() {
  const [items, setItems] = useState<FaqItem[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<FaqResponse>("/api/v1/faq")
      .then(({ items: nextItems }) => {
        setItems(nextItems);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="app narrow">
      <Header title="Частые вопросы" back="/profile" />
      <div className="screen-body faq-screen">
        {status === "loading" && (
          <div role="status" aria-live="polite">
            <LoadingView />
            <p className="muted faq-loading-label">Загружаем ответы…</p>
          </div>
        )}
        {status === "error" && <ErrorView onRetry={load} />}
        {status === "ready" && items && (
          <div className="faq-list">
            <p className="muted">Здесь собраны простые ответы о маршруте, сроках, напоминаниях и ваших данных.</p>
            {Array.from(new Set(items.map((item) => item.category))).map((category) => (
              <section className="faq-category" key={category} aria-labelledby={`faq-${category}`}>
                <h2 id={`faq-${category}`}>{category}</h2>
                <div className="faq-questions">
                  {items.filter((item) => item.category === category).sort((left, right) => left.order - right.order).map((item) => (
                    <details className="faq-item" key={item.id}>
                      <summary>{item.question}</summary>
                      <p>{item.answer}</p>
                    </details>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
