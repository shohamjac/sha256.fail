import type { ReactElement } from 'react';
import { PROBLEM_TITLES } from '../config';

interface Props {
  problems: readonly string[];
  /** The problem shown now. */
  value: string;
  onChange: (problem: string) => void;
}

/** The choice of problem: one button per problem, joined into one control. */
export function ProblemToggle({ problems, value, onChange }: Props): ReactElement {
  return (
    <div className="filters">
      <span className="filter-label" id="problem-label">Problem</span>
      <div className="segmented" role="group" aria-labelledby="problem-label">
        {problems.map((problem) => (
          <button key={problem} type="button" aria-pressed={problem === value} onClick={() => onChange(problem)}>
            {PROBLEM_TITLES[problem] ?? problem}
          </button>
        ))}
      </div>
    </div>
  );
}
