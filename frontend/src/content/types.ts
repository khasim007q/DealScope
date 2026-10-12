// Shape of the "How it works" walkthrough content (frontend/src/content/howItWorks.ts).
// Evidence images are repository paths under evidence/ (e.g. "evidence/neatlogs/screenshots/x.png");
// the frontend loads them from the API at /api/evidence/<path relative to evidence/>.

export interface ContentTable {
  headers: string[];
  rows: string[][];
}

export interface EvidenceImage {
  path: string; // repo-relative, must start with "evidence/"
  caption: string;
}

export interface HowItWorksSection {
  id: string; // anchor id, kebab-case
  title: string;
  summary: string; // one or two sentences shown in the section header
  paragraphs: string[];
  bullets?: string[];
  table?: ContentTable;
  images?: EvidenceImage[];
}

export interface HowItWorksContent {
  intro: string;
  sections: HowItWorksSection[];
}
