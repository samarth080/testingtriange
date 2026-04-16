import Link from 'next/link'
import { API_URL } from '@/lib/api'

interface TriageRow {
  id: number
  github_number: number
  title: string
  confidence: string
  labels: string[]
  latency_ms: number | null
  created_at: string
}

const BADGE: Record<string, string> = {
  high: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  low: 'bg-red-100 text-red-700',
}

export default async function RepoPage({
  params,
}: {
  params: { repoId: string }
}) {
  let results: TriageRow[] = []
  try {
    const res = await fetch(
      `${API_URL}/dashboard/repos/${params.repoId}/results`,
      { cache: 'no-store' }
    )
    if (res.ok) results = await res.json()
  } catch {
    // backend not running
  }

  return (
    <div>
      <div className="mb-6">
        <Link href="/" className="text-sm text-blue-600 hover:underline">
          ← All repositories
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">Triage History</h1>
      </div>

      {results.length === 0 ? (
        <p className="text-gray-500">
          No triage results yet. New issues will be triaged automatically.
        </p>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">#</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Title</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Confidence</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Labels</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Latency</th>
                <th className="text-left px-4 py-3 text-gray-600 font-medium">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {results.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500">#{row.github_number}</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/repos/${params.repoId}/results/${row.id}`}
                      className="text-blue-600 hover:underline font-medium"
                    >
                      {row.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-1 rounded-full font-medium ${
                        BADGE[row.confidence] ?? 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {row.confidence}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {row.labels.map((label) => (
                        <span
                          key={label}
                          className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {row.latency_ms != null ? `${row.latency_ms}ms` : '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {new Date(row.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
