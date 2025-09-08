"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RefreshCw, Clock, CheckCircle, AlertCircle, FileText, Video } from "lucide-react"

interface JobStatus {
  status: string
  message: string
  filename: string
  uploaded_at: string
  progress?: number
}

interface StatusMonitorProps {
  jobId: string | null
  refreshTrigger?: number
}

export function StatusMonitor({ jobId: initialJobId, refreshTrigger }: StatusMonitorProps) {
  const [jobId, setJobId] = useState(initialJobId || "")
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchStatus = async (id: string) => {
    if (!id.trim()) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/status/${id}`)
      const data = await response.json()

      if (response.ok) {
        setStatus(data)
      } else {
        setError(data.error || "Failed to fetch status")
        setStatus(null)
      }
    } catch (err) {
      setError("Network error. Please try again.")
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialJobId) {
      setJobId(initialJobId)
      fetchStatus(initialJobId)
    }
  }, [initialJobId, refreshTrigger])

  useEffect(() => {
    if (status && ["queued", "processing", "transcribing", "embedding", "rendering"].includes(status.status)) {
      const interval = setInterval(() => {
        fetchStatus(jobId)
      }, 2000)

      return () => clearInterval(interval)
    }
  }, [status, jobId])

  const getStatusIcon = (statusType: string) => {
    switch (statusType) {
      case "completed":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case "failed":
      case "error":
        return <AlertCircle className="h-4 w-4 text-red-500" />
      default:
        return <Clock className="h-4 w-4 text-blue-500" />
    }
  }

  const getStatusVariant = (statusType: string) => {
    switch (statusType) {
      case "completed":
        return "default" as const
      case "failed":
      case "error":
        return "destructive" as const
      default:
        return "secondary" as const
    }
  }

  const downloadFile = async (type: "video" | "srt") => {
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

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="flex-1">
          <Label htmlFor="jobId">Job ID</Label>
          <Input
            id="jobId"
            placeholder="Enter job ID to monitor"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          />
        </div>
        <div className="flex items-end gap-2">
          <Button onClick={() => fetchStatus(jobId)} disabled={loading || !jobId.trim()}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Check Status
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {status && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Processing Status</span>
              <Badge variant={getStatusVariant(status.status)} className="flex items-center gap-1">
                {getStatusIcon(status.status)}
                {status.status.toUpperCase()}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="font-medium">Filename:</span>
                <p className="text-muted-foreground">{status.filename}</p>
              </div>
              <div>
                <span className="font-medium">Uploaded:</span>
                <p className="text-muted-foreground">{new Date(status.uploaded_at).toLocaleString()}</p>
              </div>
            </div>

            <div>
              <span className="font-medium">Status Message:</span>
              <p className="text-muted-foreground mt-1">{status.message}</p>
            </div>

            {status.progress !== undefined && (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span>Progress</span>
                  <span>{status.progress}%</span>
                </div>
                <Progress value={status.progress} />
              </div>
            )}

            {status.status === "completed" && (
              <div className="flex gap-2 pt-4">
                <Button onClick={() => downloadFile("video")} className="flex-1">
                  <Video className="mr-2 h-4 w-4" />
                  Download Video
                </Button>
                <Button onClick={() => downloadFile("srt")} variant="outline" className="flex-1">
                  <FileText className="mr-2 h-4 w-4" />
                  Download SRT
                </Button>
              </div>
            )}

            {["embedding", "rendering"].includes(status.status) && (
              <Button onClick={() => downloadFile("srt")} variant="outline" className="w-full">
                <FileText className="mr-2 h-4 w-4" />
                Download SRT (Available)
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
