import type { Job } from "@/core/jobs/job.model";
import { JobCard } from "@/ui/components/JobCard";

export function JobList({ jobs, onSelect, emptyMessage }: { jobs: Job[]; onSelect: (id: string) => void; emptyMessage: string }) {
  if (jobs.length === 0) {
    return <p className="af-muted">{emptyMessage}</p>;
  }
  return (
    <div className="af-stack">
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} onSelect={onSelect} />
      ))}
    </div>
  );
}
