import { Link } from "react-router-dom";

export default function HeroPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <h1 className="text-3xl font-bold">Rhombus</h1>
      <p className="text-gray-600">Upload a file and describe your data transformation.</p>
      <Link to="/jobs" className="underline text-purple-600">
        Go to Jobs
      </Link>
    </div>
  );
}
