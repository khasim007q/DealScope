import { useRef, useState, type KeyboardEvent } from "react";
import type { CompanyRow, JobRow, PersonRow } from "../api/types";
import { formatDate, formatInt, formatSignedPct } from "../lib/format";
import { EmptyBox, Icon, SectionHead, StatusPill } from "./ui";

type TabKey = "companies" | "people" | "jobs";

function periodSort(a: string, b: string): number {
  const na = parseInt(a, 10);
  const nb = parseInt(b, 10);
  if (Number.isNaN(na) || Number.isNaN(nb)) return a.localeCompare(b);
  return na - nb;
}

function GrowthCell({ growth, periods }: { growth: Record<string, number>; periods: string[] }) {
  const present = periods.filter((p) => growth[p] !== undefined);
  if (present.length === 0) return <span className="muted">n/a</span>;
  return (
    <div>
      {present.map((p) => (
        <div key={p} className={growth[p] > 0 ? "pos" : growth[p] < 0 ? "neg" : undefined}>
          <span className="muted small">{p}: </span>
          {formatSignedPct(growth[p])}
        </div>
      ))}
    </div>
  );
}

function CompaniesTable({ rows }: { rows: CompanyRow[] }) {
  const totalPeriods = Array.from(new Set(rows.flatMap((r) => Object.keys(r.total_growth)))).sort(periodSort);
  const engPeriods = Array.from(new Set(rows.flatMap((r) => Object.keys(r.engineering_growth)))).sort(periodSort);
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Companies compared</caption>
        <thead>
          <tr>
            <th scope="col">Company</th>
            <th scope="col">Role</th>
            <th scope="col" className="num">Headcount</th>
            <th scope="col">Headcount growth</th>
            <th scope="col" className="num">Engineers</th>
            <th scope="col">Engineering growth</th>
            <th scope="col" className="num">Open jobs</th>
            <th scope="col">Data quality</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.domain}>
              <td>
                <strong>{r.name ?? r.domain}</strong>
                {r.name ? <div className="muted small">{r.domain}</div> : null}
              </td>
              <td>
                <StatusPill tone={r.role === "Target" ? "info" : "neutral"}>{r.role}</StatusPill>
              </td>
              <td className="num">{formatInt(r.headcount)}</td>
              <td>
                <GrowthCell growth={r.total_growth} periods={totalPeriods} />
              </td>
              <td className="num">{formatInt(r.engineering_headcount)}</td>
              <td>
                <GrowthCell growth={r.engineering_growth} periods={engPeriods} />
              </td>
              <td className="num">{formatInt(r.open_jobs)}</td>
              <td>
                {r.data_quality_flags.length > 0 ? (
                  <ul className="flag-list">
                    {r.data_quality_flags.map((f, i) => (
                      <li key={i}>
                        <span className="sr-only">Warning: </span>
                        {f}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="muted small">No issues flagged</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PeopleTable({ rows }: { rows: PersonRow[] }) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">People who held roles at the target</caption>
        <thead>
          <tr>
            <th scope="col">Role group</th>
            <th scope="col">Title at target</th>
            <th scope="col">Status</th>
            <th scope="col">Now at</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.ref}>
              <td>{p.role_group}</td>
              <td>{p.title_at_target ?? <span className="muted">Unknown</span>}</td>
              <td>
                {p.status}
                {p.left_target ? <div className="muted small">Left {p.left_target}</div> : null}
              </td>
              <td>
                {p.now_at ? (
                  <>
                    {p.now_at}{" "}
                    {p.now_at_competitor ? <StatusPill tone="caution">Competitor</StatusPill> : null}
                  </>
                ) : (
                  <span className="muted">Not known</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function safeUrl(u: string | null): string | null {
  if (!u) return null;
  try {
    const parsed = new URL(u);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function JobsTable({ rows }: { rows: JobRow[] }) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Open job postings at the target</caption>
        <thead>
          <tr>
            <th scope="col">Title</th>
            <th scope="col">Capability</th>
            <th scope="col">Posted</th>
            <th scope="col">Reposted</th>
            <th scope="col" className="num">Openings</th>
            <th scope="col">Posting</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((j, i) => {
            const href = safeUrl(j.url);
            return (
              <tr key={`${j.evidence_id}-${i}`}>
                <td>{j.title}</td>
                <td>{j.capability}</td>
                <td>{j.posted ? formatDate(j.posted) : <span className="muted">n/a</span>}</td>
                <td>{j.reposted === null ? <span className="muted">Unknown</span> : j.reposted ? "Yes" : "No"}</td>
                <td className="num">{formatInt(j.openings)}</td>
                <td>
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      View posting <Icon name="external" size={12} />
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : (
                    <span className="muted">No link</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface Props {
  companies: CompanyRow[];
  people: PersonRow[];
  jobs: JobRow[];
}

export function EvidenceTabs({ companies, people, jobs }: Props) {
  const [tab, setTab] = useState<TabKey>("companies");
  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "companies", label: "Companies", count: companies.length },
    { key: "people", label: "People", count: people.length },
    { key: "jobs", label: "Job postings", count: jobs.length },
  ];
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, idx: number) => {
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    setTab(tabs[next].key);
    refs.current[tabs[next].key]?.focus();
  };

  return (
    <section className="section" aria-labelledby="evidence-h">
      <SectionHead
        id="evidence-h"
        title="Evidence"
        subtitle="The underlying public data the signals and findings are built from."
      />
      <div className="tabs" role="tablist" aria-label="Evidence type">
        {tabs.map((t, i) => (
          <button
            key={t.key}
            ref={(el) => {
              refs.current[t.key] = el;
            }}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            className="tab"
            aria-selected={tab === t.key}
            aria-controls={`panel-${t.key}`}
            tabIndex={tab === t.key ? 0 : -1}
            onClick={() => setTab(t.key)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
            <span className="count">({t.count})</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "companies" ? (
          companies.length ? (
            <CompaniesTable rows={companies} />
          ) : (
            <EmptyBox>No company data was collected.</EmptyBox>
          )
        ) : tab === "people" ? (
          people.length ? (
            <PeopleTable rows={people} />
          ) : (
            <EmptyBox>No people-history data was collected.</EmptyBox>
          )
        ) : jobs.length ? (
          <JobsTable rows={jobs} />
        ) : (
          <EmptyBox>No job postings were collected.</EmptyBox>
        )}
      </div>
    </section>
  );
}
