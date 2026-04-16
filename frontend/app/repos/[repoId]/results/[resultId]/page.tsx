import Link from 'next/link'
import { API_URL } from '@/lib/api'

interface TriageDetail {
  id: number
  github_number: number
  title: string
  body: string | null
  actual_labels: string[]
  confidence: string
  labels: string[]
  duplicate_of: number | null
  relevant_files: string[]
  suggested_assignees: string[]
  reasoning: string
  latency_ms: number | null
  comment_url: string | null
  created_at: string
}

const BADGE: Record<string, string> = {
  high: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  low: 'bg-red-100 text-red-700',
}

export default async function ResultDetailPage({
  params,
}: {
  params: { repoId: string; resultId: string }
}) {
  let detail: TriageDetail | null = null
  try {
    const res = await fetch(
      `${API_URL}/dashboard/repos/${params.repoId}/results/${params.resultId}`,
      { cache: 'no-store' }
    )
    if (res.ok) detail = await res.json()
  } catch {
    // backend not running
  }

  if (!detail) {
    return (
      <div>
        <Link href={`/repos/${params.repoId}`} className="text-sm text-blue-600 hover:underline">
          ← Triage history
        </Link>
        <p className="mt-4 text-gray-500">Result not found.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <Link href={`/repos/${params.repoId}`} className="text-sm text-blue-600 hover:underline">
          ← Triage history
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          #{detail.github_number}: {detail.title}
        </h1>
      </div>

      <div className="grid gap-6">
        {/* Triage result */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            Triage Result
          </h2>
          <div className="flex items-center gap-4 mb-4">
            <div>
              <p className="text-xs text-gray-500 mb-1">Confidence</p>
              <span
                className={`text-sm px-3 py-1 rounded-full font-medium ${
                  BADGE[detail.confidence] ?? 'bg-gray-100 text-gray-600'
                }`}
              >
                {detail.confidence}
              </span>
            </div>
            {detail.duplicate_of && (
              <div>
                <p className="text-xs text-gray-500 mb-1">Duplicate of</p>
                <span className="text-sm font-medium text-gray-900">
                  #{detail.duplicate_of}
                </span>
              </div>
            )}
          </div>

          <div className="mb-4">
            <p className="text-xs text-gray-500 mb-2">Predicted labels</p>
            <div className="flex gap-2 flex-wrap">
              {detail.labels.length > 0 ? (
                detail.labels.map((l) => (
                  <span
                    key={l}
                    className="text-sm bg-blue-50 text-blue-700 px-3 py-1 rounded-full"
                  >
                    {l}
                  </span>
                ))
              ) : (
                <span className="text-sm text-gray-400">None</span>
              )}
            </div>
          </div>

          {detail.suggested_assignees.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-gray-500 mb-2">Suggested assignees</p>
              <div className="flex gap-2 flex-wrap">
                {detail.suggested_assignees.map((a) => (
                  <span
                    key={a}
                    className="text-sm bg-purple-50 text-purple-700 px-3 py-1 rounded-full"
                  >
                    @{a}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-gray-500 mb-2">Reasoning</p>
            <p className="text-sm text-gray-700 leading-relaxed">
              {detail.reasoning || '—'}
            </p>
          </div>
        </div>

        {/* Relevant files */}
        {detail.relevant_files.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Relevant Files
            </h2>
            <ul className="space-y-1">
              {detail.relevant_files.map((f) => (
                <li
                  key={f}
                  className="text-sm font-mono text-gray-700 bg-gray-50 px-3 py-1.5 rounded"
                >
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Meta */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Meta
          </h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-gray-500">Latency</dt>
              <dd className="text-gray-900 font-medium">
                {detail.latency_ms != null ? `${detail.latency_ms}ms` : '—'}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Triaged at</dt>
              <dd className="text-gray-900 font-medium">
                {new Date(detail.created_at).toLocaleString()}
              </dd>
            </div>
            {detail.comment_url && (
              <div className="col-span-2">
                <dt className="text-gray-500">GitHub comment</dt>
                <dd>
                  <a
                    href={detail.comment_url}
                    className="text-blue-600 hover:underline text-xs break-all"
                  >
                    {detail.comment_url}
                  </a>
                </dd>
              </div>
            )}
          </dl>
        </div>
      </div>
    </div>
  )
}
