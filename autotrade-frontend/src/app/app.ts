import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from './chat';
import { AuthService } from './auth.service'; // <-- Imported Auth Service
import { User } from '@supabase/supabase-js'; // <-- Imported Supabase User
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
export class App implements OnInit {
  // --- AUTHENTICATION STATE ---
  user: User | null = null;
  authEmail = '';
  authPassword = '';
  isAuthLoading = false;
  authError = '';
  isSignUpMode = false;
  showLoginModal = false;

  // --- CHAT STATE ---
  userQuestion: string = '';
  isLoading: boolean = false;
  sessionId: string = ''; // Now securely tied to their Supabase ID
  isRecording: boolean = false;
  mediaRecorder: any;
  audioChunks: any[] = [];
  messages: Message[] = [];

  constructor(
    private chatService: ChatService,
    private authService: AuthService,
    private cdr: ChangeDetectorRef
  ) { }

  // --- RUNS WHEN THE PAGE LOADS ---
  ngOnInit() {
    // Listen to the auth state. If they log in, load their specific history!
    this.authService.user$.subscribe(user => {
      this.user = user;
      if (user) {
        this.sessionId = user.id; // The user's unique ID is now their session ID
        this.showLoginModal = false; // Close the modal on successful login
        this.loadUserHistory();
      } else {
        this.messages = [];
        this.sessionId = '';
      }
      this.cdr.detectChanges();
    });
  }

  // --- LOGIN / SIGNUP LOGIC ---
  async handleAuth() {
    if (!this.authEmail || !this.authPassword) return;
    this.isAuthLoading = true;
    this.authError = '';

    try {
      const { error } = this.isSignUpMode
        ? await this.authService.signUp(this.authEmail, this.authPassword)
        : await this.authService.signIn(this.authEmail, this.authPassword);

      if (error) {
        this.authError = error.message;
      } else {
        this.showLoginModal = false;
      }
    } catch (err: any) {
      this.authError = err.message;
    } finally {
      this.isAuthLoading = false;
      this.cdr.detectChanges();
    }
  }

  async logout() {
    await this.authService.signOut();
  }

  async signInWithGoogle() {
    this.authError = '';
    const { error } = await this.authService.signInWithGoogle();
    if (error) {
      this.authError = error.message;
      this.cdr.detectChanges();
    }
  }

  // --- CHAT LOGIC ---
  loadUserHistory() {
    this.isLoading = true;
    this.chatService.getHistory(this.sessionId).subscribe({
      next: async (res: any) => {
        this.messages = []; // Clear the array first
        if (res.messages && res.messages.length > 0) {
          for (let msg of res.messages) {
            const parsedHtml = msg.role === 'ai' ? await marked.parse(msg.content) : undefined;
            this.messages.push({ role: msg.role, content: msg.content, htmlContent: parsedHtml });
          }
        } else {
          // Default welcome message for new users
          this.messages = [{ role: 'ai', content: 'Welcome to AutoTrade-Comply. Your secure session has started.', htmlContent: '<p>Welcome to AutoTrade-Comply. Your secure session has started.</p>' }];
        }
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        console.error("Failed to load history:", err);
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  sendMessage() {
    if (!this.user) { this.showLoginModal = true; return; }
    if (!this.userQuestion.trim()) return;
    const query = this.userQuestion;

    this.messages = [...this.messages, { role: 'user', content: query }];
    this.userQuestion = '';
    this.isLoading = true;
    this.cdr.detectChanges();

    this.chatService.sendMessage(query, this.sessionId).subscribe({
      next: async (res: any) => await this.handleResponse(res),
      error: (err) => this.handleError(err)
    });
  }

  // --- AUDIO LOGIC ---
  async toggleRecording() {
    if (!this.user) { this.showLoginModal = true; return; }
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
    this.chatService.sendAudioMessage(blob, this.sessionId).subscribe({
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