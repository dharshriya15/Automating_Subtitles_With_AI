import { type NextRequest, NextResponse } from "next/server"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:5000"

export async function GET(request: NextRequest, { params }: { params: { jobId: string } }) {
  try {
    const response = await fetch(`${API_BASE_URL}/download/${params.jobId}`)

    if (!response.ok) {
      const errorData = await response.json()
      return NextResponse.json(errorData, { status: response.status })
    }

    const blob = await response.blob()

    return new NextResponse(blob, {
      headers: {
        "Content-Type": "video/mp4",
        "Content-Disposition": `attachment; filename="${params.jobId}_with_subtitles.mp4"`,
      },
    })
  } catch (error) {
    return NextResponse.json({ error: "Failed to download video" }, { status: 500 })
  }
}
