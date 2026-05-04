import { Injectable } from '@angular/core';
import { createClient, SupabaseClient, User } from '@supabase/supabase-js';
import { BehaviorSubject } from 'rxjs';

@Injectable({
    providedIn: 'root'
})
export class AuthService {
    private supabase: SupabaseClient;

    // This keeps track of who is logged in and alerts the rest of the app when it changes
    private currentUser = new BehaviorSubject<User | null>(null);
    user$ = this.currentUser.asObservable();

    constructor() {
        // ⚠️ PASTE YOUR KEYS HERE ⚠️
        const supabaseUrl = 'https://gzrtmwpopdhfjrpugzmy.supabase.co';
        const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd6cnRtd3BvcGRoZmpycHVnem15Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc2NDM2MzQsImV4cCI6MjA5MzIxOTYzNH0.-b-UCI9MNO8_zGhkE1BpTSZu2k9hSt_6SDjU0vGfJdA';

        this.supabase = createClient(supabaseUrl, supabaseKey);

        // Check if the user is already logged in when they open the app
        this.supabase.auth.getSession().then(({ data: { session } }) => {
            this.currentUser.next(session?.user ?? null);
        });

        // Listen for login/logout events
        this.supabase.auth.onAuthStateChange((_event, session) => {
            this.currentUser.next(session?.user ?? null);
        });
    }

    // --- AUTHENTICATION METHODS ---

    async signUp(email: string, password: string) {
        return await this.supabase.auth.signUp({ email, password });
    }

    async signIn(email: string, password: string) {
        return await this.supabase.auth.signInWithPassword({ email, password });
    }

    async signOut() {
        return await this.supabase.auth.signOut();
    }

    async signInWithGoogle() {
        return await this.supabase.auth.signInWithOAuth({ provider: 'google' });
    }

    // Get the current User ID (We will use this as the new Session ID!)
    getCurrentUserId(): string | null {
        return this.currentUser.value?.id || null;
    }
}