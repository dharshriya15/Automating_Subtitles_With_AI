"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { RefreshCw, FileText, Video, AlertCircle, Eye } from "lucide-react"

interface Job {
  status: string
  message: string
  filename: string
  uploaded_at: string
  progress?: number
}

interface JobsListProps {
  onJobSelect: (jobId: string) => void
  refreshTrigger?: number
}

export function JobsList({ onJobSelect, refreshTrigger }: JobsListProps) {
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchJobs = async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch("/api/jobs")
      const data = await response.json()

      if (response.ok) {
        setJobs(data)
      } else {
        setError("Failed to fetch jobs")
      }
    } catch (err) {
      setError("Network error. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchJobs()
  }, [refreshTrigger])

  const getStatusVariant = (status: string) => {
    switch (status) {
      case "completed":
        return "default" as const
      case "failed":
      case "error":
        return "destructive" as const
      default:
        return "secondary" as const
    }
  }

  const downloadFile = async (jobId: string, type: "video" | "srt") => {
    try {
      const endpoint = type === "video" ? `/api/download/${jobId}` : `/api/download/${jobId}/srt`
      const response = await fetch(endpoint)

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = type === "video" ? `${jobId}_with_subtitles.mp4` : `${jobId}.srt`
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } else {
        const data = await response.json()
        setError(data.error || "Download failed")
      }
    } catch (err) {
      setError("Download failed. Please try again.")
    }
  }

  const jobEntries = Object.entries(jobs).sort(
    ([, a], [, b]) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">Processing Jobs ({jobEntries.length})</h3>
        <Button onClick={fetchJobs} disabled={loading} variant="outline" size="sm">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {jobEntries.length === 0 && !loading ? (
        <Card>
          <CardContent className="p-6 text-center text-muted-foreground">
            No processing jobs found. Upload a video to get started.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {jobEntries.map(([jobId, job]) => (
            <Card key={jobId}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant={getStatusVariant(job.status)}>{job.status.toUpperCase()}</Badge>
                      <span className="text-sm font-mono text-muted-foreground truncate">{jobId}</span>
                    </div>
                    <p className="font-medium truncate">{job.filename}</p>
                    <p className="text-sm text-muted-foreground">{new Date(job.uploaded_at).toLocaleString()}</p>
                    <p className="text-sm text-muted-foreground mt-1">{job.message}</p>
                  </div>

                  <div className="flex items-center gap-2 ml-4">
                    <Button onClick={() => onJobSelect(jobId)} variant="outline" size="sm">
                      <Eye className="h-4 w-4" />
                    </Button>

                    {job.status === "completed" && (
                      <>
                        <Button onClick={() => downloadFile(jobId, "video")} variant="outline" size="sm">
                          <Video className="h-4 w-4" />
                        </Button>
                        <Button onClick={() => downloadFile(jobId, "srt")} variant="outline" size="sm">
                          <FileText className="h-4 w-4" />
                        </Button>
                      </>
                    )}

                    {["embedding", "rendering"].includes(job.status) && (
                      <Button onClick={() => downloadFile(jobId, "srt")} variant="outline" size="sm">
                        <FileText className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
