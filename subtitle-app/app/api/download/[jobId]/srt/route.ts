import { type NextRequest, NextResponse } from "next/server"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:5000"

export async function GET(request: NextRequest, { params }: { params: { jobId: string } }) {
  try {
    const response = await fetch(`${API_BASE_URL}/download/${params.jobId}/srt`)

    if (!response.ok) {
      const errorData = await response.json()
      return NextResponse.json(errorData, { status: response.status })
    }

    const blob = await response.blob()

    return new NextResponse(blob, {
      headers: {
        "Content-Type": "text/plain",
        "Content-Disposition": `attachment; filename="${params.jobId}.srt"`,
      },
    })
  } catch (error) {
    return NextResponse.json({ error: "Failed to download SRT file" }, { status: 500 })
  }
}
