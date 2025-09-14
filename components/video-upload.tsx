"use client"

import { useState, useCallback } from "react"
import { useDropzone } from "react-dropzone"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent } from "@/components/ui/card"
import { Upload, File, CheckCircle, AlertCircle, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface VideoUploadProps {
  onUploadSuccess: (jobId: string) => void
}

export function VideoUpload({ onUploadSuccess }: VideoUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const file = acceptedFiles[0]
    if (file) {
      setSelectedFile(file)
      setError(null)
      setSuccess(null)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "video/*": [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"],
    },
    maxFiles: 1,
    onDropRejected: (fileRejections) => {
      setError("Invalid file type. Please upload a video file.")
    },
  })

  const uploadVideo = async () => {
    if (!selectedFile) return

    setUploading(true)
    setUploadProgress(0)
    setError(null)
    setSuccess(null)

    const formData = new FormData()
    formData.append("video", selectedFile)

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      })

      const data = await response.json()

      if (response.ok) {
        setSuccess(`Upload successful! Job ID: ${data.job_id}`)
        onUploadSuccess(data.job_id)
        setSelectedFile(null)
      } else {
        setError(data.error || "Upload failed")
      }
    } catch (err) {
      setError("Network error. Please try again.")
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const removeFile = () => {
    setSelectedFile(null)
    setError(null)
    setSuccess(null)
  }

  return (
    <div className="space-y-4">
      {!selectedFile ? (
        <Card>
          <CardContent className="p-6">
            <div
              {...getRootProps()}
              className={cn(
                "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
                isDragActive ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50",
              )}
            >
              <input {...getInputProps()} />
              <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-lg font-medium mb-2">
                {isDragActive ? "Drop your video here" : "Drag & drop your video here"}
              </p>
              <p className="text-muted-foreground mb-4">or click to browse files</p>
              <Button variant="outline">Choose Video File</Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between p-4 border rounded-lg">
              <div className="flex items-center gap-3">
                <File className="h-8 w-8 text-primary" />
                <div>
                  <p className="font-medium">{selectedFile.name}</p>
                  <p className="text-sm text-muted-foreground">{(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</p>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={removeFile} disabled={uploading}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {uploading && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>Uploading...</span>
            <span>{uploadProgress}%</span>
          </div>
          <Progress value={uploadProgress} />
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert>
          <CheckCircle className="h-4 w-4" />
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      )}

      {selectedFile && !uploading && (
        <Button onClick={uploadVideo} className="w-full" size="lg">
          <Upload className="mr-2 h-4 w-4" />
          Start Processing
        </Button>
      )}
    </div>
  )
}
