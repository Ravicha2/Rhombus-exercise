import { Link } from "react-router-dom";

export default function JobsPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <h1 className="text-3xl font-bold">Job Logs</h1>
      <p className="text-gray-600">List of processing jobs will appear here.</p>
      <Link to="/" className="underline text-purple-600">
        Back to Home
      </Link>
      <Link to="/jobs/123" className="underline text-purple-600">
        View Example Job
      </Link>
    </div>
  );
}
