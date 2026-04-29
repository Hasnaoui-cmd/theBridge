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
  private apiUrl = 'http://127.0.0.1:8000/chat';

  constructor(private http: HttpClient) { }

  // Now accepts a history array!
  sendMessage(question: string, history: any[]): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(this.apiUrl, { question, history });
  }

  // Now accepts a history array!
  sendAudioMessage(audioBlob: Blob, history: any[]): Observable<any> {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice_memo.webm');
    // Convert the history array into a string so it can travel with the audio file
    formData.append('history', JSON.stringify(history));
    return this.http.post<any>('http://127.0.0.1:8000/audio-chat', formData);
  }
}