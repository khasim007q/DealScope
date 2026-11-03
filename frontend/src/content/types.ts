// Shape of the "How it works" walkthrough content (frontend/src/content/howItWorks.ts).

export interface ContentTable {
  headers: string[];
  rows: string[][];
}

export interface HowItWorksSection {
  id: string; // anchor id, kebab-case
  title: string;
  summary: string; // one or two sentences shown in the section header
  paragraphs: string[];
  bullets?: string[];
  table?: ContentTable;
}

export interface HowItWorksContent {
  intro: string;
  sections: HowItWorksSection[];
}
