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

  // Fetch old messages when the user opens the app
  getHistory(sessionId: string): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/history/${sessionId}`);
  }

  // Send just the session ID now!
  sendMessage(question: string, sessionId: string): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${this.apiUrl}/chat`, { question, session_id: sessionId });
  }

  // Audio requires the session ID too
  sendAudioMessage(audioBlob: Blob, sessionId: string): Observable<any> {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice_memo.webm');
    formData.append('session_id', sessionId);
    return this.http.post<any>(`${this.apiUrl}/audio-chat`, formData);
  }
}