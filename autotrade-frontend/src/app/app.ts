import { Component, OnInit, ChangeDetectorRef, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from './chat';
import { AuthService } from './auth.service';
import { User } from '@supabase/supabase-js';
import { marked } from 'marked';

interface Message {
  role: 'user' | 'ai';
  content: string;
  htmlContent?: string;
  sources?: string[];
  statusText?: string;  // Temporary status like "📊 Querying Database..."
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
  isStreaming: boolean = false;    // True while an AI stream is actively running
  sessionId: string = '';
  isRecording: boolean = false;
  mediaRecorder: any;
  audioChunks: any[] = [];
  messages: Message[] = [];

  // Tracks whether we've loaded history for the current session at least once.
  // Prevents the "Ghost Wipe" — Supabase auth emits the same user repeatedly
  // (e.g. on token refresh), and without this guard, every emission would
  // call loadUserHistory() and wipe the conversation mid-stream.
  private historyLoadedForSession: string = '';

  // --- DOM REFERENCE for auto-scroll ---
  @ViewChild('conversationCanvas') private conversationCanvas!: ElementRef;

  constructor(
    private chatService: ChatService,
    private authService: AuthService,
    private cdr: ChangeDetectorRef
  ) { }

  // ─────────────────────────────────────────────
  // LIFECYCLE — Runs when the page loads
  // ─────────────────────────────────────────────
  ngOnInit() {
    this.authService.user$.subscribe(user => {
      this.user = user;
      if (user) {
        this.sessionId = user.id;
        this.showLoginModal = false;

        // 🛡️ FIX FOR "GHOST WIPE" BUG:
        // Only load history if:
        //   1. This is a NEW session (different user ID), AND
        //   2. We are NOT currently streaming an AI response
        // Supabase's onAuthStateChange fires periodically (token refresh),
        // and without this guard it would wipe the screen every time.
        if (this.historyLoadedForSession !== user.id && !this.isStreaming) {
          this.historyLoadedForSession = user.id;
          this.loadUserHistory();
        }
      } else {
        // User logged out — clear everything
        this.messages = [];
        this.sessionId = '';
        this.historyLoadedForSession = '';
      }
      this.cdr.detectChanges();
    });
  }

  // ─────────────────────────────────────────────
  // LOGIN / SIGNUP LOGIC
  // ─────────────────────────────────────────────
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

  // ─────────────────────────────────────────────
  // CHAT HISTORY LOADER
  // ─────────────────────────────────────────────
  loadUserHistory() {
    this.isLoading = true;
    this.chatService.getHistory(this.sessionId).subscribe({
      next: async (res: any) => {
        this.messages = [];
        if (res.messages && res.messages.length > 0) {
          for (let msg of res.messages) {
            const parsedHtml = msg.role === 'ai' ? await marked.parse(msg.content) : undefined;
            this.messages.push({ role: msg.role, content: msg.content, htmlContent: parsedHtml });
          }
        } else {
          this.messages = [{
            role: 'ai',
            content: 'Bienvenue sur AutoTrade-Comply. Votre session sécurisée a démarré.',
            htmlContent: '<p>Bienvenue sur AutoTrade-Comply. Votre session sécurisée a démarré.</p>'
          }];
        }
        this.isLoading = false;
        this.cdr.detectChanges();
        this.scrollToBottom();
      },
      error: (err) => {
        console.error("Failed to load history:", err);
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  // ─────────────────────────────────────────────
  // 🚀 STREAMING TEXT CHAT
  // ─────────────────────────────────────────────
  async sendMessage() {
    if (!this.user) { this.showLoginModal = true; return; }
    if (!this.userQuestion.trim()) return;
    const query = this.userQuestion;

    // 1. Immutable push for User Message
    this.messages = [...this.messages, { role: 'user', content: query }];
    this.userQuestion = '';

    // 2. Trigger the HTML animated typing dots (no placeholder message needed)
    this.isLoading = true;
    this.isStreaming = true;  // Lock: prevents Ghost Wipe during stream
    this.cdr.detectChanges();
    this.scrollToBottom();

    try {
      let currentText = '';
      let receivedTokens = false;
      let isFirstChunk = true;
      let aiIndex = -1;
      let aiMessage: Message = { role: 'ai', content: '', htmlContent: '' };

      // 3. Consume the async stream from the service
      for await (const data of this.chatService.sendMessageStream(query, this.sessionId)) {

        // 4. The moment the backend wakes up, swap dots for the real bubble
        if (isFirstChunk) {
          this.isLoading = false;
          isFirstChunk = false;

          // Inject the empty AI bubble NOW (not before the stream)
          this.messages = [...this.messages, aiMessage];
          aiIndex = this.messages.length - 1;
        }

        if (data.type === 'status') {
          // Only show statuses IF we haven't started receiving the real answer yet
          if (!receivedTokens) {
            currentText = `*${data.content}*`; // Overwrite, don't append, so statuses don't stack
            const parsedHtml = await marked.parse(currentText);
            this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: parsedHtml };
          }
        }
        else if (data.type === 'token') {
          // The moment the first token arrives, wipe any temporary statuses!
          if (!receivedTokens) {
            currentText = '';
            receivedTokens = true;
          }
          currentText += data.content;
          // FIREHOSE OPTIMIZATION: Do NOT parse markdown here. Just render raw text!
          this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: currentText };
        }
        else if (data.type === 'done') {
          // AI is finished! Now we parse the final markdown to make it pretty.
          const finalHtml = await marked.parse(currentText);
          this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: finalHtml, sources: data.sources };
        }

        // Force Angular to repaint
        this.messages = [...this.messages];
        this.cdr.detectChanges();
        this.scrollToBottom();
      }

      // Safeguard: If the stream ended without ever sending a chunk
      if (isFirstChunk) {
        this.isLoading = false;
        this.messages = [...this.messages, {
          role: 'ai' as const,
          content: '❌ La connexion a échoué.',
          htmlContent: '<p>❌ La connexion a échoué.</p>'
        }];
        this.cdr.detectChanges();
      }

    } catch (err) {
      this.isLoading = false;
      this.isStreaming = false;
      this.handleError(err);
    } finally {
      // Safety: always reset loading/streaming state
      this.isLoading = false;
      this.isStreaming = false;  // Unlock: allow auth-triggered history loads again
      this.cdr.detectChanges();
    }
  }

  // ─────────────────────────────────────────────
  // AUDIO RECORDING LOGIC
  // ─────────────────────────────────────────────
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
      this.isLoading = true; // Show spinner while Whisper transcribes
      this.cdr.detectChanges();
    }
  }

  // ─────────────────────────────────────────────
  // 🚀 STREAMING AUDIO CHAT
  // ─────────────────────────────────────────────
  async processAudio(blob: Blob) {
    let aiIndex = -1;
    this.isStreaming = true;  // Lock: prevents Ghost Wipe during stream
    let currentText = '';
    let receivedTokens = false;
    let isFirstRealChunk = true;
    let aiMessage: Message = { role: 'ai', content: '', htmlContent: '' };

    try {
      for await (const data of this.chatService.sendAudioStream(blob, this.sessionId)) {
        this.isLoading = false;

        if (data.type === 'transcription') {
          // 1. Show what the user said
          this.messages = [...this.messages, { role: 'user', content: '🎤 ' + data.content }];

          // 2. Trigger the HTML animated typing dots (no placeholder AI message)
          this.isLoading = true;
          currentText = '';
          receivedTokens = false;
          isFirstRealChunk = true;
          this.cdr.detectChanges();
          this.scrollToBottom();
          continue;
        }

        // 3. The moment the backend sends a real chunk, swap dots for the AI bubble
        if (isFirstRealChunk) {
          this.isLoading = false;
          isFirstRealChunk = false;

          // Inject the empty AI bubble NOW
          this.messages = [...this.messages, aiMessage];
          aiIndex = this.messages.length - 1;
        }

        if (aiIndex === -1) continue;

        if (data.type === 'status') {
          // Only show statuses IF we haven't started receiving the real answer yet
          if (!receivedTokens) {
            currentText = `*${data.content}*`; // Overwrite, don't append, so statuses don't stack
            const parsedHtml = await marked.parse(currentText);
            this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: parsedHtml };
          }
        }
        else if (data.type === 'token') {
          // The moment the first token arrives, wipe any temporary statuses!
          if (!receivedTokens) {
            currentText = '';
            receivedTokens = true;
          }
          currentText += data.content;
          // FIREHOSE OPTIMIZATION: Do NOT parse markdown here. Just render raw text!
          this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: currentText };
        }
        else if (data.type === 'done') {
          // AI is finished! Now we parse the final markdown to make it pretty.
          const finalHtml = await marked.parse(currentText);
          this.messages[aiIndex] = { ...aiMessage, content: currentText, htmlContent: finalHtml, sources: data.sources };
        }

        // Force Angular to repaint
        this.messages = [...this.messages];
        this.cdr.detectChanges();
        this.scrollToBottom();
      }
    } catch (err) {
      this.isLoading = false;
      this.isStreaming = false;
      this.handleError(err);
    } finally {
      this.isLoading = false;
      this.isStreaming = false;  // Unlock
      this.cdr.detectChanges();
    }
  }

  // ─────────────────────────────────────────────
  // HELPER: Error Handler
  // ─────────────────────────────────────────────
  handleError(err: any) {
    this.messages.push({ role: 'ai', content: '❌ Erreur fatale de connexion au serveur.' });
    this.isLoading = false;
    this.isStreaming = false;
    this.cdr.detectChanges();
    this.scrollToBottom();
    console.error(err);
  }

  // ─────────────────────────────────────────────
  // HELPER: Auto-Scroll to bottom of conversation
  // ─────────────────────────────────────────────
  private scrollToBottom(): void {
    try {
      if (this.conversationCanvas) {
        const el = this.conversationCanvas.nativeElement;
        // Use setTimeout to ensure DOM has painted before scrolling
        setTimeout(() => {
          el.scrollTop = el.scrollHeight;
        }, 0);
      }
    } catch (err) {
      // Silently ignore scroll errors (element may not exist yet)
    }
  }
}