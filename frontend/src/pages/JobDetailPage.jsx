import { useParams, Link } from "react-router-dom";

export default function JobDetailPage() {
  const { id } = useParams();

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <h1 className="text-3xl font-bold">Job Detail</h1>
      <p className="text-gray-600">Job ID: {id}</p>
      <Link to="/jobs" className="underline text-purple-600">
        Back to Jobs
      </Link>
    </div>
  );
}
