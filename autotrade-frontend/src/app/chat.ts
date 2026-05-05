import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface ChatResponse {
  answer: string;
  sources: string[];
}

@Injectable({
  providedIn: 'root'
})
export class ChatService {
  private apiUrl = 'http://127.0.0.1:8000';

  constructor(private http: HttpClient) { }

  // ─────────────────────────────────────────────
  // 1. Fetch old messages when the user opens the app
  // ─────────────────────────────────────────────
  getHistory(sessionId: string): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/history/${sessionId}`);
  }

  // ─────────────────────────────────────────────
  // 2. UPGRADED: Stream Text Messages (with chunk buffer)
  // ─────────────────────────────────────────────
  async *sendMessageStream(question: string, sessionId: string) {
    const response = await fetch(`${this.apiUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question, session_id: sessionId })
    });

    // 🛡️ Guard: if the server returns a non-200 status (e.g. 500),
    // read the error body and throw so the UI can display it.
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Server Error: ${response.status} - ${errorText.substring(0, 500)}`);
    }

    if (!response.body) throw new Error('No response body');

    // Use the shared SSE parser to safely handle sliced chunks
    yield* this.parseSSEStream(response.body);
  }

  // ─────────────────────────────────────────────
  // 3. UPGRADED: Stream Audio Messages (with chunk buffer)
  // ─────────────────────────────────────────────
  async *sendAudioStream(audioBlob: Blob, sessionId: string) {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice_memo.webm');
    formData.append('session_id', sessionId);

    const response = await fetch(`${this.apiUrl}/audio-chat/stream`, {
      method: 'POST',
      body: formData
    });

    // 🛡️ Guard: if the server returns a non-200 status (e.g. 500),
    // read the error body and throw so the UI can display it.
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Server Error: ${response.status} - ${errorText.substring(0, 500)}`);
    }

    if (!response.body) throw new Error('No response body');

    // Use the shared SSE parser to safely handle sliced chunks
    yield* this.parseSSEStream(response.body);
  }

  // ─────────────────────────────────────────────
  // 4. CORE FIX: Buffered SSE Stream Parser
  //
  //    The browser's ReadableStream can deliver chunks at
  //    ARBITRARY byte boundaries. A single SSE line like:
  //       data: {"type":"token","content":"hello"}
  //    can be split across two or more read() calls.
  //
  //    This parser accumulates bytes into a string buffer,
  //    only extracts COMPLETE lines (terminated by \n),
  //    and keeps any trailing fragment for the next read.
  // ─────────────────────────────────────────────
  private async *parseSSEStream(body: ReadableStream<Uint8Array>) {
    const reader = body.getReader();
    const decoder = new TextDecoder('utf-8');

    // 🛡️ The buffer holds incomplete data between read() calls
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log('%c[SSE] ✅ Stream ended (done=true)', 'color: #22c55e; font-weight: bold');
          break;
        }

        // Append the decoded chunk to the buffer
        buffer += decoder.decode(value, { stream: true });
        console.log("📦 RAW NETWORK BUFFER:", buffer);

        // Split by newline — only COMPLETE lines are safe to parse
        const lines = buffer.split('\n');

        // The LAST element may be an incomplete fragment.
        // Pop it back into the buffer for the next iteration.
        buffer = lines.pop() || '';

        // Process each complete line
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(trimmed.substring(6));
              console.log("✅ SUCCESSFULLY PARSED:", parsed);
              yield parsed;
            } catch (e) {
              // Malformed JSON — log and skip, don't crash
              console.error("❌ STREAM PARSE ERROR ON LINE:", trimmed, e);
            }
          }
        }
      }

      // ─── After stream ends, flush any remaining data in the buffer ───
      if (buffer.trim().startsWith('data: ')) {
        try {
          const parsed = JSON.parse(buffer.trim().substring(6));
          yield parsed;
        } catch (e) {
          console.warn('[SSE] Skipping final malformed chunk:', buffer);
        }
      }

    } finally {
      // Always release the reader lock
      reader.releaseLock();
    }
  }
}