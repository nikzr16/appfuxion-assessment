import HealthBadge from "./components/HealthBadge.tsx";

export default function App() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 p-6">
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
        Document Intelligence Agent
      </h1>
      <p className="text-slate-600">Upload an invoice or receipt and get validated data.</p>
      <HealthBadge />
    </main>
  );
}
