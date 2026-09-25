import { useState } from "react";
import { Header, useToast } from "../components/ui";
import { I } from "../icons";

/** Подготовка к приёму: что взять и вопросы врачу. Чекбоксы и вопросы хранятся локально (демо). */
export default function Prep() {
  const [toast, showToast] = useToast();
  const [taken, setTaken] = useState<Record<string, boolean>>({
    "Паспорт РФ": true,
    "Полис ОМС": true,
    СНИЛС: false,
    "Медицинская карта": false,
  });
  const [questions, setQuestions] = useState<string[]>([
    "Каков план дальнейшего лечения?",
    "Нужно ли сдавать дополнительные анализы?",
    "Какие есть ограничения по режиму?",
  ]);
  const [draft, setDraft] = useState("");

  const addQuestion = () => {
    const q = draft.trim();
    if (!q) return;
    setQuestions((qs) => [...qs, q]);
    setDraft("");
    showToast("Вопрос добавлен в список");
  };

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Подготовка к приёму" back="/" />
      <div className="screen-body">
        <div className="card">
          <h3 className="h3">Что взять</h3>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 8 }}>
            {Object.entries(taken).map(([title, checked]) => (
              <button
                key={title}
                className={`check-row bare${checked ? " checked" : ""}`}
                onClick={() => setTaken((t) => ({ ...t, [title]: !t[title] }))}
              >
                <span className="cbx blue-c"><I.check size={15} /></span>
                <span className="lbl">{title}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          <h3 className="h3">Вопросы врачу</h3>
          <ul className="bullet-list" style={{ marginTop: 12 }}>
            {questions.map((q) => <li key={q}>{q}</li>)}
          </ul>
          <div className="field" style={{ marginTop: 14 }}>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Добавить свой вопрос…"
              onKeyDown={(e) => e.key === "Enter" && addQuestion()}
            />
            <button style={{ border: "none", background: "none", color: "#2563EB", cursor: "pointer" }} onClick={addQuestion} aria-label="Добавить вопрос">
              <I.plus size={20} />
            </button>
          </div>
        </div>
      </div>
      {toast}
    </div>
  );
}
