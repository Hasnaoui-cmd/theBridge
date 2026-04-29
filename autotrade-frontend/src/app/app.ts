import { Component, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService, ChatResponse } from './chat';
import { marked } from 'marked';

interface Message {
  role: 'user' | 'ai';
  content: string;
  htmlContent?: string;
  sources?: string[];
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  userQuestion: string = '';
  isLoading: boolean = false;
  isRecording: boolean = false;
  mediaRecorder: any;
  audioChunks: any[] = [];

  messages: Message[] = [
    {
      role: 'ai',
      content: 'Hello! I am the AutoTrade-Comply AI. Ask me about Moroccan Customs or European Trade Law.',
      htmlContent: '<p>Hello! I am the AutoTrade-Comply AI. Ask me about Moroccan Customs or European Trade Law.</p>'
    }
  ];

  constructor(private chatService: ChatService, private cdr: ChangeDetectorRef) { }

  // --- HELPER: GET HISTORY ---
  // Grabs the last 6 messages to give the AI context without overloading its memory
  getChatHistory() {
    return this.messages.slice(-6).map(m => ({
      role: m.role,
      content: m.content
    }));
  }

  // --- TEXT LOGIC ---
  sendMessage() {
    if (!this.userQuestion.trim()) return;
    const query = this.userQuestion;

    // Grab the history BEFORE adding the new question
    const historyPayload = this.getChatHistory();

    this.messages = [...this.messages, { role: 'user', content: query }];
    this.userQuestion = '';
    this.isLoading = true;
    this.cdr.detectChanges();

    // Send the query AND the history
    this.chatService.sendMessage(query, historyPayload).subscribe({
      next: async (res: any) => await this.handleResponse(res),
      error: (err) => this.handleError(err)
    });
  }

  // --- AUDIO LOGIC ---
  async toggleRecording() {
    if (this.isRecording) {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  }

  async startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (event: any) => {
        if (event.data.size > 0) this.audioChunks.push(event.data);
      };

      this.mediaRecorder.onstop = () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        this.processAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };

      this.mediaRecorder.start();
      this.isRecording = true;
      this.cdr.detectChanges();
    } catch (err) {
      console.error("Microphone access denied", err);
      alert("Please allow microphone permissions in your browser.");
    }
  }

  stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.isRecording = false;
      this.isLoading = true;
      this.cdr.detectChanges();
    }
  }

  processAudio(blob: Blob) {
    // Grab the history BEFORE sending the audio
    const historyPayload = this.getChatHistory();

    // Send the audio AND the history
    this.chatService.sendAudioMessage(blob, historyPayload).subscribe({
      next: async (res: any) => {
        if (res.transcription) {
          this.messages = [...this.messages, { role: 'user', content: '🎤 ' + res.transcription }];
        }
        await this.handleResponse(res);
      },
      error: (err) => this.handleError(err)
    });
  }

  // --- HELPER LOGIC ---
  async handleResponse(res: any) {
    if (res.error) {
      this.messages = [...this.messages, { role: 'ai', content: '⚠️ Server Error: ' + res.error }];
    } else {
      const parsedHtml = await marked.parse(res.answer);
      this.messages = [...this.messages, {
        role: 'ai',
        content: res.answer,
        htmlContent: parsedHtml,
        sources: res.sources
      }];
    }
    this.isLoading = false;
    this.cdr.detectChanges();
  }

  handleError(err: any) {
    this.messages = [...this.messages, { role: 'ai', content: '❌ Fatal Error connecting to the server.' }];
    this.isLoading = false;
    this.cdr.detectChanges();
    console.error(err);
  }
}