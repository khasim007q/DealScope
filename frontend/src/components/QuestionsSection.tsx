import { EmptyBox } from "./ui";
import { ReportHead } from "./ReportHead";

export function QuestionsSection({ questions }: { questions: string[] }) {
  return (
    <section className="section" aria-labelledby="questions-h">
      <ReportHead
        num={3}
        title="Questions to validate with management"
        subtitle="Public data cannot settle these. Raise them in management meetings and data-room requests."
      />
      {questions.length === 0 ? (
        <EmptyBox>No management questions were generated.</EmptyBox>
      ) : (
        <ol className="question-list">
          {questions.map((q, i) => (
            <li key={i}>
              <span>{q}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
