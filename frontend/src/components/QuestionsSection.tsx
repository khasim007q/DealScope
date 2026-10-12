import { EmptyBox, SectionHead } from "./ui";

export function QuestionsSection({ questions }: { questions: string[] }) {
  return (
    <section className="section" aria-labelledby="questions-h">
      <SectionHead
        id="questions-h"
        title="Questions to ask management"
        subtitle="Public data cannot settle these. Raise them in management meetings and data-room requests."
      />
      {questions.length === 0 ? (
        <EmptyBox>No management questions were generated.</EmptyBox>
      ) : (
        <div className="card">
          <ol className="question-list" style={{ margin: 0 }}>
            {questions.map((q, i) => (
              <li key={i}>
                <span>{q}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
