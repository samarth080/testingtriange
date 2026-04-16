import Link from 'next/link'
import { API_URL } from '@/lib/api'

interface Repo {
  id: number
  owner: string
  name: string
  backfill_status: string
  created_at: string
}

export default async function HomePage() {
  let repos: Repo[] = []
  try {
    const res = await fetch(`${API_URL}/dashboard/repos`, { cache: 'no-store' })
    if (res.ok) repos = await res.json()
  } catch {
    // backend not running — show empty state
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Repositories</h1>
      {repos.length === 0 ? (
        <p className="text-gray-500">
          No repositories found. Install the GitHub App on a repo to get started.
        </p>
      ) : (
        <div className="grid gap-4">
          {repos.map((repo) => (
            <Link
              key={repo.id}
              href={`/repos/${repo.id}`}
              className="block bg-white rounded-lg border border-gray-200 px-6 py-4 hover:border-blue-400 hover:shadow-sm transition-all"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-900">
                  {repo.owner}/{repo.name}
                </span>
                <span
                  className={`text-xs px-2 py-1 rounded-full font-medium ${
                    repo.backfill_status === 'done'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-yellow-100 text-yellow-700'
                  }`}
                >
                  {repo.backfill_status}
                </span>
              </div>
              <p className="text-sm text-gray-500 mt-1">
                Indexed {new Date(repo.created_at).toLocaleDateString()}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
