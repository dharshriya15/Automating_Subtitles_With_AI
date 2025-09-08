"use client"

import { useState } from "react"
import { VideoUpload } from "@/components/video-upload"
import { JobsList } from "@/components/jobs-list"
import { StatusMonitor } from "@/components/status-monitor"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Video, Upload, List, Monitor } from "lucide-react"

export default function VideoProcessorPage() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  const handleUploadSuccess = (jobId: string) => {
    setActiveJobId(jobId)
    setRefreshTrigger((prev) => prev + 1)
  }

  const handleJobSelect = (jobId: string) => {
    setActiveJobId(jobId)
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-8 max-w-6xl">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Video className="h-8 w-8 text-primary" />
            <h1 className="text-4xl font-bold text-balance">Video Subtitle Processor</h1>
          </div>
          <p className="text-muted-foreground text-lg text-pretty">
            Upload your videos and automatically generate subtitles with AI-powered processing
          </p>
        </div>

        <Tabs defaultValue="upload" className="space-y-6">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="upload" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              Upload Video
            </TabsTrigger>
            <TabsTrigger value="monitor" className="flex items-center gap-2">
              <Monitor className="h-4 w-4" />
              Monitor Status
            </TabsTrigger>
            <TabsTrigger value="jobs" className="flex items-center gap-2">
              <List className="h-4 w-4" />
              All Jobs
            </TabsTrigger>
          </TabsList>

          <TabsContent value="upload" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Upload Video for Processing</CardTitle>
                <CardDescription>Supported formats: MP4, AVI, MOV, MKV, WMV, FLV, WebM</CardDescription>
              </CardHeader>
              <CardContent>
                <VideoUpload onUploadSuccess={handleUploadSuccess} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="monitor" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Processing Status</CardTitle>
                <CardDescription>Monitor the progress of your video processing jobs</CardDescription>
              </CardHeader>
              <CardContent>
                <StatusMonitor jobId={activeJobId} refreshTrigger={refreshTrigger} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="jobs" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>All Processing Jobs</CardTitle>
                <CardDescription>View and manage all your video processing jobs</CardDescription>
              </CardHeader>
              <CardContent>
                <JobsList onJobSelect={handleJobSelect} refreshTrigger={refreshTrigger} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
